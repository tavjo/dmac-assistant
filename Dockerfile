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

# Plan A · T0 R4: pin uv-managed CPython 3.14 BEFORE any downstream
# dependency-install or run step. Two well-known symlinks make `python`
# and `python3.14` resolve to the managed interpreter via PATH;
# $DMAC_PYTHON is exposed for callers that prefer an explicit absolute path.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN mkdir -p /opt/uv-python \
    && uv python install 3.14 \
    && ln -sfn "$(uv python find 3.14)" /usr/local/bin/python3.14 \
    && ln -sfn /usr/local/bin/python3.14 /usr/local/bin/python \
    && chmod -R a+rX /opt/uv-python
ENV DMAC_PYTHON=/usr/local/bin/python3.14

RUN useradd -m -u 1001 -s /bin/sh user

COPY build_context/plugins/ /app/plugins/
COPY build_context/docs/nextseek-api/ /app/docs/nextseek-api/
COPY docs/nextseek/ /app/docs/nextseek/
COPY container/CLAUDE.md /app/CLAUDE.md
COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# DD-37: claude-code discovers CLAUDE.md from cwd / project tree, not /app/.
# Symlink the image-baked spec into the WORKDIR so the in-container Claude
# Code sees the plugin guidance.
RUN ln -sfn /app/CLAUDE.md /home/user/CLAUDE.md \
    && chown -h user:user /home/user/CLAUDE.md

ENV UV_CACHE_DIR=/opt/uv-cache
RUN mkdir -p /opt/uv-cache
RUN uv run --with httpx --with pydantic --with python-dotenv --with markitdown \
      python -c "import httpx, pydantic, dotenv, markitdown" \
    && chmod -R a+rwX /opt/uv-cache \
    && echo "uv cache pre-warmed at /opt/uv-cache"

# DD-37 (PATH half, moved below pre-warm per L-4): put the plugin's bin/ on
# PATH so Claude can invoke `nextseek-call` etc. without spelling the full
# path. Placed AFTER the expensive uv pre-warm so a PATH tweak (e.g. adding
# a second plugin's bin dir) does not invalidate the pre-warm cache layer.
ENV PATH="/app/plugins/nextseek-api/bin:${PATH}"

USER user
WORKDIR /home/user

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude", "--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
