# 项目研究资料索引

> 本目录汇集了研究本项目所需的全部本地资料：教程摘录、本次改动记录、优化路线。
> 仓库本体：https://github.com/tonny0812/ai-picture-editor （fork 自官方 yuyuanweb/ai-picture-editor）

## 文档导航

| 文档 | 内容 | 适合场景 |
|---|---|---|
| [tutorial/教程目录与访问指南.md](tutorial/教程目录与访问指南.md) | codefather 教程完整目录、章节链接、访问状态 | 想按教程系统学习时 |
| [tutorial/01-项目总览.md](tutorial/01-项目总览.md) | 教程「项目总览」全文（可试学章节已完整抓取） | 快速理解项目定位、业务流程、技术选型 |
| [tutorial/02-项目大纲.md](tutorial/02-项目大纲.md) | 教程「项目大纲」全文：10 期大纲 + 官方 7 个扩展点 | 按章节对照代码学习、找扩展方向 |
| [CHANGES.md](CHANGES.md) | 本地部署与二次开发的全部改动记录 | 维护、回顾"我改了什么、为什么" |
| [OPTIMIZATION-ROADMAP.md](OPTIMIZATION-ROADMAP.md) | 33 条代码审计问题摘要 + 三阶段优化路线 | 决定下一步修什么 |

## 30 秒上手

```bash
cd ai-picture-editor
./dev.sh up        # 启动全部服务（首次自动迁移数据库）
./dev.sh urls      # 查看各服务地址
./dev.sh smoke     # 跑 23 项端到端冒烟
./dev.sh test      # 跑后端 pytest（167 个）
```

应用地址：http://localhost:7302 （本地 Docker 部署，5 容器全部 healthy）

## 项目一句话

**AI 修图智能体**：用户说一句「去掉背景，把主体放大一点，调亮一些」，Agent 自动拆解成多步计划，确认后逐步调用 21 个编辑工具执行。技术栈 FastAPI + LangChain/LangGraph + ARQ + PostgreSQL/Redis/MinIO + React 19 + react-konva。

## 关键代码入口（配合大纲第 2~10 期阅读）

| 主题 | 代码位置 |
|---|---|
| 应用入口 / SPA 托管 | `backend/app/main.py` |
| 配置中心（含本次新增的网关配置） | `backend/app/config.py` |
| Agent 规划模型绑定 | `backend/app/agent/llm.py` |
| LangGraph 状态图 plan→verify | `backend/app/agent/graph.py` |
| 计划校验 / 拓扑排序 | `backend/app/agent/plan.py` |
| 执行引擎（⚠️ 存在 P0 重复执行 bug，见路线图 A1） | `backend/app/services/agent.py:204-232` |
| 工具注册表 ToolRegistry | `backend/app/services/tools.py` + `backend/app/tools/` |
| Provider 抽象层（mock/dashscope/openai） | `backend/app/providers/` |
| 异步任务 Worker | `backend/app/worker.py` |
| 前端画布（1087 行，待拆分） | `frontend/src/components/editor/CanvasStage.tsx` |
| 前端路由 / 页面 | `frontend/src/App.tsx` + `frontend/src/pages/` |
