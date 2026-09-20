import { api } from '@/api/client'

export type FieldName =
  | 'planner_base_url'
  | 'planner_api_key'
  | 'planner_model'
  | 'planner_timeout'
  | 'planner_max_retries'
  | 'images_base_url'
  | 'images_api_key'
  | 'images_model'
  | 'images_sizes'
  | 'image_provider'

export type EffectiveView = {
  planner_base_url: string
  planner_model: string
  planner_timeout: number
  planner_max_retries: number
  planner_api_key_masked: string
  images_base_url: string
  images_model: string
  images_sizes: string
  images_api_key_masked: string
  image_provider: string
  lock_image_provider: boolean
  source: Record<string, string>
  overridden: string[]
}

export type MeLlmConfig = {
  effective: EffectiveView
  overrides: { values: Record<string, unknown>; updated_at: string | null }
}

export type ConfigDraft = { include_images?: boolean } & Partial<Record<FieldName, string>>

export type TestOutcome = { ok?: boolean; skipped?: string; latency_ms?: number; model?: string; error?: string; status?: number }

export type TestResult = { fingerprint: string; planner: TestOutcome; images: TestOutcome }

export type AuditEntry = {
  id: string
  actor_id: string | null
  scope: 'global' | 'user'
  target_user_id: string | null
  action: 'update' | 'clear' | 'test'
  diff: Record<string, unknown>
  created_at: string | null
}

export const llmConfigApi = {
  mine: () => api.get<MeLlmConfig>('/me/llm-config'),
  saveMine: (body: ConfigDraft) => api.put<MeLlmConfig>('/me/llm-config', body),
  clearMine: () => api.delete<void>('/me/llm-config'),
  testMine: (body: ConfigDraft) => api.post<TestResult>('/me/llm-config/test', body),

  global: () => api.get<EffectiveView>('/admin/llm-config'),
  saveGlobal: (body: ConfigDraft & { lock_image_provider?: boolean }) =>
    api.put<EffectiveView>('/admin/llm-config', body),
  testGlobal: (body: ConfigDraft) => api.post<TestResult>('/admin/llm-config/test', body),
  audit: () => api.get<AuditEntry[]>('/admin/llm-config/audit'),
}
