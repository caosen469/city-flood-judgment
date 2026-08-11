# 南沙积水研判 Demo · 前端（wayfinder #16）

落地 [#9 原型](../prototype/frontend-layouts.html) 锁定的设计：

- **布局 = B 三列**：看 / 知 / 判 并排（整页尽量无纵向滚动）
- **视觉 = premium**：暖米白底 `#f4f1ea` + 衬线标题（Georgia / 思源宋体）+ 金铜点缀 `#9a7b3f`
  + 细线大留白 + 卡片顶端细金线；Element Plus 经 CSS 变量整体覆写（`src/styles/premium.css`）
- **证据链 = 横向证据流 `EvidenceFlow`**：画面观察 → 道路定位 → 城市数据 → 规则派生 → 事件判定，
  每节点带具体引用，箭头串联，节点按来源类型用左边框色区分
- **后端通信 = SSE 为主**：消费 `POST /analyze/stream`（`thinking → stage×4 → done | error`）
  逐阶段渐进出现；fetch + ReadableStream 手写 SSE 解析（EventSource 不能 POST multipart）
- **地图 = Leaflet**：真实 OSM 瓦片 + 挂接垂足点标记 + 偏移环（circle）

## 运行

```bash
# 1) 后端（默认 http://localhost:8000；无 DASHSCOPE_API_KEY 时自动确定性降级）
cd .. && python -m uvicorn src.api.app:create_app --factory --reload --port 8000

# 2) 前端 dev（http://localhost:5173，dev 代理 /analyze* → :8000）
cd frontend && npm install && npm run dev

# 仅前端预览（不连后端，走内置 mock SSE，便于看 UI）
VITE_API_BASE=mock npm run dev

# 生产构建（含 vue-tsc 类型检查）
npm run build && npm run preview
```

环境变量 `VITE_API_BASE`：
- 缺省 / 任意 URL：dev 走同源 `/analyze` 代理（生产由后端同源托管）。
- `mock`：完全不连后端，由 `src/composables/mockStream.ts` 按真实 SSE 时序喂
  **真实 schema 形状**的 `AnalysisResult`（happy / 无位置降级两种场景），既是 UI 预览，
  也充当"前端对契约理解"的 conformance 样本。

## 契约对齐（单一真值源）

- 后端 `AnalysisResult` / SSE 载荷形状：[`../docs/openapi.yaml`](../docs/openapi.yaml)
  + Pydantic 模型 [`../src/schemas/*.py`](../src/schemas) + [`../src/api/models.py`](../src/api/models.py)
- 前端 TS 镜像：[`src/types.ts`](src/types.ts)
- 中文标签：[`src/labels.ts`](src/labels.ts)（对齐
  [`../src/schemas/display_labels.py`](../src/schemas/display_labels.py)，并补齐后端未收录的
  `lowness_class` / `block_type` / `grounding_status` / `availability` / `context_source` 等分组）

**注意**：#9 原型的 mock 数据简化了若干字段（如 `depth_estimate.value_cm`、
`visual_cues` 当字符串数组、`knowledge_items.actor/level` 单值、evidence `{type,ref}`）。
本实现严格按 **真实 schema** 渲染：`depth_cm.{min,max,most_likely}`、
`visual_cues` 为 `VisualCues` 对象、`road_impact.impacts: [{actor,level}]` 列表、
evidence `{ref_type, note, field_path}`、provenance `source` 为枚举码。

## 组件树

```
App.vue                      顶栏 + InputBar + ThinkingPanel + 三列布局；持 useAnalysisStream
├─ composables/
│  ├─ useAnalysisStream.ts   SSE 客户端（fetch+ReadableStream 解析 event:/data:）
│  └─ mockStream.ts          dev mock（real-schema 形状，happy + degraded）
├─ components/
│  ├─ InputBar.vue           图片上传 + 位置(road_name/raw_text/lat/lon) + 触发
│  ├─ ThinkingPanel.vue      思考增量 + 四阶段进度
│  ├─ ObservationPanel.vue   列1 我所见：等级 / 深度 / 视觉线索 / 参照物 / 置信度
│  ├─ ContextPanel.vue       列2 我所知：Leaflet Map + 挂接 + road/elevation/terrain mini 卡
│  │  └─ MapView.vue         Leaflet（circleMarker + 偏移环）
│  ├─ KnowledgePanel.vue     列3 这意味着：事件判定 banner + 知识条目 + 综合解释
│  │  └─ EvidenceFlow.vue    横向证据链
│  └─ SevTag.vue             语义色 Tag（success/warning/danger/neutral → el-tag）
└─ styles/premium.css        premium 主题 tokens + Element Plus 覆写
```

## 降级表达（镜像后端 graceful degradation）

前端按值渲染、不报错：

- grounding `unresolved` → 列2 地图显示"无位置"、road block unavailable、候选条目缺省
- context block `availability` 三态（available/unavailable/uncertain）逐 block 表达
- knowledge 资格门关 → `knowledge_items` 空、event_assessment 可判 `uncertain`
- 证据链节点按来源数据是否可用自动缺省（如无位置则跳过"道路定位"节点）
