# Pipeline 架构（城市积水知识理解 Demo）

> 对应 wayfinder ticket #8；决策依据见 [ADR-0005](adr/0005-pipeline-architecture.md)。端点契约见 [openapi.yaml](openapi.yaml)。本文是装配级架构，数据契约见 ADR-0001~0004 与 `src/schemas/`。

## 1. 主接缝

整条 pipeline 是一个函数（PRD §5.2「Analysis Pipeline Seam」）：

```python
# src/pipeline/service.py
def analyze(image: ImageInput, location: LocationRef | None) -> AnalysisResult: ...
```

FastAPI handler 是它的薄包装。绝大多数验收测试（PRD Case A–H）打在此签名上，**不**绑定 VLM prompt / 数据库 / 推理实现——换模型、换数据源、换推理方式都不重写产品级测试。

## 2. 三阶段与数据流

```
                ┌─────────────────────────────────────────────────────┐
   image ──────▶│ Stage 1 — What I See                                │
   location     │   src/observation/generate.py                       │
                │   Qwen3-VL (json_object + Pydantic 校验 + 修复)     │
                └───────────────┬─────────────────────────────────────┘
                                │ Observation  (ADR-0001)
                                ▼
                ┌─────────────────────────────────────────────────────┐
                │ Stage 2 — What I Know                               │
                │   2a Grounding (src/grounding/, ADR-0003)           │
                │      locate(LocationRef) -> LocatedPoint | None     │
                │      match(lat, lon)     -> GroundedEntity          │
                │   2b Context (src/context/, ADR-0002)               │
                │      ContextAssembler.assemble(point, grounding)    │
                │                          -> UrbanContext            │
                └───────────────┬─────────────────────────────────────┘
                                │ GroundedEntity + UrbanContext
                                ▼
                ┌─────────────────────────────────────────────────────┐
                │ Stage 3 — What It Means                             │
                │   src/knowledge/engine.py (ADR-0004)                │
                │   KnowledgeEngine.assemble(obs, grounding, context) │
                │      rules.py   : FactBundle + 确定 TerrainRisk     │
                │      infer.py   : LLM RoadImpact + EventAssessment  │
                │      explain.py : LLM explanation (基于 chain)      │
                └───────────────┬─────────────────────────────────────┘
                                │ KnowledgeResult (ADR-0004)
                                ▼
                     AnalysisResult (扁平信封, ADR-0005)
```

阶段**恒跑全三阶段，无短路**。阶段内部的资格门（ADR-0004）决定哪些 knowledge 产出，而非决定阶段是否执行。

## 3. 数据契约（阶段间）

每阶段的输入/输出已是上流 ADR 锁定的 Pydantic v2 契约，pipeline 不重新定义，仅组装：

| 阶段 | 输入 | 输出 | 契约文件 |
|---|---|---|---|
| Stage 1 | `image`（URL/文件/bytes） | `Observation` | `src/schemas/observation.py` |
| Stage 2a | `LocationRef`（Observation.meta 或请求） | `GroundedEntity` | `src/schemas/grounding.py` |
| Stage 2b | `point` + `GroundedEntity` | `UrbanContext` | `src/schemas/context.py` |
| Stage 3 | `Observation` + `GroundedEntity` + `UrbanContext` | `KnowledgeResult` | `src/schemas/knowledge.py` |
| 装配 | 全部 | `AnalysisResult` | `src/api/models.py` |

`AnalysisResult`（扁平，状态内含）：

```python
class AnalysisResult(BaseModel):
    request_id: str
    observation: Observation
    grounding: GroundedEntity
    context: UrbanContext
    knowledge: KnowledgeResult
    timings: dict[str, float]   # {"observation": ms, "grounding": ms, "context": ms, "knowledge": ms}
```

降级从各模型字段读，不另设阶段包装：
- grounding 不可用 → `grounding.status == "unresolved"` + `unresolved_reason`
- context 某源缺失 → 对应 block `availability.status == "unavailable"` + `reason`
- knowledge 因依赖缺失而不产出 → 该 item 不在 `knowledge.knowledge_items` 中，`event_assessment.reasoning` / `explanation` 显式说明

## 4. 错误传播与部分结果

| 情形 | 策略 | 表现 |
|---|---|---|
| 图片不可读 / 非图像 | **硬失败 abort** | `POST /analyze` → HTTP 422；`/analyze/stream` → `error` 事件后关闭 |
| VLM 上游失败（超时/5xx/JSON 修复仍败） | **硬失败 abort** | HTTP 502；`error` 事件 |
| Grounding unresolved | 软降级 | 仍返回 Observation + 全 UrbanContext（road block unavailable，elevation/terrain 视有无点位）；knowledge 关 RoadImpact 门 |
| Elevation/Terrain 数据缺失 | 软降级 | 对应 block unavailable；TerrainRisk 资格门关闭 |
| 无位置输入 | 软降级 | grounding `unresolved(no_location)` → context 各 block 全 unavailable → knowledge 仅图像 EventAssessment |
| 视觉证据不足 | 软降级 | Observation `overall_confidence=low` / `status=uncertain`；EventAssessment 可判 `uncertain` |

只有 Stage 1 的 VLM 硬失败会中断整条 pipeline；其余一切 graceful，由值表达（ADR-0001~0004 一致哲学）。

## 5. Stage 1 结构化输出策略

约束（事实，见 ADR-0005）：DashScope 的 `json_schema` 严模式对任何 Qwen3-VL 模型均无文档支持；思考模式 + `json_object` 可能产出非严格 JSON。

