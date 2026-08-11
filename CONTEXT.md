# 城市积水知识理解 Demo（南沙内涝）

面向政府合作方的概念验证 Demo：接收带位置信息的道路积水图片，经多模态 LLM 生成结构化 Observation，结合南沙真实路网（OSM）与高程（SRTM）数据，产出可追溯、分阶段展示的城市积水事件知识。

## Language

### 三层数据分离（架构核心，详见 PRD §4.4）

**Observation**:
来源于图片、回答 "What is visible?" 的事实层。一张图片对应一个 Observation；由 VLM 按 Observation Schema 生成，禁止混入外部知识或推导结论。
_Avoid_: detection result, inference

**Context**:
来源于外部城市数据（路网、高程等）、回答 "Where is it, and what is known about this place?" 的背景层。
_Avoid_: background knowledge（泛指时用 Context）

**Inference**:
由 Observation + Context 推导、回答 "What does this combination imply?" 的知识层。不得由 VLM 直接生成，也不得与 Observation 混成一个自由文本结论。
_Avoid_: conclusion, analysis（泛指时用 Inference）

### 空间与证据

**Grounding**:
把 Observation 关联到一个真实 Road / Location 实体的过程。真实道路身份必须来自图片位置信息 / Demo 输入 / GIS 空间匹配，不得依赖 LLM 世界知识。无法完成时保留 unresolved 状态。
_Avoid_: geo-tag, location lookup（指该机制时用 Grounding）

**Evidence Chain**:
从视觉证据 → 空间 Grounding → 城市背景 → 推导知识 → 事件评估的可展示链路。优先来自真实计算与数据引用，自然语言解释基于此链生成，而非据结论反向编造。
_Avoid_: reasoning trace

**Phenomenon Type**:
Observation 顶层的事件类型判别值（v1 仅 `road_waterlogging`），作为 Schema 向其他城市事件扩展的接缝；waterlogging 专属字段收纳在其同类型子块下。
_Avoid_: event category

**Visual Impact Hint**:
Observation 中、仅基于画面可见证据给出的影响提示（如淹没标线、接近车辆底盘）。是描述性观察，区别于 Knowledge Engine 基于道路背景产出的 `traffic_risk` 推论。

**Depth Estimate**:
Observation 层对积水深度的分层表达：`waterlogging_level`（L0–L5）是**视觉保守估计**，按可见强度给出、可在无尺寸参照时保守取档并标 `low` 置信；`depth_cm` 是**测量**，仅在存在可靠尺寸参照（清晰水位线、已知尺寸物体比例）时填写，否则全 `null`。二者分离——等级承载"估计"、厘米承载"测量"，不得无参照编造厘米数（PRD §4.13）。`LX` 仅在积水存在与否本身存疑时使用，非"缺参照"的兜底。
_Avoid_: depth value（指该分层表达时用 Depth Estimate）

### Context 层（城市背景）

**Urban Context**:
一个位置的背景层聚合——由若干 typed Context Block 组成，回答 "Where is it, and what is known about this place?"。不与 Observation（可见事实）或 Inference（推导知识）混层；以 `blocks` 列表承载，新知识源作为新 Block 类型接入，根模型不改形（ADR-0002）。
_Avoid_: background info, metadata（指该聚合时用 Urban Context）

**Context Block**:
Urban Context 内一个知识源的载荷单元，带 `block_type` 判别字段。v1 含 Road / Elevation / Terrain 三种；每个 Block 自带 Provenance 与 Availability。未来源（历史内涝、排水、POI 等）作为新 Block 类型平级扩展。
_Avoid_: context field, data entry

**Road Context**:
匹配到的道路实体属性（名称、highway 等级、车道、桥/隧、与 query point 的空间关系）。仅在 Grounding 成功后产出；Grounding unresolved 时该 Block 标 unavailable（Case F）。不携带道路几何。
_Avoid_: road info

**Elevation Context**:
绝对高程 + 周边地形统计（min/max/mean/std）。回答 "这里多高" 的事实层；可基于裸经纬度计算，不依赖道路匹配。

**Terrain Context**:
基于多尺度 TPI 的相对低洼判别（lowness_class 四档）。回答 "相对周边是否低洼"，是 Knowledge Engine 产出 TerrainRisk 知识、实现 Case C（视觉相同高程不同→知识不同）的依据。与 Elevation Context 分离。
_Avoid_: terrain data（指该判别时用 Terrain Context）

