// 后端 AnalysisResult 契约的 TypeScript 镜像。
// 单一真值源 = src/schemas/{observation,grounding,context,knowledge}.py（Pydantic v2）+
// src/api/models.py（顶层信封 + SSE 载荷）+ docs/openapi.yaml。
//
// 重要：后端用 "unknown by value"（枚举哨兵 / 可空数值 / 空列表），绝不用缺键。
// 因此本文件里大量字段可空 —— 前端按值渲染、不报错（镜像后端 graceful degradation）。

// ───────────────────────── 通用 ─────────────────────────

export type Confidence = 'high' | 'medium' | 'low'
export type Likelihood = 'high' | 'medium' | 'low'

// ───────────────────────── Observation (ADR-0001) ─────────────────────────

export type PhenomenonType = 'road_waterlogging'
export type WaterloggingStatus = 'present' | 'absent' | 'uncertain'
export type WaterloggingLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4' | 'L5' | 'LX'
export type SurfaceCondition =
  | 'dry' | 'wet' | 'suspected_water' | 'clear_water' | 'unknown'
export type ReflectionType =
  | 'water_reflection' | 'wet_road_glare' | 'light_glare' | 'shadow' | 'lens_artifact' | 'unknown'
export type PatchCoverage = 'localized' | 'moderate' | 'extensive' | 'unknown'
export type VisualImpactHint =
  | 'none' | 'minor' | 'obstructing' | 'submerging' | 'unclear'

export interface LocationRef {
  lat?: number | null
  lon?: number | null
  road_name?: string | null
  raw_text?: string | null
}

export interface ObservationMeta {
  observation_id: string
  source_image: string
  observed_at: string // ISO datetime
  source_location?: LocationRef | null
}

export interface DepthCm {
  min?: number | null
  max?: number | null
  most_likely?: number | null
}

export interface DepthEstimate {
  depth_cm: DepthCm
  confidence: Confidence
}

export interface WaterPatch {
  patch_id: string
  location_in_frame: string
  coverage: PatchCoverage
  waterlogging_level: WaterloggingLevel
  depth_cm: DepthCm
}

export interface VisualCues {
  reflection_present: boolean
  reflection_type: ReflectionType
  visible_water_boundary: boolean
  visible_waterline: boolean
  visible_ripple_or_wave: boolean
}

export interface ReferenceObject {
  object: string
  known_size: string
  relation_to_water: string
  reliability: Likelihood
}

export interface VisualEvidence {
  evidence: string
  supports: string
  reliability: Likelihood
}

export interface AlternativeExplanation {
  possibility: string
  likelihood: Likelihood
  reason: string
}

export interface WaterloggingAttributes {
  status: WaterloggingStatus
  waterlogging_level: WaterloggingLevel
  depth_estimate: DepthEstimate
  water_patches: WaterPatch[]
  surface_condition: SurfaceCondition
  visual_cues: VisualCues
  reference_objects: ReferenceObject[]
  visual_impact_hint: VisualImpactHint
  visual_evidence: VisualEvidence[]
  alternative_explanations: AlternativeExplanation[]
  uncertainty_reasons: string[]
}

export interface Observation {
  meta?: ObservationMeta | null
  phenomenon_type: PhenomenonType
  overall_confidence: Confidence
  presence_probability: number // 0..1
  waterlogging: WaterloggingAttributes
  visible_location_text?: string | null
  observed_summary: string
}

// ───────────────────────── Grounding (ADR-0003) ─────────────────────────

export type GroundingStatus = 'grounded' | 'ambiguous' | 'unresolved'
export type LocationSource = 'exif' | 'user_latlon' | 'geocoded_text' | 'none'
export type UnresolvedReason =
  | 'out_of_buffer' | 'outside_nansha' | 'geocode_failed' | 'no_location'

export interface LatLon {
  lat: number
  lon: number
}

export interface MatchedRoad {
  osm_way_id: string
  edge_ref: [number, number, number]
  road_name?: string | null
  highway: string
  bridge: boolean
  tunnel: boolean
  match_point: LatLon
  match_distance_m: number
  confidence: Confidence
}

export interface GroundedEntity {
  status: GroundingStatus
  query_point?: LatLon | null
  source: LocationSource
  best_match?: MatchedRoad | null
  candidates: MatchedRoad[]
  unresolved_reason?: UnresolvedReason | null
}

// ───────────────────────── Urban Context (ADR-0002) ─────────────────────────

export type Availability = 'available' | 'unavailable' | 'uncertain'
export type UnavailabilityReason =
  | 'no_data_in_bounds' | 'grounding_unresolved' | 'low_pixel_count'
  | 'fallback_used' | 'source_error' | 'not_applicable'
export type ContextSource =
  | 'osm' | 'srtm_local' | 'opentopography' | 'open_meteo' | 'open_elevation' | 'user_provided'
export type HighwayClass =
  | 'motorway' | 'trunk' | 'primary' | 'secondary' | 'tertiary'
  | 'unclassified' | 'residential' | 'living_street' | 'service' | 'other'
