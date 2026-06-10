# syntax=docker/dockerfile:1.7
# NS shared-cred sidecar image. Build context = repo root (compose sets context: ..).
FROM --platform=linux/amd64 python:3.14-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV VIRTUAL_ENV=/opt/sidecar-venv PATH="/opt/sidecar-venv/bin:$PATH"
RUN uv venv /opt/sidecar-venv

RUN uv pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY vendor/chat_nextseek /tmp/chat_nextseek
RUN uv pip install /tmp/chat_nextseek websockets~=16.0 pydantic>=2.9

COPY sidecar/__init__.py /app/sidecar/__init__.py
COPY sidecar/app/ /app/sidecar/app/
COPY build_context/plugins/nextseek/context/read_safe_endpoints.json /app/context/read_safe_endpoints.json

RUN useradd -m -u 1001 -s /bin/sh sidecar
USER sidecar
WORKDIR /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "sidecar.app.server"]
