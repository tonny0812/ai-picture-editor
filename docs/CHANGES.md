# 本地部署与二次开发改动记录

> 记录时间：2026-09-17 · 基线：克隆自 https://github.com/tonny0812/ai-picture-editor
> 全部改动**尚未提交**（`git status` 可见 5 个修改 + 5 个新增），可 `git diff` 逐条 review。

## 一、部署现状

| 服务 | 地址 | 凭据 |
|---|---|---|
| Web 应用 | http://localhost:7302 | 自行注册（测试账号 smoketest / smoke1234） |
| 接口文档 | http://localhost:7302/api/docs | — |
| MinIO 控制台 | http://localhost:7314 | retouch / retouch_dev |
| PostgreSQL | localhost:7311 | retouch / retouch_dev |
| Redis | localhost:7312 | — |

容器：`ai-retouch-agent-{app,worker,postgres,redis,minio}-1` 全部 healthy。
Alembic 7 个迁移已应用；**167 个后端 pytest 全绿**；自写冒烟脚本 **23 项端到端全绿**。

当前 `.env` 用 `IMAGE_PROVIDER=mock`（占位图，免 API Key）。接真实模型见第四节。

## 二、修改的文件（5 个）

### 1. `docker-compose.yml` — MinIO 镜像源修复

```yaml
- image: minio/minio:latest
+ image: quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z
```

原因：MinIO 官方已下架 Docker Hub 社区镜像（`pull access denied`），官方现存分发渠道为 Quay。顺手锁版本避免 latest 漂移。

### 2. `backend/app/main.py` — SPA 深链回退（不修则刷新 404）

新增 `SPAStaticFiles`：前端用 `BrowserRouter` 真实路径，原 `StaticFiles(html=True)` 不做回退，在 `/editor/xxx` 按 F5 直接 404。现在非 API/非静态路径回落 `index.html`，同时保证 `/api`、`/events` 的 404 不被吞（不会把接口 404 错误地回成页面）。

### 3. `backend/app/config.py` — 新增网关相关配置项

```python
# 对话规划模型（OpenAI 兼容）
planner_base_url: str = ""      # 留空回退百炼 compatible-mode
planner_api_key: str = ""       # 留空回退 DASHSCOPE_API_KEY
planner_timeout: float = 60.0
planner_max_retries: int = 2

# 图像模型（OpenAI 兼容 images API）
images_base_url: str = ""       # 留空复用 planner_* 
images_api_key: str = ""
images_model: str = ""
images_sizes: str = ""          # 如 "1024x1024,1536x1024,1024x1536"
```

### 4. `backend/app/agent/llm.py` — 规划模型可配置化

- `base_url` 支持任意 OpenAI 兼容网关（`PLANNER_BASE_URL` 需自带 `/v1`），不再硬编码百炼路径；
- `PLANNER_API_KEY` 优先，缺失回退 `DASHSCOPE_API_KEY`；
- **补上 `timeout` 和 `max_retries`**（原代码完全没有——这同时是审计报告中 B2 项的修复）。

### 5. `backend/app/providers/__init__.py` — 注册 `openai` Provider 分支

`IMAGE_PROVIDER=openai` 时启用新的 `OpenAIImagesProvider`。

## 三、新增的文件（5 个）

| 文件 | 用途 |
|---|---|
| `backend/app/providers/openai_images.py` | OpenAI 兼容图像 Provider，实现 `generate / edit / upscale`。关键设计：图生图用 JSON+dataURI（不用 multipart，聚合网关不认）；**不做端点静默回退**——`/images/edits` 挂了就明确报错；`n` 拆成 n 个 `n=1` 并行请求；配置 `IMAGES_SIZES` 后按最近比例选档、下载后中心裁切回目标尺寸 |
| `backend/tests/test_openai_images.py` | 上述 Provider 的 7 个单测（尺寸选档/裁切/响应解析等） |
| `backend/scripts/probe_gateway.py` | 网关能力探测：`/models` 可达性、模型是否支持 function calling、`/images/generations` 尺寸档、`/images/edits` 是否可用。`./dev.sh probe` 一键跑 |
| `dev.sh` | 日常运维脚本（见下） |
| `smoke-test.py` | 23 项端到端冒烟：登录、文生图、签名 URL 匿名下载、同步/异步工具、revision 推进、撤销重做、ZIP 导出、422/404/越权等 |

