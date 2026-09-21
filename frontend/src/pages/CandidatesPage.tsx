import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Asset } from '@/api/assets'
import ErrorDetail, { errorSummary } from '@/components/ErrorDetail'
import { CATEGORY_LABELS } from '@/api/prompts'
import ProgressBar from '@/components/ui/ProgressBar'
import { errorMessage } from '@/hooks/useAuth'
import { useSaveEntry } from '@/hooks/usePrompts'
import { toast } from '@/stores/toasts'
import { useRun } from '@/hooks/useRun'
import { useCreateSession } from '@/hooks/useSessions'

export default function CandidatesPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<string | null>(null)
  const { status, progress, stage, error, prompt, negativePrompt, ratio, candidates, notFound } =
    useRun(runId || null)
  const createSession = useCreateSession()

  // 采用一张进入编辑，同批其余候选一并带进会话图片墙
  const adopt = () =>
    picked &&
    createSession.mutate(
      {
        current_asset_id: picked,
        asset_ids: candidates.map((asset) => asset.id),
        title: prompt ?? undefined,
      },
      { onSuccess: (session) => navigate(`/editor/${session.id}`) },
    )

  if (notFound) {
    return <Centered title="任务不存在" hint="链接可能已失效，回到创作页重新开始。" />
  }

  if (status === 'failed' || status === 'canceled') {
    return (
      <Centered title="生成失败" hint={errorSummary(error) || '未知原因'}>
        <ErrorDetail error={error} />
        <Link
          to="/create"
          className="bg-ink hover:bg-dark rounded-control mt-5 px-4 py-2 text-sm font-medium text-white"
        >
          返回重试
        </Link>
      </Centered>
    )
  }

  if (status !== 'succeeded') {
    return <Progress percent={progress} stage={stage} />
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-ink text-2xl font-semibold tracking-tight">选出一张</h1>
          <p className="text-muted mt-1 text-sm">
            挑一张满意的进入编辑，其余候选图会留在会话图片墙随时切回。
          </p>
        </div>
        <button
          type="button"
          disabled={!picked || createSession.isPending}
          onClick={adopt}
          className="bg-ink hover:bg-dark rounded-control shrink-0 px-4 py-2 text-sm font-medium text-white transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100"
        >
          {createSession.isPending ? '打开中…' : picked ? '进入编辑' : '先点选一张'}
        </button>
      </header>

      {runId && prompt && (
        <SavePrompt
          runId={runId}
          prompt={prompt}
          negativePrompt={negativePrompt}
          ratio={ratio}
          previewAssetId={picked}
        />
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {candidates.map((asset, index) => (
          <Candidate
            key={asset.id}
            asset={asset}
            index={index}
            selected={picked === asset.id}
            onSelect={() => setPicked(asset.id)}
          />
        ))}
      </div>
    </div>
  )
}

function Candidate({
  asset,
  index,
  selected,
  onSelect,
}: {
  asset: Asset
  index: number
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`rounded-panel group relative block overflow-hidden border-2 bg-white transition-all duration-200 ${
        selected
          ? 'border-brand shadow-lift'
          : 'border-line hover:border-brand hover:-translate-y-0.5 hover:shadow-lift'
      }`}
    >
      <img
        src={asset.url}
        alt={`候选图 ${index + 1}`}
        loading="lazy"
        className="block max-h-[52vh] w-full object-contain transition-transform duration-300 group-hover:scale-[1.01]"
      />
      <span className="text-muted bg-paper/90 absolute top-2 left-2 rounded-full px-2 py-0.5 text-xs font-medium backdrop-blur">
        {index + 1}
      </span>
      {selected && (
        <span className="bg-brand absolute top-2 right-2 rounded-full px-2 py-0.5 text-xs font-medium text-white">
          已选
        </span>
      )}
    </button>
  )
}

function Progress({ percent, stage }: { percent: number; stage: string }) {
  return (
    <Centered title="正在生成" hint={stage || '任务已提交，正在排队'}>
      <ProgressBar value={percent} className="mt-6 h-1 w-64 rounded-full" />
      <p className="text-faint mt-2 text-xs tabular-nums">{percent}%</p>
    </Centered>
  )
}

function Centered({
  title,
  hint,
  children,
}: {
  title: string
  hint: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <h1 className="text-ink text-xl font-semibold">{title}</h1>
      <p className="text-muted mt-1 max-w-md text-sm">{hint}</p>
      {children}
    </div>
  )
}

/**
 * 把这次满意的成果收进提示词库。
 *
 * 带上 preview_asset_id 与 source_run_id：以后在库里看到这条能直接看到当时那张图，
 * 也能回溯是哪一次生成——判断"这条到底好不好"全靠这两样。
 */
function SavePrompt({
  runId,
  prompt,
  negativePrompt,
  ratio,
  previewAssetId,
}: {
  runId: string
  prompt: string
  negativePrompt: string | null
  ratio: string | null
  previewAssetId: string | null
}) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState('')
  const [category, setCategory] = useState('other')
  const [error, setError] = useState<string | null>(null)
  const save = useSaveEntry()

  const submit = async () => {
    setError(null)
    try {
      await save.mutateAsync({
        title: title.trim(),
        prompt,
        negative_prompt: negativePrompt,
        ratio: (ratio as '1:1' | '4:5' | '3:4' | '9:16' | '16:9') ?? '1:1',
        category,
        tags: tags.split(/[,，\s]+/).map((tag) => tag.trim()).filter(Boolean),
        preview_asset_id: previewAssetId,
        source_run_id: runId,
      })
      setOpen(false)
      setTitle('')
      setTags('')
      toast('已收进提示词库', 'ok')
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  if (!open) {
    return (
      <p className="mb-6 mt-4">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-muted hover:text-ink border-line hover:border-line-strong rounded-control border px-3 py-1.5 text-xs transition-colors"
        >
          收进提示词库
        </button>
        <span className="text-faint ml-2 text-[11px]">
          {previewAssetId ? '会用选中的这张作为预览图' : '先点选一张，存进去时顺便带上预览图'}
        </span>
      </p>
    )
  }

  return (
    <div className="border-line bg-soft rounded-card animate-fade-in mb-6 mt-4 border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="给这段提示词起个名字"
          aria-label="收藏标题"
          autoFocus
          className="border-line bg-paper text-ink placeholder:text-faint rounded-control w-56 border px-2.5 py-1.5 text-xs outline-none focus:border-brand"
        />
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="标签，逗号分隔"
          aria-label="标签"
          className="border-line bg-paper text-ink placeholder:text-faint rounded-control w-40 border px-2.5 py-1.5 text-xs outline-none focus:border-brand"
        />
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          aria-label="分类"
          className="border-line bg-paper text-ink rounded-control border px-2 py-1.5 text-xs outline-none focus:border-brand"
        >
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!title.trim() || save.isPending}
          onClick={submit}
          className="bg-ink hover:bg-dark rounded-control px-3 py-1.5 text-xs font-medium text-white transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {save.isPending ? '保存中…' : '保存'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-muted hover:text-ink px-2 py-1.5 text-xs transition-colors"
        >
          取消
        </button>
      </div>
      {error && <p className="text-danger mt-2 text-xs">{error}</p>}
    </div>
  )
}
