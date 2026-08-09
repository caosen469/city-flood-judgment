<script setup lang="ts">
import { computed } from 'vue'
import MapView from './MapView.vue'
import SevTag from './SevTag.vue'
import { L } from '../labels'
import type { ContextBlock, GroundedEntity, UrbanContext } from '../types'

const props = defineProps<{
  grounding: GroundedEntity | null
  context: UrbanContext | null
  arrived: boolean
}>()

// 地图取点：优先挂接垂足点，其次查询点。
const mapLat = computed(() => props.grounding?.best_match?.match_point.lat ?? props.grounding?.query_point?.lat ?? null)
const mapLon = computed(() => props.grounding?.best_match?.match_point.lon ?? props.grounding?.query_point?.lon ?? null)
const offsetM = computed(() => props.grounding?.best_match?.match_distance_m ?? null)
const roadName = computed(() => props.grounding?.best_match?.road_name ?? null)

function blocks(): ContextBlock[] {
  return props.context?.blocks ?? []
}
const road = computed(() => blocks().find((b) => b.block_type === 'road') as Extract<ContextBlock, { block_type: 'road' }> | undefined)
const elev = computed(() => blocks().find((b) => b.block_type === 'elevation') as Extract<ContextBlock, { block_type: 'elevation' }> | undefined)
const terr = computed(() => blocks().find((b) => b.block_type === 'terrain') as Extract<ContextBlock, { block_type: 'terrain' }> | undefined)

const grounded = computed(() => props.grounding?.status === 'grounded' || props.grounding?.status === 'ambiguous')

function availSev(status?: string): 's' | 'w' | 'n' {
  if (status === 'available') return 's'
  if (status === 'uncertain') return 'n'
  return 'w'
}
function provenanceText(b: ContextBlock): string {
  const p = b.provenance
  const src = L('context_source', p.source)
  const v = p.data_vintage ? `（${p.data_vintage}）` : ''
  return `来源：${src}${v}`
}
</script>