另有本地配置 `.env`（已 gitignore，不入库）。

### `dev.sh` 命令速查

```bash
./dev.sh up|down|restart   # 启停（up 自动迁移数据库）
./dev.sh urls|ps|logs [svc]
./dev.sh migrate           # alembic upgrade head
./dev.sh shell             # 进 app 容器
./dev.sh probe             # 网关能力探测
./dev.sh smoke             # 23 项端到端冒烟
./dev.sh test              # 后端 pytest（一次性容器，自动补 dev 依赖）
./dev.sh lint              # ruff 检查
./dev.sh reset             # ⚠️ 清空数据卷重来
```

## 四、接真实模型（✅ 2026-09-17 已接入并验证）

`.env` 当前生效配置：`PLANNER_BASE_URL/IMAGES_BASE_URL=http://keepgulp.com:8002/v1`，规划模型 `kimi-k3`，生图模型 `hunyuan-image-alpha`，`IMAGE_PROVIDER=openai`，`IMAGES_SIZES=1024x1024,1536x1024,1024x1536,1080x1350,1080x1920`（探测实测档位）。

**网关探测结论**（`./dev.sh probe`）：
- 文生图 5 档全通、图生图（dataURI+JSON）可用 → 改图类工具全部可用
- kimi-k3 **支持 function calling**（注意：它是推理模型，思考计入 completion tokens，`max_tokens` 太小会误报不支持——探测脚本已修正为 4000）
- `/models` 端点对该 key 返回 401，是网关该端点的怪癖，不影响功能

**端到端实测**：
- 23 项冒烟全绿（真实出图，PNG ~900KB 非占位图）
- 单步对话「把图片水平翻转」：kimi-k3 规划 → 直接执行 → revision +1 ✅
- 冒烟中「把背景换成海滩」：`replace_background` 真实执行成功 ✅
- 两步对话「翻转，然后调亮」：规划出 `flip_layer`+`adjust_image` → HITL 确认（`POST /messages/{turn_id}/confirm`）→ 全部成功，revision +2 **无重复执行**
- ⚠️ 注：审计静态分析的 P0（A1 重复执行）在此两步场景**未复现**，但触发条件涉及特定交错时序，修复项仍建议保留在路线图
- 多步计划卡在 `queued` 不是故障，是 HITL 设计：等用户在前端点确认

## 五、已知问题（改前先看 OPTIMIZATION-ROADMAP.md）

- **P0**：多步计划会重复执行同一工具（`services/agent.py:204-232` 双层 `_advance` 重入），触发条件日常（如「翻转再调亮」两步指令）；
- **P1**：`needs_approval` 审批机制全项目从未置 True，等于空跑；
- **P1**：`worker.py` 的 `job_timeout=300` 与 DashScope 轮询超时 300s 打平，长任务必被 ARQ 杀掉；
- 完整 33 条见工作区 `ai-picture-editor-代码优化方案.html`（含路线图与验收标准）。

## 六、LLM 接口页面化配置 · 批次①角色地基（✅ 2026-09-20 已实施）

按 `LLM-CONFIG-DESIGN.md` §8 批次①交付，全部测试与线上验证通过。

**改动清单**：

| 类型 | 文件 | 内容 |
|---|---|---|
| 改 | `backend/app/models/user.py` | 新增 `Role` 枚举（user/admin）与 `users.role` 列 |
| 增 | `migrations/versions/20260920_1716_users_role.py` | 加列迁移，存量用户回填 `user` |
| 改 | `backend/app/deps.py` | `require_admin` 依赖 + `AdminUser` 类型（403 闸门） |
| 增 | `backend/app/cli.py` | `python -m app.cli promote/demote/list` 运维命令 |
| 增 | `backend/app/routers/admin.py` | `GET /api/admin/users`、`PATCH /api/admin/users/{id}/role` |
| 增 | `backend/app/schemas/admin.py` | `AdminUserOut` / `RolePatchIn` |
| 改 | `backend/app/config.py` | `ADMIN_USERNAMES` 白名单（逗号分隔，注册时精确命中即 admin） |
| 改 | `backend/app/schemas/auth.py` | `UserOut` 增加 `role`（`/api/auth/me` 可见，前端守卫用） |
| 改 | `dev.sh` | 新增 `promote` / `demote` / `users` 三个命令 |
| 增 | `backend/tests/test_admin_roles.py` | 18 项权限矩阵测试 |

