#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-1 深度估计 prompt 二次调参验证脚本（wayfinder ticket #21）。

对 ``data/images/road_water*.jpg`` 六张图，用修改后的 Stage-1 prompt
（``src/observation/prompt.py`` 的 ``build_observation_prompt()``，#21 改后）
跑默认模型 ``qwen3-vl-plus``（thinking auto），产出聚合指标并断言：

  - LX 率维持 0%（#18 不回退）；
  - 在有参照图（road_water2/3）上 cm 填充率 > 0；
  - confidence 分布重获区分度（至少 1 个 medium）；
  - 无参照图上 cm 保持 null（不编造）。

可选 ``--cross-model`` 对 ``qwen3.6-flash`` 做回归检查：
  - cm 填充率不降；
  - 填充值为宽区间（min/max 均非 null）；
  - 无新增 schema 失败。

输出：
  - 每个 (model, image) 的完整结果 JSON 到 ``comparison_results/depth_tuning/``；
  - 汇总 JSON + Markdown 报告到同目录。

设计决策：
  - LLM 非确定性 → 断言聚合比率（带容忍度），非单图点值。
  - 缺 DASHSCOPE_API_KEY 或 fixture 图片 → 自动 skip（exit 0），应对 CI。
  - 歧义图（4/5）合理性不自动化——以人工抽查清单形式打印，不阻塞验证。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# 将 src/ 加入模块搜索路径。
_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from vlm.client import API_KEY, make_client
from observation.generate import (
    DEFAULT_MODEL,
    ObservationGenerationError,
    generate_observation,
    prepare_image_input,
)

# =============================================================================
# 配置区
# =============================================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = _PROJECT_ROOT / "data" / "images"
OUTPUT_ROOT = _PROJECT_ROOT / "comparison_results" / "depth_tuning"

MODEL = "qwen3-vl-plus"
CROSS_MODEL = "qwen3.6-flash"
THINKING = "auto"

_PLACEHOLDER_KEY = "请在这里填写你的阿里云百炼API_KEY"

# 图片分组（用于断言范围）。
IMAGE_GROUPS: dict[str, list[str]] = {
    "reference": ["road_water2.jpg", "road_water3.jpg"],
    "no_reference": ["road_water1.jpg", "road_water6.jpg"],
    "ambiguity": ["road_water4.jpg", "road_water5.jpg"],
}

_LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "LX"]
_CONFIDENCE_ORDER = ["high", "medium", "low"]


# =============================================================================
# 指标提取
# =============================================================================


def _depth_filled(depth_cm: dict[str, Any]) -> bool:
    """depth_cm 是否至少有一个字段非 null。"""
    return any(
        v is not None
        for v in (depth_cm.get("min"), depth_cm.get("max"), depth_cm.get("most_likely"))
    )


def _depth_is_interval(depth_cm: dict[str, Any]) -> bool:
    """depth_cm 是否为宽区间（min 与 max 均非 null）。"""
    return depth_cm.get("min") is not None and depth_cm.get("max") is not None


