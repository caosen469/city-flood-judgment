"""Request / response envelopes for the FastAPI API (ADR-0005).

The nested stage models (``Observation`` / ``GroundedEntity`` / ``UrbanContext``
/ ``KnowledgeResult``) are the single source of truth in ``src/schemas/``; this
module only defines the **flat top-level envelope** and the request/SSE shapes
that wrap them. Degradation is read off the nested-model fields (grounding
status, per-block availability, eligibility-gated absent knowledge items) —
there is intentionally **no** per-stage ``StageResult`` wrapper (ADR-0005 §2).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from schemas.context import UrbanContext
from schemas.grounding import GroundedEntity
from schemas.knowledge import KnowledgeResult
from schemas.observation import Observation


# =========================================================================== #
# Top-level response envelope.                                                #
# =========================================================================== #


class AnalysisResult(BaseModel):
    """The flat envelope produced by the pipeline seam (ADR-0005 §2).

    The four nested models carry their own degradation signals; ``timings`` is
    demo-only instrumentation (not state). ``request_id`` (a uuid4 hex) threads
    the same identity through logs, the SSE ``done`` payload, and the
    Observation meta.
    """

    request_id: str
    observation: Observation
    grounding: GroundedEntity
    context: UrbanContext
    knowledge: KnowledgeResult
    timings: dict[str, float] = Field(
        default_factory=dict,
        description="各阶段耗时（毫秒）。键：observation / grounding / context / knowledge。",
    )


# =========================================================================== #
# Hard-failure error envelope (HTTP 422 / 502; SSE `error` event payload).    #
# =========================================================================== #


class ErrorCode(str, Enum):
    """The only failures that abort the pipeline (ADR-0005 §4). Everything else
    is graceful degradation expressed inside ``AnalysisResult``."""

    UNREADABLE_IMAGE = "unreadable_image"  # not an image / bad URL → 422
    VLM_PROVIDER_ERROR = "vlm_provider_error"  # DashScope timeout / 5xx → 502
    VLM_JSON_INVALID = "vlm_json_invalid"  # JSON repair still failed → 502
    INTERNAL_ERROR = "internal_error"  # anything unexpected → 500


class StageName(str, Enum):
    """The four pipeline stages, in execution order. Used both by the SSE
    ``stage`` event (success) and the ``error`` event's ``stage`` field
    (where the hard failure occurred)."""

    OBSERVATION = "observation"
    GROUNDING = "grounding"
    CONTEXT = "context"
    KNOWLEDGE = "knowledge"


class ErrorBody(BaseModel):
    """JSON body of an error HTTP response, and the SSE ``error`` event data."""

    code: ErrorCode
    message: str
    stage: Optional[StageName] = None


# =========================================================================== #
# Request input — location (mirrors LocationRef; all fields optional).        #
# =========================================================================== #


class LocationRefInput(BaseModel):
    """Mirror of :class:`schemas.observation.LocationRef` for the request body.

    All fields optional; an all-None value means "no location supplied" and the
    pipeline walks the ``no_location`` degradation path.
    """

    lat: Optional[float] = None
    lon: Optional[float] = None
    road_name: Optional[str] = None
    raw_text: Optional[str] = None

    def is_empty(self) -> bool:
        return all(
            v is None or (isinstance(v, str) and not v.strip())
            for v in (self.lat, self.lon, self.road_name, self.raw_text)
        )


# =========================================================================== #
# SSE event payloads — the JSON shape carried in each event's `data:` line.   #
# =========================================================================== #


class SseThinking(BaseModel):
    delta: str


class SseStage(BaseModel):
    """One per stage, in order observation → grounding → context → knowledge."""

    stage: StageName
    data: dict  # the stage's output model, model_dump(mode="json")
    duration_ms: float


class SseError(BaseModel):
    code: ErrorCode
    message: str
    stage: Optional[StageName] = None
