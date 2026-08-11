#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""道路积水视觉研判 CLI —— Pipeline Stage 1 调试工具。

ADR-0005 §7 重构后，本脚本不再自带 prompt 与 JSON 校验，而是薄薄地包一层
``src/observation/generate.py``（image -> Observation）。可复用 VLM 机器在
``src/vlm/``，结构化输出契约在 ``src/schemas/observation.py``，提示词在
``src/observation/prompt.py``。

使用方法：
    1. 设置环境变量 DASHSCOPE_API_KEY（阿里云百炼 API Key）。
    2. 安装依赖：pip install -r requirements.txt
    3. 运行：
           python src/waterlogging.py "https://example.com/road.jpg"
           python src/waterlogging.py ./data/images/sample.jpg --model qwen3-vl-plus

说明：
    - 图片可为公网 URL 或本地文件路径（本地文件转 base64 data URL）。
    - 思考型模型的 reasoning_content 会实时打印到终端。
    - 最终输出为校验通过的 Observation JSON（+ 元信息：是否经修复、原始回复）。
"""

from __future__ import annotations

import argparse
import sys

from observation.generate import (
    DEFAULT_MODEL,
    REPAIR_MODEL,
    ObservationGenerationError,
    generate_observation,
    prepare_image_input,
)
from vlm.client import API_KEY, classify_model, resolve_thinking_choice


# =============================================================================
# 工具
# =============================================================================

def configure_console_encoding() -> None:
    """尽量保证 Windows 和其他终端能够正确显示中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1 调试工具：调用 Qwen3-VL 把道路积水图片转为结构化 Observation。"
    )
    parser.add_argument(
        "image",
        help="公网可访问的图片 URL，或本地图片文件路径。",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"被测 Qwen3-VL 模型名。默认：%(default)s。",
    )
    parser.add_argument(
        "--thinking",
        choices=["auto", "on", "off"],
        default="auto",
        help="思考模式开关（auto/on/off），按模型档位自动裁剪。默认：%(default)s。",
    )
    parser.add_argument(
        "--repair-model",
        default=REPAIR_MODEL,
        help=f"两步修复用的非思考 json_object 模型。默认：%(default)s。",
    )
    return parser.parse_args()


def validate_configuration() -> None:
    if not API_KEY.strip() or API_KEY == "请在这里填写你的阿里云百炼API_KEY":
        raise ValueError(
            "尚未配置 API Key。请设置环境变量 DASHSCOPE_API_KEY 为你的阿里云百炼 API Key。"
        )


# =============================================================================
# 入口
# =============================================================================

def main() -> int:
    configure_console_encoding()

    try:
        args = parse_arguments()
        validate_configuration()
        image_source, _label = prepare_image_input(args.image)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    thinking_decision = resolve_thinking_choice(args.model, args.thinking)
    _, _, notice = thinking_decision
    if notice:
        print(notice, file=sys.stderr)

    expect_reasoning = (
        (thinking_decision[0] and thinking_decision[1] is True)
        or classify_model(args.model) == "always"
    )
    if expect_reasoning:
        print("=" * 24 + " 模型原始 reasoning_content " + "=" * 24)
        print(flush=True)

    reasoning_received = False

    def on_reasoning(text: str) -> None:
        nonlocal reasoning_received
        reasoning_received = True
        print(text, end="", flush=True)

    try:
        result = generate_observation(
            image_source,
            model=args.model,
            thinking=args.thinking,
            repair_model=args.repair_model,
            on_reasoning=on_reasoning,
        )
    except ObservationGenerationError as exc:
        if expect_reasoning and reasoning_received:
            print()
        print(f"\n\nStage 1 硬失败：{exc}", file=sys.stderr)
        return 3

    if expect_reasoning:
        print() if reasoning_received else print("（本次响应未收到 reasoning_content）")

    print()
    print("=" * 28 + " Observation (Stage 1) " + "=" * 28)
    print()
    print(result.observation.model_dump_json(indent=2, exclude_none=True))
    print()
    print(f"[meta] 经两步修复：{'是' if result.repaired else '否'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
