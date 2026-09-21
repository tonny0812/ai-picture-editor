/**
 * 模板变量的前端渲染。
 *
 * 规则与后端 app/prompts.py 保持一致（同一套正则与清理口径），否则会出现
 * 「界面预览是这样、提交后变那样」。差别只在一处：后端缺必填会直接报错，
 * 前端预览要把缺失处留空，让用户在输入过程中也能看到大致效果。
 */

const VARIABLE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([^{}]*?)\s*)?\}\}/g

export function extractVariables(template: string): string[] {
  const names: string[] = []
  for (const match of template.matchAll(VARIABLE)) {
    if (!names.includes(match[1])) names.push(match[1])
  }
  return names
}

/** 缺值又没默认值的变量——用于禁用「生成」按钮并提示用户。 */
export function missingVariables(template: string, values: Record<string, string>): string[] {
  const missing: string[] = []
  for (const match of template.matchAll(VARIABLE)) {
    const [, name, rawDefault] = match
    const value = (values[name] ?? '').trim()
    if (!value && rawDefault === undefined && !missing.includes(name)) missing.push(name)
  }
  return missing
}

function tidy(text: string): string {
  return text
    .replace(/[,，]{2,}/g, '，')
    .replace(/\s*[,，]\s*(?=\n|$)/g, '')
    .replace(/(?<!\S)[,，]\s*/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

/** 预览用：必填缺失也不抛错，缺失处按空处理。 */
export function renderPreview(template: string, values: Record<string, string>): string {
  const rendered = template.replace(VARIABLE, (_, name: string, rawDefault?: string) => {
    const value = (values[name] ?? '').trim()
    return value || (rawDefault ?? '').trim()
  })
  return tidy(rendered)
}
