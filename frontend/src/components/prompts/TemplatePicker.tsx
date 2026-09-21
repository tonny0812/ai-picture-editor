import { useState } from 'react'

import type { Ratio } from '@/api/runs'
import { promptsApi, categoryLabel, type PromptTemplate } from '@/api/prompts'
import type { GenerateDraft } from '@/components/GenerateForm'
import { errorMessage } from '@/hooks/useAuth'
import { usePromptTemplates } from '@/hooks/usePrompts'
import { missingVariables, renderPreview } from '@/lib/promptTemplate'

/** 模板入口：点胶囊填变量，预览没问题再回填到输入框。 */
export default function TemplatePicker({
  onApply,
}: {
  onApply: (patch: Partial<GenerateDraft>) => void
}) {
  const { data: templates = [], isPending } = usePromptTemplates()
  const [active, setActive] = useState<PromptTemplate | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const open = (template: PromptTemplate) => {
    const initial: Record<string, string> = {}
    for (const variable of template.variables ?? []) initial[variable.name] = variable.default ?? ''
    setError(null)
    setValues(initial)
    setActive(template)
  }

  const missing = active ? missingVariables(active.prompt_template, values) : []
  const preview = active ? renderPreview(active.prompt_template, values) : ''

  const apply = async () => {
    if (!active || missing.length > 0) return
    setPending(true)
    setError(null)
    try {
      // 走后端渲染：结果可靠（同一套规则），顺便累计使用次数
      const rendered = await promptsApi.renderTemplate(active.id, values)
      onApply({
        prompt: rendered.prompt,
        negative_prompt: rendered.negative_prompt ?? undefined,
        ratio: active.default_ratio as Ratio,
        count: active.default_count,
      })
      setActive(null)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setPending(false)
    }
  }

  if (!isPending && templates.length === 0) return null

  return (
    <section className="mt-4">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-muted text-xs font-medium">套用模板</h2>
        <span className="text-faint text-[11px]">选一个骨架，只填变化的部分</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {isPending && <p className="text-faint text-xs">加载中…</p>}
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            onClick={() => open(template)}
            aria-pressed={active?.id === template.id}
            className={`rounded-control border px-3 py-1.5 text-xs transition-all duration-150 active:scale-[0.97] ${
              active?.id === template.id
                ? 'border-brand bg-brand-soft text-ink'
                : 'border-line text-muted hover:border-brand hover:text-ink'
            }`}
          >
            <span className="text-faint mr-1">{categoryLabel(template.category)}</span>
            {template.title}
          </button>
        ))}
      </div>

      {active && (
        <div className="border-line bg-soft rounded-card animate-fade-in mt-3 border p-4">
          {active.description && <p className="text-muted mb-3 text-xs">{active.description}</p>}

          {(active.variables ?? []).length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {active.variables.map((variable) => (
                <label key={variable.name} className="block">
                  <span className="text-muted mb-1 block text-xs font-medium">
                    {variable.label || variable.name}
                  </span>
                  {variable.options.length > 0 ? (
                    <select
                      value={values[variable.name] ?? ''}
                      onChange={(event) =>
                        setValues({ ...values, [variable.name]: event.target.value })
                      }
                      className="border-line bg-paper text-ink rounded-control w-full border px-2.5 py-1.5 text-sm outline-none focus:border-brand"
                    >
                      <option value="">请选择</option>
                      {variable.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={values[variable.name] ?? ''}
                      onChange={(event) =>
                        setValues({ ...values, [variable.name]: event.target.value })
                      }
                      placeholder={variable.placeholder}
                      className="border-line bg-paper text-ink rounded-control w-full border px-2.5 py-1.5 text-sm outline-none focus:border-brand"
                    />
                  )}
                </label>
              ))}
            </div>
          ) : (
            <p className="text-muted text-xs">这个模板没有要填的变量，直接用就行。</p>
          )}

          <div className="mt-3">
            <span className="text-muted mb-1 block text-xs font-medium">预览</span>
            <p className="border-line bg-paper text-ink rounded-control max-h-24 overflow-auto border px-3 py-2 text-xs leading-relaxed">
              {preview || '填完上面的内容这里会实时显示'}
            </p>
          </div>

          {error && <p className="text-danger mt-2 text-xs">{error}</p>}

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              disabled={missing.length > 0 || pending}
              onClick={apply}
              className="bg-ink hover:bg-dark rounded-control px-3 py-1.5 text-xs font-medium text-white transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {pending ? '处理中…' : '填进输入框'}
            </button>
            {missing.length > 0 && (
              <span className="text-faint text-[11px]">还有必填项没写：{missing.join('、')}</span>
            )}
            <button
              type="button"
              onClick={() => setActive(null)}
              className="text-muted hover:text-ink ml-auto px-2 py-1.5 text-xs transition-colors"
            >
              收起
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
