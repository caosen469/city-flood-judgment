"""Reusable VLM machinery for the city-waterlogging demo.

Extracted from the legacy ``src/waterlogging.py`` (ADR-0005 §7) so that Stage 1
(``src/observation/``) and later LLM-driven stages share one Qwen client factory
and the thinking-mode cross table guarded by ``tests/test_thinking_mode.py``.
"""

from .client import (
    ALWAYS_THINKING_MODELS,
    HYBRID_THINKING_MODELS,
    BASE_URL,
    classify_model,
    make_client,
    resolve_thinking_choice,
)
from .reasoning import get_reasoning_content

__all__ = [
    "ALWAYS_THINKING_MODELS",
    "HYBRID_THINKING_MODELS",
    "BASE_URL",
    "classify_model",
    "make_client",
    "resolve_thinking_choice",
    "get_reasoning_content",
]
