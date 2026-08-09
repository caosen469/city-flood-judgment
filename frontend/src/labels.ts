// zh-CN 显示标签。与 src/schemas/display_labels.py 对齐（同一份枚举码本），
// 并补齐后端 display_labels.py 未收录、但前端展示需要的分组
// （lowness_class / block_type / grounding_status / availability /
//   context_source / highway_class / unresolved_reason / location_source）。
//
// 规则：后端永远存码，前端查表展示，缺码时回退原码本身。

type Group = Record<string, string>

export const LABELS: Record<string, Group> = {
  // ── 与 src/schemas/display_labels.py 一致 ──
  phenomenon_type: { road_waterlogging: '道路积水' },
  overall_confidence: { high: '高', medium: '中', low: '低' },
  confidence: { high: '高', medium: '中', low: '低' }, // 别名，方便直接传 confidence 值
  likelihood: { high: '高', medium: '中', low: '低' },
  waterlogging_status: { present: '存在', absent: '不存在', uncertain: '不确定' },
  waterlogging_level: {
    L0: 'L0 · 无积水/轻微潮湿',
    L1: 'L1 · 约 0–3 cm',
    L2: 'L2 · 约 3–10 cm',
    L3: 'L3 · 约 10–20 cm',
    L4: 'L4 · 约 20–30 cm',
    L5: 'L5 · 大于 30 cm',
    LX: 'LX · 疑似积水但深度不可估',
  },
  surface_condition: {
    dry: '干燥', wet: '潮湿', suspected_water: '疑似积水',
    clear_water: '明确积水', unknown: '无法判断',
  },
  reflection_type: {
    water_reflection: '水面倒影', wet_road_glare: '潮湿路面反光',
    light_glare: '灯光反射', shadow: '阴影',
    lens_artifact: '镜头异常', unknown: '未知',
  },
  patch_coverage: {
    localized: '局部', moderate: '中等范围', extensive: '大范围', unknown: '未知',
  },
  visual_impact_hint: {
    none: '无明显影响', minor: '轻微（如路缘水洼）',
    obstructing: '覆盖道路特征/标线', submerging: '接近车辆/行人底盘', unclear: '无法判断',
  },
  knowledge_type: { terrain_risk: '地形风险', road_impact: '道路通行影响' },
  inference_mechanism: { rule: '规则推导', llm: '模型推断' },
  mechanism: { rule: '规则推导', llm: '模型推断' }, // 别名
  evidence_ref_type: {
    observation: '画面观察', grounding: '道路定位',
    context: '城市数据', derived: '规则派生',
  },
  road_actor: { pedestrian: '行人', non_motor_vehicle: '非机动车', motor_vehicle: '机动车' },
  road_impact_level: {
    low: '低', medium: '中', high: '高', severe: '严重', uncertain: '无法判断',
  },
  event_severity: {
    ordinary_puddle: '普通局部积水',
    suspected_flood_significant: '疑似具内涝意义',
    uncertain: '不确定',
  },

  // ── 前端补充分组（后端 display_labels.py 未收录）──
  lowness_class: {
    level_or_higher: '平坦/偏高',
    slightly_low: '轻微低洼',
    moderately_low: '中等低洼',
    significantly_low: '显著低洼',
    insufficient_data: '数据不足',
  },
  block_type: { road: '道路', elevation: '高程', terrain: '地形' },
  grounding_status: { grounded: '已定位', ambiguous: '歧义', unresolved: '未定位' },
  availability: { available: '可用', unavailable: '不可用', uncertain: '不确定' },
  unavailability_reason: {
    no_data_in_bounds: '范围内无数据',
    grounding_unresolved: '未挂接到道路（grounding 未解析）',
    low_pixel_count: '有效像素过少',
    fallback_used: '使用兜底数据源',
    source_error: '数据源异常',
    not_applicable: '本场景不适用',
  },
  context_source: {
    osm: 'OSM 路网',
    srtm_local: '本地 SRTM 30m',
    opentopography: 'OpenTopography',
    open_meteo: 'Open-Meteo（兜底）',
    open_elevation: 'Open-Elevation（兜底）',
    user_provided: '用户输入',
  },
  highway_class: {
    motorway: '高速', trunk: '干道', primary: '主干路', secondary: '次干路',
    tertiary: '支路', unclassified: '未分级', residential: '居住区道路',
    living_street: '生活街道', service: '服务路', other: '其他',
  },
  unresolved_reason: {
    out_of_buffer: '距最近路段超 100m',
    outside_nansha: '点位不在南沙范围',
    geocode_failed: '地名无法解析',
    no_location: '未提供位置',
  },
  location_source: {
    exif: '图片 EXIF',
    user_latlon: '手动输入经纬度',
    geocoded_text: '地名解析',
    none: '无',
  },
  stage: {
    observation: '我所见',
    grounding: '我所知 · 定位',
    context: '我所知 · 城市数据',
    knowledge: '这意味着',
  },
  error_code: {
    unreadable_image: '图片不可读',
    vlm_provider_error: 'VLM 上游异常',
    vlm_json_invalid: 'VLM 输出解析失败',
    internal_error: '内部错误',
  },
}

/** 查标签，缺码回退原码。group 用 LABELS 的键。 */
export function L(group: string, code: string | null | undefined): string {
  if (code == null || code === '') return '—'
  return LABELS[group]?.[code] ?? code
}

// ── 语义化的颜色档（供 tag/badge 着色）──

/** 积水等级 L0..L5,LX → severity 语义色键：success/warning/danger/neutral。 */
export function levelSeverity(level: string): 's' | 'w' | 'd' | 'n' {
  return ({ L0: 's', L1: 's', L2: 'n', L3: 'w', L4: 'd', L5: 'd', LX: 'w' } as const)[level as 'L0'] ?? 'n'
}

/** 道路通行影响等级 → 语义色。 */
export function impactLevelColor(level: string): 's' | 'w' | 'd' | 'n' {
  if (level === 'low') return 's'
  if (level === 'medium') return 'w'
  if (level === 'high' || level === 'severe') return 'd'
  return 'n' // uncertain
}

/** 事件判定 severity → 语义色。 */
export function severityColor(severity: string): 's' | 'w' | 'd' | 'n' {
  if (severity === 'ordinary_puddle') return 's'
  if (severity === 'suspected_flood_significant') return 'd'
  return 'n' // uncertain
}
