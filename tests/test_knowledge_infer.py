# -*- coding: utf-8 -*-
"""Inference tests (``src/knowledge/infer.py``).

Covers the deterministic heuristic / rule assessment, the LLM path via a fake
client, and the post-validation guardrails (whitelist drop + eligibility gate).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schemas.context import HighwayClass, LownessClass
from schemas.knowledge import (
    EventSeverity,
    InferenceMechanism,
    KnowledgeType,
    RoadActor,
    RoadImpactLevel,
)
from schemas.observation import VisualImpactHint, WaterloggingLevel, WaterloggingStatus

from knowledge.infer import (
    assess_event,
    assess_event_rule,
    infer_road_impact,
    road_impact_heuristic,
)
from knowledge.rules import extract_fact_bundle

from _knowledge_fixtures import (  # noqa: E402
    fake_client,
    make_context,
    make_grounded,
    make_observation,
)

_LEVEL_RANK = {
    RoadImpactLevel.LOW: 0,
    RoadImpactLevel.MEDIUM: 1,
    RoadImpactLevel.HIGH: 2,
    RoadImpactLevel.SEVERE: 3,
}


def _bundle(level=WaterloggingLevel.L3, hint=VisualImpactHint.OBSTRUCTING, **ctx_kw):
    return extract_fact_bundle(make_observation(level, hint=hint), make_grounded(), make_context(**ctx_kw))


class RoadImpactHeuristicTests(unittest.TestCase):
    def test_three_actors_emitted(self):
        item = road_impact_heuristic(_bundle(WaterloggingLevel.L3))
        actors = {i.actor for i in item.impacts}
        self.assertEqual(actors, set(RoadActor))

    def test_deeper_water_higher_impact(self):
        shallow = road_impact_heuristic(_bundle(WaterloggingLevel.L1))
        deep = road_impact_heuristic(_bundle(WaterloggingLevel.L5))
        motor_shallow = next(i for i in shallow.impacts if i.actor is RoadActor.MOTOR_VEHICLE).level
        motor_deep = next(i for i in deep.impacts if i.actor is RoadActor.MOTOR_VEHICLE).level
        self.assertLess(_LEVEL_RANK[motor_shallow], _LEVEL_RANK[motor_deep])

    def test_tunnel_worsens_bridge_eases(self):
        plain = road_impact_heuristic(_bundle(WaterloggingLevel.L3))
        tunnel = road_impact_heuristic(
            _bundle(WaterloggingLevel.L3, is_tunnel=True)  # type: ignore[arg-type]
        )
        bridge = road_impact_heuristic(
            _bundle(WaterloggingLevel.L4, is_bridge=True)  # type: ignore[arg-type]
        )
        ped_plain = next(i for i in plain.impacts if i.actor is RoadActor.PEDESTRIAN).level
        ped_tunnel = next(i for i in tunnel.impacts if i.actor is RoadActor.PEDESTRIAN).level
        self.assertLessEqual(_LEVEL_RANK[ped_plain], _LEVEL_RANK[ped_tunnel])
        self.assertEqual(bridge.mechanism, InferenceMechanism.RULE)

    def test_lx_yields_uncertain(self):
        item = road_impact_heuristic(_bundle(WaterloggingLevel.LX))
        self.assertTrue(all(i.level is RoadImpactLevel.UNCERTAIN for i in item.impacts))
        self.assertEqual(item.confidence.value, "low")

    def test_evidence_non_empty(self):
        item = road_impact_heuristic(_bundle(WaterloggingLevel.L3))
        self.assertGreaterEqual(len(item.evidence), 1)


class InferRoadImpactTests(unittest.TestCase):
    def test_gate_closed_returns_none(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(road_available=False, terrain_available=False),
        )
        self.assertIsNone(infer_road_impact(bundle, client=fake_client("{}")))

    def test_no_client_uses_heuristic(self):
        item = infer_road_impact(_bundle(WaterloggingLevel.L3))
        self.assertIsNotNone(item)
        self.assertEqual(item.mechanism, InferenceMechanism.RULE)

    def test_llm_path_mechanism_llm(self):
        payload = {
            "statement": "该道路积水对机动车影响较大。",
            "confidence": "high",
            "impacts": [
                {"actor": "pedestrian", "level": "high"},
                {"actor": "non_motor_vehicle", "level": "high"},
                {"actor": "motor_vehicle", "level": "medium"},
            ],
        }
        item = infer_road_impact(_bundle(WaterloggingLevel.L3), client=fake_client(json.dumps(payload)))
        self.assertIsNotNone(item)
        self.assertEqual(item.mechanism, InferenceMechanism.LLM)
        self.assertEqual(item.statement, "该道路积水对机动车影响较大。")
        self.assertEqual(len(item.impacts), 3)
        self.assertEqual(item.confidence.value, "high")

    def test_llm_invalid_impacts_falls_back_to_heuristic(self):
        # Out-of-whitelist actor/levels must be dropped; with nothing valid
        # left, the heuristic takes over (mechanism flips to rule).
        payload = {"statement": "x", "confidence": "high",
                   "impacts": [{"actor": "drone", "level": "catastrophic"}]}
        item = infer_road_impact(_bundle(WaterloggingLevel.L3), client=fake_client(json.dumps(payload)))
        self.assertIsNotNone(item)
        self.assertEqual(item.mechanism, InferenceMechanism.RULE)

    def test_llm_malformed_json_falls_back(self):
        item = infer_road_impact(_bundle(WaterloggingLevel.L3), client=fake_client("not json at all"))
        self.assertEqual(item.mechanism, InferenceMechanism.RULE)

    def test_llm_partial_impacts_kept(self):
        payload = {"statement": "", "confidence": "medium",
                   "impacts": [{"actor": "motor_vehicle", "level": "severe"},
                               {"actor": "bogus", "level": "nope"}]}
        item = infer_road_impact(_bundle(WaterloggingLevel.L3), client=fake_client(json.dumps(payload)))
        self.assertEqual(item.mechanism, InferenceMechanism.LLM)
        self.assertEqual(len(item.impacts), 1)
        self.assertEqual(item.impacts[0].actor, RoadActor.MOTOR_VEHICLE)


class AssessEventTests(unittest.TestCase):
    def test_deep_water_suspected(self):
        b = _bundle(WaterloggingLevel.L4)
        a = assess_event_rule(b, [])
        self.assertEqual(a.severity, EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT)

    def test_shallow_ordinary(self):
        b = _bundle(WaterloggingLevel.L1)
        a = assess_event_rule(b, [])
        self.assertEqual(a.severity, EventSeverity.ORDINARY_PUDDLE)

    def test_lx_uncertain(self):
        b = _bundle(WaterloggingLevel.LX)
        a = assess_event_rule(b, [])
        self.assertEqual(a.severity, EventSeverity.UNCERTAIN)

    def test_absent_ordinary(self):
        from _knowledge_fixtures import make_observation

        b = extract_fact_bundle(
            make_observation(WaterloggingLevel.L0, status=WaterloggingStatus.ABSENT),
            make_grounded(), make_context(),
        )
        a = assess_event_rule(b, [])
        self.assertEqual(a.severity, EventSeverity.ORDINARY_PUDDLE)

    def test_event_evidence_non_empty(self):
        a = assess_event_rule(_bundle(WaterloggingLevel.L2), [])
        self.assertGreaterEqual(len(a.evidence), 1)

    def test_llm_assessment(self):
        payload = {"severity": "suspected_flood_significant", "confidence": "high",
                   "reasoning": "深层积水叠加低洼地形。"}
        a = assess_event(_bundle(WaterloggingLevel.L4), [], client=fake_client(json.dumps(payload)))
        self.assertEqual(a.severity, EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT)
        self.assertEqual(a.mechanism, InferenceMechanism.LLM)


if __name__ == "__main__":
    unittest.main()
