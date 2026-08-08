#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
道路积水视觉研判 CLI。

使用方法：
    1. 将 API_KEY 修改为你的阿里云百炼 API Key。
    2. 安装依赖：
           pip install -r requirements.txt
    3. 运行：
           python waterlogging.py "https://example.com/road.jpg"

说明：
    - 图片 URL 必须能够被阿里云百炼服务从公网访问。
    - 程序不会创建日志文件。
    - 模型的原始 reasoning_content 会实时显示在终端。
    - 模型最终回复会被解析并格式化为 JSON。
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


# =============================================================================
# 配置区
# =============================================================================

# 按你的要求，API Key 直接定义在程序中。
# 请勿把填写了真实 API Key 的代码提交到 GitHub 或发送给他人。
# API Key 优先从环境变量 DASHSCOPE_API_KEY 读取（推荐，避免提交到 git）；
# 未设置时回退到源码中的占位符，运行前请在源码中填写你的 key。
API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
    "请在这里填写你的阿里云百炼API_KEY",
)

MODEL = "qwen3-vl-8b-thinking"

# 仅思考型模型名单（作为 `thinking` 关键字规则的补充，存放名字不含 thinking
# 后缀但确实仅支持思考模式的模型，例如部分 QwQ 系列变体）。
ALWAYS_THINKING_MODELS: set[str] = set()

# 混合思考型模型名单：支持通过 enable_thinking 控制开关。
HYBRID_THINKING_MODELS: set[str] = {
    "qwen3-vl-plus",
    "qwen3-vl-8b",
    # 新一代 Qwen 3.5/3.6/3.7 系列混合思考型模型。
    "qwen3.7-plus",
    "qwen3.7-plus-2026-05-26",
    "qwen3.6-plus",
    "qwen3.6-plus-2026-04-02",
    "qwen3.6-flash",
    "qwen3.6-flash-2026-04-16",
    "qwen3.5-27b",
}

# 中国内地（北京）公共兼容端点。
# 阿里云也提供业务空间专属端点：
# https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 该上限同时覆盖思考过程与最终回复。若输出被截断，可适当调大。
MAX_TOKENS = 8192

