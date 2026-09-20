#!/usr/bin/env bash
# AI 修图智能体 · 本地 Docker 运维入口
# 用法：./dev.sh <命令>
set -euo pipefail
cd "$(dirname "$0")"

PROFILE=deploy
# 某些终端环境的 PATH 不含 /usr/local/bin，找不到时兜底到 Docker Desktop 默认路径
DOCKER=${DOCKER:-$(command -v docker || echo /usr/local/bin/docker)}
DC=("$DOCKER" compose --profile "$PROFILE")

urls() {
  cat <<'EOF'
  Web 应用      http://localhost:7302
  接口文档      http://localhost:7302/api/docs
  健康检查      http://localhost:7302/api/health
  MinIO 控制台  http://localhost:7314   (retouch / retouch_dev)
  PostgreSQL    localhost:7311          (retouch / retouch_dev / retouch)
  Redis         localhost:7312
EOF
}

# 生产镜像用 --no-dev 构建，不含 pytest/ruff，故在一次性容器里临时装开发依赖。
# 测试走 Redis 1 号库与独立的 test_ 前缀账号，不会污染应用数据。
in_container() {
  "$DOCKER" run --rm --network ai-retouch-agent_default \
    -e DATABASE_URL=postgresql+asyncpg://retouch:retouch_dev@postgres:5432/retouch \
    -e REDIS_URL=redis://redis:6379 \
    -e S3_ENDPOINT=http://minio:9000 \
    -e S3_PUBLIC_ENDPOINT=http://localhost:7313 \
    -e IMAGE_PROVIDER=mock \
    -e JWT_SECRET=dev-only-secret-please-change-in-production \
    ai-retouch-agent-app sh -c "uv sync --all-extras --group dev >/dev/null 2>&1; $1"
}

case "${1:-help}" in
  up)
    "${DC[@]}" up -d
    sleep 4
    "${DC[@]}" exec -T app alembic upgrade head
    echo "已启动。"
    urls
    ;;
  down)
    "${DC[@]}" down
    ;;
  restart)
    "${DC[@]}" restart app worker
    ;;
  ps)     "${DC[@]}" ps ;;
  logs)   "${DC[@]}" logs -f --tail=120 "${2:-app}" ;;
  migrate) "${DC[@]}" exec -T app alembic upgrade head ;;
  promote)
    "${DC[@]}" exec -T app python -m app.cli promote "${2:?用法: ./dev.sh promote <用户名>}"
    ;;
  demote)
    "${DC[@]}" exec -T app python -m app.cli demote "${2:?用法: ./dev.sh demote <用户名>}"
    ;;
  users)  "${DC[@]}" exec -T app python -m app.cli list ;;
  shell)  "${DC[@]}" exec app bash ;;
  dbshell) "${DC[@]}" exec postgres psql -U retouch -d retouch ;;
  smoke)
    echo "运行冒烟验证..."
    "$DOCKER" run --rm --network host -v "$PWD/smoke-test.py:/tmp/smoke.py:ro" \
      ai-retouch-agent-app python /tmp/smoke.py
    ;;
  test)
    in_container "uv run pytest -q"
    ;;
  lint)
    in_container "uv run ruff check app tests"
    ;;
  probe)
    # 探测自建网关能力：需先在 .env 配 PLANNER_BASE_URL / PLANNER_API_KEY
    set -a; . ./.env 2>/dev/null; set +a
    if [ -z "${PLANNER_BASE_URL:-}" ] || [ -z "${PLANNER_API_KEY:-}" ]; then
      echo "请先在 .env 配置 PLANNER_BASE_URL 与 PLANNER_API_KEY"; exit 1
    fi
    "$DOCKER" run --rm --network host \
      -e PROBE_BASE_URL="${PLANNER_BASE_URL}" \
      -e PROBE_API_KEY="${PLANNER_API_KEY}" \
      -e PROBE_CHAT_MODEL="${PLANNER_MODEL}" \
      -e PROBE_IMAGE_MODEL="${IMAGES_MODEL}" \
      -v "$PWD/backend/scripts/probe_gateway.py:/tmp/probe.py:ro" \
      ai-retouch-agent-app python /tmp/probe.py
    ;;
  build)
    "${DC[@]}" build
    ;;
  rebuild)
    "${DC[@]}" build --no-cache
    "${DC[@]}" up -d
    ;;
  reset)
    # 清空数据库与对象存储，保留镜像
    read -r -p "将删除全部数据（数据库/Redis/MinIO），确认？[y/N] " a
    [[ "$a" == "y" || "$a" == "Y" ]] || { echo "已取消"; exit 0; }
    "${DC[@]}" down -v
    docker compose up -d
    "${DC[@]}" up -d
    sleep 5
    "${DC[@]}" exec -T app alembic upgrade head
    echo "已重置。"
    ;;
  urls) urls ;;
  *)
    cat <<'EOF'
AI 修图智能体 · 本地运维脚本

  up        启动全栈并执行数据库迁移
  down      停止并移除容器（保留数据卷）
  restart   重启 app 与 worker
  ps        查看容器状态
  logs [服务]  跟踪日志，默认 app（可选 worker/minio/postgres/redis）
  migrate   执行 Alembic 迁移
  promote   把某个已注册用户提升为管理员
  demote    把管理员降回普通用户（唯一管理员不允许降级）
  users     列出全部用户及其角色
  shell     进入 app 容器
  dbshell   进入 PostgreSQL 命令行
  smoke     跑端到端冒烟验证（23 项）
  test      跑后端 pytest
  lint      ruff 检查
  probe     探测自建网关能力（function calling / 生图档位 / 图生图）
  build     重新构建镜像
  rebuild   无缓存重建并启动
  reset     清空数据并重来（危险）
  urls      打印各服务地址
EOF
    ;;
esac