**安全约束（已实现并测试）**：
- `PATCH role` 禁止操作自己（400）——防止最后一个管理员自锁；CLI `demote` 拒绝降级唯一管理员；
- 白名单是精确匹配（大小写/空白都不算命中）；
- 角色每请求从数据库读取：CLI 提权后**旧会话立即生效**，无需重新登录。

**验证**：185 项单测全绿（167 + 18）、ruff 通过、迁移 `fa850313b768 → b7d24f0a91ce` 成功、23 项冒烟全绿；
线上实测：普通用户访问 admin 接口 403 → `./dev.sh promote` → 同一会话 200 → 改自己角色 400。

**给当前部署提权管理员**：`./dev.sh promote <用户名>`（库里现有账号见 `./dev.sh users`）。

---

## 四、批次②③ — LLM 接口页面化配置（2026-09-20）

### 1. 配置模型：全局默认 + 用户覆盖三层合并

生效顺序：**用户覆盖 > 全局配置 > `.env` 兜底**。管理员在管理页配全局默认值，普通用户可在设置页覆盖自己的
（如换成本人网关密钥），清除个人覆盖即回到全局默认。

| 类型 | 文件 | 内容 |
|---|---|---|
| 增 | `backend/app/llm_config.py` | `ResolvedLlmConfig` 数据类 + 指纹计算 + `mask_secret` |
| 增 | `backend/app/services/crypto.py` | Fernet 对称加密（密钥由 `JWT_SECRET` 派生，未配时兜底） |
| 增 | `backend/app/models/llm_config.py` | `LlmConfig`（scope=global/user）+ `LlmConfigAudit` 审计表 |
| 增 | `migrations/versions/20260920_2001_llm_configs.py` | 建表迁移（含 `lock_image_provider` 列） |
| 增 | `backend/app/services/llm_config.py` | 解析服务：三层合并、TTL 缓存、SSRF 校验、审计、连接测试 |

- **热生效**：provider / planner 按配置指纹缓存，保存后立即失效重建，**不用重启容器**；
- **密钥安全**：API Key 落库前 Fernet 加密，接口只回 `sk-***abcd` 掩码，永不回明文；
- **SSRF 防护**：`base_url` 写入时校验，拒绝内网/回环/link-local 地址；
- **worker 隔离**：异步任务载荷只带 `user_id`，到 worker 内再解析配置，避免跨用户串 key。

### 2. 强制锁（lock_image_provider）

全局开关，默认关闭。开启后**禁止用户覆盖 `image_provider`**：防止普通用户把真模型切成 `mock`
（占位假图）绕开额度或被假图误导。前端表现为下拉框禁用 + 明确提示。

### 3. 接口与页面

| 类型 | 文件 | 内容 |
|---|---|---|
| 增 | `backend/app/routers/me.py` | `GET/PUT/DELETE /api/me/llm-config`、`POST /api/me/llm-config/test` |
| 改 | `backend/app/routers/admin.py` | 全局配置读写/测试 + 审计日志查询（均 403 闸门） |
| 增 | `backend/app/schemas/llm_config.py` | 读写与测试响应的 Pydantic 模型 |
| 增 | `frontend/src/api/llmConfig.ts` | 前端 API 封装；`api/client.ts` 补 `put` 方法 |
| 增 | `frontend/src/components/LlmConfigForm.tsx` | 用户/全局共用表单组件（含来源标记、只写密钥、测试连接） |
| 增 | `frontend/src/pages/SettingsPage.tsx` | 个人设置页（覆盖 + 清除 + 测试） |
| 增 | `frontend/src/pages/AdminLlmConfigPage.tsx` | 管理员全局配置页（含强制锁 + 审计流水） |
| 增 | `frontend/src/layouts/RequireAdmin.tsx` | 路由级 admin 守卫 |
| 改 | `frontend/src/App.tsx` / `WorkbenchLayout.tsx` | 新增 `/settings`、`/admin/llm-config` 路由与导航入口 |
| 增 | `backend/tests/test_llm_config.py` | 解析顺序/强制锁/加密/SSRF/权限测试 |

