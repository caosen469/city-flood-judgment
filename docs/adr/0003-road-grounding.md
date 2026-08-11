# ADR 0003 — Road Grounding：点→路段纯匹配 + 三态结果模型

PRD §4.7 要求把 Observation 关联到真实道路，且 Grounding **不得依赖 LLM 世界知识**。我们决定 Grounding 模块分两层、可独立测试：`locate(LocationRef) -> LocatedPoint | None`（归一化前端，有经纬度直通、仅文本才跑 Nominatim，拥有地理编码与错误处理）与 `match(lat, lon) -> GroundedEntity`（纯几何：投影到 UTM 50N + `ox.nearest_edges(G, lon, lat, k=5)`，无网络、可 mock）。匹配基是 #2 缓存的 OSMnx 图 edges，命中后用 `osm_way_id` 反聚类回原 way；结果用三态 `grounded / ambiguous / unresolved` 表达，`unresolved` 携带 `reason`（`out_of_buffer` / `outside_nansha` / `geocode_failed` / `no_location`）。

## 考量

这是难以回退的决定：GroundedEntity 是 Observation→Context 之间的契约，被 #6（Urban Context）和 #8（Pipeline）直接消费，状态枚举与字段一旦被下游绑定就难以无痛改。它也需要解释——读者会奇怪为何 (1) 把地理编码和匹配拆开、(2) 用三态而非"匹配到/匹配不到"两态、(3) v1 不要 heading、(4) 明确拒绝 GCJ-02 坐标却只字面声明 WGS-84。

- **geocoding 与匹配分离**：中文地名→经纬度的 Nominatim 调用不可靠且有网络依赖，与确定性几何匹配是两种性质的不确定性。拆开后 `match()` 是纯函数可单测，"地理编码失败"与"点位远离路网"成为两种不同的 `unresolved`，Evidence Chain 更干净。备选是把两者合一为黑盒——被否，因为牺牲了可测性与失败归因。
- **三态**：`ambiguous`（第 2 近路段 ≤15m 或 ≤1.5× 最近）让 Knowledge Engine 在路口/双向路上"承认道路身份不唯一"，而非 silent 二选一——坐实 PRD Case F"不假装确定道路"。两态被否，因为它把勉强匹配与真正匹配混为一谈。
- **不要 heading**：v1 是单帧图、无轨迹，手机 EXIF 朝向不可靠；双向路歧义用"反聚类回 way + 路名"吸收，不引入 heading。代价是边级方向信息丢失，但 v1 可接受。
- **GCJ-02 拒绝**：中国地图 App 输出 GCJ-02，在本区偏移约 300–500m，若用户从前端点选或粘贴 App 坐标会静默匹配错路（Case F"Wrong Grounding"的隐蔽来源）。v1 在 `LocationRef` 增 `crs` 字段、仅声明 `wgs84`，GCJ-02→WGS-84 转换列入 map 的 Not yet specified。"诚实的不支持"优于"静默错配"；`crs` 字段保证未来加 GCJ-02 路径是非破坏性扩展。

## 附带决定

- **距离→状态/置信度**：`<15m` grounded/high，`15–35m` grounded/medium，`35–100m` grounded/low，`>100m` unresolved(`out_of_buffer`)；ambiguous 覆盖上面，置信度取最近距离档。100m 阈值依南沙城区路网密度选定，设为可配置常量。
- **置信度复用**：Grounding 置信度复用 Observation 的 `Confidence` 枚举（high/medium/low），跨层一致；地理编码精度通过 `source == "geocoded_text"` 单独标注，不混入匹配置信度。
- **边界案例归类**：路口→自然落入 ambiguous，不写分支；桥/隧→照常 grounded，仅带 `bridge`/`tunnel` 布尔（高程差异归 #6 Elevation Context）；南沙区外（R3287345 边界外）→ unresolved(`outside_nansha`)，不加载全城路网；Nominatim 失败→ unresolved(`geocode_failed`)，Observation 照常返回。
- **坐标投影**：距离计算与 buffer 必须在米制 CRS（UTM 50N，~EPSG:32650）下进行，不可用经纬度直接算缓冲。
- **位置来源（v1）**：仅支持 (a) 原始 lat/lon（EXIF/手填，`source=exif|user_latlon`）与 (b) 自由文本（`source=geocoded_text`）；显式道路名作为 (b) 的特例。
- **画面地名文字的接入（对 ADR-0001 的连带补充）**：监控照片 OSD/水印上的地名属"可见内容"而非世界知识，允许 VLM 抄出原文到新 Observation 字段 `visible_location_text`（看不到则空），由 pipeline 搬进 `LocationRef.raw_text` 再交 GIS 解析。模型仍不产出 `LocationRef`、不解析道路身份，故与 ADR-0001"LocationRef 非 VLM 产出"不冲突——模型产的是可见观察字段，pipeline 做搬迁。该字段需在实现时同步加入 `src/schemas/observation.py` 与 `observation_schema.md`。
- **契约实现**：Pydantic v2 模型置于 `src/schemas/grounding.py`（`GroundingStatus` / `MatchedRoad` / `GroundedEntity` / `LocatedPoint` 等）；`locate()`/`match()` 实现落在后续 `src/grounding/` 模块（#8 Pipeline 之后）。
