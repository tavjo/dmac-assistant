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
    && ln -sfn /usr/local/bin/python3.14 /usr/bin/python \
    && chmod -R a+rX /opt/uv-python
ENV DMAC_PYTHON=/usr/local/bin/python3.14

RUN useradd -m -u 1001 -s /bin/sh user

# Plan B · T14: ship only the new nextseek plugin in the image.
# The old nextseek-api plugin is preserved on disk under
# build_context/plugins/nextseek-api/ (host-side codebase) for reuse,
# but is NOT included in the image (D25 amended).
COPY build_context/plugins/nextseek/ /app/plugins/nextseek/

# NEW-6: fail the build if catalog files weren't snapshotted before
# `docker build`. Without this, an image can ship with an empty
# /app/plugins/nextseek/context/ and degrade silently at runtime.
RUN test -n "$(ls /app/plugins/nextseek/context/min_*.json 2>/dev/null)" || \
    (echo "ERROR: no min_*.json catalog files in /app/plugins/nextseek/context/; run 'make snapshot-nextseek-catalogs' before 'docker build'" >&2 && exit 1)
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

# Plan A · T8 Amendment 5 v3 (canonical uv-in-Docker): materialize the
# project venv at /opt/dmac-venv and prepend its bin/ to PATH so plain
# `python`, `uv pip install`, and plugin-shim invocations all resolve to
# the venv interpreter without `uv run` wrappers. Replaces Amendment 4's
# system-wide install model in favor of venv-on-PATH (the canonical
# uv-in-Docker pattern from docs.astral.sh/uv/guides/integration/docker).
ENV UV_PROJECT_ENVIRONMENT=/opt/dmac-venv \
    VIRTUAL_ENV=/opt/dmac-venv \
    PATH="/opt/dmac-venv/bin:$PATH"

# Install bridge dependencies from pyproject.toml + uv.lock into the venv.
# --locked asserts lockfile-up-to-date (loud failure on drift, preserving
# the M4 dep-conflict guarantee). --no-install-project because the bridge
# source code lives on the host, not in this image.
COPY pyproject.toml uv.lock /tmp/dmac-deps/
RUN cd /tmp/dmac-deps \
    && uv sync --locked --no-install-project \
    && echo "uv sync done; deps installed into /opt/dmac-venv"

# Plan A T8 Amendment 4 (vendored-source): install chat_nextseek from the
# host-side vendor/ tree (populated by `make sync-vendor-deps`). No
# build-time GitHub egress; the image rebuilds wheels in its own
# linux/amd64 + Python 3.14 environment. With the venv active via PATH +
# VIRTUAL_ENV, uv pip install targets the venv automatically.
COPY vendor/chat_nextseek /tmp/chat_nextseek
RUN uv pip install /tmp/chat_nextseek \
    && chmod -R a+rX /opt/uv-cache /opt/dmac-venv

# DD-37 (PATH half, moved below pre-warm per L-4): put the plugin's bin/ on
# PATH so Claude can invoke `nextseek-call` etc. without spelling the full
# path. Placed AFTER the expensive uv pre-warm so a PATH tweak (e.g. adding
# a second plugin's bin dir) does not invalidate the pre-warm cache layer.
ENV PATH="/app/plugins/nextseek/bin:${PATH}"

USER user
WORKDIR /home/user

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude", "--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
