import { useMemo, useState } from 'react'

import { CATEGORY_LABELS, categoryLabel } from '@/api/prompts'
import type { GenerateDraft } from '@/components/GenerateForm'
import { errorMessage } from '@/hooks/useAuth'
import { useDeleteEntry, useEntry, usePromptEntries, useSaveEntry } from '@/hooks/usePrompts'

/** 提示词库：一半是把当前输入存下来，一半是把存过的套回去。 */
export default function PromptLibrary({
  draft,
  onApply,
}: {
  draft: GenerateDraft
  onApply: (patch: Partial<GenerateDraft>) => void
}) {
  const [keyword, setKeyword] = useState('')
  const [entries, setEntries] = useState(false)
  const query = usePromptEntries(entries && keyword ? { q: keyword } : {})
  const save = useSaveEntry()
  const remove = useDeleteEntry()
  const use = useEntry()

  const [title, setTitle] = useState('')
  const [tags, setTags] = useState('')
  const [category, setCategory] = useState('other')
  const [error, setError] = useState<string | null>(null)

  const list = useMemo(() => {
    const items = query.data ?? []
    if (!keyword) return items
    const lowered = keyword.trim().toLowerCase()
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(lowered) ||
        item.prompt.toLowerCase().includes(lowered) ||
        item.tags.some((tag) => tag.toLowerCase().includes(lowered)),
    )
  }, [query.data, keyword])

  const saveCurrent = async () => {
    setError(null)
    try {
      await save.mutateAsync({
        title: title.trim(),
        prompt: draft.prompt.trim(),
        negative_prompt: draft.negative_prompt ?? null,
        ratio: draft.ratio,
        category,
        tags: tags
          .split(/[,，\s]+/)
          .map((tag) => tag.trim())
          .filter(Boolean),
      })
      setTitle('')
      setTags('')
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <section className="border-line bg-paper rounded-card mt-3 border">
      <button
        type="button"
        onClick={() => setEntries((open) => !open)}
        className="text-muted hover:text-ink flex w-full items-center gap-2 px-4 py-2.5 text-xs transition-colors"
      >
        <span className="font-medium">提示词库</span>
        <span className="text-faint">把好用的提示词存下来</span>
        <span className="text-faint ml-auto">{entries ? '收起' : '展开'}</span>
      </button>

      {entries && (
        <div className="border-line animate-fade-in border-t px-4 py-3">
          {/* 存当前的 */}
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="给这段提示词起个名字"
              aria-label="收藏标题"
              className="border-line text-ink placeholder:text-faint rounded-control w-48 border px-2.5 py-1.5 text-xs outline-none focus:border-brand"
            />
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="标签，逗号分隔"
              aria-label="标签"
              className="border-line text-ink placeholder:text-faint rounded-control w-40 border px-2.5 py-1.5 text-xs outline-none focus:border-brand"
            />
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              aria-label="分类"
              className="border-line text-ink rounded-control border px-2 py-1.5 text-xs outline-none focus:border-brand"
            >
              {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!draft.prompt.trim() || !title.trim() || save.isPending}
              onClick={saveCurrent}
              className="bg-ink hover:bg-dark rounded-control px-3 py-1.5 text-xs font-medium text-white transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {save.isPending ? '保存中…' : '存当前'}
            </button>
          </div>

          {error && <p className="text-danger mt-2 text-xs">{error}</p>}

          {/* 存过的 */}
          <div className="border-line mt-3 flex items-center gap-2 border-t pt-3">
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索已保存的提示词"
              aria-label="搜索提示词"
              className="border-line text-ink placeholder:text-faint rounded-control flex-1 border px-2.5 py-1.5 text-xs outline-none focus:border-brand"
            />
          </div>

          <div className="mt-2 max-h-72 space-y-2 overflow-auto pr-1">
            {query.isPending && <p className="text-faint py-3 text-xs">加载中…</p>}
            {!query.isPending && list.length === 0 && (
              <p className="text-faint py-3 text-xs">还没有存过提示词。</p>
            )}
            {list.map((entry) => (
              <div
                key={entry.id}
                className="border-line hover:border-brand rounded-control border p-2.5 transition-colors"
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-ink truncate text-xs font-medium">{entry.title}</span>
                  <span className="text-faint shrink-0 text-[11px]">
                    {categoryLabel(entry.category)} · {entry.ratio}
                  </span>
                  {entry.use_count > 0 && (
                    <span className="text-faint shrink-0 text-[11px]">用过 {entry.use_count}</span>
                  )}
                  <button
                    type="button"
                    onClick={() => remove.mutate(entry.id)}
                    className="text-faint hover:text-danger ml-auto shrink-0 px-1 text-[11px] transition-colors"
                  >
                    删除
                  </button>
                </div>
                <p className="text-muted mt-1 line-clamp-2 text-[11px] leading-relaxed">
                  {entry.prompt}
                </p>
                {entry.tags.length > 0 && (
                  <p className="text-faint mt-1 text-[11px]">{entry.tags.join(' · ')}</p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    onApply({
                      prompt: entry.prompt,
                      negative_prompt: entry.negative_prompt ?? undefined,
                      ratio: entry.ratio as GenerateDraft['ratio'],
                    })
                    // 计数失败无所谓，不该因为记一次数就打断套用
                    use.mutate(entry.id, { onError: () => undefined })
                  }}
                  className="text-muted hover:text-ink mt-1.5 text-[11px] font-medium transition-colors"
                >
                  套用这段
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
