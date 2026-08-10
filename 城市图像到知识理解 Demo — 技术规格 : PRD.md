# 城市图像到知识理解 Demo — 技术规格 / PRD

## 文档状态

**阶段：** Demo / Proof of Concept
**首个垂直场景：** 城市道路内涝
**主要使用对象：** 政府城市管理相关合作方
**核心能力定位：** Urban Image → Structured Observation → Urban Context → Contextualized Knowledge
**长期愿景：** Urban Data → Knowledge → Management Understanding

---

# 1. 问题陈述（Problem Statement）

政府现有或潜在的城市视觉感知系统能够利用摄像头、无人机或图像识别模型发现道路中的“水”或“积水区域”，但单纯的视觉检测存在明显局限。

典型问题包括：

* 小面积普通水洼容易被识别成内涝；
* 模型能够检测“存在水”，但无法充分判断该积水是否已经构成值得关注的城市事件；
* 单一类别标签无法描述积水范围、道路覆盖、车辆涉水、通行受影响程度等更丰富的场景信息；
* 图像识别结果与道路、地形、高程等既有城市数据彼此分离；
* 即使识别出疑似内涝，系统仍难回答“该事件发生在怎样的城市环境中”“为什么值得关注”“当前判断依据是什么”等问题。

因此，当前实际需求不仅是提高“内涝 / 非内涝”分类精度，而是：

> **让系统从“看到画面里有水”，提升到“理解这里发生了什么样的城市积水事件，并能够结合城市背景生成更完整、可解释的知识”。**

第一阶段项目不是为了构建完整的自动化城市决策系统，而是通过一个小型、直观、可演示的 Demo 向政府合作方证明：

1. 多模态大模型能够对单帧城市图片进行比传统二分类更丰富的场景理解；
2. 大模型输出可以被转换成稳定、结构化的 Observation；
3. Observation 可以与道路、高程等已有城市数据关联；
4. 关联后可以形成图片本身不能直接提供的风险、影响和上下文知识；
5. 系统能够展示这些知识是依据哪些 observation 和城市数据形成的。

最终希望建立一个更大的产品愿景：

> **From seeing the city to understanding the city.**

---

# 2. 解决方案（Solution）

系统提供一个面向城市事件理解的轻量级 Data-to-Knowledge Pipeline。

第一版以内涝为唯一需要真正做通的 vertical use case。

核心链路为：

**Single Image**

→ **Multimodal LLM Visual Understanding**

→ **Structured Observation**

→ **Observation Schema / Lightweight Ontology Validation**

→ **Spatial / Road Grounding**

→ **Urban Context Enrichment**

→ **Knowledge Inference**

→ **Event / Risk / Impact Knowledge**

→ **Evidence Chain + Human-readable Explanation**

系统首先使用多模态大模型理解图片，但不允许模型自由生成任意结构的城市知识。

模型第一阶段的职责是：

> **描述“从图像中观察到了什么”。**

例如：

* 是否存在明显积水；
* 积水范围；
* 道路被水覆盖的程度；
* 是否存在车辆涉水；
* 是否出现明显交通影响线索；
* 图像是否存在足够证据支持内涝判断；
* 模型对此判断的不确定性。

这些结果将被规范化成结构化 Observation。

结构化 Observation 受到一个轻量级 Observation Schema / Ontology 的约束，用于规定：

* 可以输出哪些 observation 类型；
* 每种 observation 有哪些属性；
* 属性值的允许范围；
* 枚举值；
* 必要字段；
* 不允许的字段组合；
* 未知信息如何表示。

随后，系统利用图片对应位置或道路实体，把 Observation grounding 到真实的城市对象。

例如：

**ObservedWaterArea**

→ located_on

**Road_A**

然后关联 Road_A 的已有城市数据，例如：

* 道路空间位置；
* 道路属性；
* 当前点位高程；
* 周围区域高程；
* 地形特征。

系统基于：

**Visual Observation + Urban Context**

生成新的 contextualized knowledge。

例如：

> 图像显示较大面积道路积水。

结合：

> 该事件发生在 Road_A。

结合：

> 当前路段位于相对周边较低的地形位置。

形成：

