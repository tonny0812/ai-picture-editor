# 前端构建产物由后端同源托管，因此在同一镜像内完成构建
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --all-extras --no-dev

# CV 模型在构建期预下载并烤进镜像（u2net 176MB + SAM 量化 112MB）：
# 生产机常常没有外网、也没有持久化卷，留到运行时首次调用再拉模型必然失败，
# 多副本还会同时下载互相打架。放在 COPY backend/ 之前，改业务代码不会让这层缓存失效。
# 离线 CI 可用 --build-arg PRELOAD_CV_MODELS=0 跳过（跳过则必须挂载模型目录或保持联网）。
ENV U2NET_HOME=/opt/cv_models
ARG PRELOAD_CV_MODELS=1
RUN if [ "$PRELOAD_CV_MODELS" = "1" ]; then \
      .venv/bin/python -c "from rembg import new_session; new_session('u2net'); new_session('sam', sam_quant=True)"; \
    fi

COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 7302
