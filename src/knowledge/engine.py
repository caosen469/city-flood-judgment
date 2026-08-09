"""Stage 3 — Knowledge Engine (ADR-0004).

:class:`KnowledgeEngine.assemble` is the pipeline-facing entry point::

    KnowledgeEngine(client=...).assemble(observation, grounding, context)
        -> KnowledgeResult

It wires the three stages of hybrid inference (ADR-0004):

1. **Rule extraction** (:mod:`knowledge.rules`) — deterministic
   :class:`FactBundle` + the always-rule TerrainRisk item (Case C).
2. **LLM-assisted inference** (:mod:`knowledge.infer`) — RoadImpact +
   EventAssessment over the bundle, schema-whitelisted + post-validated.
3. **Explanation** (:mod:`knowledge.explain`) — narration of the chain.

Partial results are expressed by value: an item whose gate is closed (Case D/F)
is simply absent from ``knowledge_items``; the EventAssessment reasoning +
explanation say so. The engine never raises on missing context — only a wired
LLM call that the caller did not guard could, and even then each step falls back
to its deterministic path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from openai import OpenAI

from schemas.context import UrbanContext
from schemas.grounding import GroundedEntity
from schemas.knowledge import KnowledgeItem, KnowledgeResult
from schemas.observation import Observation

from .explain import DEFAULT_MODEL as EXPLAIN_MODEL
from .explain import render_explanation
from .infer import DEFAULT_MODEL as INFER_MODEL
from .infer import assess_event, infer_road_impact
from .rules import extract_fact_bundle, produce_terrain_risk

ReasoningCallback = Callable[[str], None]


@dataclass
class KnowledgeEngine:
    """Assemble a :class:`KnowledgeResult` from the three upstream contracts.

    Parameters
    ----------
    client : OpenAI, optional
        Wired LLM client for RoadImpact / EventAssessment / explanation. When
        ``None`` (or when a call fails) each step uses its deterministic
        fallback, so the engine runs fully offline and in tests.
    model : str
        Model id for the LLM steps (default ``qwen-plus``).
    thinking : str
        Thinking-mode policy passed to the inference steps (``off`` by default —
        knowledge inference wants clean JSON).
    """

    client: Optional[OpenAI] = None
    model: str = INFER_MODEL
    thinking: str = "off"
    _own_client: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.client is None and _has_api_key():
            self.client = _lazy_client()
            self._own_client = True

    # ------------------------------------------------------------------ #
    def assemble(
        self,
        observation: Observation,
        grounding: Optional[GroundedEntity],
        context: Optional[UrbanContext],
        *,
        on_reasoning: Optional[ReasoningCallback] = None,
    ) -> KnowledgeResult:
        """Run all three inference stages and return the assembled result."""
        bundle = extract_fact_bundle(observation, grounding, context)

        terrain_item = produce_terrain_risk(bundle)
        road_item = infer_road_impact(
            bundle,
            client=self.client,
            model=self.model,
            thinking=self.thinking,
            on_reasoning=on_reasoning,
        )

        items: list[KnowledgeItem] = [it for it in (terrain_item, road_item) if it is not None]

        assessment = assess_event(
            bundle,
            items,
            client=self.client,
            model=self.model,
            thinking=self.thinking,
            on_reasoning=on_reasoning,
        )
        explanation = render_explanation(
            items, assessment, bundle, client=self.client, model=EXPLAIN_MODEL
        )

        return KnowledgeResult(
            knowledge_items=items,
            event_assessment=assessment,
            explanation=explanation,
        )


# --------------------------------------------------------------------------- #
# Lazy client — only auto-wire when a real API key is present, so the engine   #
# degrades to deterministic fallbacks in CI / offline / tests by default.       #
# --------------------------------------------------------------------------- #


def _has_api_key() -> bool:
    from vlm.client import API_KEY  # local import to avoid module-level side effects

    return bool(API_KEY.strip()) and API_KEY != "请在这里填写你的阿里云百炼API_KEY"


def _lazy_client() -> OpenAI:
    from vlm.client import make_client

    return make_client()