> 该积水发生在局部低洼道路位置，其城市背景与普通随机小水洼存在明显差异。

第一版 Demo 的输出重点停留在：

* Event Characterization；
* Risk / Impact Knowledge；
* Evidence / Reasoning Chain。

系统明确不负责直接替政府做正式管理决策。

---

# 3. 用户故事（User Stories）

## 3.1 图片输入与视觉理解

1. 作为城市管理人员，我想上传一张道路场景图片，以便系统分析当前场景是否存在明显积水现象。

2. 作为城市管理人员，我想让系统区分普通小水洼和更可能构成道路内涝的积水，以便减少仅凭“画面中存在水”产生的误判。

3. 作为城市管理人员，我想让系统不仅输出“内涝 / 非内涝”，还描述它从图片中观察到的关键证据，以便理解判断依据。

4. 作为城市管理人员，我想看到积水范围、道路覆盖、车辆涉水等视觉信息，以便快速理解事件的实际情况。

5. 作为城市管理人员，我想看到模型对当前判断的不确定程度，以便知道哪些图片需要进一步人工核查。

6. 作为系统开发者，我想让多模态模型生成结构化 Observation，而不是只有自然语言回答，以便这些结果可以被后续知识模块可靠消费。

7. 作为系统开发者，我想让模型在无法从图片确认某项属性时明确输出 unknown / uncertain，而不是自行猜测，以便减少虚构事实进入知识层。

---

## 3.2 Observation Schema / Ontology

8. 作为系统开发者，我想定义一套统一的 Observation Schema，以便不同图片和不同模型产生一致的数据结构。

9. 作为系统开发者，我想约束每个 Observation 可以包含哪些属性，以便防止 LLM 每次生成不同形式的数据。

10. 作为系统开发者，我想限制枚举类属性的允许值，以便后续规则、查询和知识推理能够稳定运行。

11. 作为系统开发者，我想区分“图片中直接观察到的事实”和“后续系统推导出的知识”，以便保持数据来源清晰。

12. 作为系统开发者，我想保存 Observation 的置信度或不确定性，以便知识层能够识别低可靠输入。

13. 作为未来扩展开发者，我想让 Observation Schema 独立于“内涝”这一单一事件，以便后续扩展到其他城市事件时可以复用整体框架。

---

## 3.3 空间与道路实体关联

14. 作为城市管理人员，我想知道当前积水对应哪一个真实道路或空间位置，以便把视觉发现放入实际城市环境中。

15. 作为系统开发者，我想把视觉 Observation grounding 到明确的 Road / Location 实体，以便后续查询该位置已有城市数据。

16. 作为系统开发者，我想明确区分“图片中看到了道路”和“该图片对应数据库中的哪条道路”，以便避免视觉推断代替真实空间关联。

17. 作为系统开发者，我想在无法确定道路实体时保留 unresolved 状态，以便系统不会错误关联城市背景信息。

---

## 3.4 城市背景知识

18. 作为城市管理人员，我想查看发生积水位置的道路背景，以便理解该事件所处的城市环境。

19. 作为城市管理人员，我想查看该位置的高程和相对周边地形特征，以便判断它是否处于明显低洼区域。

20. 作为系统开发者，我想根据道路实体查询已有道路数据，以便把视觉结果与真实城市数据结合。

21. 作为系统开发者，我想根据道路位置查询高程数据，以便生成地形上下文。

22. 作为系统开发者，我想区分“绝对高程”和“相对周边是否低洼”，以便生成对内涝场景更有意义的知识。

23. 作为未来扩展开发者，我想能够继续增加道路等级、历史内涝、排水设施、POI、关键设施等知识源，而不需要重构整个视觉分析链路。

---

## 3.5 Event Characterization

24. 作为城市管理人员，我想得到比“检测到水”更完整的事件描述，以便快速理解发生了什么。

25. 作为城市管理人员，我想看到系统对当前场景属于普通积水还是疑似内涝的综合判断，以便快速筛选值得进一步关注的事件。

26. 作为城市管理人员，我想看到该判断分别受哪些视觉证据支持，以便理解分类结果。

