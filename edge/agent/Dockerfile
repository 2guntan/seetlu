# Multi-arch (amd64 + arm64). Production runs on arm64 next to Frigate.
# Build context is `edge/` so the Frigate config template ships with the agent.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# docker CLI + compose plugin for `update_agent` (docs/05); the host socket is mounted on the kit
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /app/agent
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY frigate/config.template.yml /app/frigate/config.template.yml
COPY agent/ ./
RUN uv sync --frozen --no-dev
EXPOSE 8080
CMD ["seetlu-agent"]
