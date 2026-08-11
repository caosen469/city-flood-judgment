"""Stage 3 — Knowledge Engine (ADR-0004).

Hybrid inference over (Observation, Grounding, UrbanContext):

* :mod:`knowledge.rules` — deterministic FactBundle extraction + TerrainRisk.
* :mod:`knowledge.infer` — LLM-assisted RoadImpact + EventAssessment.
* :mod:`knowledge.explain` — chain narration.
* :class:`KnowledgeEngine` — the pipeline-facing orchestrator.

Consumes only the committed schemas (ADR-0001/0002/0003/0004); does not depend
on the Stage 2 implementations.
"""

from __future__ import annotations

from .engine import KnowledgeEngine
from .infer import assess_event, infer_road_impact, road_impact_heuristic
from .rules import extract_fact_bundle, produce_terrain_risk

__all__ = [
    "KnowledgeEngine",
    "extract_fact_bundle",
    "produce_terrain_risk",
    "infer_road_impact",
    "road_impact_heuristic",
    "assess_event",
]
