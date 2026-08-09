# ADR 0001 — Observation Schema：判别式 phenomenon_type + 分类型子块

PRD §4.5/§3.2-13 要求 Observation Schema 不与 "内涝" 单一事件绑定，为后续城市事件类型留扩展空间。我们决定在 Observation 顶层设一个 `phenomenon_type` 判别字段（v1 仅 `road_waterlogging`），并把 waterlogging 专属视觉字段收纳在与其类型对应的子块 `waterlogging` 下；未来新增事件类型（如结冰、塌陷）作为平级子块加入。

## 考量

这是难以回退的决定：一旦 Knowledge Engine（#7）、Urban Context（#6）等下游代码绑定到具体字段路径，事后把平铺字段重构成分类型子块的代价会随下游增长而放大。它也需要解释——读者会奇怪为何 v1 只有一种事件却已分层。两个备选：**(a)** 仅加 `event_type` 字符串字段、字段平铺、日后再重构；**(b)** 判别字段 + 分类型子块（本决定）。选 (b) 的代价只是 v1 多一层嵌套，但锁住了扩展接缝。

## 附带决定

- **Observation 单元**：一张图片 → 一个 Observation；多个积水区域、参照物、视觉证据作为 Observation 内的嵌套数组，而非兄弟 Observation（保证 1 图 → 1 Grounding 目标）。
- **Observation / Inference 边界**：`traffic_risk` 移出 Observation，归 Knowledge Engine 的 Inference；Observation 仅保留 `visual_impact_hint` 这种纯可见证据的描述性提示。
- **unknown 表示**：枚举字段用各自约定哨兵值（status `uncertain`、level `LX`、condition `unknown`），数值用 `null`，列表用空 `[]`；必需键一律出现，unknown 由值表达，而非缺键。
- **置信度**：observation 级 `overall_confidence` + 深度估算置信度 + 既有的逐项 `reliability`，不为每个字段加置信度。
- **枚举值**：以语言中性 code 为规范存储值，zh-CN 展示标签维护在独立映射表（`display_labels.py`）。
- **契约实现**：Pydantic v2 模型作为规范契约，置于 `src/schemas/`；`waterlogging.py` 的 prompt 与校验重构到其上，不保留并行格式。
