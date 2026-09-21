import { useState } from 'react'

/**
 * 任务失败原因的展示。
 *
 * 后端把「一句话摘要 + 请求摘要 / 网关原文 / 排查建议」按行拼成字符串，
 * 这里拆开重新排版：摘要突出，网关原文用等宽块，并支持一键复制整段去问人。
 */

const BLOCK_KEYS = ['请求摘要', '网关原文', '排查建议', '错误信息']

export function errorSummary(error: string | null | undefined): string {
  return error?.split('\n')[0]?.trim() ?? ''
}

function splitRows(lines: string[]) {
  return lines.map((line) => {
    const at = line.indexOf('：')
    if (at > 0 && at <= 6 && BLOCK_KEYS.includes(line.slice(0, at))) {
      return { label: line.slice(0, at), text: line.slice(at + 1) }
    }
    return { label: '', text: line }
  })
}

export default function ErrorDetail({ error }: { error: string | null }) {
  const [copied, setCopied] = useState(false)
  if (!error) return null

  const [summary = '', ...rest] = error.split('\n')
  const rows = splitRows(rest).filter((row) => row.text.trim())

  const copy = () => {
    void navigator.clipboard
      .writeText(error)
      .then(() => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1600)
      })
      .catch(() => setCopied(false))
  }

  return (
    <div className="border-danger/25 bg-danger/[0.04] rounded-card mt-5 w-full max-w-xl border p-4 text-left">
      <p className="text-danger text-sm leading-relaxed font-medium">{summary}</p>

      {rows.length > 0 && (
        <dl className="mt-3 space-y-2.5">
          {rows.map((row, index) => (
            <div key={index}>
              {row.label && <dt className="text-muted text-xs font-medium">{row.label}</dt>}
              <dd
                className={
                  row.label === '网关原文'
                    ? 'bg-paper border-line text-ink mt-1 max-h-32 overflow-auto rounded-control border p-2.5 font-mono text-[11px] leading-relaxed break-all whitespace-pre-wrap'
                    : 'text-muted mt-0.5 text-xs leading-relaxed'
                }
              >
                {row.text}
              </dd>
            </div>
          ))}
        </dl>
      )}

      <button
        type="button"
        onClick={copy}
        className="text-muted hover:text-ink border-line hover:border-line-strong mt-3 rounded-chip border px-2.5 py-1 text-xs transition-colors"
      >
        {copied ? '已复制' : '复制完整错误'}
      </button>
    </div>
  )
}
