# syntax=docker/dockerfile:1.7
#
# DMAC Assistant POC image.
# Plan: dmac-image-poc. See DD-10 (layout contract), DD-17 (pre-warm), ADR-011.

FROM --platform=linux/amd64 node:20-bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      jq \
      ca-certificates \
      curl \
      git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN npm install -g @anthropic-ai/claude-code@2.1.92

RUN useradd -m -u 1001 -s /bin/sh user

COPY build_context/plugins/ /app/plugins/
COPY build_context/docs/ /app/docs/
COPY container/CLAUDE.md /app/CLAUDE.md
COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

ENV UV_CACHE_DIR=/opt/uv-cache
RUN mkdir -p /opt/uv-cache
RUN uv run --with httpx --with pydantic --with python-dotenv --with markitdown \
      python -c "import httpx, pydantic, dotenv, markitdown" \
    && chmod -R a+rwX /opt/uv-cache \
    && echo "uv cache pre-warmed at /opt/uv-cache"

USER user
WORKDIR /home/user

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude", "--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
