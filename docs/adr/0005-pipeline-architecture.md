# ADR 0005 — Pipeline 架构：阶段装配、扁平信封、SSE 流式、Stage-1 结构化输出策略

本决定（wayfinder #8）把 ADR-0001~0004 已落地的四份契约（Observation / GroundedEntity / UrbanContext / KnowledgeResult）与各自模块接口，组装成一条可运行的 Analysis Pipeline，并锁定 PRD §5.2「Analysis Pipeline Seam」的顶层形状、FastAPI 端点、流式协议、与现有 `src/waterlogging.py` 的关系、新目录结构，以及 Stage 1 让 Qwen3-VL 产出丰富 Observation 的结构化输出策略。它解除 #9（前端）之外、所有后端实现 ticket 的最后一层 fog。

## 决定

1. **顶层接缝 = 一个函数**：`analyze(image, location) -> AnalysisResult`（`src/pipeline/service.py`）。FastAPI handler 是它的薄包装；PRD §5.2 的「Analysis Pipeline Seam」即此函数签名，绝大多数验收测试（Case A–H）打在这里，不绑 VLM prompt / 数据库 / 推理实现。

2. **扁平 `AnalysisResult`，状态内含于数据模型**：
   ```
   AnalysisResult {
     request_id: str
     observation: Observation          # ADR-0001
     grounding:   GroundedEntity       # ADR-0003（status 三态自带降级）
     context:     UrbanContext         # ADR-0002（per-block availability 自带降级）
     knowledge:   KnowledgeResult      # ADR-0004（资格门缺项自带降级）
     timings:     dict[stage, ms]      # 仅 Demo 计时，非状态
   }
   ```
   **不**给每阶段套 `StageResult[T]` 包装。理由：前序 ADR 已把降级信号刻意塞进各数据模型（`GroundedEntity.status`、block `availability`、eligibility-gated 缺失 knowledge item），再套一层 `StageResult.status` 会重复表达。唯一模型无法表达的失败是 VLM 硬失败，它正确地是一个 HTTP 错误、而非 AnalysisResult 的一个字段。

3. **三阶段映射（PRD §7.1）**——阶段边界与数据流严格沿用前序 ADR 的模块接口：
   - **Stage 1 — What I See**：`image -> Observation`（`src/observation/generate.py`）。
   - **Stage 2 — What I Know**：`Grounding`（`locate(LocationRef)->LocatedPoint|None` → `match(lat,lon)->GroundedEntity`，ADR-0003）随后 `ContextAssembler.assemble(point, grounding) -> UrbanContext`（ADR-0002）。
   - **Stage 3 — What It Means**：`KnowledgeEngine.assemble(observation, grounding, context) -> KnowledgeResult`（ADR-0004：规则确定产 TerrainRisk + LLM 在 FactBundle 上推断 RoadImpact/EventAssessment/explanation）。
   - **无短路**：pipeline 恒跑全三阶段；阶段内部资格门（ADR-0004）决定哪些 knowledge 产出。无位置输入时，grounding 为 `unresolved(no_location)` → context 各 block 全 `unavailable`（无点可查）→ knowledge 退化为仅图像的 EventAssessment。降级由值表达，符合 Case D/F。

4. **错误传播与部分结果（ticket Q3）**：
   - **硬失败（abort）**：仅 Stage 1 的 VLM 调用硬失败或图片不可读。图片不可读 → HTTP **422**；VLM 上游错误（DashScope 超时/5xx/JSON 修复仍失败）→ HTTP **502**。流式端点对应发一个 `error` 事件后关闭。
   - **软降级（graceful，仍返回 AnalysisResult）**：其余一切——grounding unresolved、context block unavailable、knowledge 因资格门缺失而不产出——均已在数据模型内表达，前端据字段渲染并显式提示「知识增强不完整」。不抛异常、不中断 pipeline。

