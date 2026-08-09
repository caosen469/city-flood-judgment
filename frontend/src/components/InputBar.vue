<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'

interface LocationInput {
  lat?: number
  lon?: number
  road_name: string
  raw_text: string
}

const props = defineProps<{
  imageFile: File | null
  imageUrl: string
  location: LocationInput
  displayImage: string
  status: 'idle' | 'streaming' | 'done' | 'error'
}>()

const emit = defineEmits<{
  'update:imageFile': [File | null]
  'update:imageUrl': [string]
  'update:location': [LocationInput]
  analyze: []
}>()

const busy = computed(() => props.status === 'streaming')

function onFile(file: File | null) {
  emit('update:imageFile', file)
  if (file) emit('update:imageUrl', '')
}
function onUrl(v: string) {
  emit('update:imageUrl', v)
  if (v) emit('update:imageFile', null)
}
function patch(p: Partial<LocationInput>) {
  emit('update:location', { ...props.location, ...p })
}

// el-upload 的自定义选择（不真正上传，只取 File）
function pickFile(file: File) {
  onFile(file)
  return false // 阻止 element-plus 自动上传
}

function trigger() {
  if (!props.imageFile && !props.imageUrl) {
    ElMessage.warning('请先提供图片（上传文件或填写图片 URL）。')
    return
  }
  emit('analyze')
}
</script>

<template>
  <div class="card inputbar">
    <el-upload
      :show-file-list="false"
      :auto-upload="true"
      :before-upload="pickFile"
      accept="image/*"
    >
      <div class="thumb-wrap">
        <img v-if="displayImage" class="thumb" :src="displayImage" alt="待分析图片" />
        <div v-else class="thumb empty">＋ 上传图片</div>
      </div>
    </el-upload>

    <div class="fields">
      <div class="line">
        <span class="lab">图片</span>
        <span v-if="imageFile" class="text-2">{{ imageFile.name }} <span class="muted">（已上传）</span></span>
        <el-input
          v-else
          :model-value="imageUrl"
          size="small"
          placeholder="或填图片 URL（http…）"
          style="max-width: 320px"
          @update:model-value="onUrl"
        />
      </div>

      <div class="line">
        <span class="lab">位置</span>
        <el-input
          :model-value="location.road_name"
          size="small"
          placeholder="道路名（如 进港大道）"
          style="width: 180px"
          @update:model-value="(v: string) => patch({ road_name: v })"
        />
        <el-input
          :model-value="location.raw_text"
          size="small"
          placeholder="自由地名 / 画面 OSD 文字"
          style="width: 200px"
          @update:model-value="(v: string) => patch({ raw_text: v })"
        />
        <span class="muted small">经纬度（可选）</span>
        <el-input-number
          :model-value="location.lat"
          size="small"
          :controls="false"
          placeholder="纬度"
          style="width: 96px"
          @update:model-value="(v: number | undefined) => patch({ lat: v ?? undefined })"
        />
        <el-input-number
          :model-value="location.lon"
          size="small"
          :controls="false"
          placeholder="经度"
          style="width: 96px"
          @update:model-value="(v: number | undefined) => patch({ lon: v ?? undefined })"
        />
        <span class="muted small hint">不填位置 → grounding 未解析的降级路径</span>
      </div>
    </div>

    <el-button type="primary" :loading="busy" @click="trigger">
      {{ busy ? '分析中…' : '🔍 触发分析' }}
    </el-button>
  </div>
</template>

<style scoped>
.inputbar {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  border-top: none; /* 输入条不要金线 */
  border: 1px solid var(--c-border);
}
.thumb-wrap {
  cursor: pointer;
}
.thumb {
  width: 72px;
  height: 72px;
  border-radius: var(--c-radius);
  object-fit: cover;
  border: 1px solid var(--c-border);
  display: block;
}
.thumb.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-3);
  background: #faf6ec;
  font-size: 12px;
}
.fields {
  flex: 1;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.lab {
  color: var(--c-text-3);
  font-size: 13px;
  min-width: 32px;
}
.small {
  font-size: 12px;
}
.hint {
  margin-left: 4px;
}
</style>