27. 作为系统开发者，我想将 Event Assessment 与原始 Observation 分开存储，以便以后可以调整推理逻辑，而无需重新生成所有视觉 Observation。

28. 作为系统开发者，我想允许 Event Assessment 使用 Observation 和 Urban Context，而不是强制只依赖图片，以便知识增强真正能够影响事件理解。

---

## 3.6 Risk / Impact Knowledge

29. 作为城市管理人员，我想知道当前积水是否发生在相对低洼位置，以便理解事件潜在的发展背景。

30. 作为城市管理人员，我想知道当前积水是否涉及重要道路属性，以便理解其潜在道路影响。

31. 作为城市管理人员，我想看到系统从图片和城市数据联合推导出的附加知识，以便获得比单一图片识别更丰富的信息。

32. 作为系统开发者，我想保证知识层只生成有明确 observation 或城市数据支撑的结论，以便避免 LLM 根据常识无限扩展。

33. 作为系统开发者，我想让知识输出能够明确区分：

* observed；
* retrieved / grounded；
* inferred；
  以便保持知识来源透明。

34. 作为系统开发者，我想为 inferred knowledge 保存支持它的 evidence references，以便系统可以生成解释链。

---

## 3.7 Evidence / Explanation

35. 作为城市管理人员，我想知道系统为什么认为该场景比普通小水洼更值得关注，以便判断系统结果是否可信。

36. 作为城市管理人员，我想看到一条从图片证据到城市背景再到最终判断的简明链路，以便快速验证判断逻辑。

37. 作为城市管理人员，我想能够区分哪些信息来自图片、哪些来自道路或高程数据库、哪些是系统推导出来的，以便避免把所有内容误认为模型直接观察所得。

38. 作为系统开发者，我想让 Evidence Chain 使用实际数据引用，而不是让 LLM 在得到结论后重新编造解释，以便解释和推理依据一致。

39. 作为系统开发者，我想允许系统同时提供结构化 evidence 和自然语言 explanation，以便兼顾机器处理和 Demo 展示。

---

## 3.8 Demo 展示

40. 作为政府合作方，我想看到一张图片从输入到知识生成的完整过程，以便理解该系统与普通图像识别的区别。

41. 作为政府合作方，我想看到“系统看到了什么”和“系统知道了什么”分别展示，以便理解视觉感知和知识增强之间的差异。

42. 作为政府合作方，我想看到道路和高程数据如何改变或丰富对积水事件的判断，以便理解现有城市数据的额外价值。

43. 作为政府合作方，我想看到系统生成的知识对应明确的数据依据，以便建立对 Demo 的信任。

44. 作为政府合作方，我想看到该系统未来如何从内涝扩展到其他城市事件，以便理解长期建设价值。

45. 作为项目团队，我想用内涝作为一个具体且容易理解的 showcase，以便展示更长期的 Urban Data → Knowledge 能力。

---

## 3.9 异常与不确定场景

46. 作为系统用户，我想在图片质量不足时看到“无法可靠判断”，而不是强制给出内涝结果，以便避免误导。

47. 作为系统用户，我想在无法确定图片对应道路时看到明确提示，以便理解后续城市背景分析为什么无法执行。

48. 作为系统用户，我想在高程或道路数据缺失时仍然看到视觉 Observation，同时明确哪些知识增强步骤未完成，以便系统可以部分工作。

49. 作为系统开发者，我想让整个 pipeline 支持部分结果，而不是任何一个知识源缺失就导致整个分析失败。

50. 作为系统开发者，我想记录每一步数据和判断状态，以便调试 Demo 中出现的误判。

---

# 4. 实现决策（Implementation Decisions）

## 4.1 产品边界

第一版是：

> **面向政府合作方的概念验证 Demo。**

不是：

* 完整商业产品；
* 完整智慧城市平台；
* 完整城市知识图谱；
* 自动政府决策系统；
* 科研 benchmark；
* 以算法 novelty 为首要目标的研究项目。

优先级是：

1. 证明视觉理解价值；
2. 证明城市数据能够丰富视觉结果；
3. 证明 Data → Knowledge 链路；
4. 用一个清晰 Demo 表达长期愿景。

---

## 4.2 第一版输入