PROMPT_TEMPLATE = r"""
你是一名城市道路积水智能研判专家。请根据输入的一张道路图片，判断画面中是否存在积水，并在视觉证据充分时估算积水深度等级。

输入信息
• 待分析图片：__IMAGE_URL__
• 场景位置或道路名称：未知
• 已知尺寸参照物：无
• 其他补充信息：无

已知尺寸参照物可以包括：路缘石、台阶、道路标线、井盖、车辆轮胎、交通锥、护栏、砖块或其他尺寸相对固定的物体。

分析目标
请完成以下任务：
1. 判断图片中是否存在真实积水。
2. 区分以下容易混淆的情况：
  • 真实积水；
  • 路面潮湿；
  • 阴影；
  • 车辆灯光、路灯或阳光反射；
  • 路面材质产生的镜面反光；
  • 镜头污渍、水滴或成像异常。
3. 描述疑似积水区域的位置和大致边界。
4. 在存在可靠视觉参照时，估算积水深度区间或积水等级。
5. 分析积水对行人、非机动车和机动车通行可能造成的风险。

重点观察内容
请综合分析以下视觉特征：

1. 水面特征
观察是否存在：
• 连续或局部镜面反射；
• 周边建筑、车辆、路灯或天空的倒影；
• 水面波纹；
• 水面边界；
• 水体颜色或透明度变化；
• 水面与干燥路面的明显分界；
• 水面覆盖道路凹陷区域的现象。

注意：仅存在反光，不能直接证明一定有积水，更不能据此判断积水深度。

2. 尺度参照
观察画面中是否存在以下参照物：
• 路缘石；
• 台阶；
• 井盖；
• 道路标线；
• 车辆轮胎或轮毂；
• 行人鞋底；
• 交通锥；
• 护栏底座；
• 砖块或其他固定尺寸物体。

如参照物与水面交界清晰，可根据其被水覆盖的比例估算积水深度。
如参照物实际尺寸未知，只能用于粗略判断，不得作为精确厘米数的依据。

3. 物体与水面的关系
观察是否存在：
• 路缘石或台阶部分被水淹没；
• 井盖被水覆盖；
• 道路标线位于水面之下；
• 轮胎、鞋底或其他物体出现明确水位线；
• 车辆周边存在水波、水花或涉水痕迹；
• 水面高度接近车辆底盘、轮毂或排气口。

4. 场景合理性
结合以下因素判断：
• 积水是否集中在道路低洼区域；
• 是否靠近排水口、桥洞、下穿通道或路口；
• 积水边界是否符合道路坡度；
• 反射区域是否具有合理的水面形状；
• 阴影、强光或路面材质是否可能造成误判。

深度估算原则
不得仅根据反光强弱估算积水深度。
只有在画面中存在清晰水位线、已知尺寸物体、车辆轮胎、路缘石、台阶或其他可靠参照时，才能给出积水深度区间。
优先输出深度区间，不要输出看似精确但缺乏依据的单一数值。
至少存在两个相互支持的视觉证据时，才能给出“中”或“高”置信度。
当证据相互矛盾时，应扩大深度范围并降低置信度。

当存在以下情况时，应主动降低置信度：
• 图片模糊；
• 夜间拍摄；
• 强光或强反射；
• 雨水遮挡；
• 镜头有水滴或污渍；
• 积水区域被车辆或其他物体遮挡；
• 缺少尺寸参照物；
• 无法看到清晰水面边界；
• 摄像机视角过低或过高；
• 图片经过裁剪、压缩或明显变形。

积水深度等级
请按照以下标准进行分级：
• L0：无积水，或仅有轻微潮湿；
• L1：约0～3厘米，浅层积水，通常不明显影响机动车通行；
• L2：约3～10厘米，可能覆盖鞋底，对行人和非机动车造成一定影响；
• L3：约10～20厘米，对行人、小型车辆和非机动车产生明显影响；
• L4：约20～30厘米，可能接近普通小汽车轮毂下沿，车辆通行风险较高；
• L5：大于30厘米，可能造成车辆熄火、失控、漂移或人员涉水危险；
• LX：存在疑似积水，但证据不足，无法可靠估算深度。

以上深度等级仅用于视觉估算，不代表现场实测结果。

必须遵守的判断规则
1. 不得仅凭反光判断积水深度。
2. 不得因为画面中出现倒影，就直接认定存在较深积水。
3. 不得将潮湿路面、阴影或灯光反射直接判断为积水。
4. 不得在缺少尺度参照时编造精确厘米数。
5. 当无法可靠判断深度时：
  • 将积水等级设为“LX”；
  • 将深度数值设为null；
  • 明确说明证据不足的原因。
6. “没有看到水位线”不等于“没有积水”。
7. “存在明显反光”不等于“积水较深”。
8. 判断结论必须基于图片中实际可见内容，不得补充图片中不存在的车辆、行人、路缘石或其他参照物。
9. 如图片中无法确认是否存在真实积水，应输出“不确定”，而不是强行二选一。
10. 所有厘米数均为视觉估算值，必须同时提供置信度和判断依据。

输出格式
请严格按照以下 JSON 格式输出，不要输出 JSON 之外的其他文字：
{
  "waterlogging_status": "存在/不存在/不确定",
  "waterlogging_probability": 0.00,
  "waterlogging_level": "L0/L1/L2/L3/L4/L5/LX",
  "estimated_depth_cm": {
    "min": null,
    "max": null,
    "most_likely": null
  },
  "confidence": "高/中/低",
  "water_area_description": "描述疑似积水区域在图片中的位置、范围和边界，例如画面左下方、道路中央、路缘石附近等",
  "scene_observations": {
    "road_surface_condition": "干燥/潮湿/疑似积水/明确积水/无法判断",
    "reflection_present": true,
    "reflection_type": "水面倒影/潮湿路面反光/灯光反射/阴影/镜头异常/未知",
    "visible_water_boundary": true,
    "visible_ripple_or_wave": false,
    "visible_waterline": false
  },
  "reference_objects": [
    {
      "object": "参照物名称",
      "known_size": "已知尺寸或未知",
      "visible_relation_to_water": "参照物与疑似水面的关系",
      "reliability": "高/中/低"
    }
  ],
  "visual_evidence": [
    {
      "evidence": "图片中实际观察到的具体视觉现象",
      "supports": "该证据支持存在积水、不存在积水或某一深度等级",
      "reliability": "高/中/低"
    }
  ],
  "alternative_explanations": [
    {
      "possibility": "潮湿路面、阴影、灯光反射、镜头污渍等其他可能解释",
      "likelihood": "高/中/低",
      "reason": "判断原因"
    }
  ],
  "traffic_risk": {
    "pedestrian": "低/中/高/严重/无法判断",
    "non_motor_vehicle": "低/中/高/严重/无法判断",
    "motor_vehicle": "低/中/高/严重/无法判断"
  },
  "uncertainty_reasons": [
    "影响判断准确性的因素"
  ],
  "additional_data_needed": [
    "提高判断准确率所需要的补充信息，例如现场水尺、路缘石高度、其他角度图片或历史无积水图片"
  ],
  "conclusion": "使用一至三句话给出最终研判，说明是否存在积水、可能的深度等级以及结论的不确定性"
}

数值填写要求
• waterlogging_probability必须为0到1之间的小数；
• 如果判断不存在积水，waterlogging_level应设为L0；
• 如果确认存在积水但无法估算深度，waterlogging_level应设为LX；
• 如果缺少可靠尺寸参照，estimated_depth_cm中的min、max和most_likely应全部填写null；
• 只有在存在清晰、可靠的尺寸参照和水位关系时，才能填写estimated_depth_cm；
• 置信度为“低”时，原则上不要填写most_likely；
• 不得为了填满字段而虚构证据；
• 如果画面中没有参照物，reference_objects输出空数组；
• 如果没有合理的替代解释，alternative_explanations可以输出空数组。
""".strip()


