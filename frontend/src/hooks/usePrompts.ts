import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  promptsApi,
  type EntryInput,
  type PromptEntry,
  type PromptTemplate,
  type TemplateInput,
} from '@/api/prompts'

const ENTRIES_KEY = ['prompts', 'entries']
const TEMPLATES_KEY = ['prompts', 'templates']

export const entriesKey = (params: Record<string, string | undefined> = {}) => [
  ...ENTRIES_KEY,
  params,
]
export const templatesKey = (category?: string) => [...TEMPLATES_KEY, category ?? '']

export function usePromptTemplates(category?: string) {
  return useQuery({
    queryKey: templatesKey(category),
    queryFn: () => promptsApi.listTemplates(category),
  })
}

export function usePromptEntries(params: { category?: string; tag?: string; q?: string } = {}) {
  return useQuery({ queryKey: entriesKey(params), queryFn: () => promptsApi.listEntries(params) })
}

export function useSaveEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: EntryInput) => promptsApi.createEntry(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTRIES_KEY }),
  })
}

export function usePatchEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<EntryInput> }) =>
      promptsApi.patchEntry(id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTRIES_KEY }),
  })
}

export function useDeleteEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => promptsApi.deleteEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTRIES_KEY }),
  })
}

export function useEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => promptsApi.useEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTRIES_KEY }),
  })
}

export function useCreateTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TemplateInput) => promptsApi.createTemplate(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  })
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => promptsApi.deleteTemplate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  })
}

/** 组合 Lib 里最常用的一组：模板列表 + 收藏列表，给创作页一次性取全。 */
export function usePromptLibrary(category?: string) {
  const templates = usePromptTemplates(category)
  const entries = usePromptEntries(category ? { category } : {})
  return {
    templates: templates.data ?? [],
    entries: (entries.data ?? []) as PromptEntry[],
    builtin: (templates.data ?? []).filter((item: PromptTemplate) => item.is_builtin),
    mine: (templates.data ?? []).filter((item: PromptTemplate) => !item.is_builtin),
    loading: templates.isPending || entries.isPending,
  }
}