export type LownessClass =
  | 'level_or_higher' | 'slightly_low' | 'moderately_low' | 'significantly_low' | 'insufficient_data'

export interface Provenance {
  source: ContextSource
  data_vintage?: string | null // ISO date
  retrieved_at: string // ISO datetime
}

export interface BlockAvailability {
  status: Availability
  reason?: UnavailabilityReason | null
}

export interface SurroundingStats {
  radius_m: number
  valid_pixels: number
  min?: number | null
  max?: number | null
  mean?: number | null
  std?: number | null
}

export interface LownessScores {
  micro?: number | null
  meso?: number | null
  macro?: number | null
  composite?: number | null
  lowness_class: LownessClass
}

export interface RoadContextBlock {
  block_type: 'road'
  road_name?: string | null
  osm_way_id?: number | null
  highway_class?: HighwayClass | null
  lanes?: number | null
  oneway?: boolean | null
  is_bridge?: boolean | null
  is_tunnel?: boolean | null
  maxspeed?: number | null
  offset_distance_m?: number | null
  grounding_confidence?: number | null
  provenance: Provenance
  availability: BlockAvailability
}

export interface ElevationContextBlock {
  block_type: 'elevation'
  elevation_pt?: number | null
  stats: SurroundingStats
  provenance: Provenance
  availability: BlockAvailability
}

export interface TerrainContextBlock {
  block_type: 'terrain'
  lowness: LownessScores
  provenance: Provenance
  availability: BlockAvailability
}

export type ContextBlock = RoadContextBlock | ElevationContextBlock | TerrainContextBlock

export interface QueryPoint {
  lat: number
  lon: number
  source_location?: string | null
}

export interface UrbanContext {
  query_point?: QueryPoint | null
  blocks: ContextBlock[]
}

// ───────────────────────── Knowledge (ADR-0004) ─────────────────────────

export type KnowledgeType = 'terrain_risk' | 'road_impact'
export type InferenceMechanism = 'rule' | 'llm'
export type EvidenceRefType = 'observation' | 'grounding' | 'context' | 'derived'
export type RoadActor = 'pedestrian' | 'non_motor_vehicle' | 'motor_vehicle'
export type RoadImpactLevel = 'low' | 'medium' | 'high' | 'severe' | 'uncertain'
export type EventSeverity = 'ordinary_puddle' | 'suspected_flood_significant' | 'uncertain'

export interface EvidenceRefBase {
  note?: string
}

export interface ObservationRef extends EvidenceRefBase {
  ref_type: 'observation'
  field_path: string
}

export interface GroundingRef extends EvidenceRefBase {
  ref_type: 'grounding'
  field_path: string
}

export interface ContextRef extends EvidenceRefBase {
  ref_type: 'context'
  block_type: string
  field_path: string
}

export interface DerivedRef extends EvidenceRefBase {
  ref_type: 'derived'
  rule_id: string
  value: string
  inputs: EvidenceRef[]
}

export type EvidenceRef =
  | ObservationRef | GroundingRef | ContextRef | DerivedRef

export interface KnowledgeItemCommon {
  statement: string
  confidence: Confidence
  mechanism: InferenceMechanism
  rule_id?: string | null
  evidence: EvidenceRef[]
}

export interface TerrainRiskKnowledge extends KnowledgeItemCommon {
  knowledge_type: 'terrain_risk'
  mechanism: 'rule' // 锁定 (Case C)
  lowness_class: LownessClass
  composite_tpi_m?: number | null
}

export interface RoadActorImpact {
  actor: RoadActor
  level: RoadImpactLevel
}

export interface RoadImpactKnowledge extends KnowledgeItemCommon {
  knowledge_type: 'road_impact'
  impacts: RoadActorImpact[]
}

export type KnowledgeItem = TerrainRiskKnowledge | RoadImpactKnowledge

export interface EventAssessment {
  severity: EventSeverity
  confidence: Confidence
  mechanism: InferenceMechanism
  reasoning: string
  evidence: EvidenceRef[]
}

export interface KnowledgeResult {
  knowledge_items: KnowledgeItem[]
  event_assessment: EventAssessment
  explanation: string
}

// ───────────────────────── 顶层信封 (ADR-0005) ─────────────────────────

export interface AnalysisResult {
  request_id: string
  observation: Observation
  grounding: GroundedEntity
  context: UrbanContext
  knowledge: KnowledgeResult
  timings: Record<string, number>
}

// ───────────────────────── SSE 事件载荷 ─────────────────────────

export type StageName = 'observation' | 'grounding' | 'context' | 'knowledge'

export interface SseThinking {
  delta: string
}

export interface SseStage {
  stage: StageName
  data: unknown // 该阶段输出模型（observation→Observation 等）
  duration_ms: number
}

export type ErrorCode =
  | 'unreadable_image' | 'vlm_provider_error' | 'vlm_json_invalid' | 'internal_error'

export interface SseError {
  code: ErrorCode
  message: string
  stage?: StageName | null
}