# =============================================================================
# 工具函数
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
        description="调用阿里云百炼 Qwen3-VL 研判道路图片中的积水情况。"
    )
    parser.add_argument(
        "image_url",
        help="公网可访问的道路图片 URL，例如 https://example.com/road.jpg",
    )
    parser.add_argument(
        "--model",
        default=MODEL,
        help=(
            "被测模型名。仅思考型（含 thinking 关键字）：qwen3-vl-8b-thinking、"
            "qwen3-vl-4b-thinking、qwen3-vl-2b-thinking；混合思考型："
            "qwen3-vl-plus、qwen3-vl-8b；非思考型：qwen2.5-vl-7b-instruct、"
            "qwen-vl-plus 等。默认：%(default)s"
        ),
    )
    parser.add_argument(
        "--thinking",
        choices=["auto", "on", "off"],
        default="auto",
        help=(
            "思考模式开关。auto：按模型档位自动决定；on：显式开启；"
            "off：显式关闭。默认：%(default)s"
        ),
    )
    return parser.parse_args()


def classify_model(model: str) -> str:
    """
    将模型名归入三档之一：`"always"` / `"hybrid"` / `"non"`。

    判定顺序：
      1. 名字包含 `thinking`（大小写不敏感）→ always
      2. 在 ALWAYS_THINKING_MODELS → always
      3. 在 HYBRID_THINKING_MODELS → hybrid
      4. 其余 → non（保守策略，不发参与避免 API 报错）
    """
    name = model.strip()
    lower = name.lower()
    if "thinking" in lower:
        return "always"
    if name in ALWAYS_THINKING_MODELS:
        return "always"
    if name in HYBRID_THINKING_MODELS:
        return "hybrid"
    return "non"


def resolve_thinking_choice(
    model: str, thinking_arg: str
) -> tuple[bool, bool | None, str | None]:
    """
    根据模型分类与 `--thinking` 参数，决定本次调用的发参与提示行为。

    返回三元组 `(should_send_param, enable_thinking_value, notice)`：
      - `should_send_param`：是否在 extra_body 中放入 enable_thinking。
      - `enable_thinking_value`：若发送，对应的布尔值；否则为 None。
      - `notice`：需要打印到 stderr 的降级/无效提示；无提示时为 None。

    交叉语义表（详见 spec）：
      | thinking | ALWAYS       | HYBRID          | NON               |
      | auto     | 不发参       | 发 True         | 不发参            |
      | on       | 不发参       | 发 True         | 降级：不发参+提示 |
      | off      | 不发参+提示  | 发 False        | 不发参            |
    """
    category = classify_model(model)

    if category == "always":
        if thinking_arg == "off":
            return (
                False,
                None,
                f"提示：模型 {model} 为仅思考型，--thinking off 对该模型无效，"
                "仍会输出思考过程。",
            )
        # auto / on：ALWAYS 模型不发参（发了也无效），但会输出思考。
        return False, None, None

    if category == "hybrid":
        if thinking_arg == "off":
            return True, False, None
        # auto / on：开启思考。
        return True, True, None

    # NON：不支持 enable_thinking，任何情况都不发参。
    if thinking_arg == "on":
        return (
            False,
            None,
            f"提示：模型 {model} 不支持思考模式，已忽略 --thinking on，"
            "本次不会输出思考过程。",
        )
    # auto / off：静默不发参。
    return False, None, None


