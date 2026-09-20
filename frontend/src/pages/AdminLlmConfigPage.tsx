import { useQuery } from '@tanstack/react-query'

import LlmConfigForm from '@/components/LlmConfigForm'
import { llmConfigApi } from '@/api/llmConfig'
import { errorMessage } from '@/hooks/useAuth'

const ACTION_LABEL: Record<string, string> = {
  update: '修改',
  clear: '清除',
  test: '测试',
}

function describeDiff(diff: Record<string, unknown>): string {
  const parts = Object.entries(diff).map(([key, value]) => {
    if (value === '已变更' || value === '已清除') return `${key} ${value}`
    if (typeof value === 'object' && value !== null && 'to' in value) {
      const to = (value as { to: unknown }).to
      return `${key} → ${String(to)}`
    }
    return `${key}: ${String(value)}`
  })
  return parts.join('；') || '—'
}

export default function AdminLlmConfigPage() {
  const audit = useQuery({ queryKey: ['llm-config', 'audit'], queryFn: llmConfigApi.audit })

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-ink text-2xl font-semibold tracking-tight">管理 · 全局模型配置</h1>
        <p className="text-muted mt-2 text-sm">
          全局默认对所有未自行覆盖的用户生效，保存后热生效（无需重启）。
          角色管理目前请使用 CLI：<code className="bg-soft rounded px-1.5 py-0.5">./dev.sh promote 用户名</code>
        </p>
      </header>

      <div className="border-line bg-paper shadow-panel rounded-panel border p-8">
        <LlmConfigForm mode="global" />
      </div>

      <section className="mt-10">
        <h2 className="text-ink mb-3 text-sm font-semibold">变更审计（最近 100 条）</h2>
        {audit.isPending && <p className="text-muted text-sm">加载审计…</p>}
        {audit.isError && <p className="text-danger text-sm">{errorMessage(audit.error)}</p>}
        {audit.data && audit.data.length === 0 && (
          <p className="text-faint text-sm">还没有任何配置变更记录。</p>
        )}
        {audit.data && audit.data.length > 0 && (
          <div className="border-line bg-paper overflow-hidden rounded-[18px] border">
            <table className="w-full text-left text-sm">
              <thead className="bg-soft text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">时间</th>
                  <th className="px-4 py-2.5 font-medium">范围</th>
                  <th className="px-4 py-2.5 font-medium">动作</th>
                  <th className="px-4 py-2.5 font-medium">内容</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.map((entry) => (
                  <tr key={entry.id} className="border-line border-t">
                    <td className="text-muted px-4 py-2.5 whitespace-nowrap">
                      {entry.created_at ? new Date(entry.created_at).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-2.5">{entry.scope === 'global' ? '全局' : '个人'}</td>
                    <td className="px-4 py-2.5">{ACTION_LABEL[entry.action] ?? entry.action}</td>
                    <td className="text-muted px-4 py-2.5 break-all">{describeDiff(entry.diff)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
