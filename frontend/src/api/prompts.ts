import { api } from '@/api/client'

export interface PromptEntry {
  id: string
  title: string
  prompt: string
  negative_prompt: string | null
  ratio: string
  category: string
  tags: string[]
  note: string | null
  preview_asset_id: string | null
  source_run_id: string | null
  use_count: number
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface TemplateVariable {
  name: string
  label: string
  placeholder: string
  default: string
  options: string[]
}

export interface PromptTemplate {
  id: string
  title: string
  category: string
  description: string | null
  prompt_template: string
  negative_template: string | null
  variables: TemplateVariable[]
  default_ratio: string
  default_count: number
  preview_asset_id: string | null
  use_count: number
  is_builtin: boolean
  created_at: string
}

/** 内置分类；category 本身不约束，用户也能自填。 */
export const CATEGORY_LABELS: Record<string, string> = {
  portrait: '人物',
  knowledge_graph: '知识图谱',
  architecture: '架构流程',
  product: '产品电商',
  poster: '海报封面',
  illustration: '插画概念',
  other: '其他',
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

export interface EntryInput {
  title: string
  prompt: string
  negative_prompt?: string | null
  ratio?: string
  category?: string
  tags?: string[]
  note?: string | null
  preview_asset_id?: string | null
  source_run_id?: string | null
}

export interface TemplateInput {
  title: string
  category?: string
  description?: string | null
  prompt_template: string
  negative_template?: string | null
  variables?: TemplateVariable[]
  default_ratio?: string
  default_count?: number
  preview_asset_id?: string | null
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const promptsApi = {
  listEntries: (params: { category?: string; tag?: string; q?: string } = {}) =>
    api.get<PromptEntry[]>(`/prompts/entries${query(params)}`),
  createEntry: (body: EntryInput) => api.post<PromptEntry>('/prompts/entries', body),
  getEntry: (id: string) => api.get<PromptEntry>(`/prompts/entries/${id}`),
  patchEntry: (id: string, body: Partial<EntryInput>) =>
    api.patch<PromptEntry>(`/prompts/entries/${id}`, body),
  deleteEntry: (id: string) => api.delete<void>(`/prompts/entries/${id}`),
  useEntry: (id: string) => api.post<PromptEntry>(`/prompts/entries/${id}/use`),

  listTemplates: (category?: string) =>
    api.get<PromptTemplate[]>(`/prompts/templates${query({ category })}`),
  createTemplate: (body: TemplateInput) => api.post<PromptTemplate>('/prompts/templates', body),
  getTemplate: (id: string) => api.get<PromptTemplate>(`/prompts/templates/${id}`),
  patchTemplate: (id: string, body: Partial<TemplateInput>) =>
    api.patch<PromptTemplate>(`/prompts/templates/${id}`, body),
  deleteTemplate: (id: string) => api.delete<void>(`/prompts/templates/${id}`),
  renderTemplate: (id: string, values: Record<string, string>) =>
    api.post<{ prompt: string; negative_prompt: string | null }>(
      `/prompts/templates/${id}/render`,
      { values },
    ),
}
