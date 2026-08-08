#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
批量多模型积水研判测试脚本。

对指定图片目录下的所有 JPG 图片，使用 HYBRID_THINKING_MODELS 中的全部模型，
以固定 --thinking auto 模式进行积水研判，并将每个 (模型, 图片) 组合的结果
保存为独立 JSON 文件，便于后续横向对比分析。

使用方法：
    python scripts/batch_test.py

所有配置（图片目录、模型列表、并发数等）硬编码于本文件顶部配置区。
本脚本复用 src/waterlogging.py 中的 analyze_image / prepare_image_input /
resolve_thinking_choice / validate_basic_result，不修改其业务逻辑。
"""

from __future__ import annotations

import io
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# 将 src/ 加入模块搜索路径，以便导入主程序。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from waterlogging import (
    HYBRID_THINKING_MODELS,
    analyze_image,
    prepare_image_input,
    resolve_thinking_choice,
    validate_basic_result,
)


# =============================================================================
# 配置区
# =============================================================================

# 项目根目录（scripts/ 的上一级）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 图片目录（仅处理 .jpg 后缀，忽略同目录下的 .jfif 等其他格式）。
IMAGE_DIR = str(_PROJECT_ROOT / "data" / "images")

# 结果输出目录（脚本自动创建）。
OUTPUT_DIR = str(_PROJECT_ROOT / "batch_results")

# 最大并发 API 调用数（避免触发百炼 QPS 限制）。
MAX_WORKERS = 3

# 批量测试固定的思考模式（对 HYBRID_THINKING_MODELS 发送 enable_thinking=True）。
THINKING_MODE = "auto"

# 图片文件后缀。
IMAGE_SUFFIX = ".jpg"


# =============================================================================
# 线程安全的 stdout/stderr 捕获
# =============================================================================
#
# analyze_image 内部使用 print 输出思考过程与研判 JSON。在 ThreadPoolExecutor
# 中并发调用时，直接 redirect_stdout 会因 sys.stdout 是全局对象而产生竞态。
# 这里使用 threading.local 让每个线程的 write/flush 路由到各自缓冲区，
# 从而安全地捕获每个任务的输出。

_REAL_STDOUT = sys.stdout
_REAL_STDERR = sys.stderr


class _ThreadLocalStream:
    """将 write/flush 调用按线程路由到各自缓冲区的流包装器。

    线程通过 activate(buffer) 激活自己的缓冲区；未激活时回退到原始流。
    其余属性（encoding、isatty 等）代理到原始流。
    """

    def __init__(self, fallback: Any) -> None:
        self._fallback = fallback
        self._local = threading.local()

    def _buffer(self) -> io.StringIO | None:
        return getattr(self._local, "buffer", None)

    def activate(self, buffer: io.StringIO) -> None:
        self._local.buffer = buffer

    def deactivate(self) -> None:
        self._local.buffer = None

    def write(self, text: str) -> int:
        buf = self._buffer()
        if buf is not None:
            return buf.write(text)
        return self._fallback.write(text)

    def flush(self) -> None:
        buf = self._buffer()
        if buf is not None:
            buf.flush()
        else:
            self._fallback.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fallback, name)


_THREAD_STDOUT = _ThreadLocalStream(_REAL_STDOUT)
_THREAD_STDERR = _ThreadLocalStream(_REAL_STDERR)


def _real_print(*args: Any, **kwargs: Any) -> None:
    """直接打印到真实 stdout，不受线程本地缓冲影响。"""
    print(*args, file=_REAL_STDOUT, **kwargs)


# =============================================================================
# 单任务执行
# =============================================================================

_JSON_MARKER = "=" * 30 + " 最终研判 JSON " + "=" * 30


def _extract_result_json(stdout_text: str) -> Any:
    """从 analyze_image 的 stdout 输出中提取研判 JSON。

    analyze_image 在返回 exit code 0 时，将 json.dumps(result) 打印到 stdout，
    位于 "最终研判 JSON" 分隔线之后。取最后一次出现的分隔线之后的文本解析。
    """
    idx = stdout_text.rfind(_JSON_MARKER)
    if idx == -1:
        return None
    json_text = stdout_text[idx + len(_JSON_MARKER):].strip()
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


def _summarize_error(exit_code: int, stderr_text: str) -> str:
    """根据退出码和 stderr 内容生成简洁的错误描述。"""
    if exit_code == 3:
        if "超时" in stderr_text:
            return "请求超时"
        http_match = re.search(r"HTTP (\d+)", stderr_text)
        if http_match:
            return f"HTTP {http_match.group(1)}"
        if "无法连接" in stderr_text:
            return "无法连接到 API"
        return "API 调用失败"
    if exit_code == 4:
        return "模型未返回最终 content"
    if exit_code == 5:
        return "模型回复不是合法 JSON"
    if exit_code == 130:
        return "用户中断"
    return f"未知错误（退出码 {exit_code}）"


def run_single_test(model: str, image_path: Path) -> dict[str, Any]:
    """对单个 (模型, 图片) 组合执行研判，返回结果字典。"""
    base: dict[str, Any] = {
        "model": model,
        "image": image_path.name,
        "thinking_mode": THINKING_MODE,
    }

    # 准备图片输入（本地路径转 base64 data URL）。
    try:
        image_source, image_label = prepare_image_input(str(image_path))
    except Exception as exc:
        return {**base, "success": False, "error": f"图片输入准备失败：{exc}"}

    thinking_decision = resolve_thinking_choice(model, THINKING_MODE)

    # 捕获 analyze_image 的 stdout/stderr 到线程本地缓冲区。
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    _THREAD_STDOUT.activate(stdout_buf)
    _THREAD_STDERR.activate(stderr_buf)
    try:
        exit_code = analyze_image(
            image_source, image_label, model, thinking_decision
        )
    except Exception as exc:
        # analyze_image 内部已捕获大部分异常，此处为兜底。
        exit_code = -1
        stderr_buf.write(f"未捕获异常：{type(exc).__name__}: {exc}\n")
    finally:
        _THREAD_STDOUT.deactivate()
        _THREAD_STDERR.deactivate()

    if exit_code == 0:
        result = _extract_result_json(stdout_buf.getvalue())
        if result is not None:
            warnings = validate_basic_result(result)
            return {**base, "success": True, "result": result, "warnings": warnings}
        return {**base, "success": False, "error": "成功调用但无法解析研判 JSON"}

    error = _summarize_error(exit_code, stderr_buf.getvalue())
    return {**base, "success": False, "error": error}


# =============================================================================
# 主流程
# =============================================================================

def main() -> int:
    # 安装线程本地流包装器，使 analyze_image 的 print 按线程隔离。
    sys.stdout = _THREAD_STDOUT
    sys.stderr = _THREAD_STDERR

    image_dir = Path(IMAGE_DIR)
    if not image_dir.is_dir():
        _real_print(f"错误：图片目录不存在：{image_dir}")
        return 2

    images = sorted(image_dir.glob(f"*{IMAGE_SUFFIX}"))
    if not images:
        _real_print(f"错误：在 {image_dir} 中未找到 *{IMAGE_SUFFIX} 文件。")
        return 2

    models = sorted(HYBRID_THINKING_MODELS)
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(model, img) for model in models for img in images]
    total = len(tasks)

    _real_print(
        f"批量测试：{len(models)} 个模型 × {len(images)} 张图片 = {total} 次调用"
    )
    _real_print(f"输出目录：{output_dir.resolve()}")
    _real_print(f"最大并发：{MAX_WORKERS}")
    _real_print(f"思考模式：{THINKING_MODE}")
    _real_print()

    success_count = 0
    failure_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_task = {
            executor.submit(run_single_test, model, img): (model, img)
            for model, img in tasks
        }

        for i, future in enumerate(as_completed(future_to_task), 1):
            model, img = future_to_task[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "model": model,
                    "image": img.name,
                    "thinking_mode": THINKING_MODE,
                    "success": False,
                    "error": f"任务异常：{type(exc).__name__}: {exc}",
                }

            output_file = output_dir / f"{model}__{img.stem}.json"
            output_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if result["success"]:
                success_count += 1
                status = "OK"
            else:
                failure_count += 1
                status = "FAIL"

            _real_print(f"[{i}/{total}] {status}  {model} × {img.name}")
            if not result["success"]:
                _real_print(f"         → {result.get('error', '未知错误')}")

    _real_print()
    _real_print(
        f"完成：{success_count} 成功 / {failure_count} 失败 / {total} 总计"
    )
    _real_print(f"结果已保存至：{output_dir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