<template>
  <template v-if="!arrived || (!grounding && !context)">
    <div class="placeholder">等待 Stage 2 · 我所知…</div>
  </template>

  <template v-else>
    <div class="card mapcard"><MapView :lat="mapLat" :lon="mapLon" :offset-m="offsetM" :road-name="roadName" /></div>

    <div class="card">
      <h3>道路挂接 · Grounding</h3>
      <div class="kv">
        <span class="k">状态</span>
        <span class="v">
          <SevTag :sev="grounded ? 's' : 'w'" size="small">{{ L('grounding_status', grounding?.status) }}</SevTag>
          <span v-if="grounding" class="muted small"> · 来源 {{ L('location_source', grounding.source) }}</span>
        </span>
      </div>
      <template v-if="grounding && grounding.best_match">
        <div class="kv"><span class="k">挂接路段</span><span class="v"><b>{{ grounding.best_match.road_name ?? '（无名）' }}</b></span></div>
        <div class="kv"><span class="k">道路等级</span><span class="v">{{ grounding.best_match.highway }}<span class="muted small"> · 偏移 {{ grounding.best_match.match_distance_m.toFixed(1) }} m · 置信度 {{ L('overall_confidence', grounding.best_match.confidence) }}</span></span></div>
        <div class="kv">
          <span class="k">其他候选</span>
          <span class="v muted small">
            <span v-for="(c, i) in (grounding?.candidates ?? []).filter((x) => x !== grounding?.best_match)" :key="i">
              {{ c.road_name ?? c.osm_way_id }} ({{ c.match_distance_m.toFixed(0) }}m){{ i < (grounding?.candidates.length ?? 0) - 2 ? '、' : '' }}
            </span>
            <span v-if="(grounding?.candidates.length ?? 0) <= 1">—</span>
          </span>
        </div>
      </template>
      <div v-else-if="grounding" class="uh">⚠ {{ L('unresolved_reason', grounding.unresolved_reason) }}</div>
    </div>

    <!-- Road block -->
    <div class="mini" :class="{ unavail: road && road.availability.status !== 'available' }">
      <h4>{{ L('block_type', 'road') }}
        <SevTag :sev="availSev(road?.availability.status)" size="small" style="margin-left:auto">{{ L('availability', road?.availability.status) }}</SevTag>
      </h4>
      <template v-if="road && road.availability.status === 'available'">
        <div class="kv"><span class="k">道路</span><span class="v">{{ road.road_name ?? '—' }} · {{ L('highway_class', road.highway_class) }} · {{ road.lanes ?? '?' }} 车道</span></div>
        <div class="kv"><span class="k">属性</span><span class="v muted small">{{ road.is_bridge ? '桥 ' : '' }}{{ road.is_tunnel ? '隧 ' : '' }}{{ road.oneway ? '单行 ' : '' }}{{ road.maxspeed ? `限速 ${road.maxspeed}` : '' }} · 偏移 {{ road.offset_distance_m?.toFixed(1) ?? '?' }} m</span></div>
        <div class="muted small src">{{ provenanceText(road) }}</div>
      </template>
      <div v-else class="uh">⚠ {{ road ? L('unavailability_reason', road.availability.reason) : '无道路数据' }}</div>
    </div>

    <!-- Elevation block -->
    <div class="mini" :class="{ unavail: elev && elev.availability.status !== 'available' }">
      <h4>{{ L('block_type', 'elevation') }}
        <SevTag :sev="availSev(elev?.availability.status)" size="small" style="margin-left:auto">{{ L('availability', elev?.availability.status) }}</SevTag>
      </h4>
      <template v-if="elev && elev.availability.status === 'available'">
        <div class="kv"><span class="k">点高程</span><span class="v">{{ elev.elevation_pt ?? '—' }} m</span></div>
        <div class="kv"><span class="k">邻域统计</span><span class="v muted small">min {{ elev.stats.min ?? '—' }} / max {{ elev.stats.max ?? '—' }} / mean {{ elev.stats.mean ?? '—' }} / σ {{ elev.stats.std ?? '—' }}（{{ elev.stats.valid_pixels }} 像素）</span></div>
        <div class="muted small src">{{ provenanceText(elev) }}</div>
      </template>
      <div v-else class="uh">⚠ {{ elev ? L('unavailability_reason', elev.availability.reason) : '无高程数据' }}</div>
    </div>

    <!-- Terrain block -->
    <div class="mini" :class="{ unavail: terr && terr.availability.status !== 'available' }">
      <h4>{{ L('block_type', 'terrain') }}
        <SevTag :sev="availSev(terr?.availability.status)" size="small" style="margin-left:auto">{{ L('availability', terr?.availability.status) }}</SevTag>
      </h4>
      <template v-if="terr && terr.availability.status === 'available'">
        <div class="kv"><span class="k">低洼等级</span><span class="v"><SevTag size="small" :sev="terr.lowness.lowness_class === 'significantly_low' ? 'd' : terr.lowness.lowness_class === 'moderately_low' ? 'w' : 's'">{{ L('lowness_class', terr.lowness.lowness_class) }}</SevTag></span></div>
        <div class="kv"><span class="k">多尺度 TPI</span><span class="v muted small">micro {{ terr.lowness.micro ?? '—' }} / meso {{ terr.lowness.meso ?? '—' }} / macro {{ terr.lowness.macro ?? '—' }} / 复合 {{ terr.lowness.composite ?? '—' }} m</span></div>
        <div class="muted small src">{{ provenanceText(terr) }}</div>
      </template>
      <div v-else class="uh">⚠ {{ terr ? L('unavailability_reason', terr.availability.reason) : '无地形数据' }}</div>
    </div>
  </template>
</template>

<style scoped>
.mapcard {
  padding: 8px;
}
.src {
  margin-top: 4px;
}
</style>
