# ADR 0004 — Knowledge Engine：混合推理（规则提取 + LLM 辅助推断）+ 组合式 Knowledge

PRD §4.10 要求一个轻量 Knowledge Engine：接收 Structured Observation + Urban Context，组合二者产出 contextualized knowledge，保留 evidence，输出可解释结果。§7.2 明确禁止它退化成"第二次 LLM 聊天"；§5.3 Case C（视觉相同、地形不同→知识不同）"非常重要"，须确定性成立；§4.12/§4.13/Case G 禁止无据因果（排水管网堵塞、暴雨导致等）。本决定（wayfinder #7）确定 Knowledge 层的数据模型、推理分工、规则表与不准生成知识的约束机制。

## 决定

1. **组合式 KnowledgeResult**：`KnowledgeResult { knowledge_items: list[KnowledgeItem]（判别联合，按 knowledge_type）+ event_assessment: EventAssessment + explanation: str }`。每个 item 独立带 evidence；新知识类型 = 新 item 子类 + 新 `knowledge_type` 字面量，根模型不改形——与 ADR-0002（Urban Context 的 `blocks` 列表 + 判别 `block_type`）同构，全栈扩展机制一致。Event Assessment 是**单数**综合 roll-up，非列表项（§4.11 综合判断、§3.5-27 与 Observation 分离存储）。

2. **v1 Knowledge 类型集**（对齐 ticket 命名 FloodRisk / TerrainRisk / RoadImpact）：
   - `TerrainRiskKnowledge` —— Observation(有水) × TerrainContextBlock(低洼) → "积水发生在 [moderately_low/significantly_low] 低洼位置"。**Case C 的核心 item**。
   - `RoadImpactKnowledge` —— Observation(深度/影响提示) × RoadContextBlock(等级/桥/隧) → 取代从 Observation 迁出的 `traffic_risk`（ADR-0001），现基于真实道路属性。保留旧 `pedestrian / non_motor_vehicle / motor_vehicle` 三 actor 拆分；等级沿用旧 5 档 `low/medium/high/severe/uncertain`。
   - `EventAssessment` —— ≡ ticket 的 FloodRisk，综合三档 `ordinary_puddle / suspected_flood_significant / uncertain`（§4.11）。FloodRisk 与 Event Assessment 合并为同一物，不重叠。
   - **不设"纯 Context-only"knowledge item**：Knowledge 永远是"关联"（§7.3 要求引入 Observation 之外信息并与数据语义关联），孤立背景事实留在 Context 层不重发；桥/隧事实作 RoadImpact 的 evidence/触发条件，不单发。

3. **混合推理，LLM 可介入（Q2/Q4）**——分工线：
   - **规则引擎（确定）**：(i) 从 (Observation, Grounding, UrbanContext) 提取 typed `FactBundle`；(ii) 资格门（见下）；(iii) **完整产出 `TerrainRiskKnowledge`**（查表：有水 且 `lowness_class ∈ {moderately_low, significantly_low}`）——Case C 必须确定，TerrainRisk 永远 `mechanism=rule`（schema 校验器锁死）。
   - **LLM（辅助推断）**：在规则提取的 FactBundle 上、白名单 `knowledge_type` 内，推断 `RoadImpactKnowledge` 与 `EventAssessment`；并把整条 chain 渲染成 `explanation`（§4.14：基于 chain 生成，不得反向编造）。LLM 只在规则提取的 grounded 事实上推理，**不重新判图**。
   - 因此"inference 允许 LLM 介入"成立（RoadImpact / Event Assessment 是真推断），而 Case C 由规则确定性保证。

4. **Evidence 四型判别联合（Q5）**：`EvidenceRef` 按 `ref_type` 分 `observation_ref / grounding_ref / context_ref / derived_ref`。`context_ref` 指向 block 字段时**继承该 block 已有的 Provenance**（source/vintage/retrieved_at 不重存）。每个 KnowledgeItem / EventAssessment 的 `evidence` 强制非空（`min_length=1`）——落 PRD Case H。

5. **不准生成知识的三层约束（Q7，Case G/D/F）**：
   - **结构白名单（主）**：`KnowledgeType` 是闭集（v1 仅 `terrain_risk / road_impact`），LLM 输出 schema 物理上没有"causal"类型，"排水管网堵塞"无处安放。
   - **资格门（规则层）**：类型只在所需数据齐全时才 eligible——terrain 块 unavailable/`insufficient_data` 或无水 → 不生成 TerrainRisk（**Case D**）；grounding unresolved 或 road 块 unavailable → 不生成 RoadImpact（**Case F**）。FactBundle.eligible_types 承载门控结果，LLM 只能在其内推断。
   - **后校验（兜底）**：emit 的每条 item 必须 type ∈ 白名单 **且** evidence 非空且指向真实提取事实，否则丢弃并记 warn；附 negative prompt 作软约束。因果诊断整体已在 map Out of scope（§4.13/§6.7），本机制从实现层再锁一道。

6. **TerrainRisk 触发阈值（Q12）**：`moderately_low` 及以上（composite TPI ≥ 1.0m）触发。30m SRTM 分辨率下亚米级 `slightly_low`（0.3–1m）噪声偏大，记 evidence 但不立为风险。阈值以常量 `TERRAIN_RISK_CLASSES` 内联契约（单一真值源），`terrain_risk_eligible()` 为门控函数。

7. **"unknown by value"**：沿用 ADR-0001，必需键一律出现；缺失由 `severity=uncertain` / `level=uncertain` / 可空数值 / 空列表表达。

## 第一版推理规则表（规则引擎部分）

