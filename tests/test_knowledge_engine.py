# -*- coding: utf-8 -*-
"""End-to-end KnowledgeEngine tests (``src/knowledge/engine.py``).

Exercises the orchestrator across the PRD cases — C (deterministic terrain
risk), D (terrain missing), F (grounding unresolved, terrain still on raw
latlon), no-location, and absent water — asserting item presence, non-empty
evidence on every emitted item + the assessment, and a non-empty explanation.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schemas.context import LownessClass
from schemas.grounding import GroundingStatus, UnresolvedReason
from schemas.knowledge import (
    EventSeverity,
    InferenceMechanism,
    KnowledgeType,
    TerrainRiskKnowledge,
)
from schemas.observation import WaterloggingLevel, WaterloggingStatus

from knowledge import KnowledgeEngine

from _knowledge_fixtures import (  # noqa: E402
    fake_client,
    make_context,
    make_grounded,
    make_observation,
)


class EngineCaseTests(unittest.TestCase):
    def setUp(self):
        # No DASHSCOPE_API_KEY in CI → engine falls back to deterministic paths.
        self.eng = KnowledgeEngine()

    def _check_evidence(self, result):
        for item in result.knowledge_items:
            self.assertGreaterEqual(len(item.evidence), 1, "every item needs evidence (Case H)")
        self.assertGreaterEqual(len(result.event_assessment.evidence), 1)
        self.assertTrue(result.explanation.strip())

    def test_case_c_full(self):
        r = self.eng.assemble(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        types = {i.knowledge_type for i in r.knowledge_items}
        self.assertEqual(types, {KnowledgeType.TERRAIN_RISK, KnowledgeType.ROAD_IMPACT})
        terrain = next(i for i in r.knowledge_items if isinstance(i, TerrainRiskKnowledge))
        self.assertEqual(terrain.mechanism, InferenceMechanism.RULE)
        self.assertEqual(r.event_assessment.severity, EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT)
        self._check_evidence(r)

    def test_case_d_terrain_missing(self):
        r = self.eng.assemble(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_available=False),
        )
        types = {i.knowledge_type for i in r.knowledge_items}
        self.assertEqual(types, {KnowledgeType.ROAD_IMPACT})

    def test_case_f_grounding_unresolved_terrain_still_fires(self):
        r = self.eng.assemble(
            make_observation(WaterloggingLevel.L4),
            make_grounded(status=GroundingStatus.UNRESOLVED, reason=UnresolvedReason.OUTSIDE_NANSHA),
            make_context(terrain_class=LownessClass.SIGNIFICANTLY_LOW, road_available=False),
        )
        types = {i.knowledge_type for i in r.knowledge_items}
        # TerrainRisk still fires (terrain computed on raw latlon per ADR-0002);
        # RoadImpact gate closed (no road). Assessment rolls up to suspected.
        self.assertEqual(types, {KnowledgeType.TERRAIN_RISK})
        self.assertEqual(r.event_assessment.severity, EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT)

    def test_no_location_image_only(self):
        r = self.eng.assemble(
            make_observation(WaterloggingLevel.L2),
            make_grounded(status=GroundingStatus.UNRESOLVED, reason=UnresolvedReason.NO_LOCATION, has_point=False),
            make_context(terrain_available=False, road_available=False),
        )
        self.assertEqual(r.knowledge_items, [])
        self.assertEqual(r.event_assessment.severity, EventSeverity.ORDINARY_PUDDLE)
        self._check_evidence(r)

    def test_absent_water(self):
        r = self.eng.assemble(
            make_observation(WaterloggingLevel.L0, status=WaterloggingStatus.ABSENT),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        self.assertEqual(r.knowledge_items, [])
        self.assertEqual(r.event_assessment.severity, EventSeverity.ORDINARY_PUDDLE)

    def test_case_c_deterministic(self):
        a = self.eng.assemble(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        b = self.eng.assemble(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        self.assertEqual(a.model_dump(), b.model_dump())


class EngineWithFakeClientTests(unittest.TestCase):
    def test_llm_items_marked_llm(self):
        # Fake client answers all three LLM calls (road impact, assessment,
        # explanation). Engine auto-wires no client without an API key, so pass
        # one explicitly.
        road = json.dumps({
            "statement": "LLM 陈述", "confidence": "medium",
            "impacts": [{"actor": "pedestrian", "level": "high"},
                        {"actor": "non_motor_vehicle", "level": "medium"},
                        {"actor": "motor_vehicle", "level": "low"}],
        })
        eng = KnowledgeEngine(client=fake_client(road))
        r = eng.assemble(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        road_item = next(i for i in r.knowledge_items if i.knowledge_type is KnowledgeType.ROAD_IMPACT)
        self.assertEqual(road_item.mechanism, InferenceMechanism.LLM)


if __name__ == "__main__":
    unittest.main()
