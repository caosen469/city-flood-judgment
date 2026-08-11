"""Stage 2b — Urban Context assembler + provider protocol (ADR-0002).

``UrbanContext`` is a composition of typed ``ContextBlock``s — one per knowledge
source. Each source is a :class:`ContextProvider` that emits its own block
(road / elevation / terrain / …); :class:`ContextAssembler` just walks the
registered providers and collects their blocks. A new source extends as a new
provider + block subclass with no change here or to the root model.

Per ADR-0002, every block carries its own :class:`Provenance` and three-state
:class:`BlockAvailability`. When Grounding is unresolved, ``RoadContext`` is
``unavailable(grounding_unresolved)`` but elevation/terrain still compute on the
raw lat/lon — they never claim to be *a road's* elevation (PRD Case F).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from schemas.context import ContextBlock, UrbanContext, QueryPoint
from schemas.grounding import GroundedEntity, LocatedPoint


def _now() -> datetime:
    """Retrieval timestamp for a block's provenance (UTC, timezone-aware)."""
    return datetime.now(timezone.utc)


@runtime_checkable
class ContextProvider(Protocol):
    """One knowledge source → one typed ContextBlock.

    Implementations are stateless beyond their loaded dataset handle and must
    never raise — a source that cannot answer returns its block with
    ``availability.status = unavailable`` and a ``reason`` code (ADR-0002
    "unknown by value, not by missing key").
    """

    #: discriminator the assembler/frontend dispatch on ("road" / "elevation" / …).
    block_type: str

    def query(self, point: LocatedPoint, grounding: GroundedEntity) -> ContextBlock:
        ...


class ContextAssembler:
    """Assemble an :class:`UrbanContext` by walking registered providers.

    Providers run in registration order; the resulting ``blocks`` list order is
    stable (road, elevation, terrain for the default registration). Each provider
    owns its availability — the assembler does not interpret partial failures.
    """

    def __init__(self, providers: list[ContextProvider]):
        self._providers = list(providers)

    @property
    def providers(self) -> list[ContextProvider]:
        return list(self._providers)

    def assemble(
        self,
        point: LocatedPoint,
        grounding: GroundedEntity,
        *,
        source_location: Optional[str] = None,
    ) -> UrbanContext:
        """Build the background layer for one located point.

        Parameters
        ----------
        point : LocatedPoint
            The query point (always present — the no-location path builds no
            context). Elevation/terrain compute on this raw lat/lon even when
            ``grounding`` is unresolved (Case F).
        grounding : GroundedEntity
            Stage-2a result. Consumed by the road provider; elevation/terrain
            ignore the road binding and use ``point`` directly.
        source_location : str, optional
            Free-text/structured input the point was geocoded from, surfaced onto
            ``UrbanContext.query_point.source_location`` for the Evidence Chain.
        """
        blocks = [provider.query(point, grounding) for provider in self._providers]
        return UrbanContext(
            query_point=QueryPoint(
                lat=point.point.lat,
                lon=point.point.lon,
                source_location=source_location,
            ),
            blocks=blocks,
        )