访问路径：普通用户 `http://localhost:7302/settings`；管理员额外有 `/admin/llm-config`
（导航入口仅 admin 可见）。

### 4. 已修复缺陷与验证状态（2026-09-21 上线验证）

本机部署实测暴露并已修复的问题：

| 缺陷 | 现象 | 修复 |
|---|---|---|
| `uv.lock` 未同步 `pyproject` | 容器启动即崩：`ModuleNotFoundError: cryptography` | 重新生成锁文件（新增 cryptography/cffi/pycparser） |
| `graph.run()` 签名缺 `config` | 所有 Agent 规划失败（`takes 2 positional arguments but 3 given`），22 项测试红 | 补 `config` 参数并纳入初始状态 |
| `admin.py` 缺 `crypto` 导入 | 管理员保存全局 API Key 时 `NameError` | 补 `from app.services import crypto` |
| 用户 PUT 只含被忽略字段 | 返回 400，语义不清 | 视为空操作，返回当前配置视图 |
| 测试共用同一用户名 | `admin_client` 与 `signed_in` 重复注册 409，后续请求 401 | `signed_in` 改用另一套凭据 |
| 测试 `_set_user` 重复 INSERT | 撞 `uq_llm_config_user` 唯一约束 | 改为 upsert |

构建层面同样加固：`Dockerfile` 为 `uv sync` 与 `npm ci` 加 BuildKit 缓存挂载，并新增
`UV_INDEX_URL` 构建参数以切换 PyPI 镜像源（直连不稳时用清华源）。

**验证**：214 项 pytest 全绿、ruff 全部通过、23 项端到端冒烟全绿、健康检查三项 ok；
迁移链 `b7d24f0a91ce → c3a9f1b02d47` 已在线应用。镜像重建耗时主要来自 Python 依赖与 CV 模型
（u2net/SAM 约 290MB）下载，加了缓存挂载后重复构建会快很多。

---

## 五、兼容「一次请求返回多张」的文生图网关（2026-09-21）

**背景**：自建/聚合网关对 `n` 的支持很不一致——有的忽略 `n` 一次回多张，有的把多张塞进
`data` 数组，还有的直接返回字符串数组（base64 串或 http 链接）。原来的适配器只取
`data[0]`，**多返回的图被静默丢掉**，用户花了额度却只拿到一张。

### 适配器改造（`app/providers/openai_images.py`）

| 项 | 改造前 | 改造后 |
|---|---|---|
| 响应解析 | `items[0]`，只取第一张 | `_extract_all()` 取出**全部**图片并保持顺序 |
| 结果形态 | 只认 dict 里的 `b64_json` / `url` | 兼容 dict、纯 base64 串、纯 http 链接；`data` 或 `choices` |
| 坏项处理 | 整批报错 | 跳过坏项保留可用图，只记 warning；全坏才报错 |
| 多次请求 | 每张一个请求 | 保持并行，结果**展平**（`_flatten`），实际张数多于请求数记日志 |
| base64 | 手工 `b64decode` | `decode_base64()` 统一处理 dataURI 前缀与 padding |

### 上层语义（返回多张时怎么办）

- **创作候选**（`/api/generations`）：全部落成候选图，图片墙照数展示（前端本就按数组渲染）；
- **换背景**（`replace_background`）：判定条件由 `count > 1` 改为 `len(images) > 1`，
  网关多返回时同样**全部进图片墙**、不自动上画布；
- **批量任务**（`batch_process`）：一进一出，`images[:1]` 取首张，避免产物数量与素材数量错位；
- **区域编辑 / 拆层补洞 / 超分**：必须合并回图层，显式取首张（代码内已注明理由）。

### 验证

新增 9 项测试：`test_openai_images.py` 6 项（多 b64、字符串+链接混排、坏项跳过、
`choices` 回退、单请求展平、多请求展平）、`test_generation.py` 1 项（网关多返回 →
多候选落盘）、`test_tools.py` 1 项（换背景下 count=1 但回 2 张全部上墙）。
全量 **223 项 pytest 全绿**，ruff 通过。

