# -*- coding: utf-8 -*-
"""Shared builders for knowledge-engine tests.

Synthetic :class:`Observation` / :class:`GroundedEntity` / :class:`UrbanContext`
instances that exercise the eligibility gates (Cases C/D/F, no-location, absent,
slightly_low). Kept here so the three knowledge test files build on identical
fixtures — and so they don't depend on the Stage 2 implementations (grounding/
context), only on the committed schemas.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from schemas.context import (
    Availability,
    BlockAvailability,
    ContextSource,
    ElevationContextBlock,
    HighwayClass,
    LownessClass,
    LownessScores,
    Provenance,
    QueryPoint,
    RoadContextBlock,
    TerrainContextBlock,
    UnavailabilityReason,
    UrbanContext,
)
from schemas.grounding import (
    GroundedEntity,
    GroundingStatus,
    LatLon,
    LocationSource,
    MatchedRoad,
    UnresolvedReason,
)
from schemas.observation import (
    Observation,
    VisualImpactHint,
    WaterloggingAttributes,
    WaterloggingLevel,
    WaterloggingStatus,
)

NOW = datetime(2026, 8, 9, 12, 0, 0)


def provenance(source: ContextSource = ContextSource.SRTM_LOCAL) -> Provenance:
    return Provenance(source=source, retrieved_at=NOW)


def make_observation(
    level: WaterloggingLevel = WaterloggingLevel.L3,
    status: WaterloggingStatus = WaterloggingStatus.PRESENT,
    hint: VisualImpactHint = VisualImpactHint.OBSTRUCTING,
) -> Observation:
    return Observation(
        presence_probability=0.85,
        waterlogging=WaterloggingAttributes(
            status=status, waterlogging_level=level, visual_impact_hint=hint
        ),
    )


def make_matched_road(distance_m: float = 8.0, highway: str = "primary") -> MatchedRoad:
    return MatchedRoad(
        osm_way_id="12345",
        edge_ref=(1, 2, 0),
        highway=highway,
        bridge=False,
        tunnel=False,
        match_point=LatLon(lat=22.7, lon=113.5),
        match_distance_m=distance_m,
    )


def make_grounded(
    status: GroundingStatus = GroundingStatus.GROUNDED,
    reason: UnresolvedReason | None = None,
    has_point: bool = True,
) -> GroundedEntity:
    point = LatLon(lat=22.7, lon=113.5) if has_point else None
    if status is GroundingStatus.UNRESOLVED:
        return GroundedEntity(
            status=status,
            query_point=point,
            source=LocationSource.USER_LATLON,
            unresolved_reason=reason or UnresolvedReason.OUTSIDE_NANSHA,
        )
    road = make_matched_road()
    return GroundedEntity(
        status=status,
        query_point=point,
        source=LocationSource.USER_LATLON,
        best_match=road,
        candidates=[road],
    )


def make_context(
    *,
    terrain_class: LownessClass | None = LownessClass.MODERATELY_LOW,
    terrain_composite: float | None = 1.24,
    terrain_available: bool = True,
    road_available: bool = True,
    highway: HighwayClass = HighwayClass.PRIMARY,
    is_tunnel: bool = False,
    is_bridge: bool = False,
) -> UrbanContext:
    blocks = []
    if road_available:
        blocks.append(
            RoadContextBlock(
                road_name="测试路",
                osm_way_id=12345,
                highway_class=highway,
                is_bridge=is_bridge,
                is_tunnel=is_tunnel,
                offset_distance_m=8.0,
                grounding_confidence=0.9,
                provenance=provenance(ContextSource.OSM),
            )
        )
    else:
        blocks.append(
            RoadContextBlock(
                availability=BlockAvailability(
                    status=Availability.UNAVAILABLE,
                    reason=UnavailabilityReason.GROUNDING_UNRESOLVED,
                ),
                provenance=provenance(ContextSource.OSM),
            )
        )

    if terrain_available:
        blocks.append(
            TerrainContextBlock(
                lowness=LownessScores(
                    composite=terrain_composite, lowness_class=terrain_class
                ),
                provenance=provenance(ContextSource.SRTM_LOCAL),
            )
        )
    else:
        blocks.append(
            TerrainContextBlock(
                availability=BlockAvailability(
                    status=Availability.UNAVAILABLE,
                    reason=UnavailabilityReason.NO_DATA_IN_BOUNDS,
                ),
                provenance=provenance(ContextSource.SRTM_LOCAL),
            )
        )

    blocks.append(ElevationContextBlock(elevation_pt=2.0, provenance=provenance()))
    return UrbanContext(query_point=QueryPoint(lat=22.7, lon=113.5), blocks=blocks)


class FakeCompletions:
    """Minimal OpenAI-compatible completions stub returning canned content.

    Non-streaming only (the knowledge inference default). Construct with the
    raw ``content`` string the "model" should return; ``calls`` records every
    invocation so tests can assert prompt wiring.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []

        class _Msg:
            def __init__(self, c: str) -> None:
                self.content = c

        class _Choice:
            def __init__(self, c: str) -> None:
                self.message = _Msg(c)

        class _Resp:
            def __init__(self, c: str) -> None:
                self.choices = [_Choice(c)]

        self._resp_cls = _Resp

    def create(self, **kwargs):  # noqa: ANN201
        self.calls.append(kwargs)
        return self._resp_cls(self._content)


def fake_client(content: str) -> SimpleNamespace:
    """A stand-in OpenAI object whose ``chat.completions.create`` returns
    ``content``."""
    comps = FakeCompletions(content)
    return SimpleNamespace(chat=SimpleNamespace(completions=comps))