第一版视觉输入固定为：

**单帧图片。**

当前不要求：

* 视频；
* 连续帧；
* 时间序列；
* 实时流；
* 多摄像头事件跟踪。

因此第一版不得依赖：

* 积水增长速度；
* 水位变化；
* 持续时间；
* 事件演化趋势；

作为核心判断依据。

---

## 4.3 多模态大模型角色

Multimodal LLM 主要承担：

### 视觉语义理解

识别：

* 水体 / 积水；
* 道路区域；
* 水覆盖程度；
* 车辆与积水交互；
* 道路通行相关视觉线索；
* 其他 schema 中允许的视觉 observation。

### Structured Observation Generation

模型需要按照系统提供的 Schema 产生结构化结果。

### Human-readable Explanation

可以额外提供面向用户的自然语言说明。

LLM 不应该直接成为：

* 城市道路数据库；
* 高程数据库；
* 城市事实来源；
* 正式管理规则来源；
* 正式政策来源。

---

## 4.4 Observation 与 Inference 分离

这是当前架构中的核心决策。

系统必须逻辑上区分：

### Observation

来源于图片。

回答：

> **What is visible?**

### Context

来源于外部城市数据。

回答：

> **Where is it, and what is known about this place?**

### Inference

来源于 Observation + Context。

回答：

> **What does this combination imply?**

不能把三个阶段混成一个自由生成的 LLM response。

---

## 4.5 Observation Schema / Lightweight Ontology

第一版需要建立轻量 Schema。

其职责主要是：

* 规范 LLM 输出；
* 提供统一属性；
* 提供枚举值；
* 允许 unknown；
* 支撑后续知识模块；
* 为未来其他城市事件留下扩展空间。

Schema 的详细字段目前没有确定。

因此当前规格只要求：

> **Schema 存在，并作为模型结构化输出契约。**

不能要求第一版先建设完整 Urban Ontology。

---

## 4.6 建议的概念级数据形状

以下为规格级概念，不代表最终 API 字段名称：

### Observation

包含：

* observation identifier；
* source image；
* detected phenomenon；
* visual attributes；
* confidence / uncertainty；
* supporting visual cues。

### Grounded Entity

包含：

* entity type；
* entity identifier；
* spatial association；
* grounding confidence / status。

### Urban Context

包含：

* road attributes；
* elevation；
* relative terrain features；
* future optional context fields。

### Inferred Knowledge

包含：

* knowledge statement；
* knowledge type；
* evidence references；
* confidence / uncertainty；
* inference source。

### Evidence

能够指向：

* image observation；
* grounded urban entity；
* retrieved city data；
* derived calculation；
* prior inference。

---

## 4.7 道路 Grounding

Observation 必须能够关联到一个实际 Road / Location，才能进入完整知识增强阶段。

Grounding 不应该通过 LLM 世界知识完成。

真实道路身份应来自：

* 图片自带位置信息；
* Demo 输入；
* GIS 空间匹配；
* 或其他真实城市数据关联方式。

如果无法完成 grounding：

系统仍可以返回视觉分析结果，但不得假设某条具体道路。

---

## 4.8 第一版城市知识源

已确认可以使用：

### Road Data

例如：

* road geometry；
* road identity；
* 已有道路属性。

### Elevation / Terrain Data

至少支持：

* 当前道路或点位高程；
* 周边高程；
* 相对高低关系。

第一版应该优先验证：

> **相对地形信息是否可以给内涝理解提供额外价值。**

---

## 4.9 后续可扩展 Knowledge Sources

未来可增加，但第一版不要求：

* Road class；
* Historical flooding；
* Drainage network；
* Drainage facilities；
* Critical facilities；
* POI；
* Rainfall；
* Traffic；
* Population；
* Emergency information；
* Planning / regulation documents。

系统架构应允许增加知识源，但不需要现在全部实现。

---

## 4.10 Knowledge Engine

第一版需要一个轻量 Knowledge Engine。

它不要求一定采用：

* RDF；
* OWL；
* Neo4j；
* Property Graph；
* GraphRAG；
* Vector RAG。

这些属于后续技术选择。

