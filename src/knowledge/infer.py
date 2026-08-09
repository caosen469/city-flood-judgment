"""Stage 3 LLM-assisted inference (ADR-0004): RoadImpact + EventAssessment.

The rule engine (``rules.py``) extracts a grounded :class:`FactBundle` and
produces the deterministic TerrainRisk. This module does the *genuinely
judgemental* part over that bundle:

* :func:`infer_road_impact` — per-actor road-user impact (3 actors × 5 levels),
  replacing the legacy ``traffic_risk`` now grounded in real road attributes
  (ADR-0001). LLM over the FactBundle, schema-whitelisted + post-validated.
* :func:`assess_event` — the composite event tier
  (``ordinary_puddle`` / ``suspected_flood_significant`` / ``uncertain``), PRD
  §4.11. Always eligible (may be ``uncertain``).

Design rules (ADR-0004):

* The LLM reasons **only over the FactBundle** — it never re-judges the image
  (PRD §7.2). Its output is restricted to the closed ``KnowledgeType`` whitelist
  + the RoadImpact/Event enums; "排水管网堵塞" has nowhere to live.
* Eligibility gates from ``bundle.eligible_types`` are honoured first: a closed
  gate returns ``None`` before any LLM call (Case F for RoadImpact).
* A deterministic heuristic (:func:`road_impact_heuristic`) and rule assessment
  (:func:`assess_event_rule`) serve as **offline / test fallbacks** and as the
  graceful degradation when no client is wired or the LLM call fails — an
  ADR-0004-acknowledged lever ("RoadImpact 够表格化…可回退为规则查表"). The
  ``mechanism`` field records which path actually produced each item, so the
  Evidence Chain never claims an LLM judgement that was in fact a rule.
* Evidence is constructed programmatically from the extracted facts (not from
  LLM text), so post-validation on evidence never drops a structurally-valid
  item — the LLM only fills the judgement fields (statement / level / severity).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from openai import OpenAI

from schemas.context import HighwayClass
from schemas.knowledge import (
    Confidence,
    ContextRef,
    DerivedRef,
    EventAssessment,
    EventSeverity,
    EvidenceRef,
    FactBundle,
    GroundingRef,
    InferenceMechanism,
    KnowledgeItem,
    KnowledgeType,
    ObservationRef,
    RoadActor,
    RoadActorImpact,
    RoadImpactKnowledge,
    RoadImpactLevel,
    TerrainRiskKnowledge,
)
from schemas.observation import VisualImpactHint, WaterloggingLevel, WaterloggingStatus

from vlm.client import build_extra_body, make_client, resolve_thinking_choice

log = logging.getLogger(__name__)

# Default text model for knowledge inference — a stable non-thinking Qwen, so
# json_object emits clean JSON without thinking-mode noise. Inject any model in
# tests / via the engine.
DEFAULT_MODEL = "qwen-plus"

ReasoningCallback = Callable[[str], None]

_ROAD_IMPACT_RULE_ID = "road_impact_heuristic"
_EVENT_RULE_ID = "event_assessment_rule"

# Ordered severity ladder for bumping (UNCERTAIN is invariant — not bumped).
_LEVEL_ORDER: list[RoadImpactLevel] = [
    RoadImpactLevel.LOW,
    RoadImpactLevel.MEDIUM,
    RoadImpactLevel.HIGH,
    RoadImpactLevel.SEVERE,
]


# --------------------------------------------------------------------------- #
# LLM plumbing.                                                                #
# --------------------------------------------------------------------------- #

_FENCED_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _extract_json(raw: str) -> Any:
    """Tolerant JSON parse: strip fences / surrounding prose, then ``json.loads``."""
    text = raw.strip()
    m = _FENCED_RE.fullmatch(text)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _json_completion(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    thinking: str = "off",
    on_reasoning: Optional[ReasoningCallback] = None,
) -> str:
    """One non-streaming ``json_object`` completion. Returns raw content text.

    ``thinking="off"`` by default — knowledge inference wants clean JSON, and
    most candidate models classify as ``non`` (no enable_thinking sent).
    """
    should_send, enable_thinking, _ = resolve_thinking_choice(model, thinking)
    extra_body = build_extra_body((should_send, enable_thinking, None))
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    if on_reasoning is not None:
        # Streaming lets us surface reasoning_content (SSE `thinking` event).
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        parts: list[str] = []
        for chunk in client.chat.completions.create(**kwargs):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "model_extra", None)
            if reasoning and isinstance(reasoning, dict):
                rc = reasoning.get("reasoning_content")
                if rc:
                    on_reasoning(rc)
            content = getattr(delta, "content", None)
            if isinstance(content, str):
                parts.append(content)
        return "".join(parts).strip()
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- #
# Evidence construction (programmatic — independent of LLM output).            #
# --------------------------------------------------------------------------- #


def _road_evidence(bundle: FactBundle) -> list[EvidenceRef]:
    """Evidence for a RoadImpact item: the visual water signals + the road
    block attributes it was reasoned over. Always non-empty when the gate is
    open (present water + available road)."""
    refs: list[EvidenceRef] = [
        ObservationRef(
            field_path="waterlogging.waterlogging_level",
            note=f"画面积水等级 {bundle.observation.waterlogging_level.value}。",
        ),
        ObservationRef(
            field_path="waterlogging.visual_impact_hint",
            note=f"视觉影响提示 {bundle.observation.visual_impact_hint.value}。",
        ),
    ]
    if bundle.road.highway_class is not None:
        refs.append(
            ContextRef(
                block_type="road",
                field_path="highway_class",
                note=f"匹配路段等级 {bundle.road.highway_class.value}（来自 road 块）。",
            )
        )
    if bundle.road.is_tunnel:
        refs.append(ContextRef(block_type="road", field_path="is_tunnel", note="该路段为隧道/下穿段。"))
    if bundle.road.is_bridge:
        refs.append(ContextRef(block_type="road", field_path="is_bridge", note="该路段为桥梁。"))
    return refs


def _event_evidence(bundle: FactBundle, items: list[KnowledgeItem]) -> list[EvidenceRef]:
    """Evidence for the composite EventAssessment: the water status + any
    generated knowledge items it rolls up. Always non-empty."""
    refs: list[EvidenceRef] = [
        ObservationRef(
            field_path="waterlogging.status",
            note=f"积水判定 {bundle.observation.status.value}，等级 "
            f"{bundle.observation.waterlogging_level.value}。",
        )
    ]
    for item in items:
        if isinstance(item, TerrainRiskKnowledge):
            refs.append(
                DerivedRef(
                    rule_id="terrain_risk_low_lying",
                    value=f"terrain_risk:{item.lowness_class.value}",
                    inputs=[],
                    note="已生成 TerrainRisk（低洼地形风险）——支持内涝意义判级。",
                )
            )
        elif isinstance(item, RoadImpactKnowledge):
            worst = max(
                (i.level for i in item.impacts),
                key=lambda lv: _LEVEL_ORDER.index(lv) if lv in _LEVEL_ORDER else -1,
            )
            refs.append(
                DerivedRef(
                    rule_id=_ROAD_IMPACT_RULE_ID,
                    value=f"road_impact_worst:{worst.value}",
                    inputs=[],
                    note=f"已生成 RoadImpact，最严重 actor 等级 {worst.value}。",
                )
            )
    if bundle.grounding.highway is not None:
        refs.append(
            GroundingRef(
                field_path="best_match.highway",
                note=f"匹配路段 highway={bundle.grounding.highway}。",
            )
        )
    return refs


# --------------------------------------------------------------------------- #
# RoadImpact — heuristic fallback (also the offline / test path).              #
# --------------------------------------------------------------------------- #

# Base per-actor severity by visual waterlogging level:
#   (pedestrian, non_motor_vehicle, motor_vehicle)
_BASE_IMPACT: dict[WaterloggingLevel, tuple[RoadImpactLevel, RoadImpactLevel, RoadImpactLevel]] = {
    WaterloggingLevel.L0: (RoadImpactLevel.LOW,) * 3,
    WaterloggingLevel.L1: (RoadImpactLevel.LOW,) * 3,
    WaterloggingLevel.L2: (RoadImpactLevel.MEDIUM, RoadImpactLevel.MEDIUM, RoadImpactLevel.LOW),
    WaterloggingLevel.L3: (RoadImpactLevel.HIGH, RoadImpactLevel.HIGH, RoadImpactLevel.MEDIUM),
    WaterloggingLevel.L4: (RoadImpactLevel.SEVERE, RoadImpactLevel.HIGH, RoadImpactLevel.HIGH),
    WaterloggingLevel.L5: (RoadImpactLevel.SEVERE, RoadImpactLevel.SEVERE, RoadImpactLevel.HIGH),
    WaterloggingLevel.LX: (RoadImpactLevel.UNCERTAIN,) * 3,
}


def _bump(level: RoadImpactLevel, delta: int) -> RoadImpactLevel:
    if level is RoadImpactLevel.UNCERTAIN:
        return level
    idx = _LEVEL_ORDER.index(level) + delta
    idx = max(0, min(len(_LEVEL_ORDER) - 1, idx))
    return _LEVEL_ORDER[idx]


def road_impact_heuristic(bundle: FactBundle) -> RoadImpactKnowledge:
    """Deterministic RoadImpact from the FactBundle (rule fallback, ADR-0004
    lever). Tuning: deeper water ⇒ higher impact; pedestrians/non-motor affected
    sooner than motors; tunnels/underpasses (low points) worsen, bridges ease;
    submerging visuals worsen motors."""
    base = _BASE_IMPACT.get(bundle.observation.waterlogging_level, _BASE_IMPACT[WaterloggingLevel.LX])
    ped, nmv, motor = base

    if bundle.road.is_tunnel:
        ped, nmv, motor = _bump(ped, 1), _bump(nmv, 1), _bump(motor, 1)
    if bundle.road.is_bridge:
        ped, nmv, motor = _bump(ped, -1), _bump(nmv, -1), _bump(motor, -1)
    if bundle.observation.visual_impact_hint is VisualImpactHint.SUBMERGING:
        nmv, motor = _bump(nmv, 1), _bump(motor, 1)

    impacts = [
        RoadActorImpact(actor=RoadActor.PEDESTRIAN, level=ped),
        RoadActorImpact(actor=RoadActor.NON_MOTOR_VEHICLE, level=nmv),
        RoadActorImpact(actor=RoadActor.MOTOR_VEHICLE, level=motor),
    ]
    has_uncertain = any(i.level is RoadImpactLevel.UNCERTAIN for i in impacts)
    confidence = Confidence.LOW if has_uncertain else Confidence.MEDIUM

    worst = max(
        impacts,
        key=lambda i: _LEVEL_ORDER.index(i.level) if i.level in _LEVEL_ORDER else -1,
    ).level
    road_desc = _road_descriptor(bundle)
    statement = (
        f"结合画面积水（{bundle.observation.waterlogging_level.value}）与匹配道路属性"
        f"（{road_desc}），对通行的影响估算为：最严重 {worst.value}。"
    )

    return RoadImpactKnowledge(
        statement=statement,
        confidence=confidence,
        mechanism=InferenceMechanism.RULE,
        rule_id=_ROAD_IMPACT_RULE_ID,
        evidence=_road_evidence(bundle),
        impacts=impacts,
    )


def _road_descriptor(bundle: FactBundle) -> str:
    bits: list[str] = []
    if bundle.road.highway_class is not None:
        bits.append(f"等级 {bundle.road.highway_class.value}")
    if bundle.road.is_tunnel:
        bits.append("隧道/下穿")
    if bundle.road.is_bridge:
        bits.append("桥梁")
    return "、".join(bits) if bits else "普通路段"


# --------------------------------------------------------------------------- #
# RoadImpact — LLM path.                                                       #
# --------------------------------------------------------------------------- #


_ROAD_IMPACT_SYSTEM = (
    "你是道路积水通行影响研判助手。你会收到一段结构化事实（FactBundle 的 JSON）："
    "画面积水等级、视觉影响提示、匹配道路的等级/桥隧属性。请仅基于这些事实，为三类"
    "道路使用者各给出一个通行影响等级，并给出一句话陈述与置信度。\n"
    "严格约束：\n"
    "1) 不得引入事实以外的信息（禁止编造排水管网、降雨、事故等因果）。\n"
    "2) actor 只能是 pedestrian / non_motor_vehicle / motor_vehicle。\n"
    "3) level 只能是 low / medium / high / severe / uncertain。\n"
    "4) 只输出 JSON，结构：\n"
    '{"statement": str, "confidence": "high|medium|low", '
    '"impacts": [{"actor": str, "level": str}, ...]}\n'
    "5) impacts 必须恰好覆盖三类 actor。"
)


def _fact_bundle_json(bundle: FactBundle) -> str:
    """Compact, LLM-facing serialization of the FactBundle (no re-judgement)."""
    payload = {
        "observation": {
            "status": bundle.observation.status.value,
            "waterlogging_level": bundle.observation.waterlogging_level.value,
            "visual_impact_hint": bundle.observation.visual_impact_hint.value,
            "has_depth_estimate": bundle.observation.has_depth_estimate,
        },
        "grounding": {
            "status": bundle.grounding.status,
            "highway": bundle.grounding.highway,
            "is_bridge": bundle.grounding.is_bridge,
            "is_tunnel": bundle.grounding.is_tunnel,
            "offset_distance_m": bundle.grounding.offset_distance_m,
        },
        "road": {
            "available": bundle.road.available,
            "highway_class": bundle.road.highway_class.value if bundle.road.highway_class else None,
            "lanes": bundle.road.lanes,
            "is_bridge": bundle.road.is_bridge,
            "is_tunnel": bundle.road.is_tunnel,
        },
        "terrain": {
            "available": bundle.terrain.available,
            "lowness_class": bundle.terrain.lowness_class.value if bundle.terrain.lowness_class else None,
            "composite_tpi_m": bundle.terrain.composite_tpi_m,
        },
        "eligible_types": [t.value for t in bundle.eligible_types],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_confidence(value: Any) -> Confidence:
    if isinstance(value, str):
        for c in Confidence:
            if c.value == value.lower():
                return c
    return Confidence.MEDIUM


def _parse_impacts(raw: Any) -> list[RoadActorImpact]:
    if not isinstance(raw, list):
        return []
    valid: list[RoadActorImpact] = []
    seen: set[RoadActor] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        actor_str = entry.get("actor")
        level_str = entry.get("level")
        try:
            actor = RoadActor(actor_str)
            level = RoadImpactLevel(level_str)
        except (ValueError, TypeError):
            continue
        if actor in seen:
            continue
        seen.add(actor)
        valid.append(RoadActorImpact(actor=actor, level=level))
    return valid


def infer_road_impact(
    bundle: FactBundle,
    *,
    client: Optional[OpenAI] = None,
    model: str = DEFAULT_MODEL,
    thinking: str = "off",
    on_reasoning: Optional[ReasoningCallback] = None,
) -> Optional[RoadImpactKnowledge]:
    """Produce a RoadImpactKnowledge item, or ``None`` if the gate is closed.

    Gate closed (``road_impact`` not eligible) ⇒ ``None`` (Case F). Otherwise:
    LLM over the FactBundle when a ``client`` is wired; deterministic heuristic
    otherwise (or on LLM failure). ``mechanism`` records the actual producer.
    """
    if KnowledgeType.ROAD_IMPACT not in bundle.eligible_types:
        return None

    if client is None:
        return road_impact_heuristic(bundle)

    messages = [
        {"role": "system", "content": _ROAD_IMPACT_SYSTEM},
        {"role": "user", "content": "FactBundle：\n" + _fact_bundle_json(bundle)},
    ]
    try:
        raw = _json_completion(
            client, model=model, messages=messages, thinking=thinking, on_reasoning=on_reasoning
        )
        payload = _extract_json(raw)
    except Exception as exc:  # noqa: BLE001 — any LLM/parse failure ⇒ heuristic
        log.warning("RoadImpact LLM 调用/解析失败，回退规则启发式：%s", exc)
        return road_impact_heuristic(bundle)

    impacts = _parse_impacts(payload.get("impacts"))
    if not impacts:
        log.warning("RoadImpact LLM 输出无有效 impacts，回退规则启发式。")
        return road_impact_heuristic(bundle)

    statement = str(payload.get("statement") or "").strip() or road_impact_heuristic(bundle).statement
    confidence = _parse_confidence(payload.get("confidence"))

    return RoadImpactKnowledge(
        statement=statement,
        confidence=confidence,
        mechanism=InferenceMechanism.LLM,
        evidence=_road_evidence(bundle),
        impacts=impacts,
    )


# --------------------------------------------------------------------------- #
# EventAssessment — rule fallback.                                             #
# --------------------------------------------------------------------------- #


def _has_terrain_risk(items: list[KnowledgeItem]) -> bool:
    return any(isinstance(i, TerrainRiskKnowledge) for i in items)


def _worst_road_impact(items: list[KnowledgeItem]) -> Optional[RoadImpactLevel]:
    worst: Optional[RoadImpactLevel] = None
    worst_idx = -1
    for item in items:
        if not isinstance(item, RoadImpactKnowledge):
            continue
        for imp in item.impacts:
            if imp.level not in _LEVEL_ORDER:
                continue
            idx = _LEVEL_ORDER.index(imp.level)
            if idx > worst_idx:
                worst_idx, worst = idx, imp.level
    return worst


_DEEP_LEVELS = {
    WaterloggingLevel.L3,
    WaterloggingLevel.L4,
    WaterloggingLevel.L5,
}


def assess_event_rule(bundle: FactBundle, items: list[KnowledgeItem]) -> EventAssessment:
    """Deterministic composite tier. ``suspected_flood_significant`` when the
    water is deep OR a TerrainRisk fired OR road impact is severe; otherwise
    ``ordinary_puddle``; ``uncertain`` when the visual signal is unknown."""
    obs = bundle.observation
    deep = obs.waterlogging_level in _DEEP_LEVELS
    terrain = _has_terrain_risk(items)
    worst_road = _worst_road_impact(items)
    severe_road = worst_road is RoadImpactLevel.SEVERE

    if obs.status is WaterloggingStatus.ABSENT:
        severity, confidence = EventSeverity.ORDINARY_PUDDLE, Confidence.HIGH
        reasoning = "画面判定无积水，综合为普通路面状况。"
    elif obs.waterlogging_level is WaterloggingLevel.LX or obs.status is WaterloggingStatus.UNCERTAIN:
        severity, confidence = EventSeverity.UNCERTAIN, Confidence.LOW
        reasoning = "画面积水信号不明确（等级 LX 或 status uncertain），无法可靠定级。"
    elif deep or terrain or severe_road:
        severity = EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT
        confidence = Confidence.HIGH if (deep and terrain) else Confidence.MEDIUM
        signals = []
        if deep:
            signals.append(f"积水较深（{obs.waterlogging_level.value}）")
        if terrain:
            signals.append("已识别低洼地形风险")
        if severe_road:
            signals.append("道路通行影响达 severe")
        reasoning = "综合以下信号判为疑似具有内涝意义：" + "；".join(signals) + "。"
    else:
        severity = EventSeverity.ORDINARY_PUDDLE
        confidence = Confidence.MEDIUM
        reasoning = (
            f"积水较浅（{obs.waterlogging_level.value}）且无低洼地形风险、无 severe "
            "通行影响，综合为普通积水坑。"
        )

    return EventAssessment(
        severity=severity,
        confidence=confidence,
        mechanism=InferenceMechanism.RULE,
        reasoning=reasoning,
        evidence=_event_evidence(bundle, items),
    )


# --------------------------------------------------------------------------- #
# EventAssessment — LLM path.                                                  #
# --------------------------------------------------------------------------- #


_EVENT_SYSTEM = (
    "你是城市积水事件综合研判助手。基于结构化事实（FactBundle）与已生成的知识项，"
    "给出一个综合事件定级。只能从三档中选择：ordinary_puddle（普通积水坑）/ "
    "suspected_flood_significant（疑似具有内涝意义）/ uncertain（证据不足）。\n"
    "严格约束：不得引入事实以外的因果（禁止编造排水、降雨、事故原因）。\n"
    "只输出 JSON："
    '{"severity": "ordinary_puddle|suspected_flood_significant|uncertain", '
    '"confidence": "high|medium|low", "reasoning": str}'
)


def _items_summary(items: list[KnowledgeItem]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, TerrainRiskKnowledge):
            summary.append({"type": "terrain_risk", "lowness_class": item.lowness_class.value})
        elif isinstance(item, RoadImpactKnowledge):
            summary.append(
                {
                    "type": "road_impact",
                    "impacts": [{"actor": i.actor.value, "level": i.level.value} for i in item.impacts],
                }
            )
    return summary


def assess_event(
    bundle: FactBundle,
    items: list[KnowledgeItem],
    *,
    client: Optional[OpenAI] = None,
    model: str = DEFAULT_MODEL,
    thinking: str = "off",
    on_reasoning: Optional[ReasoningCallback] = None,
) -> EventAssessment:
    """Composite event tier. LLM when a client is wired; rule assessment
    otherwise / on failure. Always returns an EventAssessment (always eligible).
    """
    if client is None:
        return assess_event_rule(bundle, items)

    payload_obj = {
        "fact_bundle": json.loads(_fact_bundle_json(bundle)),
        "generated_items": _items_summary(items),
    }
    messages = [
        {"role": "system", "content": _EVENT_SYSTEM},
        {"role": "user", "content": "输入：\n" + json.dumps(payload_obj, ensure_ascii=False)},
    ]
    try:
        raw = _json_completion(
            client, model=model, messages=messages, thinking=thinking, on_reasoning=on_reasoning
        )
        payload = _extract_json(raw)
        severity = EventSeverity(str(payload.get("severity")))
    except Exception as exc:  # noqa: BLE001 — any failure ⇒ rule assessment
        log.warning("EventAssessment LLM 调用/解析失败，回退规则定级：%s", exc)
        return assess_event_rule(bundle, items)

    reasoning = str(payload.get("reasoning") or "").strip()
    if not reasoning:
        reasoning = assess_event_rule(bundle, items).reasoning

    return EventAssessment(
        severity=severity,
        confidence=_parse_confidence(payload.get("confidence")),
        mechanism=InferenceMechanism.LLM,
        reasoning=reasoning,
        evidence=_event_evidence(bundle, items),
    )
