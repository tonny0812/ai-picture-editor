import LlmConfigForm from '@/components/LlmConfigForm'

export default function SettingsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-ink text-2xl font-semibold tracking-tight">设置 · 模型接口</h1>
        <p className="text-muted mt-2 text-sm">
          不填任何内容即可使用系统默认配置。填写自己的接口信息后立即生效（无需重启），
          只影响你自己的任务，不影响他人。
        </p>
      </header>

      <div className="border-line bg-paper shadow-panel rounded-panel border p-8">
        <LlmConfigForm mode="user" />
      </div>
    </div>
  )
}
