"""``analyze(image, location) -> AnalysisResult`` — the pipeline seam (ADR-0005).

The whole pipeline is one function plus the generator that backs it. Stages run
in order with **no short-circuit** (ADR-0005 §3); degradation is expressed by
value in the nested models, never by aborting — the only abort is a Stage-1 VLM
hard failure (:class:`ObservationGenerationError`), which becomes an
:class:`AnalysisError` the API layer maps to HTTP 502 (or an SSE ``error``
event).

Design
------

* :class:`PipelineDeps` — the injectable seam. Holds the four stage callables so
  tests substitute fakes (Case A–H run with no VLM / network / city data). The
  production wiring lives in the FastAPI lifespan (:mod:`src.api.app`).
* :func:`iter_pipeline` — the single source of truth. Runs the three stages,
  yielding :class:`PipelineEvent`s (``Thinking`` deltas, then a ``Stage`` per
  stage, then ``Done`` with the full :class:`AnalysisResult`, or
  ``AnalysisError`` on a Stage-1 hard failure). Both endpoints consume it:
  streaming formats each event as SSE; ``analyze`` drains it for the final
  result.
* :func:`analyze` — the synchronous seam. Drains ``iter_pipeline``, re-raising
  an :class:`AnalysisError` as :class:`ObservationGenerationError` (the
  documented Stage-1 hard failure) so callers see the canonical exception.

Stage-2 note: the pipeline calls ``locate()`` then ``match()`` directly (rather
than the :func:`src.grounding.ground` convenience) because it needs the
:class:`LocatedPoint` to feed :meth:`ContextAssembler.assemble`. The
no-point→unresolved-reason mapping mirrors :func:`src.grounding.ground`; it is
kept inline so the LocatedPoint is not lost.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterator, Optional, Protocol, Union
from urllib.parse import urlparse
from uuid import uuid4

from schemas.context import UrbanContext
from schemas.grounding import (
    GroundedEntity,
    GroundingStatus,
    LocatedPoint,
    LocationSource,
    UnresolvedReason,
)
from schemas.knowledge import KnowledgeResult
from schemas.observation import (
    LocationRef,
    Observation,
    ObservationMeta,
)

from api.models import AnalysisResult, StageName
from observation.generate import (
    DEFAULT_MODEL as OBSERVATION_DEFAULT_MODEL,
    GenerateResult,
    ObservationGenerationError,
    validate_image_url,
)


# =========================================================================== #
# Image input — resolve a URL / path / bytes to an API-ready source string.    #
# =========================================================================== #


ImageInput = Union[str, bytes]
"""What ``analyze`` accepts as ``image``: a public URL, a local file path, or
raw image bytes. The resolver converts all three to the single ``image_source``
string the VLM client consumes (URL kept as-is; path/bytes → base64 data URL)."""


def resolve_image_source(image: ImageInput) -> tuple[str, str]:
    """Return ``(api_image_source, source_image_label)``.

    * ``http(s)`` URL  → kept as-is, label = the URL.
    * local file path  → base64 data URL, label = the path.
    * ``bytes``        → base64 data URL (mime from a magic-byte sniff, default
      ``image/jpeg``), label = ``"<uploaded bytes>"``.

    Raises ``ValueError`` on a non-http scheme or a path that is not a readable
    image file — the API layer maps that to HTTP 422 (``unreadable_image``).
    """
    if isinstance(image, (bytes, bytearray)):
        mime = _sniff_image_mime(bytes(image)) or "image/jpeg"
        encoded = base64.b64encode(bytes(image)).decode("ascii")
        return f"data:{mime};base64,{encoded}", "<uploaded bytes>"

    text = str(image).strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return validate_image_url(text), text

    path = Path(text)
    if path.is_file():
        mime, _ = mimetypes.guess_type(text)
        if not mime or not mime.startswith("image/"):
            raise ValueError(f"无法识别的图片类型：{path.name}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}", str(path)

    raise ValueError(
        "图片来源必须是公网 http(s) URL、本地图片路径或图片字节；"
        f"无法解析：{text!r}"
    )


def _sniff_image_mime(data: bytes) -> Optional[str]:
    """Best-effort MIME from magic bytes; ``None`` if unrecognized."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# =========================================================================== #