**Context Provider**:
某一知识源的查询实现（`query(point, grounding) -> Context Block`）。每源一个 provider；Context Assembler 按点遍历已注册 provider 组装 Urban Context。新源接入 = 新增 Block 类型 + 注册一个 provider。
_Avoid_: data source（指查询模块时用 Context Provider）

**Provenance**:
每个 Context Block 必带的数据来源标记（source 数据源/回退档位 + data_vintage + retrieved_at）。Evidence Chain 可追溯的前提；fallback 链命中哪一档必须可见。

**Availability**:
Context Block 的三态可用性 `available / unavailable / uncertain` + reason code。缺失数据由值表达而非缺键（沿用 ADR-0001）；承接 Case D（数据缺失）与 Case F（Grounding unresolved，但 Elevation/Terrain 仍可裸经纬度照算）。

### Knowledge 层（推导知识）

**Knowledge Engine**:
组合 Observation + Urban Context 产出可追溯推导知识的模块（PRD §4.10）。采用混合推理：规则引擎提取 FactBundle 并确定产出 TerrainRisk，LLM 仅在提取的事实上、白名单内辅助推断 RoadImpact 与 Event Assessment。不得退化成第二次 LLM 聊天（§7.2）。
_Avoid_: inference engine, reasoner（指该模块时用 Knowledge Engine）

**Knowledge Item**:
一条可追溯的推导断言，带 `knowledge_type` 判别 + statement + confidence + mechanism + evidence。`KnowledgeResult` 以 `list[KnowledgeItem]` 组合承载；新知识类型作为新 item 子类平级扩展，根模型不改形（与 Context Block 同构）。每条必带 ≥1 条 evidence（Case H）。
_Avoid_: conclusion, finding（指单条断言时用 Knowledge Item）

**Knowledge Result**:
一张图的 Knowledge Engine 产物聚合：`knowledge_items` + 单数 `event_assessment` + 一条 LLM 渲染的 `explanation`。explanation 基于结构化 Evidence Chain 生成，不得据结论反向编造（§4.14）。

**Terrain Risk**:
"积水发生在低洼位置" 的 Knowledge Item——Observation(有水) × TerrainContextBlock(低洼)。Case C 的核心证据项：同图在低洼点 vs 平坦点须产出 Terrain Risk vs 不产出，故永远由规则确定产出（mechanism=rule）。触发于 `lowness_class` ≥ moderately_low。
_Avoid_: flood risk（指该项时用 Terrain Risk；flood 风险归 Event Assessment）

**Road Impact**:
"对该道路通行有 [N] 影响" 的 Knowledge Item——Observation(深度/影响提示) × RoadContextBlock(等级/桥/隧)。取代从 Observation 迁出的 `traffic_risk`（ADR-0001），现基于真实道路属性；按 pedestrian / non_motor / motor 三 actor × 5 档给出。由 LLM 在 FactBundle 上推断。

**Event Assessment**:
综合事件定级（PRD §4.11）三档：普通局部积水 / 疑似具内涝意义 / 不确定。≈ ticket 命名的 FloodRisk，是 KnowledgeResult 的单数 roll-up 而非列表 item；允许使用 Observation + Context（非仅图像），与原始 Observation 分离存储（§3.5-27）。由 LLM 综合 FactBundle + 已生成 items 定级。
_Avoid_: classification, severity score（指该定级时用 Event Assessment）

**Evidence Reference**:
一条 Knowledge Item / Event Assessment 的依据指针，按来源分四型：observation / grounding / context（继承所在 Context Block 的 Provenance）/ derived（规则派生值）。Evidence Chain 由若干 Evidence Reference 串联，使"画面观察→道路定位→城市数据→推导→评估"可分别溯源（§4.14、Case H）。
_Avoid_: source link, citation（指该指针时用 Evidence Reference）

**Fact Bundle**:
规则引擎从 (Observation, Grounding, UrbanContext) 提取的 typed 结构化事实，是 LLM 辅助推断的**唯一**输入。LLM 只在其上、在 `eligible_types` 白名单内推断，不重新判图——这是防止 §7.2 退化的关键接缝。
_Avoid_: context payload（指该提取物时用 Fact Bundle）

**Inference Mechanism**:
每条 Knowledge Item 标注的产出方式 `rule`（确定规则）或 `llm`（模型推断），供 Evidence Chain 区分"硬规则产物"与"模型判断"（§4.16 可追溯）。Terrain Risk 恒为 rule（保 Case C）。