5. **Stage 1 结构化输出策略**（关键，受事实约束）：
   - **事实**：经查阿里云百炼官方文档（结构化输出 / OpenAI 兼容-Vision / Function Calling），`response_format={"type":"json_schema"}` **严模式仅对文本模型（Qwen3.7/3.8 系列）有文档支持，没有任何 Qwen3-VL 模型在支持列表内**；社区报告对 VL 调 json_schema 返回 HTTP 400。
   - **思考模式 + json_object**：官方支持但带明确告诫——「标注为非思考模式的模型，在思考模式下 json_object 不报错，但结构化输出可能失效」， sanctioned 修复法是两步法（先调思考模型，再用支持 JSON Mode 的模型修 JSON）。
   - **决定（Option A）**：`response_format={"type":"json_object"}` + **提示词内 schema**（由 `Observation.model_json_schema()` 自动渲染，单一真值源——Pydantic 模型已存在）+ **Pydantic 校验**（解析后直接 `Observation.model_validate(json)`）+ **两步修复 fallback**（校验失败 → 调一个非思考 json_object 模型修 JSON → 仍失败则 Stage 1 硬失败）。**不设 `max_tokens`**（官方告截断 JSON）；`enable_thinking` 经 `extra_body` 传（沿用现有代码）。
   - **保留杠杆（Option B）**：若 Stage 1 原型显示 json_object 无法稳定产出嵌套 Observation，改用 OpenAI 风格 `tools`（其 `parameters` 即 Observation schema，解析 `tool_calls[0].function.arguments`）。思考模式下 `tool_choice` 仅 `auto/none`（不能强制），但官方已演示 qwen3-vl + thinking + tools 可用。此切换属原型期结论，与 map「Event Assessment 调参」同源，留待 Stage 1 实现 ticket 验证后再定夺，不在本 ADR 锁死。

6. **FastAPI 端点（ticket Q4）**：
   - `POST /analyze` → `AnalysisResult`（JSON）。非流式，测试友好。
   - `POST /analyze/stream` → `text/event-stream`（SSE）。事件序列：`thinking`*（reasoning_content 增量，仅思考型模型，复用 `classify_model`）→ `stage`×4（按 observation/grounding/context/knowledge 顺序，载荷为该阶段模型 + `duration_ms`）→ `done`（携带**完整** `AnalysisResult`，权威聚合）| `error`（载荷 `{code,message,stage}`，随后关闭）。
   - `done` 携带完整结果而非纯终止符：`stage` 事件负责渐进展示（What I See/What I Know/What It Means），`done` 是唯一权威聚合，与非流式 `/analyze` 同形，前端可共用一个渲染器。
   - **图片来源**：URL **或** multipart 文件上传（URL 适配公网摄像头，multipart 适配本地 `data/images` 测试图与演示上传；base64 由 multipart 覆盖，不单列）。
   - **位置输入**：可选 `location` 字段，镜像 `LocationRef` `{lat, lon, road_name?, raw_text?}`。缺省时按决定 3 走 no_location 降级路径。

7. **与 `src/waterlogging.py` 的关系（ticket Q5）——Refactor，不 Wrap、不 Delete**：
   - 抽出可复用 VLM 机器到 `src/vlm/`：`client.py`（Qwen client 工厂 + 模型分类 `classify_model` + thinking-mode 交叉语义表 `resolve_thinking_choice`）、`reasoning.py`（`reasoning_content` 流式读取）。
   - 重写 prompt 与输出契约为 Observation（`src/observation/{generate,prompt}.py`），丢弃旧积水 prompt 与旧 JSON 校验。
   - CLI 保留为 Stage-1 调试工具，重指向新 generator。`tests/test_thinking_mode.py` 继续守护被复用的交叉表。
   - 否决 Wrap（旧 JSON→新 Observation 的有损映射；旧 schema 甚至含被 ADR-0001 逐出的 `traffic_risk`）与 Delete（丢弃已测试机器）。

8. **新目录结构**（物理布局，实现各 ADR 已 specced 的模块接口；空目录随各实现 ticket 落地而建，本设计 ticket 不建空骨架）：
   ```
   src/
     schemas/            # 已落地：observation/grounding/context/knowledge + display_labels
     config.py           # pydantic-settings：DASHSCOPE_API_KEY / model / data 路径 / 阈值
     vlm/                # ← 从 waterlogging.py 抽出
       client.py           # Qwen client 工厂 + classify_model + thinking-mode 交叉表
       reasoning.py        # reasoning_content 流式读取
     observation/        # Stage 1
       generate.py         # image -> Observation（json_object + 校验 + 修复）
       prompt.py           # 由 Observation.model_json_schema() 渲染的提示词
     grounding/          # Stage 2a（ADR-0003）
       locate.py match.py graph.py
     context/            # Stage 2b（ADR-0002）
       base.py providers/{road,elevation,terrain}.py
     knowledge/          # Stage 3（ADR-0004）
       rules.py infer.py explain.py engine.py
     pipeline/
       service.py          # analyze(image, location) -> AnalysisResult  ← 测试接缝
       streaming.py        # SSE 事件生成
     api/
       app.py              # FastAPI app + lifespan（启动时加载城市数据、注册 provider/engine）
       routes.py           # POST /analyze, POST /analyze/stream
       models.py           # 请求/响应信封（AnalysisResult / AnalyzeRequest / SSE 事件 schema）
   scripts/  data/{images,urban}/  tests/  docs/{architecture.md, openapi.yaml, adr/}
   ```

