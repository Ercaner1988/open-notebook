import apiClient from './client'

export type QueueJobStatus = 'new' | 'running' | 'failed' | 'completed'

export interface QueueSummary {
  paused: boolean
  counts: { new: number; running: number; completed: number; failed: number; canceled: number }
  running: { id: string; source_id: string | null; source_title: string | null; started: string | null }[]
  embedded_chunks: number
  rate_chunks_per_min: number | null
  eta_minutes: number | null
  pending_chars: number
}

export interface QueueJob {
  id: string
  status: string
  source_id: string | null
  source_title: string | null
  created: string | null
  updated: string | null
  queue_priority: number | null
  error_message: string | null
}

export interface UnembeddedSource {
  source_id: string
  title: string | null
}

export interface UnembeddedReport {
  with_text: UnembeddedSource[]
  empty_text: UnembeddedSource[]
}

export interface UnusedCredential {
  id: string
  name: string
  provider: string
  base_url: string | null
}

export interface TestEmbeddingResult {
  ok: boolean
  message: string
  model_id: string | null
}

const enc = encodeURIComponent

export const embeddingQueueApi = {
  summary: async () => (await apiClient.get<QueueSummary>('/embedding-queue/summary')).data,
  jobs: async (status: QueueJobStatus, limit = 100) =>
    (await apiClient.get<QueueJob[]>('/embedding-queue/jobs', { params: { status, limit } })).data,
  pause: async () => (await apiClient.post<{ paused: boolean }>('/embedding-queue/pause')).data,
  resume: async () => (await apiClient.post<{ paused: boolean }>('/embedding-queue/resume')).data,
  move: async (id: string, position: 'top' | 'bottom') =>
    (await apiClient.post(`/embedding-queue/jobs/${enc(id)}/move`, { position })).data,
  cancel: async (id: string) => (await apiClient.post(`/embedding-queue/jobs/${enc(id)}/cancel`)).data,
  retry: async (id: string) =>
    (await apiClient.post<{ command_id: string }>(`/embedding-queue/jobs/${enc(id)}/retry`)).data,
  retryFailed: async () =>
    (await apiClient.post<{ queued: number }>('/embedding-queue/retry-failed')).data,
  unembedded: async () =>
    (await apiClient.get<UnembeddedReport>('/embedding-queue/maintenance/unembedded')).data,
  enqueueUnembedded: async () =>
    (await apiClient.post<{ queued: number }>('/embedding-queue/maintenance/enqueue-unembedded')).data,
  unusedCredentials: async () =>
    (await apiClient.get<UnusedCredential[]>('/embedding-queue/maintenance/unused-credentials')).data,
  testEmbedding: async () =>
    (await apiClient.post<TestEmbeddingResult>('/embedding-queue/maintenance/test-embedding')).data,
}