# Grounding outcome — the pipeline needs both the LocatedPoint and the entity. #
# =========================================================================== #


@dataclass(frozen=True)
class GroundingOutcome:
    """What Stage 2a returns to the pipeline.

    ``located`` is the point Context needs (``None`` for no_location /
    geocode_failed — there is genuinely no coordinate); ``entity`` always carries
    the three-state grounding result.
    """

    located: Optional[LocatedPoint]
    entity: GroundedEntity


def make_grounder(
    network: Any,
    *,
    geocoder: Optional[Callable[[str], Any]] = None,
    default_source: LocationSource = LocationSource.USER_LATLON,
) -> Callable[[Optional[LocationRef]], GroundingOutcome]:
    """Build the production Stage-2a callable around a loaded road network.

    Runs :func:`locate` then :func:`match`; a ``None`` from locate maps to the
    honest unresolved reason (``no_location`` vs ``geocode_failed``) — mirroring
    :func:`src.grounding.ground`, kept inline so the :class:`LocatedPoint`
    (needed by Context) is not discarded.
    """
    from grounding.locate import locate  # local import avoids module-level osmnx
    from grounding.match import match

    def ground(ref: Optional[LocationRef]) -> GroundingOutcome:
        located = locate(ref, source=default_source, geocoder=geocoder)
        if located is None:
            had_text = ref is not None and bool(
                (ref.raw_text or "").strip() or (ref.road_name or "").strip()
            )
            reason = (
                UnresolvedReason.GEOCODE_FAILED
                if had_text
                else UnresolvedReason.NO_LOCATION
            )
            entity = GroundedEntity(
                status=GroundingStatus.UNRESOLVED,
                query_point=None,
                source=LocationSource.NONE,
                unresolved_reason=reason,
            )
            return GroundingOutcome(located=None, entity=entity)

        entity = match(
            located.point.lat,
            located.point.lon,
            network=network,
            source=located.source,
            geocode_confidence=located.geocode_confidence,
        )
        return GroundingOutcome(located=located, entity=entity)

    return ground


# =========================================================================== #
# Injectable stage protocols (so tests can pass plain duck-typed fakes).       #
# =========================================================================== #


class _ObservationGenerator(Protocol):
    def __call__(
        self,
        image_source: str,
        *,
        model: str = ...,
        thinking: str = ...,
        on_reasoning: Optional[Callable[[str], None]] = ...,
        **kwargs: Any,
    ) -> GenerateResult: ...


class _ContextAssembler(Protocol):
    def assemble(
        self,
        point: LocatedPoint,
        grounding: GroundedEntity,
        *,
        source_location: Optional[str] = ...,
    ) -> UrbanContext: ...


class _KnowledgeEngine(Protocol):
    def assemble(
        self,
        observation: Observation,
        grounding: Optional[GroundedEntity],
        context: Optional[UrbanContext],
        *,
        on_reasoning: Optional[Callable[[str], None]] = ...,
    ) -> KnowledgeResult: ...


@dataclass
class PipelineDeps:
    """The injectable seam — the four stage callables + model policy.

    Production wiring (FastAPI lifespan) builds this from the loaded road
    network, the default context assembler, and a knowledge engine; tests pass
    fakes to exercise Case A–H with no VLM / network / city data.
    """

    generate_observation: _ObservationGenerator
    ground: Callable[[Optional[LocationRef]], GroundingOutcome]
    context_assembler: _ContextAssembler
    knowledge_engine: _KnowledgeEngine
    observation_model: str = OBSERVATION_DEFAULT_MODEL
    observation_thinking: str = "auto"


# =========================================================================== #
# Pipeline events — the structured stream iter_pipeline yields.               #
# =========================================================================== #


@dataclass
class Thinking:
    """A reasoning_content delta from Stage 1 (only thinking-type models)."""

    delta: str


@dataclass
class Stage:
    """A completed stage's output + its duration in milliseconds."""

    stage: StageName
    data: Any  # Observation | GroundedEntity | UrbanContext | KnowledgeResult
    duration_ms: float


