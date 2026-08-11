# Observation Schema 定义（v1）

> 对应 wayfinder ticket #4。实现契约见 `observation.py`（Pydantic v2），架构决定见 ADR-0001。

本文档定义第一版 Observation Schema——它既是 **VLM（Qwen3-VL）结构化输出的契约**，也是后续 Knowledge Engine 推理的输入基础。遵循 PRD §4.4 的三层分离：Observation（图片可见）/ Context（城市数据）/ Inference（二者推导）。本 Schema 只覆盖 **Observation 层**。

---

## 1. 设计决策总览

| # | 决策 | 结论 |
|---|------|------|
| 1 | Observation 单元 | **一张图片 → 一个 Observation**；多个积水区域/参照物/证据作为 Observation 内嵌套数组 |
| 2 | 事件类型扩展 | 顶层 `phenomenon_type` 判别字段 + 同类型子块 `waterlogging`；未来事件类型以平级子块扩展 |
| 3 | 置信度模型 | observation 级 `overall_confidence` + 深度估算置信度 + 既有逐项 `reliability` |
| 4 | unknown 表示 | 枚举用哨兵值、数值用 `null`、列表用 `[]`；必需键一律出现，unknown 由值表达 |
| 5 | 契约实现 | Pydantic v2，置于 `src/schemas/`；重构 `waterlogging.py` 的 prompt 与校验，不保留并行格式 |
| 6 | 与 Inference 边界 | `traffic_risk` 移出 Observation，归 Knowledge Engine；Observation 仅留纯可见的 `visual_impact_hint` |
| 7 | 枚举值 | 语言中性 code 为规范值；zh-CN 展示标签见 `display_labels.py` |

---

## 2. 字段总览

```
Observation  （一张图片一个）
├─ meta                              [pipeline 盖戳，非 VLM 产出]
│   ├─ observation_id        str
│   ├─ source_image          str
│   ├─ observed_at           datetime
│   └─ source_location       LocationRef | null   ← 透传，非 VLM；解析见 Grounding (#5)
│       ├─ lat / lon / road_name / raw_text
├─ phenomenon_type           "road_waterlogging"  ← 判别字段 (v1 仅此一种)
├─ overall_confidence        high | medium | low
├─ presence_probability      float [0..1]          ← P(存在积水)
├─ waterlogging                                    ← 同类型子块
│   ├─ status                present | absent | uncertain
│   ├─ waterlogging_level    L0 | L1 | L2 | L3 | L4 | L5 | LX
│   ├─ depth_estimate
│   │   ├─ depth_cm          {min, max, most_likely}   ← 全可 null
│   │   └─ confidence        high | medium | low
│   ├─ water_patches[]                              ← ≥0 个积水区域
│   │   ├─ patch_id, location_in_frame
│   │   ├─ coverage          localized | moderate | extensive | unknown
│   │   ├─ waterlogging_level
│   │   └─ depth_cm          {min, max, most_likely}（可 null）
│   ├─ surface_condition     dry | wet | suspected_water | clear_water | unknown
│   ├─ visual_cues
│   │   ├─ reflection_present, visible_water_boundary,
│   │   ├─ visible_waterline, visible_ripple_or_wave     bool
│   │   └─ reflection_type   water_reflection | wet_road_glare | light_glare |
│   │                          shadow | lens_artifact | unknown
│   ├─ reference_objects[]   {object, known_size, relation_to_water, reliability}
│   ├─ visual_impact_hint    none | minor | obstructing | submerging | unclear
│   ├─ visual_evidence[]     {evidence, supports, reliability}
│   ├─ alternative_explanations[]  {possibility, likelihood, reason}
│   └─ uncertainty_reasons[] str
├─ visible_location_text     str | null   ← 画面 OSD/水印地名原文抄录（看不到则 null）
└─ observed_summary          str   ← 仅基于可见内容；禁止风险/事件/因果推论
```

---

## 3. 字段职责说明

### 3.1 meta（pipeline 盖戳）
`observation_id`、`source_image`、`observed_at` 由 pipeline 生成，**VLM 不产出**。`source_location` 是图片位置信息的**透传**（EXIF / Demo 输入），同样不由 VLM 生成；将其解析为真实道路实体是 Grounding（ticket #5）的职责，未解析时保留为 null / unresolved。这与 PRD §4.7 一致：Grounding 不得依赖 LLM 世界知识。

### 3.2 phenomenon_type（判别接缝）
v1 仅 `road_waterlogging`。waterlogging 专属视觉字段全部收纳在 `waterlogging` 子块下；未来新增事件类型（结冰、塌陷等）作为平级子块加入，`phenomenon_type` 取新值。此接缝一旦下游绑定字段路径便难以回退，故在 v1 即刻切出（见 ADR-0001）。

### 3.3 overall_confidence 与 presence_probability
两者度量不同维度，可同时分歧（如概率 0.9 但图片模糊导致 confidence 低）：
- `presence_probability`：模型对"存在积水"的概率估计；
- `overall_confidence`：本次 Observation 整体可靠性。

