<script setup lang="ts">
import { computed, ref } from 'vue'
import InputBar from './components/InputBar.vue'
import ThinkingPanel from './components/ThinkingPanel.vue'
import ObservationPanel from './components/ObservationPanel.vue'
import ContextPanel from './components/ContextPanel.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import { useAnalysisStream } from './composables/useAnalysisStream'
import type { Observation, GroundedEntity, UrbanContext, KnowledgeResult } from './types'

const stream = useAnalysisStream()

// —— 输入态 ——
const imageFile = ref<File | null>(null)
const imageUrl = ref<string>('')
const locationInput = ref<{ lat?: number; lon?: number; road_name: string; raw_text: string }>({
  lat: undefined,
  lon: undefined,
  road_name: '',
  raw_text: '',
})

// 供各面板展示的图片（对象 URL 或远程 URL）
const displayImage = computed(() => {
  if (imageFile.value) return URL.createObjectURL(imageFile.value)
  return imageUrl.value || ''
})

// —— 触发分析 ——
async function onAnalyze() {
  // 解析"经纬度"自由文本（兼容 "lat,lon" 输入），否则保留数值字段
  const loc = { ...locationInput.value }
  await stream.analyze({
    imageFile: imageFile.value,
    imageUrl: imageUrl.value || null,
    location: loc,
  })
}

// —— 渐进式展示：优先用 done 聚合，否则用已到达的 stage 局部结果 ——
const observation = computed<Observation | null>(
  () => stream.result?.observation ?? (stream.stages.observation.data as Observation | null),
)
const grounding = computed<GroundedEntity | null>(
  () => stream.result?.grounding ?? (stream.stages.grounding.data as GroundedEntity | null),
)
const context = computed<UrbanContext | null>(
  () => stream.result?.context ?? (stream.stages.context.data as UrbanContext | null),
)
const knowledge = computed<KnowledgeResult | null>(
  () => stream.result?.knowledge ?? (stream.stages.knowledge.data as KnowledgeResult | null),
)

const isMock = import.meta.env.VITE_API_BASE === 'mock'
</script>

<template>
  <div class="topbar">
    <span class="brand serif">🌊 积水研判 Demo</span>
    <span class="muted sub">南沙 · 从"看到水"到"理解这是什么样的积水事件"</span>
    <span class="muted tagline">
      <template v-if="isMock">MOCK 模式（未连后端）</template>
      <template v-else>连接 FastAPI · /analyze/stream</template>
    </span>
  </div>

  <div class="wrap">
    <InputBar
      v-model:imageFile="imageFile"
      v-model:imageUrl="imageUrl"
      v-model:location="locationInput"
      :display-image="displayImage"
      :status="stream.status"
      @analyze="onAnalyze"
    />

    <ThinkingPanel
      v-if="stream.status === 'streaming' || (stream.status === 'done' && stream.thinking)"
      :thinking="stream.thinking"
      :stages="stream.stages"
    />

    <div v-if="stream.error" class="card err">
      <h3>分析失败</h3>
      <div class="kv"><span class="k">错误码</span><span class="v">{{ stream.error.code }}</span></div>
      <div class="kv"><span class="k">阶段</span><span class="v">{{ stream.error.stage ?? '—' }}</span></div>
      <div class="muted">{{ stream.error.message }}</div>
    </div>

    <div class="cols3">
      <section>
        <div class="colhead"><span class="badge">1</span><b>我所见 · What I See</b></div>
        <ObservationPanel
          :observation="observation"
          :image="displayImage"
          :arrived="stream.stages.observation.arrived"
        />
      </section>

      <section>
        <div class="colhead"><span class="badge">2</span><b>我所知 · What I Know</b></div>
        <ContextPanel
          :grounding="grounding"
          :context="context"
          :arrived="stream.stages.grounding.arrived && stream.stages.context.arrived"
        />
      </section>

      <section>
        <div class="colhead"><span class="badge">3</span><b>这意味着 · What It Means</b></div>
        <KnowledgePanel
          :knowledge="knowledge"
          :observation="observation"
          :grounding="grounding"
          :context="context"
          :arrived="stream.stages.knowledge.arrived"
        />
      </section>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
  padding: 10px 24px;
  display: flex;
  align-items: baseline;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: 9;
}
.topbar .brand {
  font-size: 17px;
  font-weight: 700;
  color: var(--c-primary);
}
.topbar .sub {
  font-size: 13px;
}
.topbar .tagline {
  margin-left: auto;
  font-size: 12px;
}
.wrap {
  padding: 18px 24px 80px;
  max-width: 1680px;
  margin: 0 auto;
}
.cols3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1.05fr;
  gap: 18px;
  align-items: start;
  margin-top: 16px;
}
.err {
  border-top-color: var(--c-danger);
}
@media (max-width: 1180px) {
  .cols3 {
    grid-template-columns: 1fr;
  }
}
</style>
