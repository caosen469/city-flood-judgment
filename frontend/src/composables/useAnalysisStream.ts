// SSE 客户端，消费 POST /analyze/stream（multipart/form-data）。
// 事件序列：thinking* → stage×4 → done | error（见 ADR-0005 / openapi.yaml）。
//
// 注意：浏览器原生 EventSource 只能 GET、不能发 multipart，故这里用 fetch +
// ReadableStream 手写 SSE 解析器（event:\ndata:\n\n 分帧）。

import { reactive, ref } from 'vue'
import type {
  AnalysisResult, GroundedEntity, KnowledgeResult, Observation, SseError,
  SseStage, SseThinking, StageName, UrbanContext,
} from '../types'

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error'

export interface StageState {
  arrived: boolean
  durationMs: number | null
  // 该阶段输出模型（observation→Observation 等）。unknown 因为四阶段类型不同。
  data: Observation | GroundedEntity | UrbanContext | KnowledgeResult | null
}

export interface AnalysisStream {
  status: StreamStatus
  thinking: string // 累计的 reasoning_content 片段
  stages: Record<StageName, StageState>
  result: AnalysisResult | null // done 事件携带的完整结果（权威聚合）
  error: SseError | null
  /** 触发一次分析。返回最终结果或抛出错误。 */
  analyze: (req: AnalyzeRequest, signal?: AbortSignal) => Promise<void>
  reset: () => void
}

export interface AnalyzeRequest {
  imageFile?: File | null
  imageUrl?: string | null
  location?: {
    lat?: number | null
    lon?: number | null
    road_name?: string | null
    raw_text?: string | null
  }
}

const STAGE_ORDER: StageName[] = ['observation', 'grounding', 'context', 'knowledge']

function freshStages(): Record<StageName, StageState> {
  return {
    observation: { arrived: false, durationMs: null, data: null },
    grounding: { arrived: false, durationMs: null, data: null },
    context: { arrived: false, durationMs: null, data: null },
    knowledge: { arrived: false, durationMs: null, data: null },
  }
}

/** 构造 multipart/form-data 请求体（flat 字段：image/image_url + lat/lon/road_name/raw_text）。 */
function buildForm(req: AnalyzeRequest): FormData {
  const fd = new FormData()
  if (req.imageFile) {
    fd.append('image', req.imageFile)
  } else if (req.imageUrl) {
    fd.append('image_url', req.imageUrl)
  } else {
    throw new Error('必须提供图片（文件或 URL）。')
  }
  const loc = req.location ?? {}
  if (loc.lat != null && loc.lon != null) {
    fd.append('lat', String(loc.lat))
    fd.append('lon', String(loc.lon))
  }
  if (loc.road_name && loc.road_name.trim()) fd.append('road_name', loc.road_name.trim())
  if (loc.raw_text && loc.raw_text.trim()) fd.append('raw_text', loc.raw_text.trim())
  return fd
}

interface ParsedEvent {
  event: string
  data: string
}

/** 从流式文本缓冲增量解析 SSE 事件。返回 [已就绪的事件列表, 剩余未闭合缓冲]。 */
function parseSseChunk(buffer: string): [ParsedEvent[], string] {
  const events: ParsedEvent[] = []
  // 事件以空行（\n\n）分隔。
  let sep = buffer.indexOf('\n\n')
  while (sep !== -1) {
    const raw = buffer.slice(0, sep)
    buffer = buffer.slice(sep + 2)
    const lines = raw.split('\n')
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    if (dataLines.length) events.push({ event, data: dataLines.join('\n') })
    sep = buffer.indexOf('\n\n')
  }
  return [events, buffer]
}

function emptyStreamState() {
  return {
    status: 'idle' as StreamStatus,
    thinking: '',
    stages: freshStages(),
    result: null as AnalysisResult | null,
    error: null as SseError | null,
  }
}

export function useAnalysisStream(): AnalysisStream {
  const state = reactive(emptyStreamState())
  const aborter = ref<AbortController | null>(null)

  function reset() {
    aborter.value?.abort()
    Object.assign(state, emptyStreamState())
  }

  async function analyze(req: AnalyzeRequest, signal?: AbortSignal) {
    reset()
    state.status = 'streaming'

    const mode = import.meta.env.VITE_API_BASE
    const useMock = mode === 'mock'

    if (useMock) {
      // 开发用 mock：不连后端，模拟真实 SSE 时序与真实 schema 形状。
      const { emitMockStream } = await import('./mockStream')
      await emitMockStream(state, req, signal)
      return
    }

    const ctrl = new AbortController()
    aborter.value = ctrl
    if (signal) signal.addEventListener('abort', () => ctrl.abort())

    const resp = await fetch('/analyze/stream', {
      method: 'POST',
      body: buildForm(req),
      signal: ctrl.signal,
    })
    if (!resp.ok || !resp.body) {
      // 非流式错误（如 422/503/502），body 可能是 JSON Error。
      let errBody: SseError = { code: 'internal_error', message: `HTTP ${resp.status}` }
      try {
        const j = await resp.json()
        errBody = {
          code: j.code ?? 'internal_error',
          message: j.message ?? errBody.message,
          stage: j.stage ?? null,
        }
      } catch { /* 非 JSON，保留默认 */ }
      state.error = errBody
      state.status = 'error'
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const [events, rest] = parseSseChunk(buffer)
        buffer = rest
        for (const ev of events) handleEvent(ev.event, ev.data)
      }
      // 流自然结束（未收到 done/error）—— 若已有 stage 数据则视作完成。
      if (state.status === 'streaming' && state.stages.knowledge.arrived) {
        state.status = 'done'
      }
    } catch (e) {
      if (ctrl.signal.aborted) return
      state.error = { code: 'internal_error', message: (e as Error).message }
      state.status = 'error'
    }
  }

  function handleEvent(event: string, data: string) {
    let payload: unknown
    try {
      payload = JSON.parse(data)
    } catch {
      return // 忽略无法解析的帧
    }
    if (event === 'thinking') {
      const t = payload as SseThinking
      if (t.delta) state.thinking += t.delta
    } else if (event === 'stage') {
      const s = payload as SseStage
      const name = s.stage as StageName
      if (STAGE_ORDER.includes(name)) {
        state.stages[name] = { arrived: true, durationMs: s.duration_ms, data: s.data as never }
      }
    } else if (event === 'done') {
      state.result = payload as AnalysisResult
      // done 是权威聚合：用它回填各阶段 data（防止丢帧）。
      if (state.result) {
        state.stages.observation.data = state.result.observation
        state.stages.grounding.data = state.result.grounding
        state.stages.context.data = state.result.context
        state.stages.knowledge.data = state.result.knowledge
        STAGE_ORDER.forEach((n) => (state.stages[n].arrived = true))
      }
      state.status = 'done'
    } else if (event === 'error') {
      state.error = payload as SseError
      state.status = 'error'
    }
  }

  // 把方法挂到同一个 reactive 代理上：模板经 stream.status / stream.stages... 访问，
  // 响应性由 reactive proxy 保证；方法（analyze/reset）作为非响应属性附挂即可。
  ;(state as AnalysisStream).analyze = analyze
  ;(state as AnalysisStream).reset = reset
  return state as AnalysisStream
}
