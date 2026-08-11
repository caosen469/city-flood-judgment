"""Stage 3 explanation rendering (ADR-0004 §4.14).

The ``explanation`` field is a natural-language narration of the *whole*
Evidence Chain — what the government partner actually reads. Two paths:

* LLM rewrite of the structured chain into fluent zh-CN (default when a client
  is wired). The input is the already-generated items + assessment; the LLM may
  only rephrase, **never reverse-fabricate** a cause (PRD §4.14, Case G). A hard
  system prompt forbids introducing chain-external causation.
* A deterministic template fallback (``render_explanation_template``) when no
  client is available / the LLM fails — so the engine always produces a readable
  chain narration offline and in tests.

The template is also the spec for what the chain contains; the LLM path feeds
the same structured summary, keeping the two consistent.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from openai import OpenAI

from schemas.knowledge import (
    EventAssessment,
    EventSeverity,
    FactBundle,
    KnowledgeItem,
    RoadImpactLevel,
    TerrainRiskKnowledge,
    RoadImpactKnowledge,
)

from vlm.client import make_client

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen-plus"
ReasoningCallback = Callable[[str], None]

_SEVERITY_ZH: dict[EventSeverity, str] = {
    EventSeverity.ORDINARY_PUDDLE: "普通积水坑",
    EventSeverity.SUSPECTED_FLOOD_SIGNIFICANT: "疑似具有内涝意义",
    EventSeverity.UNCERTAIN: "暂不确定",
}

_LEVEL_ORDER = [
    RoadImpactLevel.LOW,
    RoadImpactLevel.MEDIUM,
    RoadImpactLevel.HIGH,
    RoadImpactLevel.SEVERE,
]


# --------------------------------------------------------------------------- #
# Template fallback (deterministic).                                           #
# --------------------------------------------------------------------------- #


def _worst_road_level(items: list[KnowledgeItem]) -> Optional[RoadImpactLevel]:
    worst, idx = None, -1
    for item in items:
        if not isinstance(item, RoadImpactKnowledge):
            continue
        for imp in item.impacts:
            if imp.level in _LEVEL_ORDER and _LEVEL_ORDER.index(imp.level) > idx:
                idx, worst = _LEVEL_ORDER.index(imp.level), imp.level
    return worst


def render_explanation_template(
    items: list[KnowledgeItem], assessment: EventAssessment, bundle: FactBundle
) -> str:
    """Deterministic zh-CN narration of the chain (offline / test fallback)."""
    obs = bundle.observation
    parts: list[str] = []

    severity_zh = _SEVERITY_ZH.get(assessment.severity, assessment.severity.value)
    parts.append(
        f"综合判定：本次事件为「{severity_zh}」"
        f"（画面积水 {obs.waterlogging_level.value}、状态 {obs.status.value}）。"
    )

    terrain = next((i for i in items if isinstance(i, TerrainRiskKnowledge)), None)
    if terrain is not None:
        comp = (
            f"{terrain.composite_tpi_m:.2f} m"
            if terrain.composite_tpi_m is not None
            else "未知"
        )
        parts.append(
            f"地形证据：积水点处于 {terrain.lowness_class.value} 低洼位置"
            f"（多尺度 TPI composite {comp}），易于汇水积水。"
        )
    elif not bundle.terrain.available:
        parts.append("地形证据：terrain 块不可用，未识别低洼地形风险。")

    road = next((i for i in items if isinstance(i, RoadImpactKnowledge)), None)
    if road is not None:
        worst = _worst_road_level(items)
        actors = "、".join(f"{i.actor.value}={i.level.value}" for i in road.impacts)
        parts.append(
            f"通行影响：结合匹配道路属性，三类使用者的影响为 {actors}"
            + (f"（最严重 {worst.value}）。" if worst else "。")
        )
    # RoadImpact absent only when the gate was closed (grounding unresolved / no
    # road block) — surface that honestly rather than silently omitting.
    road_eligible = any(
        getattr(i, "knowledge_type", None) == "road_impact" for i in items
    )
    if road is None and not road_eligible:
        if obs.status.value == "present":
            parts.append("通行影响：未匹配到可靠道路，未生成道路通行影响判断。")

    parts.append(f"判级依据：{assessment.reasoning}")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# LLM rewrite.                                                                 #
# --------------------------------------------------------------------------- #


_EXPLAIN_SYSTEM = (
    "你是城市积水研判的叙述撰写者。你会收到结构化的证据链（事件定级 + 已生成的知识项"
    "+ 事实摘要）。请把它改写成一段通顺、客观的中文叙述，供政府合作方阅读。\n"
    "严格约束：\n"
    "1) 只能复述/重组证据链中已有的事实与判断，不得引入任何链外的因果或猜测"
    "（禁止编造降雨、排水管网堵塞、事故、时间等）。\n"
    "2) 不得编造数值；数值只能引用链中给出的。\n"
    "3) 输出纯文本，2-4 句话，不要列表、不要 JSON、不要标题。"
)


def _chain_json(
    items: list[KnowledgeItem], assessment: EventAssessment, bundle: FactBundle
) -> str:
    terrain = next((i for i in items if isinstance(i, TerrainRiskKnowledge)), None)
    road = next((i for i in items if isinstance(i, RoadImpactKnowledge)), None)
    chain = {
        "event_assessment": {
            "severity": assessment.severity.value,
            "confidence": assessment.confidence.value,
            "reasoning": assessment.reasoning,
        },
        "observation": {
            "status": bundle.observation.status.value,
            "waterlogging_level": bundle.observation.waterlogging_level.value,
            "visual_impact_hint": bundle.observation.visual_impact_hint.value,
        },
        "terrain_risk": (
            {
                "lowness_class": terrain.lowness_class.value,
                "composite_tpi_m": terrain.composite_tpi_m,
                "statement": terrain.statement,
            }
            if terrain
            else None
        ),
        "road_impact": (
            {
                "impacts": [
                    {"actor": i.actor.value, "level": i.level.value} for i in road.impacts
                ],
                "statement": road.statement,
            }
            if road
            else None
        ),
        "terrain_available": bundle.terrain.available,
        "road_available": bundle.road.available,
    }
    return json.dumps(chain, ensure_ascii=False)


def render_explanation(
    items: list[KnowledgeItem],
    assessment: EventAssessment,
    bundle: FactBundle,
    *,
    client: Optional[OpenAI] = None,
    model: str = DEFAULT_MODEL,
    on_reasoning: Optional[ReasoningCallback] = None,
) -> str:
    """LLM rewrite of the chain, or the deterministic template as fallback."""
    template = render_explanation_template(items, assessment, bundle)
    if client is None:
        return template

    messages = [
        {"role": "system", "content": _EXPLAIN_SYSTEM},
        {"role": "user", "content": "证据链：\n" + _chain_json(items, assessment, bundle)},
    ]
    try:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if on_reasoning is not None:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
            parts: list[str] = []
            for chunk in client.chat.completions.create(**kwargs):
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                extra = getattr(delta, "model_extra", None)
                if extra and isinstance(extra, dict) and extra.get("reasoning_content"):
                    on_reasoning(extra["reasoning_content"])
                content = getattr(delta, "content", None)
                if isinstance(content, str):
                    parts.append(content)
            text = "".join(parts).strip()
        else:
            resp = client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — any failure ⇒ template
        log.warning("explanation LLM 渲染失败，回退模板：%s", exc)
        return template

    return text or template