def validate_configuration() -> None:
    if not API_KEY.strip() or API_KEY == "请在这里填写你的阿里云百炼API_KEY":
        raise ValueError(
            "尚未配置 API Key。请打开 waterlogging.py，"
            "将 API_KEY 修改为你的阿里云百炼 API Key。"
        )


def validate_image_url(image_url: str) -> str:
    image_url = image_url.strip()
    parsed = urlparse(image_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("图片地址必须是有效的 http:// 或 https:// URL。")

    if any(char.isspace() for char in image_url):
        raise ValueError("图片 URL 中不能包含空格。")

    return image_url


def prepare_image_input(image_arg: str) -> tuple[str, str]:
    """
    处理图片输入：
    - 本地文件路径：读取并转为 base64 data URL（百炼 OpenAI 兼容模式直接支持）；
    - http/https URL：保持原有校验。

    返回 (用于 API 调用的图片源, 用于提示词中的展示标签)。
    """
    image_arg = image_arg.strip()
    path = Path(image_arg)

    if path.is_file():
        mime, _ = mimetypes.guess_type(str(path))
        if not mime or not mime.startswith("image/"):
            raise ValueError(f"无法识别的图片类型：{path.name}")
        data = path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        return data_url, str(path)

    return validate_image_url(image_arg), image_arg


def get_reasoning_content(delta: Any) -> str | None:
    """
    兼容不同 OpenAI SDK 版本读取百炼扩展字段 reasoning_content。
    """
    value = getattr(delta, "reasoning_content", None)
    if isinstance(value, str):
        return value

    model_extra = getattr(delta, "model_extra", None)
    if isinstance(model_extra, dict):
        extra_value = model_extra.get("reasoning_content")
        if isinstance(extra_value, str):
            return extra_value

    return None


def parse_json_response(raw_text: str) -> Any:
    """
    解析模型最终回复。

    这里只移除常见 Markdown JSON 代码围栏，不会补写、改造或猜测 JSON。
    解析失败时，由主程序直接显示原始回复。
    """
    text = raw_text.strip()
    fenced_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_match:
        text = fenced_match.group(1).strip()

    return json.loads(text)


def validate_basic_result(result: Any) -> list[str]:
    """
    对关键字段做轻量校验。只产生终端警告，不修改模型结果。
    """
    warnings: list[str] = []

    if not isinstance(result, dict):
        return ["最终 JSON 的顶层必须是对象。"]

    required_keys = {
        "waterlogging_status",
        "waterlogging_probability",
        "waterlogging_level",
        "estimated_depth_cm",
        "confidence",
        "water_area_description",
        "scene_observations",
        "reference_objects",
        "visual_evidence",
        "alternative_explanations",
        "traffic_risk",
        "uncertainty_reasons",
        "additional_data_needed",
        "conclusion",
    }

    missing = sorted(required_keys - result.keys())
    if missing:
        warnings.append("缺少字段：" + ", ".join(missing))

    status = result.get("waterlogging_status")
    if status not in {"存在", "不存在", "不确定"}:
        warnings.append("waterlogging_status 不在允许值中。")

    level = result.get("waterlogging_level")
    if level not in {"L0", "L1", "L2", "L3", "L4", "L5", "LX"}:
        warnings.append("waterlogging_level 不在允许值中。")

    confidence = result.get("confidence")
    if confidence not in {"高", "中", "低"}:
        warnings.append("confidence 不在允许值中。")

    probability = result.get("waterlogging_probability")
    if (
        isinstance(probability, bool)
        or not isinstance(probability, (int, float))
        or not 0 <= probability <= 1
    ):
        warnings.append("waterlogging_probability 必须是 0 到 1 之间的数值。")

    if status == "不存在" and level != "L0":
        warnings.append("判断不存在积水时，waterlogging_level 应为 L0。")

    return warnings


# =============================================================================
# 模型调用
# =============================================================================

def analyze_image(
    image_source: str,
    image_label: str,
    model: str,
    thinking_decision: tuple[bool, bool | None, str | None],
) -> int:
    should_send_param, enable_thinking_value, notice = thinking_decision

    # 预期本次会返回思考内容的条件：显式开启思考的混合型，或仅思考型。
    expect_reasoning = (
        should_send_param and enable_thinking_value is True
    ) or classify_model(model) == "always"

    if notice:
        print(notice, file=sys.stderr)

    prompt = PROMPT_TEMPLATE.replace("__IMAGE_URL__", image_label)

    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=180.0,
        max_retries=1,
    )

    # 仅在预期返回思考时才打印思考区块标题，避免非思考模型输出噪声。
    if expect_reasoning:
        print("=" * 24 + " 模型原始 reasoning_content " + "=" * 24)
        print(flush=True)

    # 动态构造 extra_body：不发参时使用空字典（字段完全不出现）。
    extra_body: dict[str, Any] = {}
    if should_send_param:
        extra_body["enable_thinking"] = enable_thinking_value

    reasoning_received = False
    answer_parts: list[str] = []

    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_source},
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            stream=True,
            stream_options={"include_usage": True},
            response_format={"type": "json_object"},
            max_tokens=MAX_TOKENS,
            extra_body=extra_body,
        )

        for chunk in stream:
            if not chunk.choices:
                # 最后一个只有 usage 的数据块无需显示。
                continue

            delta = chunk.choices[0].delta

            reasoning = get_reasoning_content(delta)
            if reasoning:
                reasoning_received = True
                print(reasoning, end="", flush=True)

            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                answer_parts.append(content)

    except APITimeoutError:
        print("\n\n调用失败：请求超时。", file=sys.stderr)
        return 3
    except APIConnectionError as exc:
        print(
            "\n\n调用失败：无法连接到阿里云百炼。"
            "请检查网络、BASE_URL，以及图片 URL 是否可从公网访问。",
            file=sys.stderr,
        )
        print(f"详细信息：{exc}", file=sys.stderr)
        return 3
    except APIStatusError as exc:
        print(
            f"\n\n调用失败：百炼 API 返回 HTTP {exc.status_code}。",
            file=sys.stderr,
        )
        print(f"详细信息：{exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\n\n用户已中断请求。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\n\n调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    # 兜底提示仅在打印了思考区块的前提下才会出现。
    if expect_reasoning:
        if reasoning_received:
            print()
        else:
            print("（本次响应未收到 reasoning_content）")

    raw_answer = "".join(answer_parts).strip()

    print()
    print("=" * 30 + " 最终研判 JSON " + "=" * 30)
    print()

    if not raw_answer:
        print("错误：模型没有返回最终 content。", file=sys.stderr)
        return 4

    try:
        result = parse_json_response(raw_answer)
    except json.JSONDecodeError as exc:
        print(
            "错误：模型最终回复不是合法 JSON；程序不会自动修补或重试。",
            file=sys.stderr,
        )
        print(
            f"解析位置：第 {exc.lineno} 行，第 {exc.colno} 列；{exc.msg}",
            file=sys.stderr,
        )
        print("\n========== 模型原始最终回复 ==========\n")
        print(raw_answer)
        return 5

    print(json.dumps(result, ensure_ascii=False, indent=2))

    warnings = validate_basic_result(result)
    if warnings:
        print("\n========== JSON 字段校验警告 ==========", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    return 0


def main() -> int:
    configure_console_encoding()

    try:
        args = parse_arguments()
        validate_configuration()
        image_source, image_label = prepare_image_input(args.image_url)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    thinking_decision = resolve_thinking_choice(args.model, args.thinking)

    return analyze_image(
        image_source,
        image_label,
        model=args.model,
        thinking_decision=thinking_decision,
    )


if __name__ == "__main__":
    raise SystemExit(main())