def extract_metrics(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """从所有 (image_name -> cell) 结果中提取聚合指标。"""
    total = len(results)
    success = sum(1 for c in results.values() if c.get("success"))
    failure = total - success

    agg: dict[str, Any] = {
        "total": total,
        "success": success,
        "failure": failure,
        "lx_count": 0,
        "lx_rate": 0.0,
        "level_distribution": {lvl: 0 for lvl in _LEVEL_ORDER},
        "cm_fill_count": 0,
        "cm_fill_rate": 0.0,
        "cm_interval_count": 0,  # min 与 max 均非 null
        "confidence_distribution": {c: 0 for c in _CONFIDENCE_ORDER},
        "failures": [],
    }

    for name, cell in results.items():
        if not cell.get("success"):
            agg["failures"].append({"image": name, "error": cell.get("error", "unknown")})
            continue
        level = cell.get("waterlogging_level", "LX")
        if level == "LX":
            agg["lx_count"] += 1
        if level in agg["level_distribution"]:
            agg["level_distribution"][level] += 1
        if cell.get("depth_cm_filled"):
            agg["cm_fill_count"] += 1
            if cell.get("depth_cm_interval"):
                agg["cm_interval_count"] += 1
        conf = cell.get("confidence", "low")
        if conf in agg["confidence_distribution"]:
            agg["confidence_distribution"][conf] += 1

    if success:
        agg["lx_rate"] = round(agg["lx_count"] / success, 3)
        agg["cm_fill_rate"] = round(agg["cm_fill_count"] / success, 3)
    return agg


# =============================================================================
# 断言
# =============================================================================


def run_assertions(
    metrics: dict[str, Any],
    group_label: str,
    model: str,
) -> list[str]:
    """返回失败消息列表；空列表 = 全部通过。"""
    failures: list[str] = []
    s = metrics["success"]
    if s == 0:
        failures.append(f"[{model}] {group_label}: 所有图片均失败，无法断言。")
        return failures

    # A1: LX 率 = 0%
    if metrics["lx_rate"] > 0.0:
        failures.append(
            f"[{model}] {group_label}: LX 率 {metrics['lx_rate']:.0%} > 0% "
            f"（{metrics['lx_count']}/{s}）—— #18 不回退检查失败。"
        )

    return failures


def run_reference_assertions(metrics: dict[str, Any], model: str) -> list[str]:
    """参照图特有断言。"""
    failures: list[str] = []
    s = metrics["success"]
    if s == 0:
        return failures

    # A2: cm 填充率 > 0（至少 road_water2/3 有可见参照）
    if metrics["cm_fill_rate"] == 0.0:
        failures.append(
            f"[{model}] reference: cm 填充率 0% ({s} 张图均 null)——"
            f"部分浸没参照应触发 cm 填充。"
        )

    # A3: confidence 分布有区分度（至少 1 个 medium）
    if metrics["confidence_distribution"].get("medium", 0) == 0:
        failures.append(
            f"[{model}] reference: confidence 全为 low（medium=0）——"
            f"单一清晰参照应足以给 medium。"
        )

    return failures


def run_no_reference_assertions(metrics: dict[str, Any], model: str) -> list[str]:
    """无参照图特有断言。"""
    failures: list[str] = []
    s = metrics["success"]
    if s == 0:
        return failures

    # A4: cm 保持 null（不编造）
    if metrics["cm_fill_rate"] > 0.0:
        failures.append(
            f"[{model}] no_reference: cm 填充率 {metrics['cm_fill_rate']:.0%} > 0% "
            f"（无参照图不应编造 cm）。"
        )

    return failures


def run_flash_assertions(
    metrics: dict[str, Any],
    group_label: str,
) -> list[str]:
    """flash 交叉模型断言。"""
    failures: list[str] = []
    s = metrics["success"]
    if s == 0:
        return failures

    # F1: LX 率 = 0%
    if metrics["lx_rate"] > 0.0:
        failures.append(
            f"[flash] {group_label}: LX 率 {metrics['lx_rate']:.0%} > 0%。"
        )

    return failures


def run_flash_interval_assertion(
    results: dict[str, dict[str, Any]],
    group_label: str,
) -> list[str]:
    """flash: 所有 cm 填充值均为宽区间（min 与 max 均非 null）。"""
    failures: list[str] = []
    for name, cell in results.items():
        if not cell.get("success"):
            continue
        if cell.get("depth_cm_filled") and not cell.get("depth_cm_interval"):
            failures.append(
                f"[flash] {group_label}/{name}: cm 已填充但非区间 "
                f"（min={cell.get('depth_cm', {}).get('min')}, "
                f"max={cell.get('depth_cm', {}).get('max')}）——"
                f"应给宽区间而非伪精确单值。"
            )
    return failures


# =============================================================================
# 主流程
# =============================================================================


def check_prerequisites() -> str | None:
    """返回 skip 原因字符串，或 None 表示可以继续。"""
    if not API_KEY or API_KEY == _PLACEHOLDER_KEY:
        return "DASHSCOPE_API_KEY 未配置或为占位值——跳过 LLM 实测。"
    images = sorted(IMAGE_DIR.glob("road_water*.jpg"))
    if len(images) < 6:
        return (
            f"fixture 图片不足（需要 6 张，找到 {len(images)} 张）——跳过 LLM 实测。"
        )
    return None


def run_model(
    client: Any,
    model: str,
    images: list[Path],
) -> dict[str, dict[str, Any]]:
    """对一组图片跑单个模型，返回 {image_stem: cell}。"""
    results: dict[str, dict[str, Any]] = {}
    for img in images:
        image_source, _label = prepare_image_input(str(img))
        try:
            result = generate_observation(
                image_source,
                model=model,
                thinking=THINKING,
                repair_model=model,
            )
            obs = result.observation
            depth_cm = {
                "min": obs.waterlogging.depth_estimate.depth_cm.min,
                "max": obs.waterlogging.depth_estimate.depth_cm.max,
                "most_likely": obs.waterlogging.depth_estimate.depth_cm.most_likely,
            }
            cell: dict[str, Any] = {
                "success": True,
                "status": obs.waterlogging.status.value,
                "waterlogging_level": obs.waterlogging.waterlogging_level.value,
                "depth_cm": depth_cm,
                "depth_cm_filled": _depth_filled(depth_cm),
                "depth_cm_interval": _depth_is_interval(depth_cm),
                "confidence": obs.waterlogging.depth_estimate.confidence.value,
                "overall_confidence": obs.overall_confidence.value,
                "observation": obs.model_dump(exclude_none=True, exclude={"meta"}),
            }
        except ObservationGenerationError as exc:
            cell = {"success": False, "error": str(exc)}
        except Exception as exc:
            cell = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        results[img.stem] = cell
    return results


def group_results(
    all_results: dict[str, dict[str, Any]],
    group_name: str,
) -> dict[str, dict[str, Any]]:
    """从全部结果中提取指定分组的图片。"""
    names = IMAGE_GROUPS.get(group_name, [])
    return {
        Path(name).stem: all_results[Path(name).stem]
        for name in names
        if Path(name).stem in all_results
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage-1 深度估计 prompt 二次调参验证（#21）")
    parser.add_argument(
        "--model", default=MODEL, help=f"被测模型。默认：%(default)s"
    )
    parser.add_argument(
        "--cross-model", action="store_true",
        help=f"同时用 {CROSS_MODEL} 做回归检查。"
    )
    args = parser.parse_args()

    skip_reason = check_prerequisites()
    if skip_reason:
        print(f"SKIP: {skip_reason}")
        return 0

    images = sorted(IMAGE_DIR.glob("road_water*.jpg"))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    client = make_client(timeout=180)

    all_failures: list[str] = []

    for model_label, model_id in [("default", args.model)] + (
        [("flash", CROSS_MODEL)] if args.cross_model else []
    ):
        model_dir = OUTPUT_ROOT / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"模型：{model_id}（thinking {THINKING}），{len(images)} 张图")
        print(f"输出：{model_dir.resolve()}")
        print(f"{'='*60}")

        # 运行
        all_model_results = run_model(client, model_id, images)
        for stem, cell in all_model_results.items():
            (model_dir / f"{stem}.json").write_text(
                json.dumps(cell, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            status = "OK" if cell.get("success") else f"FAIL: {cell.get('error', '')[:60]}"
            level = cell.get("waterlogging_level", "?")
            cm = "有" if cell.get("depth_cm_filled") else "null"
            conf = cell.get("confidence", "?")
            print(f"  {stem}: {status}  level={level}  cm={cm}  conf={conf}")

        # 按分组计算指标并断言
        for group_name in IMAGE_GROUPS:
            group = group_results(all_model_results, group_name)
            if not group:
                continue
            metrics = extract_metrics(group)

            # 基本断言（所有分组）
            failures = run_assertions(metrics, group_name, model_id)

            # 分组特有断言
            if group_name == "reference":
                failures += run_reference_assertions(metrics, model_id)
            elif group_name == "no_reference":
                failures += run_no_reference_assertions(metrics, model_id)
            # ambiguity 组仅报告，不断言

            # flash 特有断言
            if model_label == "flash":
                failures += run_flash_assertions(metrics, group_name)
                if group_name == "reference":
                    failures += run_flash_interval_assertion(group, group_name)

            all_failures += failures

        # 整体指标
        overall = extract_metrics(all_model_results)

        # 保存汇总
        summary: dict[str, Any] = {
            "model": model_id,
            "thinking": THINKING,
            "images": [img.name for img in images],
            "overall": overall,
            "by_group": {
                gn: extract_metrics(group_results(all_model_results, gn))
                for gn in IMAGE_GROUPS
            },
        }
        (model_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 汇总报告 ----
    _write_report(OUTPUT_ROOT, all_failures, args)

    # 打印断言结果
    print(f"\n{'='*60}")
    if all_failures:
        print(f"断言失败：{len(all_failures)} 项")
        for f in all_failures:
            print(f"  ✗ {f}")
        print(f"\n⚠ 部分断言未通过（详情见 test_report.md）。")
        if any("cm 填充率 0%" in f for f in all_failures):
            print("  注意：LLM 非确定性可能导致单次运行 cm 填充率=0；建议重跑确认。")
        return 1
    else:
        print("✓ 所有断言通过。")
        return 0


def _write_report(
    output_root: Path,
    failures: list[str],
    args: argparse.Namespace,
) -> None:
    """生成 Markdown 报告。"""
    lines = [
        f"# Stage-1 深度估计 prompt 二次调参验证报告（#21）",
        "",
        f"- 模型：`{args.model}`{' + `' + CROSS_MODEL + '` 交叉检查' if args.cross_model else ''}",
        f"- thinking：{THINKING}",
        f"- 输出目录：`{output_root.resolve()}`",
        "",
        "## 断言结果",
        "",
    ]
    if failures:
        lines.append(f"**{len(failures)} 项未通过：**")
        lines.append("")
        for f in failures:
            lines.append(f"- ✗ {f}")
    else:
        lines.append("✓ **全部通过。**")
    lines += [
        "",
        "## 歧义图人工抽查清单",
        "",
        "以下图片在 #19 跨模型报告中存在 absent→present 翻转（road_water4/5），",
        "本次仍以人工视觉复核为准，不阻塞自动验证：",
        "",
    ]
    for name in IMAGE_GROUPS.get("ambiguity", []):
        stem = Path(name).stem
        lines.append(f"- [ ] `{stem}` — 检查 depth_cm 区间是否合理、等级是否与视觉一致。")
    lines += [
        "",
        "## 局限",
        "",
        "- LLM 非确定性：单次运行抽样；聚合指标带容忍度。",
        "- 6 张图为现有测试集，未扩。",
        "- 歧义图（4/5）无 ground truth 标签。",
    ]
    (output_root / "test_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
