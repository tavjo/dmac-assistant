#!/usr/bin/env bats

setup() {
  BATS_TEST_TMPDIR="$(mktemp -d)"
  export BATS_TEST_TMPDIR

  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$HOME_DIR/.claude"
  export HOME_DIR

  SETTINGS="$HOME_DIR/.claude/settings.local.json"
  export SETTINGS

  MARKER="$BATS_TEST_TMPDIR/should-not-run"
  export MARKER
  rm -f "$MARKER"

  ENTRYPOINT="$BATS_TEST_DIRNAME/../container/entrypoint.sh"
  export ENTRYPOINT

  export ENTRYPOINT_SETTINGS_PATH="$SETTINGS"
}

teardown() {
  rm -rf "$BATS_TEST_TMPDIR"
}

inode_of() {
  stat -c '%i' "$1" 2>/dev/null || stat -f '%i' "$1"
}

mode_of() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

sha256_of() {
  if [ "${1:-}" = "-" ]; then
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 | awk '{print $1}'
    else
      sha256sum | awk '{print $1}'
    fi
  else
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 "$1" | awk '{print $1}'
    else
      sha256sum "$1" | awk '{print $1}'
    fi
  fi
}

@test "missing_file_proceeds: no settings.local.json, exec runs, exit 0" {
  rm -f "$SETTINGS"
  run "$ENTRYPOINT" sh -c 'echo ran-ok'
  [ "$status" -eq 0 ]
  [[ "$output" == *"ran-ok"* ]]
}

@test "env_only_key_removed_others_preserved: env deleted, non-env bytes identical under jq normalization" {
  cat >"$SETTINGS" <<'EOF'
{
  "env": {"SECRET": "X"},
  "model": "claude-foo",
  "permissions": {"allow": []},
  "hooks": {}
}
EOF

  expected_hash="$(jq -c 'del(.env)' "$SETTINGS" | sha256_of -)"

  run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]

  run jq 'has("env")' "$SETTINGS"
  [ "$status" -eq 0 ]
  [ "$output" = "false" ]

  actual_hash="$(jq -c '.' "$SETTINGS" | shasum -a 256 | awk '{print $1}')"
  [ "$expected_hash" = "$actual_hash" ]
}

@test "no_env_key_no_change: file without env key stays byte-identical (inode preserved)" {
  cat >"$SETTINGS" <<'EOF'
{"model":"claude-xyz","permissions":{"allow":["*"]}}
EOF

  before_inode="$(inode_of "$SETTINGS")"
  before_hash="$(sha256_of "$SETTINGS")"

  run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]

  after_inode="$(inode_of "$SETTINGS")"
  after_hash="$(sha256_of "$SETTINGS")"

  [ "$before_inode" = "$after_inode" ]
  [ "$before_hash" = "$after_hash" ]
}

@test "malformed_json_fails_closed: bad JSON, exit != 0, child never executes" {
  printf '{not-json:::::' >"$SETTINGS"

  run "$ENTRYPOINT" sh -c 'touch "$MARKER"'
  [ "$status" -ne 0 ]
  [ ! -e "$MARKER" ]
}

@test "secret_not_in_logs: env.SECRET=CANARY-abc123 never appears in stdout or stderr" {
  cat >"$SETTINGS" <<'EOF'
{"env":{"SECRET":"CANARY-abc123"},"model":"claude-foo"}
EOF

  run "$ENTRYPOINT" sh -c 'echo done'
  [ "$status" -eq 0 ]
  [[ "$output" == *"done"* ]]
  [[ "$output" != *"CANARY-abc123"* ]]
}

@test "file_mode_preserved: seeded mode 600 is preserved after scrub (DD-24 atomic chmod-before-mv)" {
  cat >"$SETTINGS" <<'EOF'
{"env":{"A":"B"},"model":"m"}
EOF
  chmod 600 "$SETTINGS"

  before_mode="$(mode_of "$SETTINGS")"
  run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  after_mode="$(mode_of "$SETTINGS")"

  [ "$before_mode" = "600" ]
  [ "$after_mode" = "600" ]
}

@test "exec_passes_exit_code: child exits 42, entrypoint returns 42" {
  rm -f "$SETTINGS"
  run "$ENTRYPOINT" sh -c 'exit 42'
  [ "$status" -eq 42 ]
}

@test "shellcheck_sh_clean: entrypoint.sh passes shellcheck -s sh (DD-25 replaces checkbashisms)" {
  run shellcheck -s sh "$ENTRYPOINT"
  [ "$status" -eq 0 ]
}

@test "env_var_alias_propagates: DD-19 bridge-side vars populate canonical-side and both survive exec" {
  rm -f "$SETTINGS"
  NEXTSEEK_USERNAME="bridgeuser" \
  NEXTSEEK_PASSWORD="bridgepass" \
  NEXTSEEK_URL="https://dev.example" \
    run "$ENTRYPOINT" sh -c 'env | grep -E "^(SEEK_USER|SEEK_PASSWORD|NEXTSEEK_BASE_URL|NEXTSEEK_USERNAME|NEXTSEEK_PASSWORD|NEXTSEEK_URL)="'
  [ "$status" -eq 0 ]
  [[ "$output" == *"NEXTSEEK_USERNAME=bridgeuser"* ]]
  [[ "$output" == *"NEXTSEEK_PASSWORD=bridgepass"* ]]
  [[ "$output" == *"NEXTSEEK_URL=https://dev.example"* ]]
  [[ "$output" == *"SEEK_USER=bridgeuser"* ]]
  [[ "$output" == *"SEEK_PASSWORD=bridgepass"* ]]
  [[ "$output" == *"NEXTSEEK_BASE_URL=https://dev.example"* ]]
}

@test "env_var_alias_preserves_existing_canonical: DD-19 canonical wins over bridge-side when both set" {
  rm -f "$SETTINGS"
  NEXTSEEK_USERNAME="bridge" \
  SEEK_USER="canonical" \
    run "$ENTRYPOINT" sh -c 'env | grep -E "^SEEK_USER="'
  [ "$status" -eq 0 ]
  [[ "$output" == *"SEEK_USER=canonical"* ]]
  [[ "$output" != *"SEEK_USER=bridge"* ]]
}
