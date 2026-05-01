#!/usr/bin/env bash
# Host-side sync of vendored dependencies that cannot be pulled into the
# Docker image at build time without authentication. Idempotent.
#
# Source of truth for chat_nextseek pin (Plan A Amendment 4, 2026-04-29).
# Bump PIN to upgrade; CI / image-build will pick up the new SHA next run.
set -euo pipefail

PIN="5588f3becbbc7d8f735c7f009e4940cddf97000b"
REPO_URL="https://github.com/cdemurjian/chat_nextseek.git"
VENDOR_DIR="vendor/chat_nextseek"

mkdir -p "$(dirname "$VENDOR_DIR")"

if [ ! -d "$VENDOR_DIR/.git" ]; then
  git clone "$REPO_URL" "$VENDOR_DIR"
fi

git -C "$VENDOR_DIR" fetch --quiet origin
git -C "$VENDOR_DIR" -c advice.detachedHead=false checkout --quiet "$PIN"

ACTUAL="$(git -C "$VENDOR_DIR" rev-parse HEAD)"
if [ "$ACTUAL" != "$PIN" ]; then
  echo "ERROR: vendor/chat_nextseek HEAD ($ACTUAL) does not match PIN ($PIN)" >&2
  exit 1
fi

echo "vendor/chat_nextseek synced at $PIN"
