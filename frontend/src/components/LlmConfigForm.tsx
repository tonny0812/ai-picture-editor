import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  llmConfigApi,
  type ConfigDraft,
  type EffectiveView,
  type FieldName,
  type TestResult,
} from '@/api/llmConfig'
import { errorMessage } from '@/hooks/useAuth'
import { toast } from '@/stores/toasts'

export type FormMode = 'user' | 'global'

type Draft = Partial<Record<FieldName, string>>

const TEXT_FIELDS: { name: FieldName; label: string; placeholder?: string }[] = [
  { name: 'planner_base_url', label: '规划模型地址', placeholder: 'https://…/v1（留空用百炼兼容模式）' },
  { name: 'planner_model', label: '规划模型名', placeholder: 'qwen-plus' },
  { name: 'images_base_url', label: '图像网关地址', placeholder: 'https://…/v1（留空复用规划地址）' },
  { name: 'images_model', label: '生图模型名', placeholder: 'qwen-image-3.0-pro' },
  { name: 'images_sizes', label: '尺寸档位', placeholder: '1024x1024,1536x1024,1024x1536' },
]

const SECRET_FIELDS: {
  name: FieldName
  label: string
  maskedKey: 'planner_api_key_masked' | 'images_api_key_masked'
}[] = [
  { name: 'planner_api_key', label: '规划模型 API Key', maskedKey: 'planner_api_key_masked' },
  { name: 'images_api_key', label: '图像网关 API Key', maskedKey: 'images_api_key_masked' },
]

const NUMBER_FIELDS: { name: FieldName; label: string; min: number; max: number }[] = [
  { name: 'planner_timeout', label: '规划超时（秒）', min: 5, max: 600 },
  { name: 'planner_max_retries', label: '规划重试次数', min: 0, max: 10 },
]

const PROVIDER_OPTIONS = [
  { value: 'mock', label: 'mock（占位图，不耗额度）' },
  { value: 'dashscope', label: 'dashscope（阿里百炼）' },
  { value: 'openai', label: 'openai（OpenAI 兼容网关）' },
]

const SOURCE_LABEL: Record<string, string> = {
  user: '个人覆盖',
  global: '全局配置',
  env: '.env 默认',
}

/** 草稿里非空的键（测试连接用；密钥只在输入了新值时带上）。 */
function nonEmpty(draft: Draft): ConfigDraft {
  const body: ConfigDraft = {}
  for (const [key, value] of Object.entries(draft)) {
    if (value !== undefined && value !== '') body[key as FieldName] = value
  }
  return body
}

function OutcomeLine({ title, outcome }: { title: string; outcome: TestResult['planner'] }) {
  if (outcome.skipped) {
    return (
      <p className="text-faint text-sm">
        · {title}：跳过（{outcome.skipped}）
      </p>
    )
  }
  if (outcome.ok) {
    return (
      <p className="text-success text-sm">
        ✓ {title}：可用（{outcome.model} · {outcome.latency_ms}ms）
      </p>
    )
  }
  return (
    <p className="text-danger text-sm">
      ✗ {title}：失败{outcome.status ? `（HTTP ${outcome.status}）` : ''} — {outcome.error}
    </p>
  )
}

