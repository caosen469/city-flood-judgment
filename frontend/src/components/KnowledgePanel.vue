<script setup lang="ts">
import { computed } from 'vue'
import SevTag from './SevTag.vue'
import EvidenceFlow from './EvidenceFlow.vue'
import { L, impactLevelColor, severityColor } from '../labels'
import type {
  EvidenceRef, GroundedEntity, KnowledgeItem, KnowledgeResult, Observation, UrbanContext,
} from '../types'

const props = defineProps<{
  knowledge: KnowledgeResult | null
  observation: Observation | null
  grounding: GroundedEntity | null
  context: UrbanContext | null
  arrived: boolean
}>()

const ea = computed(() => props.knowledge?.event_assessment ?? null)

function evNote(e: EvidenceRef): string {
  if (e.note && e.note.trim()) return e.note
  // 回退：用 ref 结构拼一个简短依据
  if (e.ref_type === 'context') return `${e.block_type}.${e.field_path}`
  if (e.ref_type === 'derived') return `${e.rule_id} = ${e.value}`
  return e.field_path
}

function mechSev(m?: string): 's' | 'w' {
  return m === 'rule' ? 's' : 'w'
}

function itemIcon(it: KnowledgeItem): string {
  return it.knowledge_type === 'terrain_risk' ? '⛰' : '🚗'
}
</script>

<template>
  <template v-if="!arrived || !knowledge">
    <div class="placeholder">等待 Stage 3 · 这意味着…</div>
  </template>

  <template v-else>
    <!-- 事件判定 banner -->
    <div v-if="ea" class="assess-banner" :class="ea.severity === 'uncertain' ? 'sev-uncertain' : ea.severity === 'ordinary_puddle' ? 'sev-ordinary' : ''">
      <div class="sev">
        <SevTag :sev="severityColor(ea.severity)" size="large" effect="dark">事件判定：{{ L('event_severity', ea.severity) }}</SevTag>
        <span class="muted small">{{ L('inference_mechanism', ea.mechanism) }} · 置信度 {{ L('overall_confidence', ea.confidence) }}</span>
      </div>
      <div class="muted reasoning">{{ ea.reasoning }}</div>
    </div>

    <!-- 知识条目 -->
    <div v-if="knowledge.knowledge_items.length">
      <div v-for="(it, i) in knowledge.knowledge_items" :key="i" class="mini">
        <h4>
          {{ itemIcon(it) }} {{ L('knowledge_type', it.knowledge_type) }}
          <SevTag :sev="mechSev(it.mechanism)" size="small" style="margin-left:auto">{{ L('inference_mechanism', it.mechanism) }}{{ it.rule_id ? ` · ${it.rule_id}` : '' }}</SevTag>
        </h4>
        <div class="stmt">{{ it.statement }}</div>

        <!-- RoadImpact：impacts 列表 -->
        <div v-if="it.knowledge_type === 'road_impact'" class="impacts">
          <span v-for="(imp, j) in it.impacts" :key="j" class="impact">
            <span class="muted small">{{ L('road_actor', imp.actor) }}</span>
            <SevTag size="small" :sev="impactLevelColor(imp.level)">{{ L('road_impact_level', imp.level) }}</SevTag>
          </span>
        </div>
        <!-- TerrainRisk：低洼等级 + composite -->
        <div v-else class="kv">
          <span class="k">低洼</span>
          <span class="v"><SevTag size="small" sev="w">{{ L('lowness_class', it.lowness_class) }}</SevTag><span class="muted small"> · TPI 复合 {{ it.composite_tpi_m ?? '—' }} m</span></span>
        </div>

        <div class="ev">
          <span v-for="(e, k) in it.evidence" :key="k" class="evref">
            <span class="evtype muted">{{ L('evidence_ref_type', e.ref_type) }}</span> {{ evNote(e) }}
          </span>
        </div>
        <div class="muted small" style="margin-top:4px">置信度 {{ L('overall_confidence', it.confidence) }}</div>
      </div>
    </div>
    <div v-else class="mini unavail">
      <div class="uh">（资格门关闭：依赖的 context/grounding 缺失，本轮无知识条目产出）</div>
    </div>

    <!-- 综合解释 -->
    <div class="card"><h3>📝 综合解释</h3><div class="muted">{{ knowledge.explanation }}</div></div>

    <!-- 完整证据链 -->
    <EvidenceFlow
      :observation="observation"
      :grounding="grounding"
      :context="context"
      :knowledge="knowledge"
    />
  </template>
</template>

<style scoped>
.reasoning {
  margin-top: 6px;
}
.stmt {
  margin: 2px 0 6px;
}
.impacts {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 4px 0;
}
.impact {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ev {
  margin-top: 6px;
  font-size: 12px;
}
.evref {
  display: inline-block;
  background: #f0e9d8;
  border: 1px solid var(--c-border);
  border-radius: 3px;
  padding: 1px 7px;
  margin: 2px 4px 2px 0;
  color: var(--c-text-2);
}
.evtype {
  font-size: 11px;
}
.small {
  font-size: 12px;
}
</style>
