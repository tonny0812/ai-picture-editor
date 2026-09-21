# 提示词库 · 模板 · 多轮创作 设计方案

> 面向 `ai-picture-editor` 的「创作」链路。目标：把好提示词沉淀下来、把常用套路做成模板、
> 让创作可以一轮轮往下改，而不是每次回到创作页从零开始。

**进度**：批次 1（后端地基）、批次 2（前端库与模板）已完成并部署；
批次 3（多轮：LLM 重写 + 轮次链）与批次 4（模板内容扩充）待做。
已确认的两个取舍：知识图谱／架构图**先走生图模板**（结构文字由人后期补）；
多轮用 **LLM 重写 + planner 不可用时降级为文本追加**。

---

## 一、需求拆解

| 诉求 | 本质 | 落地形态 |
|---|---|---|
| 积累好的提示词 | 生成结果满意时，把「提示词 + 结果图 + 参数」存下来，下次能直接复用 | **提示词收藏**（带预览图、标签、溯源到哪次生成） |
| 套用模板，分不同风格 | 常见场景有固定套路，只填几个变量就能出图 | **提示词模板**（变量占位 + 分类：人物 / 知识图谱 / 架构流程 / …） |
| 创作可以多轮 | 看到候选后说「再暖一点」「换个背景」，基于上一轮继续，而不是重打一遍 | **轮次链**（run 之间建立父子关系 + 提示词改写） |

---

## 二、开源参考与可借鉴点

调研了三类项目：通用 prompt 管理平台、图像领域的 prompt 库、多轮迭代生成。

### 1. 通用 prompt 管理平台