> 说明：`count > 1` 时仍是 `count` 个并行请求。若网关一次就能返回足量图，
> 请求数会偏多（例如 count=4 且网关每次回 4 张 → 共 16 张候选）。这是刻意取舍：
> 并行保证延迟，多出的图都作为候选保留而非丢弃；如需省额度可后续加
> 「首请求够数即止」的顺序策略。

---

## 六、生图失败只显示 "upstream 400" —— 把网关原文透出来（2026-09-21）

**现象**：创作页生成失败，失败原因只有一句 `upstream 400`，看不出是提示词、
参数、并发还是上游故障，只能盲试。

**根因**：两层信息丢失。

1. 聚合网关把上游错误压缩成一句 `upstream 400`，原始响应里的 `type` / 详情被丢掉；
2. 适配器的 `parse_response` 又只取 `error.message` 这一层，
   连那一点点上下文也没带上，最终写进 `tool_runs.error` 的就是光秃秃四个单词。

### 后端：错误信息自带排查上下文

`ProviderError` 新增 `detail` 字段与 `report` 属性（摘要 + 详情），
`services/tools.py` 落库时改用 `exc.report`，用户侧看到的是：

```
图像网关返回 HTTP 400：Image generation model 'xxx' is not supported. Only supported: ...
请求摘要：POST /images/generations · 模型 xxx · 尺寸 1024x1024 · 提示词 4 字 · 张数 1 · 无参考图
网关原文：{"error": {"message": "...", "type": "invalid_request"}}
排查建议：提示词可能触发上游内容策略、含不支持的参数，或请求过大。可依次尝试：...
```

- `build_upstream_error()` 统一组装；`_extract_message()` 兼容
  `error.message` / `error` 字符串 / 平铺 `message` / 纯文本 / 非 JSON 五种形态；
- 按状态码给排查建议（400 内容策略或参数、401 密钥、404 模型名、429 限流、5xx 上游故障）；
- 网关原文截断到 800 字后原样保留，可直接复制给网关管理员。

### 后端：请求侧的加固

| 项 | 改动 |
|---|---|
| 并发上限 | 新增 `IMAGES_MAX_CONCURRENCY`（默认 **2**）。一次要 4 张时不再同时打 4 个请求——聚合网关普遍限并发，这是 400/429 的常见来源 |
| 自动重试 | 429 / 408 / 5xx 按 `IMAGES_MAX_RETRIES`（默认 2）指数退避重试；**400 不重试**（请求本身有问题，重试无意义，直接把原文报给用户） |
| 连接错误 | 带上端点与原始异常，不再只说"连接失败" |

### 前端：错误卡片

新增 `components/ErrorDetail.tsx`，把多段错误按「请求摘要 / 网关原文 / 排查建议」
分区排版，网关原文用等宽可滚动块，并支持一键复制整段。
候选页失败态从一行 hint 换成该卡片；会话页的提示条只播首行摘要，避免长文本刷屏。

### 验证

- 全量 **234 项 pytest 全绿**（新增 11 项），ruff 通过；
- 真机复现：用不存在的模型名打网关，错误四段齐全；
- 真机压测：`count=4`、并发上限 2，4 张全部成功，21.5s。

> 排查记录：把库里 4 条失败任务的 prompt 原样重放，串行全部 200 成功，
> 说明那批 400 与提示词内容无关，更像是并发/瞬时故障——并发上限与重试正是针对这一点。

---

## 七、提示词库 + 模板 + 创作页入口（2026-09-21）

对应 `docs/PROMPT-LIBRARY-DESIGN.md` 的批次 1（后端地基）与批次 2（前端库与模板）。

**背景**：好提示词散落在一次次生成里，用完就丢；常见场景（人物、知识图谱、架构流程）
每次都要从零拼。

### 后端

- 新增 `prompt_entries`（收藏）与 `prompt_templates`（模板）两张表，
  迁移 `c3a9f1b02d47 → f736011e6f77`；
- `tool_runs` 加 `parent_run_id` / `round` / `round_note` 三列，为多轮预留（批次 3 才用上）；
- `app/prompts.py`：变量语法 `{{name}}` / `{{name:默认值}}` 的解析与渲染，
  纯函数模块，前后端共用同一套规则；
- `app/services/prompts.py` + `app/routers/prompts.py`：
  `/api/prompts/entries`（收藏增删改查 + 复用计数）、
  `/api/prompts/templates`（内置只读 + 自建 CRUD + render）；