策略（Option A）：
1. 由 `Observation.model_json_schema()` 自动渲染提示词内 schema（单一真值源，模型即校验器）。
2. `response_format={"type":"json_object"}`，**不设 `max_tokens`**，`enable_thinking` 经 `extra_body` 传。
3. 流式收齐后 `json.loads` → `Observation.model_validate(...)`。
4. 校验失败 → 两步修复：调一个非思考 json_object 模型修 JSON → 再校验；仍失败 → Stage 1 硬失败。

杠杆（Option B，原型期再定）：若 json_object 不能稳定产出嵌套 Observation，改用 `tools`（`parameters` = Observation schema）。

## 6. API（摘要）

| 端点 | 方法 | 响应 | 用途 |
|---|---|---|---|
| `/analyze` | POST | `AnalysisResult` (JSON) | 非流式，测试/程序化调用 |
| `/analyze/stream` | POST | `text/event-stream` (SSE) | Demo 三阶段渐进展示 |

请求体（两种来源二选一）：`image_url: str` **或** `image: file`（multipart）；可选 `location: {lat, lon, road_name?, raw_text?}`。完整 schema 见 [openapi.yaml](openapi.yaml)。

SSE 事件序列：
```
thinking*   (reasoning_content 增量; 仅思考型模型, 复用 classify_model)
stage       (observation | grounding | context | knowledge; 载荷=该阶段模型 + duration_ms)
...         (按序共 4 个 stage 事件)
done        (携带完整 AnalysisResult —— 权威聚合, 与非流式同形)
| error     ({code, message, stage}; 随后关闭)
```

## 7. 目录结构参考

> 物理布局，实现各 ADR 已 specced 的模块接口。空目录随各实现 ticket 落地而建；本设计 ticket 不建空骨架。

```
src/
  schemas/            # 已落地：observation/grounding/context/knowledge + display_labels
  config.py           # pydantic-settings：DASHSCOPE_API_KEY / model / data 路径 / 阈值
  vlm/                # ← 从 waterlogging.py 抽出
    client.py           # Qwen client 工厂 + classify_model + thinking-mode 交叉表
    reasoning.py        # reasoning_content 流式读取
  observation/        # Stage 1
    generate.py         # image -> Observation
    prompt.py           # 由 Observation.model_json_schema() 渲染的提示词
  grounding/          # Stage 2a (ADR-0003)
    locate.py           # locate(LocationRef) -> LocatedPoint | None
    match.py            # match(lat, lon) -> GroundedEntity
    graph.py            # 加载/缓存 nansha_roads.gpkg -> OSMnx 图
  context/            # Stage 2b (ADR-0002)
    base.py             # ContextProvider 协议 + ContextAssembler
    providers/
      road.py           # RoadProvider (从 GroundedEntity join RoadContextBlock)
      elevation.py      # ElevationProvider + fallback 链 (本地 SRTM→OpenTopography→Open-Meteo→Open-Elevation)
      terrain.py        # TerrainProvider (多尺度 TPI -> LownessScores)
  knowledge/          # Stage 3 (ADR-0004)
    rules.py            # extract_fact_bundle + 资格门 + 确定 TerrainRisk
    infer.py            # LLM RoadImpact + EventAssessment (schema 白名单 + 后校验)
    explain.py          # LLM explanation 渲染 (输入=结构化 chain)
    engine.py           # KnowledgeEngine.assemble(obs, grounding, context) -> KnowledgeResult
  pipeline/
    service.py          # analyze(image, location) -> AnalysisResult   ← 测试接缝
    streaming.py        # SSE 事件生成
  api/
    app.py              # FastAPI app + lifespan (启动加载城市数据, 注册 provider/engine)
    routes.py           # POST /analyze, POST /analyze/stream
    models.py           # 请求/响应信封 (AnalysisResult / AnalyzeRequest / SSE 事件)
scripts/                # 数据获取脚本 (osm/srtm 下载) — 不变
data/
  images/               # 测试图
  urban/                # 缓存 nansha_roads.gpkg, SRTM tiff
tests/
  test_thinking_mode.py # 已有
  test_pipeline_*.py    # 接缝测试 (Case A–H)
docs/
  architecture.md       # 本文
  openapi.yaml          # 端点契约
  adr/0005-…            # 本设计决策
```

## 8. 与现有 `src/waterlogging.py` 的关系

**Refactor**（非 Wrap、非 Delete）：
- 抽 `classify_model` + `resolve_thinking_choice`（thinking-mode 交叉语义表）+ OpenAI client 工厂 → `src/vlm/client.py`；`reasoning_content` 流式读取 → `src/vlm/reasoning.py`。
- 丢弃旧积水 prompt 与旧 JSON 校验；新 prompt + Observation 契约 → `src/observation/`。
- CLI 保留为 Stage-1 调试工具，重指向 `src/observation/generate.py`。
- `tests/test_thinking_mode.py` 继续守护被复用的交叉表。

## 9. 装配与配置

- `config.py`（pydantic-settings）读 `DASHSCOPE_API_KEY`、默认模型、`data/urban` 路径、各阈值（grounding 距离档、TPI 权重等已在 schema 常量内）。
- FastAPI `lifespan` 启动时一次性加载 OSM 图 + SRTM tiff，构造 `ContextAssembler`（注册 road/elevation/terrain provider）与 `KnowledgeEngine`，注入 handler（`Depends` 或 app state）。
- CORS 对 Vue dev server 开放。
- `request_id = uuid4`，贯穿 `AnalysisResult` 与日志。
