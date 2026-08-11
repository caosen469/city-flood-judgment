"""The Analysis Pipeline (ADR-0005 §1-3).

Wires Stage 1/2/3 into the PRD §5.2 *Analysis Pipeline Seam*
``analyze(image, location, *, deps, request_id) -> AnalysisResult``. The seam's
testability comes from :class:`PipelineDeps` — every stage callable is
injectable, so PRD Case A–H run against ``analyze`` with no live VLM / network /
on-disk city data. See :mod:`src.pipeline.service` and
:mod:`src.pipeline.streaming`.
"""

from __future__ import annotations

from .service import (
    AnalysisError,
    Done,
    GroundingOutcome,
    ObservationImageError,
    PipelineDeps,
    PipelineEvent,
    Stage,
    Thinking,
    analyze,
    iter_pipeline,
    make_grounder,
    resolve_image_source,
)

__all__ = [
    "PipelineDeps",
    "PipelineEvent",
    "GroundingOutcome",
    "Thinking",
    "Stage",
    "Done",
    "AnalysisError",
    "ObservationImageError",
    "analyze",
    "iter_pipeline",
    "make_grounder",
    "resolve_image_source",
]
