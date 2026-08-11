"""Streaming reader for DashScope's ``reasoning_content`` extension field.

Different OpenAI SDK versions surface the field differently, so this helper
papers over the variations. Extracted verbatim from the legacy
``src/waterlogging.py`` (ADR-0005 §7).
"""

from __future__ import annotations

from typing import Any


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
