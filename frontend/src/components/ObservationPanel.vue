<script setup lang="ts">
import { computed } from 'vue'
import SevTag from './SevTag.vue'
import { L, levelSeverity } from '../labels'
import type { Observation } from '../types'

const props = defineProps<{
  observation: Observation | null
  image: string
  arrived: boolean
}>()

const w = computed(() => props.observation?.waterlogging ?? null)
const depth = computed(() => w.value?.depth_estimate)
const cues = computed(() => w.value?.visual_cues)

const cueTags = computed(() => {
  const c = cues.value
  if (!c) return [] as { key: string; label: string }[]
  const out: { key: string; label: string }[] = []
  if (c.reflection_present) out.push({ key: 'reflection', label: '反光：' + L('reflection_type', c.reflection_type) })
  if (c.visible_water_boundary) out.push({ key: 'boundary', label: '可见水域边界' })
  if (c.visible_waterline) out.push({ key: 'waterline', label: '可见水线' })
  if (c.visible_ripple_or_wave) out.push({ key: 'ripple', label: '可见涟漪/波浪' })
  return out
})

function depthText(min?: number | null, max?: number | null, most?: number | null): string {
  const parts: string[] = []
  if (most != null) parts.push(`约 ${most} cm`)
  if (min != null && max != null && (min !== max)) parts.push(`范围 ${min}–${max} cm`)
  return parts.length ? parts.join(' · ') : '—'
}
</script>

<template>
  <template v-if="!arrived || !observation">
    <div class="placeholder">等待 Stage 1 · 我所见…</div>
  </template>

  <template v-else>
    <div v-if="image" class="card imgcard"><img class="hero" :src="image" alt="分析图片" /></div>

    <div class="card center">
      <SevTag :sev="w ? levelSeverity(w.waterlogging_level) : 'n'" size="large" effect="dark">
        {{ L('waterlogging_level', w?.waterlogging_level) }}
      </SevTag>
      <div class="muted sub2">
        {{ L('waterlogging_status', w?.status) }} · {{ L('surface_condition', w?.surface_condition) }} ·
        {{ L('visual_impact_hint', w?.visual_impact_hint) }}
      </div>
      <hr class="thin" />
      <div class="summary">{{ observation.observed_summary }}</div>
    </div>

    <div class="card">
      <h3>积水量化</h3>
      <div class="kv">
        <span class="k">深度估计</span>
        <span class="v">
          {{ depth ? depthText(depth.depth_cm.min, depth.depth_cm.max, depth.depth_cm.most_likely) : '—' }}
          <span class="muted small">（置信度 {{ L('overall_confidence', depth?.confidence) }}）</span>
        </span>
      </div>
      <div v-if="w && w.water_patches.length" class="kv">
        <span class="k">积水区域</span>
        <span class="v">
          <SevTag v-for="(p, i) in w.water_patches" :key="i" size="small" :sev="levelSeverity(p.waterlogging_level)">
            {{ L('patch_coverage', p.coverage) }} · {{ L('waterlogging_level', p.waterlogging_level) }}
          </SevTag>
        </span>
      </div>
    </div>

    <div class="card">
      <h3>视觉线索</h3>
      <div v-if="cueTags.length" class="cues">
        <SevTag v-for="c in cueTags" :key="c.key" size="small">{{ c.label }}</SevTag>
      </div>
      <div v-else class="muted small">无明显结构性视觉线索。</div>
      <div v-if="w && w.reference_objects.length" class="refs">
        <div v-for="(r, i) in w.reference_objects" :key="i" class="kv">
          <span class="k">参照物</span>
          <span class="v">{{ r.object }}<span class="muted small"> · {{ r.relation_to_water }}（{{ L('likelihood', r.reliability) }}）</span></span>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>可信度</h3>
      <div class="kv"><span class="k">总体置信度</span><span class="v">{{ L('overall_confidence', observation.overall_confidence) }}</span></div>
      <div class="kv"><span class="k">检出概率</span><span class="v">{{ Math.round((observation.presence_probability ?? 0) * 100) }}%</span></div>
      <div v-if="observation.visible_location_text" class="kv">
        <span class="k">画面 OSD 文字</span><span class="v">{{ observation.visible_location_text }}</span>
      </div>
    </div>
  </template>
</template>

<style scoped>
.imgcard {
  padding: 8px;
}
.hero {
  width: 100%;
  border-radius: var(--c-radius);
  display: block;
  border: 1px solid var(--c-border);
}
.center {
  text-align: center;
}
.sub2 {
  margin-top: 8px;
  font-size: 13px;
}
.summary {
  text-align: left;
  color: var(--c-text-2);
}
.cues {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.refs {
  margin-top: 10px;
  border-top: 1px dashed var(--c-border);
  padding-top: 8px;
}
.small {
  font-size: 12px;
}
</style>
