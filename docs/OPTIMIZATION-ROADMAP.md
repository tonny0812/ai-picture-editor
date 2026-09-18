# 优化路线图（审计摘要）

> 完整版：工作区 `ai-picture-editor-代码优化方案.html`（33 条问题，全部 `文件:行号` 已在源码核对，含验收标准）。
> 本文档是研究时的速查摘要：先知道"哪里有雷、先修什么"。
> 审计基线：克隆自 tonny0812/ai-picture-editor，2026-09-17。

## 状态总览

- ✅ 已修复：B2（规划模型无 timeout/max_retries）——随本次网关接入顺手修复，见 `CHANGES.md`
- 🔴 未修复：下述全部条目

## 🔴 P0：真实会出事的（1 条）

### A1 · 多步计划重复执行

`backend/app/services/agent.py:204-232` + `services/tools.py:72`

外层 `_advance` 持有步骤快照，同步工具（`flip_layer`、`prepare_delivery_sizes`，`queued=False`）执行时回调 `continue_plan` 触发**内层** `_advance`。内层已把后续步骤的 `run_id` 写进 `turn.plan`，外层回到 `:218` 用旧快照覆盖 → 步骤退回 `pending`、`run_id=null`，`:222` 的 `progressed=True` 让它再循环一次 → **同一步骤被提交两次**。

- 触发条件日常：「翻转一下再调亮」两步指令即命中
- 后果：重复改图、重复计费、版本链错乱
- 修复方向二选一：①状态单一化（根治，改动大，推荐）②重入守卫（改动小，两套状态并存）

## 🔴 P1：严重问题（已验证的关键条目）

| 编号 | 位置 | 问题 |
|---|---|---|
| A2 | `tools/base.py:51`、`agent.py:210` | `needs_approval` 定义了、判断了，但**全项目从未置 True**——审批机制空跑，`generate_marketing`/`split_layers`/`batch_process` 单步时绕过确认直接执行 |
| A3 | `routers/assets.py:23` | 上传先 `await file.read()` 全量读进内存后才判 20MB —— 内存 DoS 面 |
| A4 | `services/sessions.py` | 并发写 revision 无锁，`edit_history` 有 `UniqueConstraint("session_id","seq")`，撞上直接 500 |
| A5 | `worker.py` + `providers/dashscope.py:25` | `job_timeout=300` 与轮询超时 300s 打平，再加 60s 下载 → 长任务必被 ARQ 杀掉 |
| A6 | `routers/events.py` | SSE 长连接期间占用数据库连接 |
| B1 | `agent/graph.py:60` | 只认 `tool_calls`，模型返回 ```json 文本会被**静默当成空计划**，无兜底解析与重试 |
| B3 | `tools/base.py` | 幻觉工具名/参数直接报错，错误信息未回灌模型自动修复 |

## 🟠 前端（两条硬事实 + 典型条目）

**硬事实：全库 0 处 `React.memo`、0 处 `ErrorBoundary`。**

进度状态链路：`EditorPage.tsx:42 → useSessions.ts:79 → useRun → useSmoothedProgress.ts:72`（缓动期每帧 `setShown`）把进度提到了顶层 `Workspace` —— 带着 1087 行的 `CanvasStage.tsx` 帧率级重渲，这就是「生成时整个编辑器发黏」的根因。

| 编号 | 位置 | 问题 |
|---|---|---|
| C 组 | `CanvasStage.tsx`（1087 行） | 需拆分到 ~250 行：图层渲染 / 交互手势 / 选区叠加 / 工具预览各自成模块 |
| C 组 | `useSelection.ts:103-110` | 选区撤销无并发锁，连点乱序覆盖 |
| C 组 | `EditorPage.tsx:80-99` | 撤销有两套栈，行为不可预期 |
| C 组 | `BatchPage.tsx:170` | `revokeObjectURL` 过早，Safari 下载可能被中断 |
| C 组 | `CanvasStage.tsx:162-168` | 画布无可访问性，窄屏无收起入口 |

## 三阶段路线

```
阶段一 止血（约 10 项，全部是「线上会出事」）
  A1 重复执行（先修，B3/B10 都会碰同一处，建议状态单一化）
  A3 上传内存 DoS → 流式校验
  A4 revision 写入加锁/重试
  A5 worker 超时预算重排（poll < job_timeout 留下载余量）
  A6 SSE 与 DB 连接解耦
  A7 生产密钥守卫（jwt_secret 默认值拒绝启动）

阶段二 加固（P1 与可观测性）
  A2 审批机制落地（危险工具真正置 needs_approval=True）
  B1 结构化输出兜底解析 + 校验失败回灌模型自动修复
  B2 ✅ 已完成
  prompt 抽出模板 + few-shot
  补 Agent 维度评测指标（计划准确率/工具命中率）

阶段三 体验与重构
  C 组前端全部 + ErrorBoundary + React.memo 收敛订阅粒度
  CanvasStage 拆分
  打破 services ↔ tools 循环依赖
```

## 与教程扩展点的重叠（做修复 = 拿扩展点）

| 优化项 | 顺带完成的官方扩展点 |
|---|---|
| Track A 安全加固 | 扩展点 6「安全加固：限流、敏感词过滤、上传审核」 |
| A6/信号量 | 扩展点 5「多用户并发控制」 |
| Track B 流式输出 | 扩展点 2「Agent 规划逐 token 流式输出」 |
| Track B checkpoint | 扩展点 3「LangGraph checkpoint 持久化」 |
