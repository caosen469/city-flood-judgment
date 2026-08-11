// 开发用 mock SSE 发射器：不连后端，按真实事件序列（thinking* → stage×4 → done）
// 把 real-schema 形状的 AnalysisResult 喂给 composable 的 reactive state。
//
// 目的：(1) 无 DASHSCOPE_API_KEY / 无后端时也能预览 UI；(2) 这份 mock 严格遵循
// src/schemas 的 Pydantic 契约，相当于一份"前端对契约的理解"——真后端联调时若形状
// 不符，渲染会立刻暴露差异。

import type { AnalysisResult, StageName } from '../types'

type StreamState = {
  status: 'idle' | 'streaming' | 'done' | 'error'
  thinking: string
  stages: Record<StageName, { arrived: boolean; durationMs: number | null; data: unknown }>
  result: AnalysisResult | null
  error: { code: string; message: string; stage?: string | null } | null
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function iso(): string {
  return new Date().toISOString()
}

/** happy path：有位置，全阶段产出。镜像 src/schemas 真实形状。 */
function happyResult(): AnalysisResult {
  const lat = 22.7707
  const lon = 113.5412
  const retrieved = iso()
  return {
    request_id: 'mock-happy-' + Math.random().toString(16).slice(2, 10),
    observation: {
      meta: {
        observation_id: 'obs_mock_001',
        source_image: 'road_water1.jpg',
        observed_at: '2026-08-09T14:21:00',
        source_location: { lat, lon, road_name: '进港大道', raw_text: '进港大道 · 南沙' },
      },
      phenomenon_type: 'road_waterlogging',
      overall_confidence: 'medium',
      presence_probability: 0.82,
      waterlogging: {
        status: 'present',
        waterlogging_level: 'L2',
        depth_estimate: {
          depth_cm: { min: 4, max: 9, most_likely: 6 },
          confidence: 'medium',
        },
        water_patches: [
          {
            patch_id: 'p1',
            location_in_frame: '右侧一条车道，纵向延伸',
            coverage: 'moderate',
            waterlogging_level: 'L2',
            depth_cm: { min: 4, max: 9, most_likely: 6 },
          },
        ],
        surface_condition: 'clear_water',
        visual_cues: {
          reflection_present: true,
          reflection_type: 'water_reflection',
          visible_water_boundary: true,
          visible_waterline: false,
          visible_ripple_or_wave: false,
        },
        reference_objects: [
          { object: '轿车', known_size: '约 1.5 m 高', relation_to_water: '水位至轮毂下沿', reliability: 'high' },
        ],
        visual_impact_hint: 'obstructing',
        visual_evidence: [
          { evidence: '积水覆盖约一条车道，路面标线被淹没', supports: '积水存在 (L2)', reliability: 'high' },
          { evidence: '水面可见车辆与环境倒影', supports: '明确积水 (非潮湿)', reliability: 'medium' },
        ],
        alternative_explanations: [],
        uncertainty_reasons: [],
      },
      visible_location_text: '进港大道',
      observed_summary: '路面有大面积积水，覆盖一条车道，水面可见倒影；车辆缓慢通过，无明显溅起。',
    },
    grounding: {
      status: 'grounded',
      query_point: { lat, lon },
      source: 'user_latlon',
      best_match: {
        osm_way_id: '123456789',
        edge_ref: [123456001, 123456002, 0],
        road_name: '进港大道',
        highway: 'primary',
        bridge: false,
        tunnel: false,
        match_point: { lat: 22.77069, lon: 113.54119 },
        match_distance_m: 8.2,
        confidence: 'high',
      },
      candidates: [
        {
          osm_way_id: '123456789',
          edge_ref: [123456001, 123456002, 0],
          road_name: '进港大道',
          highway: 'primary',
          bridge: false,
          tunnel: false,
          match_point: { lat: 22.77069, lon: 113.54119 },
          match_distance_m: 8.2,
          confidence: 'high',
        },
        {
          osm_way_id: '987654321',
          edge_ref: [987001, 987002, 0],
          road_name: '港前大道',
          highway: 'secondary',
          bridge: false,
          tunnel: false,
          match_point: { lat: 22.7712, lon: 113.5418 },
          match_distance_m: 42.1,
          confidence: 'low',
        },
      ],
      unresolved_reason: null,
    },
    context: {
      query_point: { lat, lon, source_location: '进港大道' },
      blocks: [
        {
          block_type: 'road',
          road_name: '进港大道',
          osm_way_id: 123456789,
          highway_class: 'primary',
          lanes: 4,
          oneway: true,
          is_bridge: false,
          is_tunnel: false,
          maxspeed: 60,
          offset_distance_m: 8.2,
          grounding_confidence: 0.9,
          provenance: { source: 'osm', data_vintage: '2026-08-01', retrieved_at: retrieved },
          availability: { status: 'available', reason: null },
        },
        {
          block_type: 'elevation',
          elevation_pt: 2.1,
          stats: { radius_m: 1000, valid_pixels: 121, min: 0.8, max: 3.4, mean: 1.9, std: 0.6 },
          provenance: { source: 'srtm_local', data_vintage: '2000-02-11', retrieved_at: retrieved },
          availability: { status: 'available', reason: null },
        },
        {
          block_type: 'terrain',
          lowness: { micro: 1.1, meso: 1.4, macro: 0.7, composite: 1.2, lowness_class: 'moderately_low' },
          provenance: { source: 'srtm_local', data_vintage: '2000-02-11', retrieved_at: retrieved },
          availability: { status: 'available', reason: null },
        },
      ],
    },
    knowledge: {
      knowledge_items: [
        {
          knowledge_type: 'terrain_risk',
          statement: '该路段处于相对低洼区（多尺度 TPI 复合约 1.2 m，属中等低洼），遇强降雨易汇水。',
          confidence: 'medium',
          mechanism: 'rule',
          rule_id: 'terrain_tpi_moderately_low',
          lowness_class: 'moderately_low',
          composite_tpi_m: 1.2,
          evidence: [
            { ref_type: 'context', block_type: 'terrain', field_path: 'lowness.composite', note: '多尺度 TPI 复合 = 1.2 m' },
            { ref_type: 'derived', rule_id: 'classify_lowness', value: 'moderately_low', inputs: [], note: '低洼分级 = 中等低洼' },
          ],
        },
        {
          knowledge_type: 'road_impact',
          statement: '积水（约 6 cm）覆盖一条车道，预计对机动车通行造成明显影响，行人/非机动车影响中等。',
          confidence: 'medium',
          mechanism: 'llm',
          rule_id: null,
          impacts: [
            { actor: 'motor_vehicle', level: 'high' },
            { actor: 'non_motor_vehicle', level: 'medium' },
            { actor: 'pedestrian', level: 'medium' },
          ],
          evidence: [
            { ref_type: 'observation', field_path: 'waterlogging.waterlogging_level', note: '积水等级 L2，深度 ≈ 6 cm' },
            { ref_type: 'observation', field_path: 'waterlogging.visual_impact_hint', note: '覆盖道路特征/标线' },
            { ref_type: 'grounding', field_path: 'best_match.highway', note: '挂接主干路 (primary)，4 车道' },
          ],
        },
      ],
      event_assessment: {
        severity: 'suspected_flood_significant',
        confidence: 'medium',
        mechanism: 'llm',
        reasoning:
          '视觉证据明确（大面积积水 + 倒影 + 标线淹没），且该点处于中等低洼、为城市主干道，综合判断具有内涝意义；非单纯局部水洼。',
        evidence: [
          { ref_type: 'observation', field_path: 'waterlogging.status', note: 'present + L2' },
          { ref_type: 'context', block_type: 'terrain', field_path: 'lowness.lowness_class', note: '中等低洼' },
          { ref_type: 'grounding', field_path: 'best_match.highway', note: '主干路' },
        ],
      },
      explanation:
        '综合画面观察与城市数据：进港大道（主干道）该路段为中等低洼区，当前积水约 6 cm 覆盖一条车道，判断为疑似具内涝意义的积水事件，建议关注后续降雨与排水。',
    },
    timings: { observation: 3180, grounding: 182, context: 241, knowledge: 1540 },
  }
}

/** degraded：无位置 → grounding unresolved(no_location) → road block unavailable →
 * elevation/terrain 无点位 unavailable → 资格门关 → knowledge_items 空、event uncertain。 */
function degradedResult(): AnalysisResult {
  const retrieved = iso()
  const base = happyResult()
  return {
    ...base,
    request_id: 'mock-degraded-' + Math.random().toString(16).slice(2, 10),
    observation: {
      ...base.observation,
      meta: { ...base.observation.meta!, source_location: {} },
    },
    grounding: {
      status: 'unresolved',
      query_point: null,
      source: 'none',
      best_match: null,
      candidates: [],
      unresolved_reason: 'no_location',
    },
    context: {
      query_point: null,
      blocks: [
        {
          block_type: 'road',
          provenance: { source: 'osm', retrieved_at: retrieved },
          availability: { status: 'unavailable', reason: 'grounding_unresolved' },
        },
        {
          block_type: 'elevation',
          stats: { radius_m: 1000, valid_pixels: 0 },
          provenance: { source: 'srtm_local', retrieved_at: retrieved },
          availability: { status: 'unavailable', reason: 'no_data_in_bounds' },
        },
        {
          block_type: 'terrain',
          lowness: { lowness_class: 'insufficient_data' },
          provenance: { source: 'srtm_local', retrieved_at: retrieved },
          availability: { status: 'unavailable', reason: 'no_data_in_bounds' },
        },
      ],
    },
    knowledge: {
      knowledge_items: [],
      event_assessment: {
        severity: 'uncertain',
        confidence: 'low',
        mechanism: 'llm',
        reasoning:
          '仅凭画面可见积水（L2），但缺少位置与城市数据，无法判断是否处于低洼区、是否为主干道，事件级别不确定。',
        evidence: [
          { ref_type: 'observation', field_path: 'waterlogging.waterlogging_level', note: 'present + L2' },
        ],
      },
      explanation:
        '未提供位置，无法进行道路挂接与城市数据装配；仅基于图像给出视觉层面的积水判断，事件意义待补充位置后复核。',
    },
    timings: { observation: 3110, grounding: 12, context: 40, knowledge: 920 },
  }
}

export async function emitMockStream(
  state: StreamState,
  req?: { location?: { lat?: number | null; lon?: number | null; road_name?: string | null; raw_text?: string | null } } | null,
  signal?: AbortSignal,
): Promise<void> {
  const hasLoc = !!(req?.location && ((req.location.lat != null && req.location.lon != null) || req.location.road_name || req.location.raw_text))
  const result = hasLoc ? happyResult() : degradedResult()
  const stages: StageName[] = ['observation', 'grounding', 'context', 'knowledge']
  const stageData: Record<StageName, unknown> = {
    observation: result.observation,
    grounding: result.grounding,
    context: result.context,
    knowledge: result.knowledge,
  }

  // thinking 增量（仅模拟，分段喂）
  const thinkingText =
    '我先把这张图看一遍：路面有大面积积水，覆盖一条车道，水面有倒影…' +
    (hasLoc ? '接着用位置去挂接路网、查高程与地形。' : '未提供位置，跳过挂接与城市数据。') +
    '最后综合判断这是什么样的积水事件。'
  for (const seg of thinkingText.match(/.{1,12}/g) ?? []) {
    if (signal?.aborted) return
    state.thinking += seg
    await sleep(40)
  }
  await sleep(150)

  // 逐阶段产出
  for (const name of stages) {
    if (signal?.aborted) return
    await sleep(280)
    state.stages[name].arrived = true
    state.stages[name].durationMs = result.timings[name] ?? 0
    state.stages[name].data = stageData[name]
  }
  await sleep(150)

  // done —— 权威聚合
  state.result = result
  for (const name of stages) {
    state.stages[name].arrived = true
    state.stages[name].data = stageData[name]
  }
  state.status = 'done'
}
