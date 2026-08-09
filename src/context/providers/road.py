"""Road context provider — joins a resolved :class:`GroundedEntity` onto a
:class:`RoadContextBlock` (ADR-0002).

When Grounding is unresolved the block is ``unavailable(grounding_unresolved)``
— elevation/terrain still compute on the raw point in their own providers (Case
F); this provider simply has nothing to say about a road identity it could not
bind.
"""

from __future__ import annotations

from datetime import date

from schemas.context import (
    Availability,
    BlockAvailability,
    ContextSource,
    HighwayClass,
    Provenance,
    RoadContextBlock,
    UnavailabilityReason,
)
from schemas.grounding import Confidence, GroundedEntity, GroundingStatus, LocatedPoint

from ..base import _now

# OSM ``highway`` tag → closed HighwayClass set. Rare/non-drivable values fold to OTHER.
_HIGHWAY_MAP: dict[str, HighwayClass] = {
    HighwayClass.MOTORWAY.value: HighwayClass.MOTORWAY,
    HighwayClass.TRUNK.value: HighwayClass.TRUNK,
    HighwayClass.PRIMARY.value: HighwayClass.PRIMARY,
    HighwayClass.SECONDARY.value: HighwayClass.SECONDARY,
    HighwayClass.TERTIARY.value: HighwayClass.TERTIARY,
    HighwayClass.UNCLASSIFIED.value: HighwayClass.UNCLASSIFIED,
    HighwayClass.RESIDENTIAL.value: HighwayClass.RESIDENTIAL,
    HighwayClass.LIVING_STREET.value: HighwayClass.LIVING_STREET,
    HighwayClass.SERVICE.value: HighwayClass.SERVICE,
}

#: map the shared Confidence enum to a scalar the Evidence Chain can sort on.
_CONFIDENCE_TO_FLOAT: dict[Confidence, float] = {
    Confidence.HIGH: 0.9,
    Confidence.MEDIUM: 0.6,
    Confidence.LOW: 0.3,
}


def _highway_class(tag: str | None) -> HighwayClass | None:
    if not tag:
        return None
    # tolerate OSM link variants ("primary_link") by stripping the suffix
    base = tag.split("_")[0]
    return _HIGHWAY_MAP.get(base)


def _way_id_int(osm_way_id: str | None) -> int | None:
    if osm_way_id is None:
        return None
    try:
        return int(osm_way_id)
    except (TypeError, ValueError):
        return None


class RoadProvider:
    """Emits the ``road`` ContextBlock from a matched road entity."""

    block_type = "road"

    def __init__(self, *, data_vintage: date | None = None):
        #: OSM data currency is not recorded by the download script; left None
        #: unless the caller knows it.
        self._data_vintage = data_vintage

    def query(self, point: LocatedPoint, grounding: GroundedEntity) -> RoadContextBlock:
        provenance = Provenance(
            source=ContextSource.OSM,
            data_vintage=self._data_vintage,
            retrieved_at=_now(),
        )

        if grounding.status is GroundingStatus.UNRESOLVED or grounding.best_match is None:
            return RoadContextBlock(
                provenance=provenance,
                availability=BlockAvailability(
                    status=Availability.UNAVAILABLE,
                    reason=UnavailabilityReason.GROUNDING_UNRESOLVED,
                ),
            )

        bm = grounding.best_match
        return RoadContextBlock(
            road_name=bm.road_name,
            osm_way_id=_way_id_int(bm.osm_way_id),
            highway_class=_highway_class(bm.highway),
            is_bridge=bool(bm.bridge),
            is_tunnel=bool(bm.tunnel),
            offset_distance_m=float(bm.match_distance_m),
            grounding_confidence=_CONFIDENCE_TO_FLOAT.get(bm.confidence),
            provenance=provenance,
            availability=BlockAvailability(status=Availability.AVAILABLE),
        )