@dataclass
class Done:
    """The authoritative aggregate (same shape as non-streaming /analyze)."""

    result: AnalysisResult


@dataclass
class AnalysisError:
    """A hard failure; the streaming layer emits an SSE ``error`` then closes.

    Exactly one of the booleans is True, picking the API error code:
    ``unreadable_image`` (HTTP 422), ``vlm_json_invalid`` (502), or
    ``vlm_provider_error`` (502).
    """

    message: str
    unreadable_image: bool = False
    json_invalid: bool = False
    stage: StageName = StageName.OBSERVATION


PipelineEvent = Union[Thinking, Stage, Done, AnalysisError]


# =========================================================================== #
# Helpers.                                                                     #
# =========================================================================== #


def _has_usable_location(ref: Optional[LocationRef]) -> bool:
    if ref is None:
        return False
    if ref.lat is not None and ref.lon is not None:
        return True
    return bool((ref.raw_text or "").strip() or (ref.road_name or "").strip())


def _effective_location(
    location: Optional[LocationRef], observation: Observation
) -> Optional[LocationRef]:
    """The LocationRef handed to Grounding.

    Priority: the explicit request location; failing that, the VLM-copied
    ``visible_location_text`` (ADR-0003 — an OSD/招牌地名 becomes a ``raw_text``
    geocode candidate). The VLM only *copies* visible text; it never geocodes —
    that stays Grounding's job.
    """
    if _has_usable_location(location):
        return location
    vlt = (observation.visible_location_text or "").strip()
    if vlt:
        return LocationRef(raw_text=vlt)
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stage1_error(exc: ObservationGenerationError) -> AnalysisError:
    msg = str(exc)
    json_invalid = any(
        kw in msg for kw in ("JSON", "解析", "校验", "修复", "parse", "validate")
    )
    return AnalysisError(message=msg, json_invalid=json_invalid)


# =========================================================================== #
# iter_pipeline — the single source of truth.                                 #
# =========================================================================== #


def iter_pipeline(
    image: ImageInput,
    location: Optional[LocationRef],
    *,
    deps: PipelineDeps,
    request_id: Optional[str] = None,
    source_image: Optional[str] = None,
) -> Iterator[PipelineEvent]:
    """Run Stage 1→2→3, yielding structured events.

    Emits, in order: zero-or-more ``Thinking`` deltas (only thinking models),
    then a ``Stage`` per stage (observation / grounding / context / knowledge),
    then ``Done`` with the full :class:`AnalysisResult`. A Stage-1 hard failure
    yields a single ``AnalysisError`` instead and stops.

    ``source_image`` (the original URL / filename / ``"<uploaded bytes>"``) is
    stamped onto ``Observation.meta.source_image``; if omitted it is derived
    from ``image`` when ``image`` is a string.

    Thinking deltas are buffered during the (blocking) Stage-1 VLM call and
    flushed immediately before the observation ``Stage`` event — matching the
    ADR-0005 SSE order (``thinking*`` precedes the first ``stage``).
    """
    request_id = request_id or uuid4().hex
    timings: dict[str, float] = {}

    try:
        image_source, label = resolve_image_source(image)
    except ValueError as exc:
        # Unreadable image is a pre-Stage-1 hard failure; the API layer maps it
        # to HTTP 422 (unreadable_image). Surfaced at the observation stage.
        yield AnalysisError(message=str(exc), unreadable_image=True)
        return

    source_image = source_image or label

    # ------------------------------------------------------------------ #
    # Stage 1 — image → Observation.                                      #
    # ------------------------------------------------------------------ #
    thinking_buf: list[str] = []
    t0 = perf_counter()
    try:
        gen = deps.generate_observation(
            image_source,
            model=deps.observation_model,
            thinking=deps.observation_thinking,
            on_reasoning=thinking_buf.append,
        )
    except ObservationGenerationError as exc:
        yield from (Thinking(delta=d) for d in thinking_buf)
        yield _stage1_error(exc)
        return
    timings["observation"] = (perf_counter() - t0) * 1000.0

    observation = gen.observation
    observation.meta = ObservationMeta(
        observation_id=request_id,
        source_image=source_image,
        observed_at=_now_utc(),
        source_location=_effective_location(location, observation),
    )
    yield from (Thinking(delta=d) for d in thinking_buf)
    yield Stage(StageName.OBSERVATION, observation, timings["observation"])

    # ------------------------------------------------------------------ #
    # Stage 2a — Grounding (locate → match).                              #
    # ------------------------------------------------------------------ #
    t0 = perf_counter()
    outcome = deps.ground(observation.meta.source_location)
    timings["grounding"] = (perf_counter() - t0) * 1000.0
    yield Stage(StageName.GROUNDING, outcome.entity, timings["grounding"])

    # ------------------------------------------------------------------ #
    # Stage 2b — Urban Context.                                           #
    # No located point (no_location / geocode_failed) ⇒ no context is     #
    # assembled — a degenerate empty UrbanContext (query_point=None) is   #
    # the honest representation (ADR-0005 §3, ADR-0002).                  #
    # ------------------------------------------------------------------ #
    t0 = perf_counter()
    if outcome.located is not None:
        context = deps.context_assembler.assemble(
            outcome.located,
            outcome.entity,
            source_location=_source_location_text(location, observation),
        )
    else:
        context = UrbanContext(query_point=None, blocks=[])
    timings["context"] = (perf_counter() - t0) * 1000.0
    yield Stage(StageName.CONTEXT, context, timings["context"])

    # ------------------------------------------------------------------ #
    # Stage 3 — Knowledge Engine (rules + LLM-assisted).                  #
    # ------------------------------------------------------------------ #
    t0 = perf_counter()
    knowledge = deps.knowledge_engine.assemble(
        observation, outcome.entity, context
    )
    timings["knowledge"] = (perf_counter() - t0) * 1000.0
    yield Stage(StageName.KNOWLEDGE, knowledge, timings["knowledge"])

    result = AnalysisResult(
        request_id=request_id,
        observation=observation,
        grounding=outcome.entity,
        context=context,
        knowledge=knowledge,
        timings=timings,
    )
    yield Done(result=result)


