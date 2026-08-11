# -*- coding: utf-8 -*-
"""Rule-engine tests (``src/knowledge/rules.py``).

Covers FactBundle extraction, the eligibility gates (Case D/F, slightly_low
Q12 threshold), and TerrainRisk determinism (Case C — same facts ⇒ identical
item, every run). No LLM, no network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schemas.context import LownessClass
from schemas.grounding import GroundingStatus, UnresolvedReason
from schemas.knowledge import InferenceMechanism, KnowledgeType
from schemas.observation import WaterloggingLevel, WaterloggingStatus

from knowledge.rules import (
    TERRAIN_RISK_RULE_ID,
    extract_fact_bundle,
    produce_terrain_risk,
)

from _knowledge_fixtures import (  # noqa: E402
    make_context,
    make_grounded,
    make_observation,
)


class ExtractFactBundleTests(unittest.TestCase):
    def test_case_c_eligible_for_both_types(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        self.assertEqual(
            set(bundle.eligible_types),
            {KnowledgeType.TERRAIN_RISK, KnowledgeType.ROAD_IMPACT},
        )

    def test_case_d_terrain_unavailable_closes_terrain_gate_only(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_available=False),
        )
        self.assertIn(KnowledgeType.ROAD_IMPACT, bundle.eligible_types)
        self.assertNotIn(KnowledgeType.TERRAIN_RISK, bundle.eligible_types)
        self.assertFalse(bundle.terrain.available)

    def test_case_f_grounding_unresolved_closes_road_gate_only(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(status=GroundingStatus.UNRESOLVED, reason=UnresolvedReason.OUTSIDE_NANSHA),
            make_context(terrain_class=LownessClass.SIGNIFICANTLY_LOW, road_available=False),
        )
        self.assertIn(KnowledgeType.TERRAIN_RISK, bundle.eligible_types)
        self.assertNotIn(KnowledgeType.ROAD_IMPACT, bundle.eligible_types)

    def test_slightly_low_below_threshold_no_terrain_risk(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L2),
            make_grounded(),
            make_context(terrain_class=LownessClass.SLIGHTLY_LOW, terrain_composite=0.6),
        )
        self.assertNotIn(KnowledgeType.TERRAIN_RISK, bundle.eligible_types)
        self.assertIn(KnowledgeType.ROAD_IMPACT, bundle.eligible_types)

    def test_absent_water_closes_all_item_gates(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L0, status=WaterloggingStatus.ABSENT),
            make_grounded(),
            make_context(terrain_class=LownessClass.MODERATELY_LOW),
        )
        self.assertEqual(bundle.eligible_types, [])

    def test_insufficient_data_lowness_treated_as_unavailable(self):
        bundle = extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=LownessClass.INSUFFICIENT_DATA, terrain_composite=None),
        )
        self.assertFalse(bundle.terrain.available)
        self.assertNotIn(KnowledgeType.TERRAIN_RISK, bundle.eligible_types)


class ProduceTerrainRiskTests(unittest.TestCase):
    def _bundle(self, klass: LownessClass, composite: float = 1.5):
        return extract_fact_bundle(
            make_observation(WaterloggingLevel.L3),
            make_grounded(),
            make_context(terrain_class=klass, terrain_composite=composite),
        )

    def test_fires_only_when_eligible(self):
        # Gate closed (slightly_low) ⇒ None.
        b = self._bundle(LownessClass.SLIGHTLY_LOW, 0.5)
        self.assertIsNone(produce_terrain_risk(b))

    def test_is_rule_produced_with_evidence(self):
        item = produce_terrain_risk(self._bundle(LownessClass.MODERATELY_LOW, 1.24))
        self.assertIsNotNone(item)
        self.assertEqual(item.mechanism, InferenceMechanism.RULE)
        self.assertEqual(item.rule_id, TERRAIN_RISK_RULE_ID)
        self.assertGreaterEqual(len(item.evidence), 1)
        self.assertEqual(item.lowness_class, LownessClass.MODERATELY_LOW)
        self.assertAlmostEqual(item.composite_tpi_m, 1.24)

    def test_case_c_is_deterministic(self):
        """Same facts ⇒ byte-identical item across runs (Case C guarantee)."""
        a = produce_terrain_risk(self._bundle(LownessClass.SIGNIFICANTLY_LOW, 2.1))
        b = produce_terrain_risk(self._bundle(LownessClass.SIGNIFICANTLY_LOW, 2.1))
        self.assertEqual(a.model_dump(), b.model_dump())

    def test_confidence_scales_with_class(self):
        moderate = produce_terrain_risk(self._bundle(LownessClass.MODERATELY_LOW, 1.2))
        severe = produce_terrain_risk(self._bundle(LownessClass.SIGNIFICANTLY_LOW, 2.5))
        # significantly_low ⇒ HIGH; moderately_low ⇒ MEDIUM.
        self.assertEqual(severe.confidence.value, "high")
        self.assertEqual(moderate.confidence.value, "medium")


if __name__ == "__main__":
    unittest.main()
