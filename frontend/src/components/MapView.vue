<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'

const props = defineProps<{
  lat?: number | null
  lon?: number | null
  offsetM?: number | null
  roadName?: string | null
  label?: string
}>()

const host = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let pointMarker: L.CircleMarker | null = null
let ring: L.Circle | null = null

const FALLBACK_CENTER: L.LatLngExpression = [22.7707, 113.5412] // 南沙中心

function hasPoint() {
  return props.lat != null && props.lon != null && Number.isFinite(props.lat) && Number.isFinite(props.lon)
}

function mount() {
  if (!host.value || map) return
  map = L.map(host.value, {
    center: hasPoint() ? [props.lat!, props.lon!] : FALLBACK_CENTER,
    zoom: hasPoint() ? 16 : 11,
    scrollWheelZoom: true,
  })
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(map)
  paint()
  // grid 容器内首帧尺寸常为 0，下一帧重算。
  setTimeout(() => map?.invalidateSize(), 60)
}

function paint() {
  if (!map) return
  if (pointMarker) {
    pointMarker.remove()
    pointMarker = null
  }
  if (ring) {
    ring.remove()
    ring = null
  }
  if (!hasPoint()) return
  const latlng: L.LatLngExpression = [props.lat!, props.lon!]
  pointMarker = L.circleMarker(latlng, {
    radius: 8,
    color: '#fff',
    weight: 3,
    fillColor: '#9a4a3a',
    fillOpacity: 0.95,
  }).addTo(map)
  const offset = props.offsetM ?? 0
  if (offset > 0) {
    ring = L.circle(latlng, {
      radius: offset,
      color: '#9a7b3f',
      weight: 1,
      dashArray: '4 4',
      fillOpacity: 0.06,
    }).addTo(map)
  }
  const road = props.roadName ? `挂接：${props.roadName}` : '查询点'
  pointMarker.bindPopup(`${props.label ?? road}${offset > 0 ? `<br/>偏移 ≈ ${offset.toFixed(1)} m` : ''}`)
  map.setView(latlng, Math.max(map.getZoom(), 15), { animate: true })
}

onMounted(mount)
onUnmounted(() => {
  map?.remove()
  map = null
})

watch(
  () => [props.lat, props.lon, props.offsetM, props.roadName],
  () => {
    if (map) paint()
  },
)
</script>

<template>
  <div class="map-wrap">
    <div ref="host" class="map" />
    <div v-if="!hasPoint()" class="no-point">⚠ 无位置 · 跳过道路挂接与城市数据</div>
    <div v-else-if="roadName" class="map-tag">OSM · {{ roadName }}<span v-if="offsetM"> · 偏移 {{ offsetM.toFixed(1) }} m</span></div>
  </div>
</template>

<style scoped>
.map-wrap {
  position: relative;
}
.map {
  width: 100%;
  height: 220px;
  border-radius: var(--c-radius);
  border: 1px solid var(--c-border);
  z-index: 0;
}
.no-point {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-3);
  background: #faf6ec;
  border-radius: var(--c-radius);
}
.map-tag {
  position: absolute;
  right: 6px;
  bottom: 6px;
  background: rgba(255, 253, 248, 0.9);
  border: 1px solid var(--c-border);
  border-radius: 3px;
  padding: 1px 7px;
  font-size: 11px;
  color: var(--c-text-2);
  z-index: 1;
}
</style>