| 规则 | 资格门（不满足则不生成 / 不开门） | 产出方 | 产出 |
|---|---|---|---|
| TerrainRisk | `status=present` **且** terrain 块可用 **且** `lowness_class ∈ {moderately_low, significantly_low}` | 规则（确定） | `TerrainRiskKnowledge`（mechanism=rule） |
| RoadImpact | `status=present` **且** grounding ∈ {grounded, ambiguous} **且** road 块可用 | LLM（在 FactBundle 上） | `RoadImpactKnowledge`（三 actor × 5 档） |
| Event Assessment | 始终 eligible（可判 `uncertain`） | LLM（FactBundle + 已生成 items） | `EventAssessment`（三 tier） |

注：按 ADR-0002，grounding unresolved 时 Elevation/Terrain 仍基于裸经纬度照算，故 TerrainRisk 在 Case F 下仍可能生成（只要 terrain 命中触发档）；RoadImpact 则因依赖道路属性而关门。

## 模块接口（接口规格，非实现）

```
src/schemas/knowledge.py     # 本契约（纯数据模型 + 阈值常量 + 门控函数）—— 已落地
src/knowledge/               # 实现层（待建，#8 Pipeline 之后）
  rules.py      # 规则引擎：提取 FactBundle + 资格门 + 确定 TerrainRisk
  infer.py      # LLM 辅助推断：RoadImpact + EventAssessment（schema 白名单 + 后校验）
  explain.py    # LLM 渲染 explanation（输入=结构化 chain）
  engine.py     # KnowledgeEngine.assemble(observation, grounding, context) -> KnowledgeResult
```

```python
# 规则引擎：纯函数，可单测
def extract_fact_bundle(obs, grounding, context) -> FactBundle: ...
def terrain_risk_eligible(status, terrain_class) -> bool: ...  # 已在契约内

# LLM 辅助推断：输入 FactBundle + 已生成的规则项，输出受 schema 白名单约束
def infer_road_impact(bundle, terrain_item) -> RoadImpactKnowledge | None: ...
def assess_event(bundle, items) -> EventAssessment: ...
def render_explanation(items, assessment) -> str: ...
```

## 考量

这是难以回退的决定：一旦 #8（Pipeline）与前端绑定到"组合式 items + 判别 knowledge_type + TerrainRisk 必规则"的形状，事后改动代价随下游增长放大。它也需要解释——读者会奇怪为何 (1) 推理分工把 TerrainRisk 锁给规则却让 LLM 做 RoadImpact/Event Assessment、(2) 不设纯 Context-only item、(3) 用 LLM 渲染 explanation 而非模板。

- **TerrainRisk 必规则、其余可 LLM**：Case C 是 Demo 要证明的核心差异（§7.4），"同图不同地形→不同 TerrainRisk"必须每次必然成立——只有规则查表能铁定保证；若交 LLM，它可能两次给出不一致结果，Case C 失守。而 RoadImpact（深度×道路等级×桥隧的综合通行影响）与 Event Assessment（"普通 vs 内涝意义"的综合定级）是真正需要判断的，让 LLM 在规则提取的 FactBundle 上、白名单内推断，既满足项目方"inference 让 LLM 介入"的意图，又有资格门 + 证据约束兜底。备选 (a) 全部 item 归规则、LLM 只渲染——被否，因项目方明确要 LLM 介入推理，且 Event Assessment 的综合判断交给规则表会过度硬化；备选 (c) 全部 item 归 LLM——被否，因 Case C 不再确定。RoadImpact 够表格化，若日后要最大化确定性可回退为规则查表（杠杆保留）。
- **不设纯 Context-only item**：§7.3 的 Knowledge 定义要求"引入 Observation 之外信息并与数据语义关联、产出新 contextualized assertion"；孤立背景事实（"该点低洼"）已在 Terrain Context 里，重发为 knowledge 是重复且不达标。桥/隧等道路事实作 RoadImpact 的 evidence 即可。
- **LLM 渲染 explanation vs 模板**：政府合作方看到的自然需要通顺中文叙述，LLM 改写比模板生硬更适 Demo；且输入是结构化 chain，输出受限为 chain 的改写，§4.14 合规。模板作为无 LLM 时的降级 fallback 保留。
- **Evidence 继承 block Provenance**：避免 provenance 双写（block 一份、evidence 一份）造成不一致；context_ref 只指 block 字段，信任溯源随 block 走。

## 影响

- **解除 #8（Pipeline）Stage 3 数据契约**：`KnowledgeEngine.assemble(observation, grounding, context) -> KnowledgeResult`；部分结果策略由"缺数据的 item 不生成 + Event Assessment/explanation 显式说明"表达（Case D/F）。
- **为 #9（前端）定 Stage 3 展示物**：`knowledge_items`（带 evidence + mechanism 标签）+ `event_assessment` + `explanation`，直接对应"What It Means"面板与 Evidence Chain。
- **解除 map 的 Event Assessment 分级 fog（部分）**：v1 三档标准已定（见本 ADR + 契约）；"跑通原型后细化"仍 pending，留在 map Not yet specified。
- **与 ADR-0001/0002/0003 一致**：复用 Observation 的 `Confidence` 枚举（跨层一致，同 Grounding/ADR-0003）；Evidence 的 context_ref 复用 Context block 的 Provenance；判别联合扩展机制与 phenomenon_type（ADR-0001）、block_type（ADR-0002）同构。
- **未来扩展**：新 Context 源（历史内涝/排水/POI，§4.9）接入 → 新 `KnowledgeType` + 新 item 子类 + 对应规则/LLM 推断，根模型与既有 item 零改动。
