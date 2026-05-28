#!/usr/bin/env bash
# Host-side sync of vendored dependencies that cannot be pulled into the
# Docker image at build time without authentication. Idempotent.
#
# Source of truth for chat_nextseek pin (Plan A Amendment 4, 2026-04-29).
# Bump PIN to upgrade; CI / image-build will pick up the new SHA next run.
set -euo pipefail

PIN="1217c95885735b8ab63399a5d021669f87b7a297"
REPO_URL="https://github.com/cdemurjian/chat_nextseek.git"
VENDOR_DIR="vendor/chat_nextseek"

mkdir -p "$(dirname "$VENDOR_DIR")"

# Shallow vendor: init empty repo, fetch the pinned SHA at depth 1.
# GitHub allows uploadpack.allowReachableSHA1InWant by default so this works.
if [ ! -d "$VENDOR_DIR/.git" ]; then
  git init --quiet "$VENDOR_DIR"
  git -C "$VENDOR_DIR" remote add origin "$REPO_URL"
fi

git -C "$VENDOR_DIR" fetch --quiet --depth 1 origin "$PIN"
git -C "$VENDOR_DIR" -c advice.detachedHead=false checkout --quiet FETCH_HEAD

ACTUAL="$(git -C "$VENDOR_DIR" rev-parse HEAD)"
if [ "$ACTUAL" != "$PIN" ]; then
  echo "ERROR: vendor/chat_nextseek HEAD ($ACTUAL) does not match PIN ($PIN)" >&2
  exit 1
fi

echo "vendor/chat_nextseek synced at $PIN"