Knowledge Engine 的功能要求是：

1. 接收 Structured Observation；
2. 获取与事件位置有关的城市上下文；
3. 组合 Observation + Context；
4. 生成 contextualized knowledge；
5. 保留 evidence；
6. 输出可解释结果。

重点是能力，而不是具体数据库品牌或知识表示形式。

---

## 4.11 Event Assessment

系统需要提供比原始视觉 Observation 更高层的事件刻画。

至少逻辑上支持：

* 普通局部积水；
* 疑似具有内涝意义的道路积水；
* 不确定。

具体分类等级后续可以调整。

Event Assessment 可以使用：

**Observation + Context**

而不是固定为：

**Image only**。

这是为了允许城市知识真正参与事件理解。

---

## 4.12 Risk / Impact Knowledge

第一版 Knowledge Engine 的主要价值输出为：

> **Risk / Impact Understanding**

例如：

* 当前积水发生于局部低洼区域；
* 当前积水对应特定道路；
* 该位置的城市环境可能使事件比普通孤立水洼更值得关注；
* 当前事件具有潜在道路通行影响。

知识输出必须有证据来源。

不得生成没有数据基础的：

* 排水管网堵塞；
* 排水能力不足；
* 暴雨导致；
* 基础设施失效；

等因果结论，除非未来确实接入相应数据。

---

## 4.13 原因分析与风险分析分离

当前 Demo 主要做：

**Risk / Impact Analysis**

不主要做：

**Causal / Mechanism Analysis**

因为当前数据主要是：

* 单帧图片；
* 道路；
* 高程。

这些信息不足以可靠确认内涝形成原因。

因此可以说：

> 当前位置具有局部低洼特征。

不能无依据说：

> 当前内涝是由于排水管网堵塞造成的。

同样的诚实边界适用于**积水深度估计**（Observation 层，详见 Observation Schema §3.4）：

* **厘米测量（`depth_cm`）仅在存在可靠尺寸参照时填写**——清晰水位线、或已知尺寸物体与水面的明确比例；无可靠参照时保持 `null`，不编造精确厘米数。
* **深度等级（`waterlogging_level`）是视觉保守估计**：即使无可靠尺寸参照，只要积水存在且视觉强度可辨，仍按可见强度给出保守等级（如 L2/L3）并标 `low` 置信。等级承载"估计"、厘米承载"测量"，二者分离。
* **`LX` 仅在积水存在与否本身存疑时使用**（极端模糊、夜间无光、镜头污渍遮挡、信号相互矛盾），不是"有积水但缺参照"的兜底——后者仍给保守等级。
* 等级估算本质保守，歧义图（反光 / 阴影 / 路面材质易混）可能高估或低估；是否填写厘米亦依赖模型对"可靠参照"的判断，跨模型实测显示此处分化明显。

---

## 4.14 Evidence Chain

系统需要支持一条可展示的知识链。

概念示例：

**Visual Observation**

积水覆盖道路较大范围

↓

**Spatial Grounding**

Observation located on Road_A

↓

**Urban Context**

Road_A 当前位置相对周边较低

↓

**Derived Knowledge**

事件发生在局部低洼道路区域

↓

**Event / Risk Assessment**

该积水相较普通孤立水洼更具有内涝事件特征

Evidence Chain 应优先来自真实计算和数据引用。

自然语言解释应基于 Evidence Chain 生成，而不是反向根据最终结论编造理由。

---

## 4.15 Management Boundary

第一版系统输出：

### 做

* 发生了什么；
* 这个事件有哪些视觉特征；
* 发生在哪里；
* 该位置有什么城市背景；
* 这些信息结合起来意味着什么；
* 为什么系统得到这个判断。

### 不做

* 应该封路；
* 应该派人；
* 应该启动什么应急响应；
* 应该通知哪个部门；
* 应该执行什么政策；
* 应该采取什么正式管理措施。

因此当前系统属于：

> **Management Understanding / Decision Information**

而不是：

> **Automated Decision Making**

---

## 4.16 LLM 与 Explicit Knowledge 的职责边界

当前产品架构不采取：

> LLM vs Ontology / KG

的二元选择。

而采用职责分工。

