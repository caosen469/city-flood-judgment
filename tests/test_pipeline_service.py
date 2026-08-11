# -*- coding: utf-8 -*-
"""Pipeline-seam tests — ``analyze()`` over PRD Case A–H (ADR-0005 §1).

These exercise the PRD §5.2 seam directly with fake stage callables (no VLM,
network, or city data). Each Case varies one input and asserts the
*knowledge-level* consequence, proving the pipeline does real contextual work
rather than repackaging the visual LLM output.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _knowledge_fixtures import make_context, make_grounded, make_observation
from _pipeline_fixtures import (
    DUMMY_IMAGE_URL,
    build_deps,
    fake_ground_no_point,
    fake_ground_with_point,
    recording_ground,
    road_item,
    terrain_item,
)
from pipeline.service import ObservationImageError, analyze, iter_pipeline

from observation.generate import ObservationGenerationError  # noqa: F401 — asserted type
from schemas.context import (
    Availability,
    BlockAvailability,
    LownessClass,
    LownessScores,
    TerrainContextBlock,
    UnavailabilityReason,
)
from schemas.grounding import GroundingStatus, UnresolvedReason
from schemas.knowledge import (
    EventSeverity,
    InferenceMechanism,
    TerrainRiskKnowledge,
)
from schemas.observation import (
    VisualImpactHint,
    WaterloggingAttributes,
    WaterloggingLevel,
    WaterloggingStatus,
)
from schemas.observation import LocationRef  # noqa: F401 — asserted


def _run(deps, location=None, **kw):
    return analyze(DUMMY_IMAGE_URL, location, deps=deps, request_id="req-test", **kw)


class CaseC_DifferentTerrainDifferentKnowledge(unittest.TestCase):
    """Case C — same Observation, different TerrainContext → different knowledge.

    THE pivotal case (PRD §5.3): proves the knowledge layer is not repackaging
    the visual answer. Same image/grounding; only the terrain block differs.
    """

    def test_low_lying_yields_terrain_risk(self):
        low_ctx = make_context(terrain_class=LownessClass.MODERATELY_LOW, terrain_composite=1.4)
        deps = build_deps(context=low_ctx)
        result = _run(deps)
        item = terrain_item(result)
        self.assertIsNotNone(item, "低洼地形应产出 TerrainRisk")
        self.assertEqual(item.mechanism, InferenceMechanism.RULE)  # Case C determinism
        self.assertEqual(item.lowness_class, LownessClass.MODERATELY_LOW)

    def test_flat_terrain_yields_no_terrain_risk(self):
        flat_ctx = make_context(terrain_class=LownessClass.LEVEL_OR_HIGHER, terrain_composite=0.1)
        # Same observation as the low-lying run (build_deps default).
        deps = build_deps(context=flat_ctx)
        result = _run(deps)
        self.assertIsNone(terrain_item(result), "平坦地形不应产出 TerrainRisk")

    def test_same_observation_different_context_diverges(self):
        """The two configurations share the identical Observation (the fake
        generator returns the same default); only the context differs. The
        knowledge output must diverge on TerrainRisk."""
        obs = make_observation()  # shared
        low_deps = build_deps(
            observation=obs,
            context=make_context(terrain_class=LownessClass.MODERATELY_LOW, terrain_composite=1.4),
        )
        flat_deps = build_deps(
            observation=obs,
            context=make_context(terrain_class=LownessClass.LEVEL_OR_HIGHER, terrain_composite=0.1),
        )
        low_result = _run(deps=low_deps)
        flat_result = _run(deps=flat_deps)
        self.assertEqual(low_result.observation.model_dump(), flat_result.observation.model_dump())
        self.assertIsNotNone(terrain_item(low_result))
        self.assertIsNone(terrain_item(flat_result))


class CaseD_ContextMissing(unittest.TestCase):
    """Case D — terrain/road data unavailable ⇒ no dependent knowledge, but the
    Observation is still returned and the block is marked unavailable."""

    def test_terrain_unavailable_no_terrain_risk(self):
        ctx = make_context(terrain_available=False)
        deps = build_deps(context=ctx)
        result = _run(deps)
        self.assertIsNone(terrain_item(result))
        # The terrain block honestly reports unavailable.
        terrain_block = result.context.terrain
        self.assertIsNotNone(terrain_block)
        self.assertEqual(terrain_block.availability.status, Availability.UNAVAILABLE)

    def test_observation_still_returned(self):
        ctx = make_context(terrain_available=False, road_available=False)
        result = _run(deps=build_deps(context=ctx))
        self.assertEqual(
            result.observation.waterlogging.status, WaterloggingStatus.PRESENT
        )


class CaseF_UnresolvedGrounding(unittest.TestCase):
    """Case F — grounding unresolved ⇒ no RoadImpact (gate closed), image-only
    analysis preserved. Terrain still reasons on a point-bearing unresolved
    entity (out_of_buffer); no-point (no_location) skips Context entirely."""

    def test_unresolved_no_road_impact(self):
        entity = make_grounded(status=GroundingStatus.UNRESOLVED, reason=UnresolvedReason.OUT_OF_BUFFER)
        # The real RoadProvider marks the road block unavailable when grounding
        # is unresolved; the fake assembler returns exactly the context we build,
        # so reflect that here (terrain still computed on the raw point).
        ctx = make_context(
            terrain_class=LownessClass.MODERATELY_LOW, road_available=False
        )
        deps = build_deps(
            entity=entity,
            context=ctx,
            ground=fake_ground_with_point(entity),
        )
        result = _run(deps=deps)
        self.assertIsNone(road_item(result), "grounding unresolved ⇒ RoadImpact 门关闭")
        # road block unavailable; terrain still computed (point-bearing).
        self.assertEqual(result.context.road.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(result.context.terrain.availability.status, Availability.AVAILABLE)

    def test_no_location_skips_context(self):
        entity = make_grounded(
            status=GroundingStatus.UNRESOLVED, reason=UnresolvedReason.NO_LOCATION, has_point=False
        )
        deps = build_deps(entity=entity, ground=fake_ground_no_point(entity))
        result = _run(deps=deps)
        self.assertIsNone(result.context.query_point)  # degenerate context
        self.assertEqual(result.context.blocks, [])
        self.assertIsNone(road_item(result))


class CaseA_OrdinaryPuddle(unittest.TestCase):
    """Case A — a small localized puddle: present water but shallow ⇒ ordinary
    tier, not escalated to suspected-flood."""

    def test_shallow_water_ordinary(self):
        obs = make_observation(level=WaterloggingLevel.L1, hint=VisualImpactHint.MINOR)
        flat_ctx = make_context(terrain_class=LownessClass.LEVEL_OR_HIGHER, terrain_composite=0.1)
        deps = build_deps(observation=obs, context=flat_ctx)
        result = _run(deps=deps)
        self.assertEqual(
            result.knowledge.event_assessment.severity, EventSeverity.ORDINARY_PUDDLE
        )


class CaseB_SignificantWaterlogging(unittest.TestCase):
    """Case B — deep water + low-lying ⇒ suspected-flood-significant, deeper
    RoadImpact than Case A."""

    def test_deep_low_lying_significant(self):
        obs = make_observation(level=WaterloggingLevel.L4, hint=VisualImpactHint.SUBMERGING)
        low_ctx = make_context(terrain_class=LownessClass.SIGNIFICANTLY_LOW, terrain_composite=2.5)
        deps = build_deps(observation=obs, context=low_ctx)
        result = _run(deps=deps)
        self.assertEqual(
            result.knowledge.event_assessment.severity,
            EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT,
        )
        road = road_item(result)
        self.assertIsNotNone(road)
        levels = {i.level for i in road.impacts}
        self.assertTrue(levels & {"high", "severe"}, "深水应有较高通行影响")


class CaseE_AmbiguousImage(unittest.TestCase):
    """Case E — uncertain visual signal ⇒ EventAssessment may be uncertain; the
    pipeline never fabricates certainty."""

    def test_uncertain_status_propagates(self):
        obs = make_observation(
            level=WaterloggingLevel.LX, status=WaterloggingStatus.UNCERTAIN
        )
        deps = build_deps(observation=obs)
        result = _run(deps=deps)
        self.assertEqual(
            result.knowledge.event_assessment.severity, EventSeverity.UNCERTAIN
        )


class CaseG_NoUnsupportedCausalClaim(unittest.TestCase):
    """Case G — the closed KnowledgeType whitelist means "排水管网堵塞" / "降雨"
    have no type to inhabit; the explanation never introduces chain-external
    causation."""

    def test_no_forbidden_knowledge_types(self):
        from schemas.knowledge import KnowledgeType

        deps = build_deps()
        result = _run(deps=deps)
        allowed = {KnowledgeType.TERRAIN_RISK, KnowledgeType.ROAD_IMPACT}
        for item in result.knowledge.knowledge_items:
            self.assertIn(item.knowledge_type, allowed)
        # Explanation stays within the chain (template path, offline).
        forbidden = ["排水管网", "降雨", "暴雨", "事故"]
        for word in forbidden:
            self.assertNotIn(word, result.knowledge.explanation)


class CaseH_EvidenceTraceability(unittest.TestCase):
    """Case H — every emitted knowledge item + the assessment carries ≥1
    evidence reference (observation / context / grounding / derived)."""

    def test_every_item_has_evidence(self):
        deps = build_deps()  # low-lying ⇒ TerrainRisk + RoadImpact
        result = _run(deps=deps)
        items = result.knowledge.knowledge_items
        self.assertTrue(items)
        for item in items:
            self.assertGreaterEqual(len(item.evidence), 1)
        self.assertGreaterEqual(len(result.knowledge.event_assessment.evidence), 1)
        # The Explanation is non-empty.
        self.assertTrue(result.knowledge.explanation.strip())


class PipelineMechanics(unittest.TestCase):
    """Mechanical guarantees of the seam: meta stamping, request_id threading,
  timings, three-stage no-short-circuit, thinking buffering, location fallback,
  and the two hard-failure paths."""

    def test_meta_stamped_and_request_id_threaded(self):
        deps = build_deps()
        result = _run(deps=deps, source_image="gs://bucket/img.png")
        self.assertEqual(result.observation.meta.observation_id, "req-test")
        self.assertEqual(result.observation.meta.source_image, "gs://bucket/img.png")
        self.assertIsNotNone(result.observation.meta.observed_at)
        self.assertEqual(result.request_id, "req-test")

    def test_timings_four_stages(self):
        deps = build_deps()
        result = _run(deps=deps)
        self.assertEqual(
            set(result.timings.keys()), {"observation", "grounding", "context", "knowledge"}
        )
        for v in result.timings.values():
            self.assertGreaterEqual(v, 0.0)

    def test_iter_pipeline_event_order(self):
        deps = build_deps(reasoning_deltas=["想 ", "中…"])
        events = list(iter_pipeline(DUMMY_IMAGE_URL, None, deps=deps, request_id="r"))
        stages = [e for e in events if e.__class__.__name__ == "Stage"]
        self.assertEqual([s.stage.value for s in stages],
                         ["observation", "grounding", "context", "knowledge"])
        self.assertEqual(events[-1].__class__.__name__, "Done")
        # Thinking deltas precede the first stage event.
        first_stage_idx = next(i for i, e in enumerate(events) if e.__class__.__name__ == "Stage")
        thinking = [e for e in events[:first_stage_idx] if e.__class__.__name__ == "Thinking"]
        self.assertEqual([t.delta for t in thinking], ["想 ", "中…"])

    def test_visible_location_text_fallback(self):
        """No explicit location, but the VLM copied an OSD place name → it
        becomes a raw_text geocode candidate handed to Grounding."""
        obs = make_observation()
        obs.visible_location_text = "南沙进港大道"
        ground = recording_ground(make_grounded())
        deps = build_deps(observation=obs, ground=ground)
        _run(deps=deps, location=None)
        received = ground.seen[0]
        self.assertIsNotNone(received)
        self.assertEqual(received.raw_text, "南沙进港大道")

    def test_explicit_location_overrides_visible_text(self):
        obs = make_observation()
        obs.visible_location_text = "画面地名"
        loc = LocationRef(lat=22.7, lon=113.5)
        ground = recording_ground(make_grounded())
        deps = build_deps(observation=obs, ground=ground)
        _run(deps=deps, location=loc)
        received = ground.seen[0]
        self.assertEqual((received.lat, received.lon), (22.7, 113.5))

    def test_unreadable_image_raises_image_error(self):
        deps = build_deps()
        with self.assertRaises(ObservationImageError):
            analyze("/no/such/file.png", None, deps=deps)

    def test_vlm_hard_failure_propagates(self):
        from observation.generate import GenerateResult  # noqa: F401

        def broken_generate(image_source, **kwargs):
            raise ObservationGenerationError("VLM 调用失败：timeout")

        deps = build_deps()
        deps.generate_observation = broken_generate
        with self.assertRaises(ObservationGenerationError):
            analyze(DUMMY_IMAGE_URL, None, deps=deps)

    def test_unreadable_image_emits_analysis_error_event(self):
        deps = build_deps()
        events = list(iter_pipeline("/no/such/file.png", None, deps=deps))
        from pipeline.service import AnalysisError

        errs = [e for e in events if isinstance(e, AnalysisError)]
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].unreadable_image)


if __name__ == "__main__":
    unittest.main()
