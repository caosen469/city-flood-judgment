"""OpenAI-compatible Qwen (DashScope) client factory + thinking-mode policy.

This module is the single home of the thinking-mode cross table — a non-trivial,
tested behavior (``tests/test_thinking_mode.py``) extracted verbatim from the
legacy ``src/waterlogging.py`` (ADR-0005 §7). Stage 1 and any later LLM-driven
stage reuse it instead of re-deriving the rules.

Thinking-mode background
------------------------
Qwen models come in three tiers w.r.t. the ``enable_thinking`` extra-body param:

* **always** — name contains ``thinking`` (or is listed): only supports thinking,
  ``enable_thinking`` is ignored.
* **hybrid** — listed in ``HYBRID_THINKING_MODELS``: ``enable_thinking`` toggles
  thinking on/off.
* **non** — neither: does not support thinking; sending ``enable_thinking`` is
  avoided to prevent API errors.

The cross table in :func:`resolve_thinking_choice` decides, per ``--thinking``
argument, whether to send the param at all and what notice (if any) to surface.
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

# DashScope API key. Read from the DASHSCOPE_API_KEY env var (recommended);
# the placeholder fallback makes a missing key loud at call time rather than
# silently leaking an empty header.
API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
    "请在这里填写你的阿里云百炼API_KEY",
)

# 中国内地（北京）公共兼容端点。
# 阿里云也提供业务空间专属端点：
# https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

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


def make_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 180.0,
    max_retries: int = 1,
) -> OpenAI:
    """Build an OpenAI-compatible Qwen client pointed at DashScope.

    Defaults read the module-level :data:`API_KEY` / :data:`BASE_URL`, which in
    turn read the environment, so callers normally pass nothing.
    """
    return OpenAI(
        api_key=api_key or API_KEY,
        base_url=base_url or BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
    )


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


def build_extra_body(thinking_decision: tuple[bool, bool | None, str | None]) -> dict[str, Any]:
    """Translate a ``resolve_thinking_choice`` decision into an ``extra_body``.

    When the param should not be sent, an empty dict is returned so the field
    never appears on the wire.
    """
    should_send_param, enable_thinking_value, _ = thinking_decision
    if not should_send_param:
        return {}
    return {"enable_thinking": enable_thinking_value}


def expects_reasoning(
    model: str, thinking_decision: tuple[bool, bool | None, str | None]
) -> bool:
    """Whether this call is expected to stream ``reasoning_content``.

    True for explicitly-enabled hybrid models and for always-thinking models.
    Used to decide whether to surface a thinking block in UI / SSE.
    """
    should_send_param, enable_thinking_value, _ = thinking_decision
    return (should_send_param and enable_thinking_value is True) or classify_model(model) == "always"