### LLM

负责：

* flexible visual semantic interpretation；
* observation extraction；
  -开放式语言理解；
* candidate semantic mapping；
* explanation generation。

### Schema / Ontology

负责：

* controlled vocabulary；
* property definition；
* allowed values；
* output normalization。

### Urban Data / Explicit Knowledge

负责：

* road identity；
* elevation；
* terrain；
* city-specific facts；
* future domain relations。

### Knowledge Engine

负责：

* context assembly；
* inference；
* evidence organization；
* contextualized knowledge generation。

---

## 4.17 RAG

第一版不要求 RAG。

当前主要知识来自结构化城市数据，而不是大量文本文档。

当未来需要处理：

* 政策；
* 规范；
* 应急预案；
* 规划文件；
* 管理手册；

时，再考虑 RAG。

因此 RAG 当前状态为：

**Out of initial implementation / future extension。**

---

# 5. 测试决策（Testing Decisions）

## 5.1 总体测试原则

测试应该验证：

> **系统对外表现出来的 Data → Knowledge 行为是否正确。**

不应该把测试主要绑定到：

* 使用哪一个 LLM；
* Prompt 具体怎么写；
* 内部是否使用 KG；
* 使用哪个数据库；
* 某个私有函数实现方式。

测试外部行为，而不是内部实现细节。

---

# 5.2 首选测试接缝（Primary Test Seam）

当前没有提供既有代码库或现成测试基础设施，因此无法复用已有 seam。

本规格建议第一版只建立 **一个主要的高层测试接缝**：

> ## **Analysis Pipeline Seam**
>
> 输入：
>
> **Image + Location / Road Context**
>
> 输出：
>
> **Structured Observation + Grounded Context + Inferred Knowledge + Evidence Chain**

这是当前最有价值的测试边界。

原因：

* 它覆盖政府 Demo 真正关心的整体行为；
* 不会把测试绑定到 LLM Prompt；
* 不会绑定到知识图谱实现；
* 可以替换模型、数据库、推理方式而不重写产品级测试；
* 能完整测试“图片 → 知识”的核心价值。

理想情况下，大多数核心验收测试都通过这一条 seam 完成。

**接缝状态：建议采用，待后续实现阶段确认。**

---

# 5.3 Pipeline 外部行为测试

应覆盖：

## Case A — 普通小水洼

输入：

明显局部、小面积水洼图片。

期望：

* Observation 可以检测到 water；
* 不应自动升级为高可信内涝；
* Explanation 能说明证据有限；
* Knowledge Layer 不应无依据扩大事件严重程度。

---

## Case B — 明显道路积水

输入：

明显大面积道路积水图片。

期望：

* Structured Observation 能表达较大 water extent；
* 可以识别道路覆盖；
* 可以识别可见车辆涉水等线索；
* Event Assessment 比普通水洼有更高内涝可能性。

---

## Case C — 视觉相似，但不同高程 Context

输入：

视觉 Observation 基本相同。

Context 1：

局部低洼。

Context 2：

无明显低洼特征。

期望：

Knowledge Engine 可以产生不同的 contextualized knowledge。

这个 Case 非常重要。

它证明：

> **知识层不是把视觉 LLM 的答案重新包装一遍。**

---

## Case D — Context Missing

输入：

图片可分析，但道路 / elevation 数据不可用。

期望：

* 仍返回 Observation；
* Grounding / Context 标记不可用；
* 不生成依赖缺失 Context 的知识；
* 明确告诉用户知识增强不完整。

---

## Case E — Ambiguous Image

输入：

模糊、夜间、遮挡等证据不足图片。

期望：

* 支持 uncertain；
* 不强制输出明确内涝；
* 不通过知识层掩盖视觉证据不足。

---

## Case F — Wrong / Unresolved Grounding

无法确认道路实体。

期望：

* 不假装获得某条道路的高程；
* Knowledge Layer 停止使用 city-specific context；
* 保留 image-only analysis。

---

## Case G — Unsupported Causal Claim

输入：

只有积水图片 + elevation。

期望：

系统不得输出：

> “排水管网堵塞导致此次内涝”

等没有证据支持的因果分析。

---

