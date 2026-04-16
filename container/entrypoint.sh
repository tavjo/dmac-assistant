#!/bin/sh
# DMAC Assistant container entrypoint.
#
# Responsibilities:
#   1. Bridge NEXTSEEK_* env vars to the nextseek-api plugin's canonical names.
#   2. Scrub settings.local.json's env block on every start.
#   3. Hand control to the declared command with exec.

set -eu

: "${SEEK_USER:=${NEXTSEEK_USERNAME:-}}"
: "${SEEK_PASSWORD:=${NEXTSEEK_PASSWORD:-}}"
: "${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}"
export SEEK_USER SEEK_PASSWORD NEXTSEEK_BASE_URL

SETTINGS_PATH="${ENTRYPOINT_SETTINGS_PATH:-/home/user/.claude/settings.local.json}"

_scrub_env_block() {
  _tmp=''

  if _has_env="$(jq 'has("env")' "$SETTINGS_PATH")"; then
    if [ "$_has_env" = "false" ]; then
      return 0
    fi
  else
    printf '%s\n' 'entrypoint: failed to parse settings.local.json' >&2
    return 1
  fi

  if ! _mode="$(stat -c '%a' "$SETTINGS_PATH" 2>/dev/null || stat -f '%Lp' "$SETTINGS_PATH" 2>/dev/null)"; then
    printf '%s\n' 'entrypoint: failed to stat settings.local.json' >&2
    return 1
  fi

  _tmp="${SETTINGS_PATH}.scrub.$$"

  if ! jq 'del(.env)' "$SETTINGS_PATH" >"$_tmp"; then
    rm -f "$_tmp"
    printf '%s\n' 'entrypoint: failed to scrub env from settings.local.json' >&2
    return 1
  fi

  chmod "$_mode" "$_tmp"
  mv "$_tmp" "$SETTINGS_PATH"
}

if [ -f "$SETTINGS_PATH" ]; then
  _scrub_env_block
fi

exec "$@"