9. **装配与配置（实现细节，非决策）**：`config.py` 用 pydantic-settings 读环境变量；FastAPI `lifespan` 启动时一次性加载城市数据（OSM `nansha_roads.gpkg` 图 + SRTM tiff）并构造 `ContextAssembler`（注册 road/elevation/terrain provider）与 `KnowledgeEngine`，注入 handler；CORS 对 Vue dev server 开放；`request_id = uuid4`。

## 考量

这是难以回退的决定：一旦 #9（前端）与后续后端实现 ticket 绑定到「扁平 AnalysisResult + SSE 事件序列 + json_object 校验修复 + waterlogging 拆为 src/vlm」的形状，事后改动代价随下游增长放大。它也需要解释——读者会奇怪为何 (1) 用扁平信封而非每阶段包装、(2) 选 SSE 而非 NDJSON、(3) `done` 仍带完整结果是否与 `stage` 事件冗余、(4) 明知 json_schema 更强却选 json_object+修复、(5) 把 waterlogging 拆开而非包装。

- **扁平信封 vs StageResult 包装**：前序 ADR 的一致设计哲学是「降级由值表达，非由缺键/异常」（ADR-0001 unknown-by-value、ADR-0002 per-block availability、ADR-0003 三态 grounding、ADR-0004 资格门缺项）。扁平信封延续此哲学，`StageResult.status` 会与之重复并制造「到底信谁」的双源。计时用轻量 `timings` map 足矣，无须整个包装层。
- **SSE vs NDJSON vs 不流式**：PRD §7.1 的三阶段渐进展示是 Demo 核心叙事；SSE 在 FastAPI（`StreamingResponse`/`EventSourceResponse`）与 Vue（原生 `EventSource`，自动重连）两侧都是惯用法，事件类型语义（`stage`/`thinking`/`done`/`error`）也比 NDJSON 裸行更清晰。并行保留非流式 `POST /analyze` 使接缝可裸测、不绑流式细节。
- **`done` 带完整结果**：与 `stage` 事件非冗余——`stage` 是「渐进展示」，`done` 是「权威聚合」。客户端可忽略所有 `stage` 事件、只从 `done` 渲染（等价于非流式），也可逐 stage 渐进。两者同形（都是 `AnalysisResult`），前端共用一套渲染器。
- **json_object + 校验 + 修复 vs tool-calling**：受事实约束——json_schema 对 VL 不可用，故只能在「json_object + 提示词 schema + 客户端校验」与「tool-calling」间选。选前者因 (a) 与决定 7 的 refactor 同向：复用现有 json_object + reasoning 流式 + JSON 解析代码路径，仅加 Pydantic 校验 + 修复；(b) Pydantic `Observation` 模型已是现成校验器，`model_json_schema()` 自动渲染提示词 schema，无手维护副本；(c) tool-calling 在思考模式下不能强制 `tool_choice`，可靠性并不更高，且偏离现有代码更大。tool-calling 留作原型期杠杆。
- **waterlogging Refactor vs Wrap/Delete**：thinking-mode 交叉语义表是非平凡且已测试的行为（`tests/test_thinking_mode.py`），丢弃浪费；Wrap 的旧→新映射有损（旧 schema 含被驱逐的 `traffic_risk`，且缺新结构）；Refactor 保留好部分、只换 prompt + 契约，成本最低、风险最小。

## 影响

- **解除 #9（前端）后端契约**：前端消费 `AnalysisResult`（扁平）+ SSE 事件序列（thinking/stage/done/error），直接对应三面板与 Evidence Chain 展示。
- **毕业 map fog → 新后端实现 ticket**：本设计把「Stage 1/2/3 如何实现」从 fog 提升为可 ticket 的工作；Stage 1（含 ADR-0003 待补的 `visible_location_text` Observation 字段）、Stage 2（grounding + context provider 链 + 高程 fallback）、Stage 3（规则引擎 + LLM 推断 + explanation 渲染）、API/pipeline 装配各自成 ticket，挂在 #1 下、被本 #8 解除阻塞。
- **测试接缝确定**：`analyze(image, location) -> AnalysisResult` 是 PRD §5.2 主接缝；Case A–H 在此断言（如 Case C：同 Observation + 不同 TerrainContextBlock → 不同 TerrainRisk）。
- **与 ADR-0001~0004 一致**：扁平信封直接嵌四份既有契约，零改动；阶段边界复用各自模块接口；降级哲学一脉相承。
- **Stage 1 杠杆保留**：json_object→tool-calling 的切换以「原型期结论」记录，不锁死；与 map「Event Assessment 调参」「摄像头位置数据格式」等同属待原型验证的开放项。