## Case H — Evidence Traceability

对每一个关键 inferred knowledge：

期望：

至少能够追踪到：

* 一个 observation；
* 或一个 urban context；
* 或一个明确 derived relation。

---

# 5.4 模块级测试对象

虽然主 seam 保持为一个高层 Pipeline seam，但仍建议对以下稳定契约进行轻量 contract testing。

## Observation Schema Validation

测试：

* required fields；
* enums；
* unknown；
* invalid values；
* malformed LLM output。

---

## Context Retrieval Contract

测试：

给定明确 Road / Location：

是否返回正确格式的：

* road context；
* elevation context。

不测试具体数据库内部实现。

---

## Inference Contract

测试：

给定确定 Observation + Context：

系统是否只生成允许的知识类型；

是否附带 evidence；

是否避免 unsupported claims。

---

# 5.5 模型测试方法

LLM / VLM 不应该只通过 unit test 判断。

需要建立一小套 Demo Evaluation Set。

至少包括：

* 明显小水洼；
* 明显内涝；
* 边界案例；
* 反光；
* 湿路面但无明显积水；
* 道路排水形成的局部水；
* 大面积浅水；
* 车辆涉水；
* 图像模糊；
* 夜间；
* 遮挡。

第一阶段评价重点不是追求完整科研 benchmark，而是：

> Demo 是否明显改善“小水洼 vs 有意义积水事件”的场景理解。

---

# 5.6 建议验收指标

当前没有确定正式 KPI，因此以下属于 Demo-level 验收方向，而不是已确认数值门槛。

### Observation Completeness

关键场景属性是否能稳定提取。

### Flood / Puddle Discrimination

是否比现有简单视觉判断更能区分普通水洼与明显道路积水。

### Schema Compliance

结构化输出是否稳定符合 Schema。

### Unsupported Knowledge Rate

是否避免生成没有 observation / context 支持的结论。

### Evidence Coverage

关键 knowledge assertion 是否拥有 evidence。

### Context Value

加入 Road / Elevation Context 后，是否能够形成 image-only 无法直接得到的新知识。

---

# 5.7 Prior Art

当前没有提供现有代码库。

因此无法确认：

* 已有测试框架；
* 已有测试 seam；
* 类似测试文件；
* ADR；
* repository architecture；
* domain glossary。

当前规格不得假设存在这些内容。

进入实际代码库后，应优先复用：

1. 现有 API / service-level integration seam；
2. 现有 domain schema；
3. 现有 GIS / elevation service interface；
4. 现有 test fixture / evaluation pipeline。

---

# 6. 范围外（Out of Scope）

以下内容明确不属于第一版 Demo。

## 6.1 视频分析

不做：

* temporal change；
* water growth；
* trajectory；
* multi-frame reasoning；
* event persistence。

---

## 6.2 自动管理决策

不输出：

* 封路建议；
* 部门派单；
* 应急响应等级；
* 正式处置策略；
* 自动 action execution。

---

## 6.3 完整政府业务规则

第一版不建设：

* 完整应急预案知识库；
* 正式处置规则引擎；
* 部门职责规则；
* 政策推理系统。

---

## 6.4 完整 Urban Ontology

第一版不试图描述整个城市。

只建设：

* 当前 Observation 所需 Schema；
* 当前 Road / Terrain Context 所需最小知识模型。

---

## 6.5 完整 Knowledge Graph Platform

不要求为了 Demo 搭建大型 KG infrastructure。

---

## 6.6 完整 RAG

第一阶段不以文档检索为核心。

---

## 6.7 自动原因诊断

第一阶段不负责可靠判断：

* 管网堵塞；
* 排水设计不足；
* 雨量超标；
* 管道损坏；
* 水泵故障；

除非未来有相应数据源。

---

## 6.8 全城市事件类型

第一版只要求内涝 use case 做通。

不同时实现：

* 道路破损；
* 垃圾；
* 违建；
* 交通事故；
* 火灾；
* 基础设施异常；
* 其他城市事件。

但架构不得人为阻止未来扩展。

---

# 7. 补充说明（Further Notes）

## 7.1 Demo 最核心的展示逻辑

