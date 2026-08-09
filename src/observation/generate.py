"""Stage 1 generator: ``image -> Observation`` (ADR-0005 §5).

Strategy (locked by ADR-0005 §5, constrained by DashScope facts):

* ``response_format={"type": "json_object"}`` — ``json_schema`` strict mode is
  **not** supported for any Qwen3-VL model.
* The prompt-embedded schema is rendered from ``Observation.model_json_schema()``
  (single source of truth — see :mod:`src.observation.prompt`).
* **No ``max_tokens``** — the official guidance warns it can truncate JSON.
* ``enable_thinking`` is passed via ``extra_body`` per the thinking-mode cross
  table (reused from :mod:`src.vlm.client`).
* Streamed content is collected, parsed, and validated with
  ``Observation.model_validate``.
* On a parse/validation failure: **two-step repair** — re-call a non-thinking
  ``json_object`` model to fix the JSON, then re-validate. Still failing ⇒
  Stage 1 hard-fails (:class:`ObservationGenerationError`).

The returned ``Observation`` carries no ``meta`` — the pipeline stamps it.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from openai import OpenAI
from pydantic import ValidationError

from schemas.observation import Observation
from vlm.client import (
    build_extra_body,
    make_client,
    resolve_thinking_choice,
)
from vlm.reasoning import get_reasoning_content

from .prompt import build_observation_prompt

# Default Stage 1 model: a hybrid-thinking VL model — json_object + toggleable
# thinking. Thinking is on by default (richer reasoning); the two-step repair
# absorbs any non-standard JSON that thinking + json_object may produce.
DEFAULT_MODEL = "qwen3-vl-plus"

# Repair model: same family, thinking forced off → a clean json_object emitter
# used to fix a broken JSON from the (possibly thinking) first pass.
REPAIR_MODEL = "qwen3-vl-plus"

ReasoningCallback = Callable[[str], None]
ContentCallback = Callable[[str], None]


class ObservationGenerationError(RuntimeError):
    """Stage 1 hard failure — the VLM call or JSON repair failed."""


# --------------------------------------------------------------------------- #
# Image input preparation (URL or local file → API-ready source).             #
# --------------------------------------------------------------------------- #


def validate_image_url(image_url: str) -> str:
    image_url = image_url.strip()
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("图片地址必须是有效的 http:// 或 https:// URL。")
    if any(char.isspace() for char in image_url):
        raise ValueError("图片 URL 中不能包含空格。")
    return image_url


def prepare_image_input(image_arg: str) -> tuple[str, str]:
    """Return ``(api_image_source, display_label)``.

    Local file → base64 data URL; http(s) URL → kept as-is.
    """
    image_arg = image_arg.strip()
    path = Path(image_arg)
    if path.is_file():
        mime, _ = mimetypes.guess_type(str(path))
        if not mime or not mime.startswith("image/"):
            raise ValueError(f"无法识别的图片类型：{path.name}")
        data = path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}", str(path)
    return validate_image_url(image_arg), image_arg


# --------------------------------------------------------------------------- #
# JSON extraction / parsing.                                                  #
# --------------------------------------------------------------------------- #


_FENCED_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _extract_json_text(raw: str) -> str:
    """Strip markdown fences; fall back to the outermost {...} span."""
    text = raw.strip()
    m = _FENCED_RE.fullmatch(text)
    if m:
        return m.group(1).strip()
    # Tolerate stray leading/trailing prose by carving out the JSON object.
    if text.startswith("{"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse_and_validate(raw: str) -> Observation:
    text = _extract_json_text(raw)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _ParseFailure(f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列 — {exc.msg}")
    if not isinstance(payload, dict):
        raise _ParseFailure("JSON 顶层不是对象。")
    try:
        return Observation.model_validate(payload)
    except ValidationError as exc:
        raise _ParseFailure("Observation 校验失败：" + str(exc))


class _ParseFailure(Exception):
    """Internal: a recoverable parse/validation failure triggering repair."""


# --------------------------------------------------------------------------- #
# Streaming call.                                                             #
# --------------------------------------------------------------------------- #


def _stream_completion(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    extra_body: dict[str, Any],
    on_reasoning: ReasoningCallback | None,
    on_content: ContentCallback | None,
) -> str:
    """Run one streamed ``json_object`` completion; return the full content."""
    parts: list[str] = []
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        response_format={"type": "json_object"},
        # ADR-0005 §5: no max_tokens (truncation risk for JSON).
        extra_body=extra_body,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = get_reasoning_content(delta)
        if reasoning and on_reasoning:
            on_reasoning(reasoning)
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
            if on_content:
                on_content(content)
    return "".join(parts).strip()


def _repair_json(
    client: OpenAI,
    *,
    repair_model: str,
    raw_broken: str,
) -> str:
    """Two-step repair: a non-thinking json_object model re-emits valid JSON."""
    thinking_decision = resolve_thinking_choice(repair_model, "off")
    extra_body = build_extra_body(thinking_decision)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 JSON 修复器。用户会给你一段损坏的 JSON 和目标 JSON Schema。"
                "请输出一个**严格符合 schema 的合法 JSON**，且只输出 JSON——"
                "不要解释、不要代码围栏、不要任何 JSON 以外的文字。"
                "保留原文中所有可用信息，丢弃无法解析的多余文本。"
            ),
        },
        {
            "role": "user",
            "content": (
                "目标 JSON Schema：\n"
                f"{json.dumps(Observation.model_json_schema(), ensure_ascii=False)}\n\n"
                "损坏的 JSON：\n"
                f"{raw_broken}"
            ),
        },
    ]
    return _stream_completion(
        client,
        model=repair_model,
        messages=messages,
        extra_body=extra_body,
        on_reasoning=None,
        on_content=None,
    )


# --------------------------------------------------------------------------- #
# Public entry point.                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GenerateResult:
    """Outcome of a Stage 1 generation."""

    observation: Observation
    raw_content: str
    repaired: bool


def generate_observation(
    image_source: str,
    *,
    model: str = DEFAULT_MODEL,
    thinking: str = "auto",
    repair_model: Optional[str] = None,
    client: OpenAI | None = None,
    on_reasoning: ReasoningCallback | None = None,
    on_content: ContentCallback | None = None,
) -> GenerateResult:
    """Generate an :class:`Observation` from one image.

    Parameters mirror the thinking-mode policy (``thinking`` = auto/on/off) and
    allow injecting a client (tests / shared lifespan) and streaming callbacks
    (CLI live print, future SSE ``thinking`` events).

    Raises:
        ObservationGenerationError: Stage 1 hard failure (empty content, or
            parse/validation failure that the two-step repair could not fix).
    """
    client = client or make_client()
    repair_model = repair_model or REPAIR_MODEL

    thinking_decision = resolve_thinking_choice(model, thinking)
    extra_body = build_extra_body(thinking_decision)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_source}},
                {"type": "text", "text": build_observation_prompt()},
            ],
        }
    ]

    try:
        raw = _stream_completion(
            client,
            model=model,
            messages=messages,
            extra_body=extra_body,
            on_reasoning=on_reasoning,
            on_content=on_content,
        )
    except Exception as exc:  # network / API errors → Stage 1 hard fail.
        raise ObservationGenerationError(f"VLM 调用失败：{type(exc).__name__}: {exc}") from exc

    if not raw:
        raise ObservationGenerationError("模型没有返回任何 content。")

    try:
        observation = _parse_and_validate(raw)
        return GenerateResult(observation=observation, raw_content=raw, repaired=False)
    except _ParseFailure as first_failure:
        # Two-step repair (ADR-0005 §5): non-thinking json_object model fixes JSON.
        try:
            repaired_raw = _repair_json(
                client, repair_model=repair_model, raw_broken=raw
            )
        except Exception as exc:
            raise ObservationGenerationError(
                f"JSON 修复调用失败：{type(exc).__name__}: {exc}"
            ) from exc
        if not repaired_raw:
            raise ObservationGenerationError(
                f"首段输出无法解析且修复模型返回空。首段错误：{first_failure}"
            )
        try:
            observation = _parse_and_validate(repaired_raw)
        except _ParseFailure as second_failure:
            raise ObservationGenerationError(
                "两步修复后仍无法解析/校验 Observation。"
                f"\n首段错误：{first_failure}\n修复后错误：{second_failure}"
            ) from second_failure
        return GenerateResult(observation=observation, raw_content=repaired_raw, repaired=True)