### 3.4 depth_estimate
`depth_cm` 仅在存在可靠尺寸参照（清晰水位线、路缘石、轮胎、标线等与水面的明确比例）时填写；无可靠参照时保持 `null`，不编造精确厘米数（PRD §4.13）。**但 `waterlogging_level` 不随之退化为 `LX`**：只要积水存在且视觉强度可辨，仍按可见强度给出**保守等级估计**（如 L2/L3）并标 `depth_estimate.confidence=low`——等级承载"估计"、厘米承载"测量"，二者分离。仅当**积水存在与否本身存疑**（极端模糊、夜间无光、镜头污渍遮挡、信号矛盾）时才用 `LX`（见 §4）。深度可同时在 observation 级（整体）与逐 patch 级出现——一张图可同时存在浅水洼与较深路面水。

### 3.5 visual_impact_hint（纯可见的影响提示）
仅基于画面可见证据给出**描述性**提示（淹没标线、接近底盘等）。它**不是**交通影响判断——后者需结合道路 Context，属 Knowledge Engine 的 Inference（`traffic_risk`）。此字段满足"基于图片的基本分析"需求，同时守住 Observation/Inference 边界。

### 3.6 observed_summary
替代旧版自由 `conclusion`。**仅**描述画面可见内容，严禁包含风险、事件定性或因果推论（那些属 Inference）。服务于 Demo"系统看到了什么"面板（PRD §3.8-41）。

### 3.7 visible_location_text（ADR-0003 待加字段）
画面中 OSD/水印/招牌等地名的**原文抄录**——VLM 仅照抄可见文字，看不到则填 `null`。它不做任何地理推断、也不依赖模型世界知识，仅作为 Grounding（ticket #5）的一个候选位置线索：pipeline 负责把它搬进 `meta.source_location.raw_text`。与 `source_location`（EXIF/Demo 输入透传）互补——后者来自图像元数据/输入，前者来自画面可见文字。

---

## 4. unknown / 不确定 / 部分结果（对应 PRD §3.9）

- 枚举字段各带哨兵：`status → uncertain`、`waterlogging_level → LX`、`surface_condition → unknown`、`visual_impact_hint → unclear`；`confidence` 无 unknown（至少 `low`）。其中 `waterlogging_level=LX` 含义已收窄——仅当**积水存在与否本身存疑**时使用（通常与 `status=uncertain` 并存），而非"有积水但缺尺寸参照"；后者仍给保守等级估计 + `low` 置信（见 §3.4）。
- 数值估算（`depth_cm`）未知用 `null`。
- 列表（参照物、替代解释等）无内容用空 `[]`。
- 必需键一律出现；未知由值表达，绝不靠缺键。
- `source_location` 可为 null（Context 缺失），此时仍返回完整视觉 Observation，仅 Knowledge 增强步骤标注未完成——支持 pipeline 部分结果。

---

## 5. 与现有 waterlogging.py 的迁移

当前 `waterlogging.py` 的 JSON 字段映射：

| 旧字段 | 去向 |
|--------|------|
| `waterlogging_status` | `waterlogging.status`（值改 code） |
| `waterlogging_probability` | `presence_probability` |
| `waterlogging_level` | `waterlogging.waterlogging_level` |
| `estimated_depth_cm` | `waterlogging.depth_estimate.depth_cm`（+ 加 confidence） |
| `confidence` | `overall_confidence` |
| `water_area_description` | 拆入 `water_patches[].location_in_frame` |
| `scene_observations` | `waterlogging.visual_cues` + `surface_condition` |
| `reference_objects` | `waterlogging.reference_objects`（reliability 改 code） |
| `visual_evidence` | `waterlogging.visual_evidence` |
| `alternative_explanations` | `waterlogging.alternative_explanations` |
| `uncertainty_reasons` | `waterlogging.uncertainty_reasons` |
| `traffic_risk` | **移除** → Knowledge Engine Inference |
| `additional_data_needed` | **移除** → Context/Inference 的缺失信号层 |
| `conclusion` | **替换**为 `observed_summary`（仅可见） |

迁移步骤：
1. `src/schemas/observation.py` 为规范契约（已建）。
2. 重构 `waterlogging.py` 的 `PROMPT_TEMPLATE` 按本 Schema 输出 code 值。
3. 用 `Observation.model_validate(...)` 替换 `validate_basic_result` 手写校验。
4. `meta` 由调用方/pipeline 盖戳，prompt 不要求模型产出。
5. 不保留旧并行格式。

---

## 6. 验收接缝（对应 PRD §5.4 Observation Schema Validation）

- Pydantic 校验即契约校验：非法 code / 缺键 / `absent` 非 `L0` 等由模型校验器拦截。
- `model_validator`：`status==absent` 时强制 `waterlogging_level==L0`。
- 可用 `Observation.model_json_schema()` 导出 JSON Schema 供前端/测试与 prompt 生成复用。
