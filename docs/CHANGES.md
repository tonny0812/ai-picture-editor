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