/** LLM 配置表单：user 模式编辑个人覆盖，global 模式编辑全局默认（admin）。 */
export default function LlmConfigForm({ mode }: { mode: FormMode }) {
  const queryClient = useQueryClient()
  const isGlobal = mode === 'global'

  const userQuery = useQuery({
    queryKey: ['llm-config', 'mine'],
    queryFn: llmConfigApi.mine,
    enabled: !isGlobal,
  })
  const adminQuery = useQuery({
    queryKey: ['llm-config', 'global'],
    queryFn: llmConfigApi.global,
    enabled: isGlobal,
  })

  const effective: EffectiveView | undefined = isGlobal ? adminQuery.data : userQuery.data?.effective
  const overrides = isGlobal ? undefined : userQuery.data?.overrides

  const [draft, setDraft] = useState<Draft>({})
  const [touched, setTouched] = useState<ReadonlySet<FieldName>>(new Set())
  const [lock, setLock] = useState<boolean | null>(null)

  const lockOn = lock ?? effective?.lock_image_provider ?? false

  const setField = (name: FieldName, value: string) => {
    setDraft((prev) => ({ ...prev, [name]: value }))
    setTouched((prev) => new Set(prev).add(name))
  }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['llm-config'] })
  }

  const save = useMutation({
    mutationFn: (body: ConfigDraft): Promise<unknown> =>
      isGlobal
        ? llmConfigApi.saveGlobal({ ...body, lock_image_provider: lock ?? undefined })
        : llmConfigApi.saveMine(body),
    onSuccess: () => {
      toast('配置已保存并热生效，无需重启')
      setDraft({})
      setTouched(new Set())
      setLock(null)
      invalidate()
    },
    onError: (error) => toast(errorMessage(error), 'danger'),
  })

  const clearMine = useMutation({
    mutationFn: () => llmConfigApi.clearMine(),
    onSuccess: () => {
      toast('已清除个人覆盖，恢复使用全局默认')
      setDraft({})
      setTouched(new Set())
      invalidate()
    },
    onError: (error) => toast(errorMessage(error), 'danger'),
  })

  const test = useMutation({
    mutationFn: (body: ConfigDraft): Promise<TestResult> =>
      isGlobal ? llmConfigApi.testGlobal(body) : llmConfigApi.testMine(body),
    onError: (error) => toast(errorMessage(error), 'danger'),
  })

  const initialValue = useMemo<Partial<Record<FieldName, string>>>(() => {
    if (!effective) return {}
    if (isGlobal) {
      return {
        planner_base_url: effective.planner_base_url,
        planner_model: effective.planner_model,
        planner_timeout: String(effective.planner_timeout),
        planner_max_retries: String(effective.planner_max_retries),
        images_base_url: effective.images_base_url,
        images_model: effective.images_model,
        images_sizes: effective.images_sizes,
        image_provider: effective.image_provider,
      }
    }
    const values: Partial<Record<FieldName, string>> = {}
    for (const [key, value] of Object.entries(overrides?.values ?? {})) {
      if (typeof value === 'string' || typeof value === 'number') {
        values[key as FieldName] = String(value)
      }
    }
    return values
  }, [effective, overrides, isGlobal])

  const valueOf = (name: FieldName): string => draft[name] ?? initialValue[name] ?? ''

  const hintOf = (name: FieldName): string | undefined => {
    if (isGlobal) return undefined
    const source = effective?.source[name]
    return source ? `当前生效：${SOURCE_LABEL[source] ?? source}` : undefined
  }

  const hasOverride = Object.keys(overrides?.values ?? {}).length > 0

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const body: ConfigDraft = {}
    for (const name of touched) {
      const value = draft[name]
      if (name.endsWith('_api_key')) {
        if (value) body[name] = value // 密钥只写：留空视为未修改，避免误清
      } else {
        body[name] = value ?? '' // 其余字段空串 = 清除覆盖
      }
    }
    if (!isGlobal && 'image_provider' in body && lockOn) {
      toast('管理员已锁定模型类型，不能切换', 'danger')
      return
    }
    const onlyLock = Object.keys(body).length === 0 && lock !== null
    if (Object.keys(body).length === 0 && !onlyLock) {
      toast('没有改动，无需保存')
      return
    }
    save.mutate(body)
  }

  const runTest = () => test.mutate({ ...nonEmpty(draft), include_images: true })

  const pending = isGlobal ? adminQuery.isPending : userQuery.isPending
  const failed = isGlobal ? adminQuery.isError : userQuery.isError

  if (pending) return <p className="text-muted text-sm">加载配置…</p>
  if (failed) return <p className="text-danger text-sm">配置加载失败，请刷新重试</p>

  const changed = touched.size > 0

  return (
    <form onSubmit={submit} className="space-y-8">
      <section className="space-y-4">
        <h3 className="text-ink text-sm font-semibold">对话规划（OpenAI 兼容）</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {TEXT_FIELDS.slice(0, 2).map((field) => (
            <Field
              key={field.name}
              {...field}
              value={valueOf(field.name)}
              hint={hintOf(field.name)}
              onChange={setField}
            />
          ))}
          {SECRET_FIELDS.slice(0, 1).map((field) => (
            <SecretField
              key={field.name}
              {...field}
              value={draft[field.name] ?? ''}
              masked={effective?.[field.maskedKey] ?? ''}
              onChange={setField}
            />
          ))}
          {NUMBER_FIELDS.map((field) => (
            <Field
              key={field.name}
              {...field}
              type="number"
              value={valueOf(field.name)}
              hint={hintOf(field.name)}
              onChange={setField}
            />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <h3 className="text-ink text-sm font-semibold">图像模型（OpenAI 兼容 images API）</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          {TEXT_FIELDS.slice(2).map((field) => (
            <Field
              key={field.name}
              {...field}
              value={valueOf(field.name)}
              hint={hintOf(field.name)}
              onChange={setField}
            />
          ))}
          {SECRET_FIELDS.slice(1).map((field) => (
            <SecretField
              key={field.name}
              {...field}
              value={draft[field.name] ?? ''}
              masked={effective?.[field.maskedKey] ?? ''}
              onChange={setField}
            />
          ))}
        </div>

        <label className="block space-y-1.5 sm:max-w-sm">
          <span className="text-muted block text-xs">模型类型（image_provider）</span>
          <select
            value={valueOf('image_provider') || 'mock'}
            disabled={!isGlobal && lockOn}
            onChange={(event) => setField('image_provider', event.target.value)}
            className="border-line bg-paper text-ink disabled:bg-soft disabled:text-faint w-full rounded-[12px] border px-3 py-2.5 text-sm"
          >
            {PROVIDER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {!isGlobal && lockOn && (
            <span className="text-danger block text-xs">管理员已锁定模型类型，不能修改</span>
          )}
          {isGlobal && (
            <span className="mt-2 flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                id="lock-image-provider"
                checked={lockOn}
                onChange={(event) => setLock(event.target.checked)}
              />
              <label htmlFor="lock-image-provider" className="text-muted">
                强制锁：禁止用户覆盖模型类型（防止把真模型切成 mock 假图）
              </label>
            </span>
          )}
        </label>
      </section>

      <div className="border-line flex flex-wrap items-center gap-3 border-t pt-5">
        <button
          type="submit"
          disabled={save.isPending || (!changed && lock === null)}
          className="bg-dark text-paper disabled:bg-soft disabled:text-faint rounded-[12px] px-5 py-2.5 text-sm font-medium transition-colors"
        >
          {save.isPending ? '保存中…' : '保存（热生效）'}
        </button>
        <button
          type="button"
          onClick={runTest}
          disabled={test.isPending}
          className="border-line text-ink hover:bg-soft rounded-[12px] border px-5 py-2.5 text-sm transition-colors"
        >
          {test.isPending ? '测试中…（真实调用模型，可能需几十秒）' : '测试连接'}
        </button>
        {!isGlobal && (
          <button
            type="button"
            onClick={() => clearMine.mutate()}
            disabled={clearMine.isPending || !hasOverride}
            className="text-danger ml-auto text-sm disabled:opacity-40"
          >
            清除全部个人覆盖
          </button>
        )}
      </div>

      {test.data && (
        <div className="border-line bg-soft space-y-1 rounded-[12px] border p-4">
          <OutcomeLine title="对话规划" outcome={test.data.planner} />
          <OutcomeLine title="图像模型" outcome={test.data.images} />
        </div>
      )}
    </form>
  )
}

function Field({
  label,
  value,
  onChange,
  hint,
  placeholder,
  type = 'text',
  min,
  max,
  name,
}: {
  label: string
  value: string
  onChange: (name: FieldName, value: string) => void
  hint?: string
  placeholder?: string
  type?: string
  min?: number
  max?: number
  name: FieldName
}) {
  return (
    <label className="space-y-1.5">
      <span className="text-muted block text-xs">{label}</span>
      <input
        type={type}
        min={min}
        max={max}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(name, event.target.value)}
        className="border-line bg-paper text-ink focus:border-brand w-full rounded-[12px] border px-3 py-2.5 text-sm outline-none"
      />
      {hint && <span className="text-faint block text-xs">{hint}</span>}
    </label>
  )
}

function SecretField({
  label,
  value,
  masked,
  onChange,
  name,
}: {
  label: string
  value: string
  masked: string
  onChange: (name: FieldName, value: string) => void
  name: FieldName
}) {
  return (
    <label className="space-y-1.5">
      <span className="text-muted block text-xs">
        {label}
        {masked && <span className="text-faint ml-2">当前：{masked}（只写，留空不变）</span>}
      </span>
      <input
        type="password"
        autoComplete="new-password"
        value={value}
        placeholder={masked ? '••••••（输入新值即更换）' : 'sk-…'}
        onChange={(event) => onChange(name, event.target.value)}
        className="border-line bg-paper text-ink focus:border-brand w-full rounded-[12px] border px-3 py-2.5 text-sm outline-none"
      />
    </label>
  )
}
