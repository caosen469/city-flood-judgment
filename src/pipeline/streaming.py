"""SSE event generation for ``POST /analyze/stream`` (ADR-0005 §6).

Wraps :func:`src.pipeline.service.iter_pipeline`, formatting each structured
:class:`PipelineEvent` as a Server-Sent-Events wire string::

    event: <type>\ndata: <json>\n\n

Event sequence (ADR-0005): ``thinking*`` → ``stage``×4 (observation /
grounding / context / knowledge) → ``done`` (full :class:`AnalysisResult`); on a
Stage-1 hard failure, a single ``error`` event replaces ``done`` and the stream
closes. The SSE payload shapes match ``docs/openapi.yaml``
(``SseThinking`` / ``SseStage`` / ``SseDone`` / ``SseError``).

The function returns a plain (sync) generator of complete SSE strings; Starlette
runs sync iterables in a threadpool, so the blocking VLM call does not stall the
event loop.
"""

from __future__ import annotations

import json
from typing import Iterator, Optional

from schemas.observation import LocationRef

from api.models import ErrorCode, StageName
from pipeline.service import (
    AnalysisError,
    Done,
    ImageInput,
    PipelineDeps,
    PipelineEvent,
    Stage,
    Thinking,
    iter_pipeline,
)


def format_sse(event: str, data: object) -> str:
    """One SSE message: ``event: <event>\\ndata: <json>\\n\\n``.

    ``data`` is JSON-encoded on a single line (``ensure_ascii=False`` so zh-CN
    reads in the browser). Pydantic models must be ``model_dump(mode="json")``-ed
    by the caller — here we only ever pass plain dicts/strings.
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _stage_payload(ev: Stage) -> dict:
    return {
        "stage": ev.stage.value,
        "data": ev.data.model_dump(mode="json"),
        "duration_ms": ev.duration_ms,
    }


def _error_code(err: AnalysisError) -> ErrorCode:
    if err.unreadable_image:
        return ErrorCode.UNREADABLE_IMAGE
    if err.json_invalid:
        return ErrorCode.VLM_JSON_INVALID
    return ErrorCode.VLM_PROVIDER_ERROR


def stream_pipeline(
    image: ImageInput,
    location: Optional[LocationRef],
    *,
    deps: PipelineDeps,
    request_id: Optional[str] = None,
    source_image: Optional[str] = None,
) -> Iterator[str]:
    """Yield SSE message strings for one analysis run.

    Consumes :func:`iter_pipeline` and maps each :class:`PipelineEvent` to its
    SSE wire form. The stream always terminates: either ``done`` (success) or
    ``error`` (Stage-1 hard failure), never both, never neither.
    """
    for ev in iter_pipeline(
        image,
        location,
        deps=deps,
        request_id=request_id,
        source_image=source_image,
    ):
        if isinstance(ev, Thinking):
            yield format_sse("thinking", {"delta": ev.delta})
        elif isinstance(ev, Stage):
            yield format_sse("stage", _stage_payload(ev))
        elif isinstance(ev, Done):
            yield format_sse("done", ev.result.model_dump(mode="json"))
        elif isinstance(ev, AnalysisError):
            yield format_sse(
                "error",
                {
                    "code": _error_code(ev).value,
                    "message": ev.message,
                    "stage": ev.stage.value,
                },
            )
            return


# Re-export for convenience so callers can ``from pipeline.streaming import StageName``.
__all__ = ["format_sse", "stream_pipeline", "StageName"]