| 项目 | 量级 | 借鉴点 | 不适用之处 |
|---|---|---|---|
| [awesome-chatgpt-prompts](https://github.com/f/awesome-chatgpt-prompts) | ~167k ★ | **分类 + 一条 prompt 一个卡片 + 一键复制**，是最朴素也最好用的提示词库形态 | 没有版本与使用数据 |
| [Langfuse](https://github.com/langfuse/langfuse) | ~33k ★ | prompt registry：**版本化 + label（production/staging）+ 每次生成绑定到具体版本**、使用统计 | 面向 LLM 文本，重观测；我们要的是"轻" |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | ~24k ★ | 用 YAML 把 prompt 当配置管理、回归测试 | CLI/测试向，无 UI |

**借鉴**：卡片式列表 + 分类 + 一键套用 + 使用计数；**不做**版本分支（图像场景不需要那么重），
但保留 `source_run_id` 溯源到具体那次生成。

### 2. 图像领域的 prompt 库（最贴近）

| 项目 | 借鉴点 |
|---|---|
| **AUTOMATIC1111 的 Styles** | 最经典：`styles.csv` 存「名字 + 片段」，选中后**追加到当前 prompt**。简单到极致，用户心智零成本 |
| **Prompt Gallery**（SD WebUI 扩展） | YAML 三层分类（大类→子类→prompt-set），每个 set 带 `value` / `negative` / `param`，且**有预览图** |
| **sd-webui-oldsix-prompt**（中文） | 中文分类词库（人物/表情/服饰/场景/风格 13 类），左键加正向、右键加负向；支持 `#[选项1,选项2]` 随机语法 |

**借鉴**：模板要带 `negative` 和默认参数（比例/数量）、必须有**预览图**（否则记不住）、
分类要贴合中文用户习惯。

### 3. 多轮 / 迭代式生成

| 项目 | 借鉴点 |
|---|---|
| [eandrei/image-generation](https://github.com/eandrei/image-generation) | **Prompter → Generator → Evaluator 循环**：评估器打分、提示词改写器按反馈重写、保留 prompt/图/反馈的历史 |
| GenEvolve（美团×港科大） | 多轮工具调用 + 「视觉经验蒸馏」——把好的经验沉淀下来（正是"积累好提示词"的自动化版本） |
| LongCat-Image / LLaDA-Image | 模型侧原生多轮编辑（保持风格与光照一致） |

**借鉴**：「上一轮 prompt + 本轮指令 → 新 prompt」这一步交给 planner 模型做**重写**而不是简单拼接——
拼接会让 prompt 越来越长且互相矛盾（"红色"和"改成蓝色"同时存在）。

---

## 三、总体设计

### 3.1 三个对象

```
收藏 PromptEntry   —— 一条具体的、可以直接用的成品提示词（带预览图、标签、溯源）
模板 PromptTemplate —— 带 {{变量}} 的骨架，分类管理，内置 + 自建
轮次 Run Thread    —— tool_runs 之间用 parent_run_id 串起来，形成一轮轮的演化史
```

### 3.2 数据模型

```sql
-- ① 提示词收藏
prompt_entries (
  id                uuid pk,
  user_id           uuid fk users on delete cascade,
  title             varchar(80) not null,
  prompt            text not null,
  negative_prompt   text,
  ratio             varchar(8),              -- 当时用的画幅，复用时回填
  category          varchar(32) not null,    -- portrait / knowledge_graph / architecture / product / poster / illustration / other
  tags              jsonb not null default '[]',
  preview_asset_id  uuid fk assets on delete set null,  -- 缩略图：复用已有素材，不重复占存储
  source_run_id     uuid fk tool_runs on delete set null, -- 溯源：从哪次生成收的
  note              text,
  use_count         int not null default 0,
  last_used_at      timestamptz,
  created_at, updated_at
)

-- ② 提示词模板
prompt_templates (
  id               uuid pk,
  user_id          uuid fk users on delete cascade,  -- NULL = 内置模板（所有人可见、只读）
  title            varchar(80) not null,
  category         varchar(32) not null,
  description      text,
  prompt_template  text not null,     -- 含 {{subject}} / {{style:水彩}} 这类占位
  negative_template text,
  variables        jsonb not null default '[]',
    -- [{"name":"subject","label":"主体","placeholder":"一位…","default":"","options":["可选A","可选B"]}]
  default_ratio    varchar(8) default '1:1',
  default_count    int default 4,
  preview_asset_id uuid fk assets on delete set null,
  use_count        int not null default 0,
  created_at, updated_at
)

-- ③ 轮次：复用 tool_runs，只加三列，不新建表
ALTER TABLE tool_runs ADD COLUMN parent_run_id uuid references tool_runs(id) on delete set null;
ALTER TABLE tool_runs ADD COLUMN round        int not null default 1;
ALTER TABLE tool_runs ADD COLUMN round_note   text;  -- 本轮用户指令："背景换成海边，光线更暖"
```

**为什么收藏和模板分两张表**：收藏是「成品」，模板是「骨架」；两者字段差异大
（模板有变量定义、默认参数），混在一张表会出现半数字段永远为空。
收藏支持一键「另存为模板」（把其中几个词抽成变量）。

**为什么轮次不新建表**：一轮本质上就是一次 `generate_image` run，
已有 `tool_runs` 的 status / progress / result / error 全部复用，
加父子指针即可，事件推送、队列、重试都不用改。

### 3.3 变量语法

```
{{name}}              必填变量
{{name:默认值}}        选填，留空则用默认值
```

渲染（前端实时预览 + 后端提交前校验）：

```
模板：{{subject}}，{{style:水彩}}风格，{{light:柔和侧光}}，高清细节
输入：subject=江南古镇的石桥
输出：江南古镇的石桥，水彩风格，柔和侧光，高清细节
```

### 3.4 API

```
# 收藏
GET    /api/prompts/entries?category=&q=&tag=    列表（q 搜标题/提示词/标签）
POST   /api/prompts/entries                      收藏（可带 source_run_id + preview_asset_id）
PATCH  /api/prompts/entries/{id}
DELETE /api/prompts/entries/{id}
POST   /api/prompts/entries/{id}/use             复用（use_count+1，返回可直接填表的 prompt）

# 模板
GET    /api/prompts/templates?category=          内置（user_id IS NULL）+ 我自建的
POST   /api/prompts/templates
PATCH  /api/prompts/templates/{id}               内置模板改 → 403
DELETE /api/prompts/templates/{id}
POST   /api/prompts/templates/{id}/render        {values:{...}} → {prompt, negative_prompt}

# 多轮
POST   /api/prompts/rewrite                      {base_prompt, instruction} → {prompt}
POST   /api/generations                          入参新增 parent_run_id / round_note
GET    /api/runs/{id}/thread                     整条轮次链（含每轮的候选图与 prompt）
```

### 3.5 前端交互

**创作页 `CreatePage`**
- 输入框上方加一排「模板」胶囊：按分类分组，点开后弹出变量表单，填完把渲染结果塞进输入框；
- 输入框右侧加「收藏夹」入口 → 打开抽屉/新页，卡片列表（缩略图 + 标题 + 标签），点「套用」回填。

**候选页 `CandidatesPage`（多轮主战场）**
- 顶部：轮次条 `第 1 轮 › 第 2 轮 › 当前`，可点回看任意一轮的候选；
- 底部：「继续优化」输入框 → 调 rewrite 得到新 prompt（**可编辑**）→ 提交第 N+1 轮；
- 可勾选「以这张为参考」→ 新一轮带上 `reference_asset_ids`，走图生图而非重新文生图；
- 满意的那条上提供「收进提示词库」，自动带上当前图作预览图、溯源到当前 run。

---

## 四、多轮创作：三种模式，推荐「手动 + LLM 重写」

| 模式 | 做法 | 优点 | 代价 |
|---|---|---|---|
| A 纯文本追加 | 新 prompt = 旧 prompt + "，" + 指令 | 零成本、零延迟 | prompt 越来越长；冲突指令互相打架（"红色" vs "改成蓝色"） |
| **B LLM 重写（推荐）** | planner 模型接收「旧 prompt + 本轮指令」，输出一份**完整的新 prompt** | 能覆盖冲突、去重、压长度；用户看到的是可读的一句话 | 多一次 LLM 调用（约 1-3 秒），依赖 planner 可用 |
| C 自动评估循环 | Evaluator 打分 → Prompter 改写 → 再生成，达标才停 | 无需人盯 | 成本极高（N×出图 + N×视觉评估），额度烧不起 |

推荐 **B**，同时把 A 留成兜底：planner 不可用或超时时降级为追加，并在界面上说明。
C 只作为后续可选（且建议默认关闭）。

rewrite 的系统提示要点：只输出最终 prompt、不要解释、保留原风格约束、
新指令覆盖旧指令中的冲突部分、控制在 200 字内。

---

## 五、知识图谱 / 架构流程图：两条路，需要你定

这类图和「人物写真」的性质完全不同——**结构和文字必须准确**，而文生图模型恰恰不保证这个。

| 路径 | 做法 | 效果 | 工作量 |
|---|---|---|---|
| **A 生图模板** | 模板约束风格（白板手绘 / 扁平矢量）、配色、版式，并**预留留白**，生图后由人在编辑器里补文字 | 氛围好、出图快；但图里的字和连线是"画"出来的，可能错乱 | 小，随模板体系一起做 |
| **B LLM 结构化渲染** | planner 生成 Mermaid / Excalidraw JSON → 前端渲染成 SVG → 转图片进编辑器 | 结构准确、可继续编辑、文字清晰 | 大，是独立模块（新增渲染器 + 存储 + 编辑器接入） |

**建议**：一期先做 A（把「知识图谱」「架构流程」作为两个分类的模板，
模板里明确写「留出中央空白用于后期添加文字」「不要渲染具体文字」这类负面约束），
跑一段时间看真实需求强度，再决定要不要上 B。

---

## 六、分批实施计划

### 批次 1（后端地基）
1. 迁移：新建 `prompt_entries` / `prompt_templates`；`tool_runs` 加 `parent_run_id` / `round` / `round_note`
2. `app/prompts.py`：变量解析与渲染（`render_template` / `extract_variables`），纯函数、易测
3. `app/services/prompts.py`：收藏与模板的 CRUD（内置模板只读、越权 404/403）
4. `app/routers/prompts.py`：上述 API
5. 测试：渲染（必填缺失、默认值、转义）、CRUD 权限、内置模板不可改

### 批次 2（前端 · 库与模板）
6. `api/prompts.ts` + 查询 hooks
7. 创作页：模板胶囊 + 变量表单弹层（实时预览渲染结果）
8. 收藏抽屉/页面：卡片列表 + 搜索 + 标签过滤 + 套用
9. 候选页：「收进提示词库」入口（带上当前图与 run 溯源）

### 批次 3（多轮）
10. `POST /api/prompts/rewrite`：调 planner 重写，失败降级为追加
11. `POST /api/generations` 支持 `parent_run_id` / `round_note`；`GET /api/runs/{id}/thread`
12. 候选页：轮次条 + 「继续优化」+ 可选「以这张为参考」
13. 端到端测试：三轮链路、回看、rewrite 降级

### 批次 4（内容）
14. 内置模板种子（人物 / 知识图谱 / 架构流程 / 产品 / 海报 / 插画 六个分类，每类 1-2 个）
15. 文档与变更记录

---

## 七、风险与取舍

- **预览图依赖素材**：收藏的预览图指向 `assets`，素材被删时置 NULL（不级联删收藏），
  前端要有占位图。
- **内置模板与自建模板混排**：接口返回时内置在前、自建在后；内置 `user_id IS NULL` 且
  写操作返回 403，避免用户误改公共内容。
- **prompt 长度**：模板渲染后可能超 `MAX_PROMPT`，提交前校验并提示。
- **rewrite 的额外开销**：每次「继续优化」多一次 planner 调用。已在方案里设计降级路径。
- **不做版本分支**：图像场景的收藏是"我觉得这条好"，不是"线上灰度发布"，
  版本化收益小于复杂度。若将来需要，可加 `revisions` 表。
