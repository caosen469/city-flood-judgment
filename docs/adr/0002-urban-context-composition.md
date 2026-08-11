# ADR 0002 — Urban Context：组合式 ContextBlock + 分层 availability/provenance

PRD §4.4/§4.6 把 Urban Context 定位为"Where is it, what is known about this place"的背景层，§4.8 锁定 v1 知识源为 Road + Elevation/Terrain，§4.9 又列出 10+ 未来可扩展源（历史内涝、排水、POI…）。本决定（wayfinder #6）确定这层的数据模型与模块接口，使新源零侵入接入，并满足 §4.14 Evidence Chain 对可追溯的要求与 §5.3 Case D/F 的 graceful degradation。

## 决定

1. **组合式 typed ContextBlock**：`UrbanContext` 不平铺字段，而是持有一个 `blocks: list[ContextBlock]`；每个知识源是一个带 `block_type` 判别字段的 block 子类。新源 = 新增一个 block 子类 + 一个 provider，根模型 `UrbanContext` 永不改形。这与 ADR-0001（Observation 的 `phenomenon_type` 判别式扩展）同一思路，保持全栈一致。

2. **Elevation 与 Terrain 拆为两个 block**：
   - `ElevationContextBlock`：绝对高程 `elevation_pt` + 周边 stats（min/max/mean/std）——"这里多高"的事实层。
   - `TerrainContextBlock`：多尺度 TPI 的相对低洼判别 `LownessScores` + `lowness_class`——"相对周边是否低洼"的判别层，Knowledge Engine 据此产 TerrainRisk 知识（Case C 的关键）。
   - 拆分的理由：语义独立、Evidence 可分别引用、§4.6 本就分开列。

3. **低洼判别信号与阈值**（核心价值点）：
   - 信号 = 多尺度 TPI composite = `meso(1km) + 0.3·micro(300m) + 0.2·macro(2km)`，单位米，正值代表比周边低。RichDEM depression-depth 仅留接口、Demo 不强制。
   - 阈值四档（米）：`<0.3 level_or_higher / 0.3–1.0 slightly_low / 1.0–2.0 moderately_low / >2.0 significantly_low`；`insufficient_data` 为 unknown 哨兵。阈值与权重以常量 `LOWNESS_THRESHOLDS` / `TPI_WEIGHTS` / `TPI_RADII_PX` 内联于契约，#7 与测试引用同一真值源。

4. **Provenance 每块必带**：`source`（`osm` / `srtm_local` / `opentopography` / `open_meteo` / `open_elevation` / `user_provided`）+ `data_vintage` + `retrieved_at`。fallback 链命中哪一档对前端可见（§4.14 可追溯）。

5. **Availability 三态 + reason**：每个 block 带 `status: available|unavailable|uncertain` 与 `reason` code。承接 Case D（数据缺失→相应 block `unavailable`，仍返回 Observation 与其余可用 block，不生成依赖缺失 Context 的知识）与 Case F（Grounding unresolved→`RoadContext` `unavailable(reason=grounding_unresolved)`）。
   - **关键行为**：Grounding unresolved 时，**Elevation/Terrain 仍基于裸经纬度照算**，`source` 仅标高程源、不挂道路。这不违反 Case F"不假装获得某条道路的高程"——我们从不说它是某条路的高程。

6. **"unknown by value"**：沿用 ADR-0001，必需键一律出现；缺失由 `status`+`reason` 与可空数值表达，而非缺键。

## 模块接口（接口规格，非实现）

```
src/schemas/context.py        # 本契约（纯数据模型，Pydantic v2）—— 已落地
src/context/                  # 实现层（待建，#6 不实现查询逻辑）
  base.py     # ContextProvider 协议、ContextAssembler
  providers/  # RoadProvider / ElevationProvider / ElevationFallbackProvider / …
```

```python
# ContextProvider：每个知识源一个 provider，返回带 provenance/availability 的 block
class ContextProvider(Protocol):
    block_type: str                       # 例 "road" / "elevation" / "terrain"
    def query(self, point: GeoPoint, grounding: GroundedEntity | None) -> ContextBlock: ...

# ContextAssembler：按点遍历已注册 provider，组装 UrbanContext
class ContextAssembler:
    def __init__(self, providers: list[ContextProvider]): ...
    def assemble(self, point: GeoPoint, grounding: GroundedEntity | None) -> UrbanContext: ...
```

新源接入：实现 `ContextProvider` + 新增一个 `ContextBlock` 子类（带新 `block_type` 字面量，加入判别联合），在 Assembler 注册。零根模型改动、零 Knowledge Engine 改动（按 `block_type` dispatch）。

## 考量

这是难以回退的决定：一旦 Knowledge Engine（#7）、Pipeline（#8）、前端绑定到 "blocks 列表 + 判别 block_type" 的形状，事后从组合式改回扁平（或反之）代价随下游增长放大。两个备选：**(a)** UrbanContext 平铺 `road`/`elevation`/`terrain` 固定字段，新源改根模型；**(b)** 组合式判别 block（本决定）。选 (b) 的代价是 v1 多一层 `blocks` 间接 + block_type dispatch，但锁住了 §4.9 十余个未来源的扩展接缝，且与 Observation（ADR-0001）扩展方式一致。Elevation/Terrain 是否拆分曾被视为可选项——拆开的代价是多一个 block 类，收益是语义独立与 Evidence 分别可引，对 Demo 的 Case C 展示更清晰。

## 影响

- **解除 #7（Knowledge Engine）剩余 fog**：TerrainRisk 知识可直接消费 `TerrainContextBlock.lowness_class`；`traffic_risk` Inference 可消费 `RoadContextBlock`；实现方式选型（规则 vs LLM 辅助）的最后一处不确定性消除。
- **为 #8（Pipeline）定 Stage 2 数据契约**：`Grounding → ContextAssembler.assemble(point, grounding) → UrbanContext`，部分结果策略由 per-block availability 表达。
- **#5（Road Grounding）** 的 `GroundedEntity` 产物直接喂 `RoadContextBlock`（`osm_way_id` / `grounding_confidence` / `offset_distance_m`）；匹配机制本身仍归 #5。
- 高程 fallback 链（本地 SRTM→OpenTopography→Open-Meteo→Open-Elevation）由 `ElevationFallbackProvider` 内部实现，命中档位写入 `Provenance.source`。
