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
