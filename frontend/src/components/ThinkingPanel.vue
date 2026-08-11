<script setup lang="ts">
import { computed } from 'vue'
import type { StageName } from '../types'
import { L } from '../labels'

type StageState = { arrived: boolean; durationMs: number | null }

const props = defineProps<{
  thinking: string
  stages: Record<StageName, StageState>
}>()

const ORDER: StageName[] = ['observation', 'grounding', 'context', 'knowledge']

const steps = computed(() =>
  ORDER.map((k) => ({
    key: k,
    label: L('stage', k),
    arrived: props.stages[k].arrived,
    ms: props.stages[k].durationMs,
  })),
)
</script>

<template>
  <div class="card think">
    <div class="steps">
      <template v-for="(s, i) in steps" :key="s.key">
        <div class="step" :class="{ done: s.arrived }">
          <div class="n">{{ i + 1 }}</div>
          <div class="meta">
            <div>{{ s.label }}</div>
            <div class="muted xsmall">{{ s.arrived ? `${s.ms ?? 0} ms` : '…' }}</div>
          </div>
        </div>
        <div v-if="i < steps.length - 1" class="bar" :class="{ done: s.arrived }" />
      </template>
    </div>

    <div v-if="thinking" class="think-text">
      <span class="think-label muted">💭 思考中</span>
      <pre>{{ thinking }}</pre>
    </div>
  </div>
</template>

<style scoped>
.think {
  border-top-color: var(--c-info);
}
.steps {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.step {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--c-text-3);
}
.step.done {
  color: var(--c-success);
}
.step .n {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid currentColor;
  font-size: 12px;
  font-weight: 600;
  font-family: -apple-system, sans-serif;
}
.step.done .n {
  background: var(--c-success);
  color: #fff;
  border-color: var(--c-success);
}
.step .meta {
  font-size: 13px;
}
.bar {
  width: 32px;
  height: 2px;
  background: var(--c-border);
  margin: 0 8px;
}
.bar.done {
  background: var(--c-success);
}
.xsmall {
  font-size: 11px;
}
.think-text {
  margin-top: 10px;
  border-top: 1px dashed var(--c-border);
  padding-top: 8px;
}
.think-label {
  font-size: 12px;
}
.think-text pre {
  margin: 4px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Georgia, "Songti SC", serif;
  font-size: 13px;
  color: var(--c-text-2);
  line-height: 1.7;
  max-height: 160px;
  overflow-y: auto;
}
</style>