def _source_location_text(
    location: Optional[LocationRef], observation: Observation
) -> Optional[str]:
    """Free-text form of the location input, for the context query_point."""
    if location is not None:
        txt = (location.raw_text or "").strip() or (location.road_name or "").strip()
        if txt:
            return txt
    return (observation.visible_location_text or "").strip() or None


# =========================================================================== #
# analyze — the synchronous seam (drains iter_pipeline).                      #
# =========================================================================== #


class ObservationImageError(ObservationGenerationError):
    """An unreadable image surfaced through the seam. Subclasses the Stage-1
    error so existing callers' ``except ObservationGenerationError`` still
    catch it, while the API layer can branch to HTTP 422 vs 502."""


def analyze(
    image: ImageInput,
    location: Optional[LocationRef] = None,
    *,
    deps: PipelineDeps,
    request_id: Optional[str] = None,
    source_image: Optional[str] = None,
) -> AnalysisResult:
    """Run the full pipeline and return the :class:`AnalysisResult`.

    The PRD §5.2 seam. Drains :func:`iter_pipeline`; the only failure mode that
    escapes is a Stage-1 hard failure, raised as
    :class:`ObservationGenerationError` (subclass
    :class:`ObservationImageError` for an unreadable image) — the API layer maps
    those to HTTP 422 / 502.

    Every other condition (grounding unresolved, a context block unavailable, an
    eligibility-gated knowledge item) is graceful degradation *inside* the
    returned :class:`AnalysisResult`, never an exception (ADR-0005 §4).
    """
    request_id = request_id or uuid4().hex
    result: Optional[AnalysisResult] = None
    for event in iter_pipeline(
        image,
        location,
        deps=deps,
        request_id=request_id,
        source_image=source_image,
    ):
        if isinstance(event, Done):
            result = event.result
        elif isinstance(event, AnalysisError):
            if event.unreadable_image:
                raise ObservationImageError(event.message)
            raise ObservationGenerationError(event.message)
        # Thinking / Stage events are ignored by the non-streaming path.
    assert result is not None  # iter_pipeline always yields Done or AnalysisError
    return result
