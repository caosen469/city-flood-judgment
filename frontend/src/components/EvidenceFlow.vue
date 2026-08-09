<script setup lang="ts">
import { computed } from 'vue'
import { L } from '../labels'
import type {
  ContextBlock, GroundedEntity, KnowledgeItem, KnowledgeResult, Observation, UrbanContext,
} from '../types'

const props = defineProps<{
  observation: Observation | null
  grounding: GroundedEntity | null
  context: UrbanContext | null
  knowledge: KnowledgeResult | null
}>()

interface Seg {
  type: 'observation' | 'grounding' | 'context' | 'derived' | 'assessment'
  label: string
  lines: string[]
}

const COLORS: Record<Seg['type'], string> = {
  observation: '#9c27b0',
  grounding: '#7b6f5e',
  context: '#6b7f4e',
  derived: '#b07b2e',
  assessment: '#9a4a3a',
}

function truncate(s: string, n = 34): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

const segs = computed<Seg[]>(() => {
  const out: Seg[] = []
  const o = props.observation
  const w = o?.waterlogging
  if (w) {
    out.push({
      type: 'observation',
      label: '画面观察',
      lines: [
        `${L('waterlogging_status', w.status)} · ${L('waterlogging_level', w.waterlogging_level)}`,
        `影响 ${L('visual_impact_hint', w.visual_impact_hint)}`,
      ],
    })
  }

  const g = props.grounding
  if (g && (g.status === 'grounded' || g.status === 'ambiguous') && g.best_match) {
    out.push({
      type: 'grounding',
      label: '道路定位',
      lines: [
        g.best_match.road_name ?? g.best_match.osm_way_id,
        `${g.best_match.highway} · 偏移 ${g.best_match.match_distance_m.toFixed(1)} m`,
      ],
    })
  }

  const blocks: ContextBlock[] = props.context?.blocks ?? []
  const terr = blocks.find((b) => b.block_type === 'terrain') as Extract<ContextBlock, { block_type: 'terrain' }> | undefined
  const elev = blocks.find((b) => b.block_type === 'elevation') as Extract<ContextBlock, { block_type: 'elevation' }> | undefined
  const lines: string[] = []
  if (terr && terr.availability.status === 'available') {
    lines.push(`TPI 复合 ${terr.lowness.composite ?? '—'} m → ${L('lowness_class', terr.lowness.lowness_class)}`)
  }
  if (elev && elev.availability.status === 'available') {
    lines.push(`点高程 ${elev.elevation_pt ?? '—'} m（mean ${elev.stats.mean ?? '—'}）`)
  }
  if (lines.length) out.push({ type: 'context', label: '城市数据', lines })

  for (const it of (props.knowledge?.knowledge_items ?? []) as KnowledgeItem[]) {
    const label =
      it.mechanism === 'rule'
        ? `规则派生 · ${it.rule_id}`
        : `模型推断 · ${L('knowledge_type', it.knowledge_type)}`
    out.push({ type: 'derived', label, lines: [truncate(it.statement)] })
  }

  const ea = props.knowledge?.event_assessment
  if (ea) {
    out.push({
      type: 'assessment',
      label: '事件判定',
      lines: [L('event_severity', ea.severity), `置信度 ${L('overall_confidence', ea.confidence)}`],
    })
  }

  return out
})
</script>

<template>
  <div class="card">
    <h3>🔗 完整证据链</h3>
    <div v-if="segs.length" class="flow">
      <template v-for="(s, i) in segs" :key="i">
        <div class="fnode" :style="{ borderLeftColor: COLORS[s.type] }">
          <div class="ftype" :style="{ color: COLORS[s.type] }">{{ s.label }}</div>
          <div v-for="(ln, j) in s.lines" :key="j" class="fline">{{ ln }}</div>
        </div>
        <div v-if="i < segs.length - 1" class="farrow">→</div>
      </template>
    </div>
    <div v-else class="muted">暂无可追溯证据。</div>
  </div>
</template>
