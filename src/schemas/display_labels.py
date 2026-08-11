"""zh-CN display labels for the schema enum codes.

The canonical stored values are language-neutral codes (see ``observation.py`` /
``context.py`` / ``knowledge.py``). This map provides Chinese display strings for
the Demo frontend and for prompts. Downstream rules / the Knowledge Engine
operate on the codes, never on these labels.
"""

from __future__ import annotations

from .knowledge import (
    EventSeverity,
    EvidenceRefType,
    InferenceMechanism,
    KnowledgeType,
    RoadActor,
    RoadImpactLevel,
)
from .observation import (
    Confidence,
    Likelihood,
    PatchCoverage,
    PhenomenonType,
    ReflectionType,
    SurfaceCondition,
    VisualImpactHint,
    WaterloggingLevel,
    WaterloggingStatus,
)

DISPLAY_LABELS: dict[str, dict[str, str]] = {
    "phenomenon_type": {
        PhenomenonType.ROAD_WATERLOGGING.value: "道路积水",
    },
    "overall_confidence": {
        Confidence.HIGH.value: "高",
        Confidence.MEDIUM.value: "中",
        Confidence.LOW.value: "低",
    },
    "likelihood": {
        Likelihood.HIGH.value: "高",
        Likelihood.MEDIUM.value: "中",
        Likelihood.LOW.value: "低",
    },
    "waterlogging_status": {
        WaterloggingStatus.PRESENT.value: "存在",
        WaterloggingStatus.ABSENT.value: "不存在",
        WaterloggingStatus.UNCERTAIN.value: "不确定",
    },
    "waterlogging_level": {
        WaterloggingLevel.L0.value: "L0：无积水/轻微潮湿",
        WaterloggingLevel.L1.value: "L1：约 0–3 cm",
        WaterloggingLevel.L2.value: "L2：约 3–10 cm",
        WaterloggingLevel.L3.value: "L3：约 10–20 cm",
        WaterloggingLevel.L4.value: "L4：约 20–30 cm",
        WaterloggingLevel.L5.value: "L5：大于 30 cm",
        WaterloggingLevel.LX.value: "LX：无法判断是否存在积水",
    },
    "surface_condition": {
        SurfaceCondition.DRY.value: "干燥",
        SurfaceCondition.WET.value: "潮湿",
        SurfaceCondition.SUSPECTED_WATER.value: "疑似积水",
        SurfaceCondition.CLEAR_WATER.value: "明确积水",
        SurfaceCondition.UNKNOWN.value: "无法判断",
    },
    "reflection_type": {
        ReflectionType.WATER_REFLECTION.value: "水面倒影",
        ReflectionType.WET_ROAD_GLARE.value: "潮湿路面反光",
        ReflectionType.LIGHT_GLARE.value: "灯光反射",
        ReflectionType.SHADOW.value: "阴影",
        ReflectionType.LENS_ARTIFACT.value: "镜头异常",
        ReflectionType.UNKNOWN.value: "未知",
    },
    "patch_coverage": {
        PatchCoverage.LOCALIZED.value: "局部",
        PatchCoverage.MODERATE.value: "中等范围",
        PatchCoverage.EXTENSIVE.value: "大范围",
        PatchCoverage.UNKNOWN.value: "未知",
    },
    "visual_impact_hint": {
        VisualImpactHint.NONE.value: "无明显影响",
        VisualImpactHint.MINOR.value: "轻微（如路缘水洼）",
        VisualImpactHint.OBSTRUCTING.value: "覆盖道路特征/标线",
        VisualImpactHint.SUBMERGING.value: "接近车辆/行人底盘",
        VisualImpactHint.UNCLEAR.value: "无法判断",
    },
    # ---- Knowledge Engine (ticket #7 / ADR-0004) ----
    "knowledge_type": {
        KnowledgeType.TERRAIN_RISK.value: "地形风险",
        KnowledgeType.ROAD_IMPACT.value: "道路通行影响",
    },
    "inference_mechanism": {
        InferenceMechanism.RULE.value: "规则推导",
        InferenceMechanism.LLM.value: "模型推断",
    },
    "evidence_ref_type": {
        EvidenceRefType.OBSERVATION.value: "画面观察",
        EvidenceRefType.GROUNDING.value: "道路定位",
        EvidenceRefType.CONTEXT.value: "城市数据",
        EvidenceRefType.DERIVED.value: "规则派生",
    },
    "road_actor": {
        RoadActor.PEDESTRIAN.value: "行人",
        RoadActor.NON_MOTOR_VEHICLE.value: "非机动车",
        RoadActor.MOTOR_VEHICLE.value: "机动车",
    },
    "road_impact_level": {
        RoadImpactLevel.LOW.value: "低",
        RoadImpactLevel.MEDIUM.value: "中",
        RoadImpactLevel.HIGH.value: "高",
        RoadImpactLevel.SEVERE.value: "严重",
        RoadImpactLevel.UNCERTAIN.value: "无法判断",
    },
    "event_severity": {
        EventSeverity.ORDINARY_PUDDLE.value: "普通局部积水",
        EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT.value: "疑似具内涝意义",
        EventSeverity.UNCERTAIN.value: "不确定",
    },
}


def label(group: str, code: str) -> str:
    """Return the zh-CN label for an enum code, falling back to the code."""
    return DISPLAY_LABELS.get(group, {}).get(code, code)