- 内置模板 `user_id IS NULL`，写操作一律 403；
- `RunOut` 补 `negative_prompt` / `ratio`，候选页存收藏时能把参数一并带走。

### 前端

- `GenerateForm` 改为受控组件（草稿提升到页面），模板与提示词库才能回填；
- `TemplatePicker`：分类胶囊 → 变量表单 → 实时预览 → 回填输入框；
  回填走后端 render（结果权威 + 累计使用次数）；
- `PromptLibrary`：存当前（标题/标签/分类）+ 已存列表（搜索/套用/删除）；
- 候选页新增「收进提示词库」，带上预览图与 `source_run_id` 溯源。

### 内置模板

`python -m app.cli seed-prompts` 写入 6 个（人物 / 知识图谱 / 架构流程 / 产品 / 海报 / 插画），
按标题 upsert，改了模板重跑即可。

知识图谱与架构流程两类按约定**只画结构不写字**（模型画不准字），
模板里明确要求"节点留白、内部不写任何文字"，文字由人在编辑器里补。

### 验证

252 项 pytest 全绿（新增 18 项），ruff 通过，23 项端到端冒烟全绿，健康检查 ok。

### 实现中修掉的坑

- `{{x:}}` 这种"默认值为空"的写法被误判成必填——改为「有冒号即视为选填」。
- 模板变量留空会留下连续逗号，渲染后统一 `tidy()` 清理，否则就是一堆 `，，` 丢给网关。
- 测试数据跨用例残留：内置模板不清理会污染后续断言，加了按表清空夹具。

### 补充：跑测试会清掉内置模板

测试用的是同一个 dev 库，`test_prompts.py` 为保证用例隔离会整表清空
`prompt_templates` / `prompt_entries`，内置模板（`user_id IS NULL`）也一并被清。
表现为「跑完测试，创作页模板入口空了」。

应对：`./dev.sh seed` 可随时重写内置模板（按标题 upsert，改了模板重跑即可）；
`./dev.sh test` 已改为跑完自动补种。

---

## 八、局部编辑与原图无关 —— 图生图请求漏传目标尺寸（2026-09-21）

**现象**：局部修改（replace_region）出的结果跟原图毫无关系——输入是 1080x1440
竖版人像，输出却是 1920x1920 的陌生人。

### 排查过程（三层实测，全部有据）

1. **网关探针**：红蓝特征图 + 「保持不变」提示词打 `/images/edits`，
   `image` / `image_url` 两种字段都返回红蓝各半——参考图被正确采纳，
   `/images/edits` 端点也已恢复可用（此前 10053 的结论过时）；
2. **历史任务导出**：9-18 那次 replace_region 的输入（仙女图 1080x1440）
   与输出（陌生蓝裙女子 1920x1920）肉眼比对，确认是纯文生图——
   属于 `/images/edits` 不可用时期旧代码的遗留结果；
3. **修复后真机复现**：同一张仙女图 + 同一句「将裙子改成淡蓝色…」，
   返回图保持人物、构图、光线，尺寸精确 1080x1440。

### 根因与修复

`EditRequest` 的四个调用点（局部编辑 / 拆层补洞 / 换背景 / 批量换背景）
**都没传 width/height**：

- 网关收不到 `size`，返回图比例随缘（9-18 那次直接给了 1920x1920 方图）；
- `fit_image` 收不到目标尺寸，不做矫正，回贴图层时被 `apply_masked`
  硬 resize 拉变形——比例一错，构图面目全非。

修复：四处统一用 `probe(source)` 取源图尺寸传入 `EditRequest`。
这样即使网关不跟随参考图尺寸，`fit_image` 也会按比例中心裁切回目标尺寸，
构图不再跑偏。

### 同时确认的网关能力边界（实测）

- `mask` 字段**被网关忽略**（正/反 mask 三组对照结果完全一致）：
  选区约束只能靠提示词语义 + 本地 `apply_masked` 合成，这是网关侧上限；
- `/images/generations` 带 `image` 无效（退化纯文生图），图生图必须走 `/images/edits`。

### 验证

253 项 pytest 全绿（新增 1 项：局部编辑断言传参尺寸），ruff 通过，健康检查 ok。
