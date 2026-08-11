# -*- coding: utf-8 -*-
"""Shared builders for pipeline-seam tests (#15).

These stand in for the four stage callables so PRD Case A–H run against
``analyze()`` / ``iter_pipeline()`` with **no live VLM, no network, no on-disk
city data** — the property ADR-0005 §1 requires of the seam. They reuse the
schema-level fixtures in :mod:`tests._knowledge_fixtures` so the synthetic
Observation / GroundedEntity / UrbanContext shapes stay identical across the
knowledge and pipeline test suites.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _knowledge_fixtures import make_context, make_grounded, make_observation  # noqa: E402

from pipeline.service import GroundingOutcome, PipelineDeps  # noqa: E402
from schemas.grounding import (  # noqa: E402
    GroundedEntity,
    LatLon,
    LocatedPoint,
    LocationSource,
)
from schemas.observation import (  # noqa: E402
    LocationRef,
    Observation,
)
from observation.generate import GenerateResult  # noqa: E402

DUMMY_IMAGE_URL = "https://example.com/waterlogging.png"


def fake_generate(
    observation: Observation,
    *,
    reasoning_deltas: Optional[Iterable[str]] = None,
    raw_content: str = "{}",
):
    """A stand-in for ``observation.generate.generate_observation``.

    Returns a :class:`GenerateResult` wrapping ``observation`` (whose ``meta`` is
    left None — the pipeline stamps it). Streams any ``reasoning_deltas`` through
    the ``on_reasoning`` callback so SSE ``thinking`` events can be exercised.
    """

    def _generate(image_source, *, model=None, thinking=None, on_reasoning=None, **kwargs):
        for delta in reasoning_deltas or ():
            if on_reasoning is not None:
                on_reasoning(delta)
        return GenerateResult(observation=observation, raw_content=raw_content, repaired=False)

    return _generate


class FakeContextAssembler:
    """Returns a fixed :class:`UrbanContext`, ignoring the located point.

    Matches :meth:`ContextAssembler.assemble`'s signature so it slots into
    :class:`PipelineDeps` directly.
    """

    def __init__(self, context) -> None:
        self.context = context
        self.calls: list[tuple] = []

    def assemble(self, point, grounding, *, source_location=None):
        self.calls.append((point, grounding, source_location))
        return self.context


def fake_ground_with_point(entity: GroundedEntity):
    """A Stage-2a fake that also hands the pipeline a LocatedPoint (the normal,
    point-bearing case — Context will be assembled)."""

    def _ground(ref: Optional[LocationRef]) -> GroundingOutcome:
        pt = entity.query_point
        located = (
            LocatedPoint(
                point=LatLon(lat=pt.lat, lon=pt.lon),
                source=LocationSource.USER_LATLON,
            )
            if pt is not None
            else None
        )
        return GroundingOutcome(located=located, entity=entity)

    return _ground


def fake_ground_no_point(entity: GroundedEntity):
    """A Stage-2a fake for the no-point case (no_location / geocode_failed):
    no LocatedPoint ⇒ the pipeline skips Context assembly."""

    def _ground(ref: Optional[LocationRef]) -> GroundingOutcome:
        return GroundingOutcome(located=None, entity=entity)

    return _ground


def recording_ground(entity: GroundedEntity):
    """Like :func:`fake_ground_with_point`, but records the LocationRef it
    received — for asserting ``visible_location_text`` fallback wiring."""

    seen: list[Optional[LocationRef]] = []
    inner = fake_ground_with_point(entity)

    def _ground(ref: Optional[LocationRef]) -> GroundingOutcome:
        seen.append(ref)
        return inner(ref)

    _ground.seen = seen  # type: ignore[attr-defined]
    return _ground


def build_deps(
    *,
    observation: Optional[Observation] = None,
    entity: Optional[GroundedEntity] = None,
    context=None,
    reasoning_deltas: Optional[Iterable[str]] = None,
    ground=None,
    use_real_engine: bool = True,
) -> PipelineDeps:
    """Assemble a :class:`PipelineDeps` from synthetic stages.

    Defaults: a present-water L3 Observation, a grounded entity, and a
    moderately-low-lying context — the Case-C "low-lying" configuration that
    *should* yield a TerrainRisk. Per-test overrides vary one input at a time.
    """
    from knowledge import KnowledgeEngine

    observation = observation or make_observation()
    entity = entity or make_grounded()
    context = context or make_context()
    ground = ground or fake_ground_with_point(entity)

    engine = KnowledgeEngine(client=None) if use_real_engine else SimpleNamespace()

    return PipelineDeps(
        generate_observation=fake_generate(observation, reasoning_deltas=reasoning_deltas),
        ground=ground,
        context_assembler=FakeContextAssembler(context),
        knowledge_engine=engine,
    )


def terrain_item(result):
    """The TerrainRisk item of a result, or None."""
    from schemas.knowledge import TerrainRiskKnowledge

    return next(
        (i for i in result.knowledge.knowledge_items if isinstance(i, TerrainRiskKnowledge)),
        None,
    )


def road_item(result):
    from schemas.knowledge import RoadImpactKnowledge

    return next(
        (i for i in result.knowledge.knowledge_items if isinstance(i, RoadImpactKnowledge)),
        None,
    )