政府合作方需要直观看到三个阶段的变化。

### Stage 1 — What I See

> 图片中有明显积水。

### Stage 2 — What I Know

> 该积水位于 Road_A。
> 当前道路位置相对周边处于低洼区域。

### Stage 3 — What It Means

> 当前积水不仅是孤立视觉现象，它发生在具有积水风险特征的道路环境中，因此更接近值得进一步关注的城市积水事件。

整个 Demo 应尽量围绕这一条故事展开。

---

# 7.2 不要让 Knowledge Engine 退化成 LLM 第二次聊天

必须避免这样的伪知识流程：

**Image**

→ LLM 判断“内涝”

→ 第二次 Prompt：“请结合高程解释为什么是内涝”

→ LLM 生成一段更长文本。

这并没有真正形成 Data → Knowledge。

目标应是：

**Observation**

* **真实城市数据**

→ **显式 context**

→ **可追踪 inference**

→ **Explanation**

---

# 7.3 Knowledge 的定义

当前项目中的“Knowledge”不是简单指：

> 一段更长、更专业的自然语言。

至少需要满足：

1. 引入了 Observation 之外的信息；
2. 信息来自明确城市实体或数据源；
3. 对数据进行了语义关联；
4. 生成了新的 contextualized assertion；
5. assertion 可以说明依据。

---

# 7.4 第一阶段最值得证明的 Knowledge Gain

如果 Demo 资源有限，优先证明一个非常具体的差异：

### Image-only

> 这里有比较明显的道路积水。

### Image + Urban Knowledge

> 这里存在明显道路积水；该位置对应 Road_A，并处于相对周边较低的道路区域，因此该事件比普通孤立水洼更具有内涝风险特征。

只要这个差异能被稳定、可信地展示，第一版 Demo 就已经证明了 Knowledge Engine 的核心价值。

---

# 7.5 长期演进方向

第一阶段：

**Image**

→ Observation

→ Road / Elevation

→ Contextualized Flood Knowledge

第二阶段可能增加：

**Historical Flooding**

**Road Importance**

**Critical Facilities**

**Drainage**

第三阶段可能增加：

**Rainfall**

**Sensor Streams**

**Video**

**Traffic**

第四阶段才可能增加：

**Management Rules**

**Regulations**

**Emergency Plans**

最终逐步形成：

**Urban Sensing**

→ **Urban Knowledge**

→ **Situation Understanding**

→ **Decision Support**

而不是第一版一次完成全部能力。

---

# 7.6 长期产品表达

当前项目不应长期被定义成：

> “一个内涝识别模型”。

更适合的产品概念是：

> **Urban Data-to-Knowledge Engine**

或者更面向非技术用户地表达为：

> **让城市感知数据从“被检测”升级到“被理解”。**

当前内涝 Demo 是这套能力的第一个垂直验证。

---

# 8. 当前已确认架构摘要

最终当前版本可以压缩为：

```text
Single Urban Image
        │
        ▼
Multimodal LLM
        │
        ▼
Structured Observation
        │
        │ constrained by
        ▼
Observation Schema / Lightweight Ontology
        │
        ▼
Spatial / Road Grounding
        │
        ├───────────────┐
        │               │
        ▼               ▼
    Road Data       Elevation Data
        │               │
        └───────┬───────┘
                ▼
         Urban Context
                │
                ▼
     Knowledge Enrichment
                │
                ▼
   Event / Risk / Impact Knowledge
                │
                ▼
      Evidence / Explanation
```

当前系统明确停止在：

> **“发生了什么、意味着什么、为什么这样判断。”**

暂不进入：

> **“政府应该采取什么行动。”**

---

# 9. 当前最重要的验收命题

第一版 Demo 最终不是在证明：

> **“LLM 会不会识别水。”**

而是在证明：

> **“多模态 LLM 能否把城市图片转成结构化 Observation，并让这些 Observation 与真实道路、高程等城市数据结合，从而产生比图片识别本身更丰富、可解释的城市事件知识。”**

如果这个命题被 Demo 清楚地证明，那么项目已经具备继续扩展到更完整：

> **Urban Data → Knowledge → Management**

体系的基础。
