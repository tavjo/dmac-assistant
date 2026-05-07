#!/usr/bin/env bash
#
# setup.sh — nextseek-api Layer 1 permission allowlist installer
#
# Adds the 5 bash allowlist patterns for the nextseek-api plugin's safe shim
# commands to ~/.claude/settings.json. The writes are:
#   - Bash(nextseek-init:*)
#   - Bash(nextseek-spec:*)
#   - Bash(nextseek-validate:*)
#   - Bash(nextseek-exec --method GET*)
#   - Bash(nextseek-exec --endpoint schema_rag/*)
#
# The script is idempotent: re-running produces no duplicate entries.
# Before modifying, it writes a timestamped .bak file and validates the new
# JSON with `jq empty`. On validation failure it aborts WITHOUT touching the
# live settings.json, so a corrupt intermediate can never break Claude Code.
#
# Usage:
#   bash ~/.claude/plugins/local/nextseek-api/skills/nextseek-api/scripts/setup.sh
#
# Exit codes:
#   0 — success, or user declined
#   1 — jq missing, settings.json missing/invalid, or write validation failed
#
set -euo pipefail

# ---- Constants --------------------------------------------------------------

SETTINGS_FILE="${HOME}/.claude/settings.json"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${SETTINGS_FILE}.bak.${TIMESTAMP}"
TMP_FILE="${SETTINGS_FILE}.tmp.$$"

# Exact Layer-1 allowlist patterns from plan Section 8.3.
# DO NOT add, remove, or reorder without updating the plan amendment log.
PATTERNS=(
  "Bash(nextseek-init:*)"
  "Bash(nextseek-spec:*)"
  "Bash(nextseek-validate:*)"
  "Bash(nextseek-exec --method GET*)"
  "Bash(nextseek-exec --endpoint schema_rag/*)"
)

# ---- Helpers ----------------------------------------------------------------

die() {
  printf '[nextseek-api setup] ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '[nextseek-api setup] %s\n' "$*"
}

cleanup_tmp() {
  if [[ -f "${TMP_FILE}" ]]; then
    rm -f "${TMP_FILE}"
  fi
}
trap cleanup_tmp EXIT

# ---- Pre-flight checks ------------------------------------------------------

# Layer-1 fail-fast: jq is the ONLY safe way to edit JSON without risking
# corruption. If it's missing, refuse to run and tell the user how to install.
if ! command -v jq >/dev/null 2>&1; then
  cat >&2 <<'JQERR'
[nextseek-api setup] ERROR: jq is not installed.

jq is required for safe JSON manipulation of ~/.claude/settings.json.
Install it with Homebrew:

    brew install jq

Then re-run this script.
JQERR
  exit 1
fi

if [[ ! -f "${SETTINGS_FILE}" ]]; then
  die "~/.claude/settings.json not found. Create it with a minimal
{\"permissions\": {\"allow\": []}} and re-run."
fi

# Validate the existing file parses as JSON before we touch it.
if ! jq empty "${SETTINGS_FILE}" >/dev/null 2>&1; then
  die "~/.claude/settings.json is not valid JSON. Fix it manually and re-run."
fi

# ---- User confirmation ------------------------------------------------------

info "This will add the following bash allowlist patterns to:"
info "    ${SETTINGS_FILE}"
echo
for p in "${PATTERNS[@]}"; do
  echo "    ${p}"
done
echo
info "A backup will be created at:"
info "    ${BACKUP_FILE}"
echo
printf '[nextseek-api setup] Proceed? [y/N]: '
read -r reply
case "${reply}" in
  [Yy]|[Yy][Ee][Ss])
    ;;
  *)
    info "Aborting. No changes made."
    exit 0
    ;;
esac

# ---- Build the jq merge expression ------------------------------------------

# Build a JSON array literal for the patterns, then pass it as a jq argument
# using --argjson so jq treats it as parsed JSON (not a raw string).
PATTERNS_JSON=$(printf '%s\n' "${PATTERNS[@]}" | jq -R . | jq -s .)

# The merge expression:
#   1. Ensure .permissions exists as an object.
#   2. Ensure .permissions.allow exists as an array.
#   3. Append the new patterns.
#   4. Dedupe with `unique` (sorts + dedupes — order within allow[] is irrelevant
#      for the matcher and sorted output is easier to diff in version control).
MERGE_EXPR='
  .permissions = (.permissions // {}) |
  .permissions.allow = (.permissions.allow // []) |
  .permissions.allow = (.permissions.allow + $new | unique)
'

# ---- Atomic write with validation ------------------------------------------

# Step 1: compute the new settings file into the tmp path.
jq --argjson new "${PATTERNS_JSON}" "${MERGE_EXPR}" "${SETTINGS_FILE}" > "${TMP_FILE}"

# Step 2: validate the tmp file parses before we consider replacing the real one.
if ! jq empty "${TMP_FILE}" >/dev/null 2>&1; then
  die "Internal error: jq produced invalid JSON. Live settings.json is untouched."
fi

# Step 3: back up the original BEFORE the atomic rename.
cp "${SETTINGS_FILE}" "${BACKUP_FILE}"

# Step 4: atomic rename — same filesystem, so mv is atomic on POSIX.
mv "${TMP_FILE}" "${SETTINGS_FILE}"

# ---- Summary ----------------------------------------------------------------

info "Success. Added allowlist patterns to ${SETTINGS_FILE}"
info "Backup saved to ${BACKUP_FILE}"
echo
info "Patterns installed:"
for p in "${PATTERNS[@]}"; do
  echo "    ${p}"
done
echo
info "You can now invoke the nextseek-api shim commands from Claude Code without"
info "a permission prompt for the safe (GET / schema_rag) operations. All other"
info "writes will still be intercepted by Claude Code's permission system."
