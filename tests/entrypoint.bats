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

@test "claude_md_symlink_recreated_when_missing: DD-37 entrypoint symlinks /app/CLAUDE.md to WORKDIR" {
  rm -f "$SETTINGS"
  CLAUDE_SRC="$BATS_TEST_TMPDIR/app-claude.md"
  CLAUDE_LINK="$BATS_TEST_TMPDIR/home-claude.md"
  printf '# in-container CLAUDE.md\n' >"$CLAUDE_SRC"
  rm -f "$CLAUDE_LINK"

  ENTRYPOINT_CLAUDE_MD_SOURCE="$CLAUDE_SRC" \
  ENTRYPOINT_CLAUDE_MD_LINK="$CLAUDE_LINK" \
    run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  [ -L "$CLAUDE_LINK" ]
  [ "$(readlink "$CLAUDE_LINK")" = "$CLAUDE_SRC" ]
}

@test "claude_md_symlink_preserved_when_already_present: DD-37 idempotent" {
  rm -f "$SETTINGS"
  CLAUDE_SRC="$BATS_TEST_TMPDIR/app-claude.md"
  CLAUDE_LINK="$BATS_TEST_TMPDIR/home-claude.md"
  printf '# image-baked\n' >"$CLAUDE_SRC"
  printf '# pre-existing override\n' >"$CLAUDE_LINK"

  ENTRYPOINT_CLAUDE_MD_SOURCE="$CLAUDE_SRC" \
  ENTRYPOINT_CLAUDE_MD_LINK="$CLAUDE_LINK" \
    run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  # Pre-existing file is left alone (not a symlink).
  [ ! -L "$CLAUDE_LINK" ]
  grep -q "pre-existing override" "$CLAUDE_LINK"
}

@test "plugin_symlinks_into_claude_local: DD-37 part B registers /app/plugins/* under ~/.claude/plugins/local/" {
  rm -f "$SETTINGS"
  PSRC="$BATS_TEST_TMPDIR/app-plugins"
  PLINK="$BATS_TEST_TMPDIR/claude-plugins-local"
  mkdir -p "$PSRC/foo-plugin" "$PSRC/bar-plugin"
  rm -rf "$PLINK"

  ENTRYPOINT_PLUGIN_SRC_ROOT="$PSRC" \
  ENTRYPOINT_PLUGIN_LINK_ROOT="$PLINK" \
    run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  [ -L "$PLINK/foo-plugin" ]
  [ -L "$PLINK/bar-plugin" ]
  [ "$(readlink "$PLINK/foo-plugin")" = "$PSRC/foo-plugin" ]
}

@test "plugin_symlink_preserves_existing_user_overlay: DD-37 part B is non-clobbering" {
  rm -f "$SETTINGS"
  PSRC="$BATS_TEST_TMPDIR/app-plugins"
  PLINK="$BATS_TEST_TMPDIR/claude-plugins-local"
  mkdir -p "$PSRC/nextseek-api"
  mkdir -p "$PLINK/nextseek-api"
  printf 'user-override\n' >"$PLINK/nextseek-api/marker"

  ENTRYPOINT_PLUGIN_SRC_ROOT="$PSRC" \
  ENTRYPOINT_PLUGIN_LINK_ROOT="$PLINK" \
    run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  # Pre-existing real dir must be left untouched (not turned into a symlink).
  [ ! -L "$PLINK/nextseek-api" ]
  [ -d "$PLINK/nextseek-api" ]
  grep -q "user-override" "$PLINK/nextseek-api/marker"
}

@test "claude_md_symlink_skipped_when_source_absent: DD-37 fails open" {
  rm -f "$SETTINGS"
  CLAUDE_SRC="$BATS_TEST_TMPDIR/missing-source.md"
  CLAUDE_LINK="$BATS_TEST_TMPDIR/home-claude.md"
  rm -f "$CLAUDE_SRC" "$CLAUDE_LINK"

  ENTRYPOINT_CLAUDE_MD_SOURCE="$CLAUDE_SRC" \
  ENTRYPOINT_CLAUDE_MD_LINK="$CLAUDE_LINK" \
    run "$ENTRYPOINT" true
  [ "$status" -eq 0 ]
  [ ! -e "$CLAUDE_LINK" ]
}

@test "b15_api_user_pass_exported_from_bridge_side: D20 NEXTSEEK_USERNAME/PASSWORD populate API_USER/API_PASS" {
  NEXTSEEK_USERNAME="alice" NEXTSEEK_PASSWORD="pw" run "$ENTRYPOINT" sh -c '
    echo "API_USER=$API_USER"
    echo "API_PASS=$API_PASS"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"API_USER=alice"* ]]
  [[ "$output" == *"API_PASS=pw"* ]]
}

@test "b15_canonical_api_user_wins_over_bridge_side: DD-19 precedence preserved for the new D20 names" {
  # If the caller explicitly sets API_USER, the bridge-side NEXTSEEK_USERNAME
  # MUST NOT override it. This is the same DD-19 precedence rule that test
  # #10 (env_var_alias_preserves_existing_canonical) enforces for SEEK_USER;
  # B15 extends the rule to API_USER.
  API_USER="canonical-user" API_PASS="canonical-pw" \
    NEXTSEEK_USERNAME="bridge-user" NEXTSEEK_PASSWORD="bridge-pw" \
    run "$ENTRYPOINT" sh -c '
      echo "API_USER=$API_USER"
      echo "API_PASS=$API_PASS"
    '
  [ "$status" -eq 0 ]
  [[ "$output" == *"API_USER=canonical-user"* ]]
  [[ "$output" == *"API_PASS=canonical-pw"* ]]
  # Negative assertion: bridge-side values MUST NOT have overwritten canonical.
  [[ "$output" != *"API_USER=bridge-user"* ]]
}

@test "b15_nextseek_mode_defaults_gcp: D23 GCP-only profile for v3 image" {
  # No NEXTSEEK_MODE supplied -> entrypoint defaults to gcp.
  unset NEXTSEEK_MODE 2>/dev/null || true
  NEXTSEEK_USERNAME="alice" NEXTSEEK_PASSWORD="pw" run "$ENTRYPOINT" sh -c '
    echo "NEXTSEEK_MODE=$NEXTSEEK_MODE"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"NEXTSEEK_MODE=gcp"* ]]
}

@test "b15_nextseek_mode_explicit_preserved: caller-supplied NEXTSEEK_MODE=aws survives" {
  # If the caller explicitly sets NEXTSEEK_MODE, the default MUST NOT
  # overwrite it (POSIX := semantics). This is regression protection for
  # post-Plan-B AWS profile work.
  NEXTSEEK_MODE="aws" NEXTSEEK_USERNAME="alice" NEXTSEEK_PASSWORD="pw" \
    run "$ENTRYPOINT" sh -c '
      echo "NEXTSEEK_MODE=$NEXTSEEK_MODE"
    '
  [ "$status" -eq 0 ]
  [[ "$output" == *"NEXTSEEK_MODE=aws"* ]]
}

@test "b15_seek_user_seek_password_back_compat: legacy names still exported for host-side tooling" {
  # Back-compat: SEEK_USER/SEEK_PASSWORD remain exported (sourced from
  # API_USER/API_PASS via the second-tier := chain in the new block). Any
  # host-side tooling that grew up reading SEEK_USER continues to work.
  # Note: the existing test #9 (env_var_alias_propagates) covered the OLD
  # path NEXTSEEK_USERNAME -> SEEK_USER directly; B15 changes the path to
  # NEXTSEEK_USERNAME -> API_USER -> SEEK_USER. The end value is identical.
  NEXTSEEK_USERNAME="alice" NEXTSEEK_PASSWORD="pw" run "$ENTRYPOINT" sh -c '
    echo "SEEK_USER=$SEEK_USER"
    echo "SEEK_PASSWORD=$SEEK_PASSWORD"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SEEK_USER=alice"* ]]
  [[ "$output" == *"SEEK_PASSWORD=pw"* ]]
}

@test "dmac_runtime_mode_idle_skips_exec_and_keeps_running: DD-04 idle branch does not run \$@" {
  # DMAC_RUNTIME_MODE=idle → entrypoint must NOT exec "$@". The child command
  # below would create MARKER; if MARKER is created, the idle branch failed.
  # We use `timeout 2` because `exec sleep infinity` blocks forever — the
  # 124 exit status from timeout proves the entrypoint was still running.
  rm -f "$SETTINGS"
  rm -f "$MARKER"

  DMAC_RUNTIME_MODE="idle" run timeout 2 "$ENTRYPOINT" sh -c 'touch "$MARKER"'
  # 124 = timeout killed it (process was alive — good).
  # On macOS coreutils-from-homebrew `gtimeout` also returns 124; if `timeout`
  # is missing this test environment is broken — that's a setup error, not a
  # test failure, but we still assert here to catch the missing-binary case.
  [ "$status" -eq 124 ]
  # The child command MUST NOT have run.
  [ ! -e "$MARKER" ]
}

@test "dmac_runtime_mode_idle_completes_pre_flight: scrub still runs before idle sleep (Risk #2 gate)" {
  # The HIGH-severity risk in the plan: idle mode must NOT bypass settings
  # scrubbing. This test verifies that even when the entrypoint goes idle,
  # the settings.local.json env block was scrubbed during pre-flight.
  cat >"$SETTINGS" <<'EOF'
{"env":{"SECRET":"CANARY-idle"},"model":"m"}
EOF
  rm -f "$MARKER"

  DMAC_RUNTIME_MODE="idle" run timeout 2 "$ENTRYPOINT" sh -c 'touch "$MARKER"'
  [ "$status" -eq 124 ]
  [ ! -e "$MARKER" ]
  # SETTINGS scrub must have already happened before the idle sleep.
  run jq 'has("env")' "$SETTINGS"
  [ "$status" -eq 0 ]
  [ "$output" = "false" ]
}

@test "dmac_runtime_mode_unset_runs_exec_normally: default path unchanged (flag-OFF parity)" {
  # When DMAC_RUNTIME_MODE is unset, behavior is byte-identical to today's
  # entrypoint: exec "$@" runs the declared command.
  rm -f "$SETTINGS"
  unset DMAC_RUNTIME_MODE 2>/dev/null || true

  run "$ENTRYPOINT" sh -c 'echo normal-path'
  [ "$status" -eq 0 ]
  [[ "$output" == *"normal-path"* ]]
}

@test "dmac_runtime_mode_non_idle_value_runs_exec: only literal 'idle' triggers idle mode" {
  # DMAC_RUNTIME_MODE=anything-else MUST behave like DMAC_RUNTIME_MODE unset.
  # This protects against typos (DMAC_RUNTIME_MODE=IDLE / =Idle / =yes / =1)
  # silently going idle.
  rm -f "$SETTINGS"

  # Empty value behaves as unset.
  DMAC_RUNTIME_MODE="" run "$ENTRYPOINT" sh -c 'echo empty-val'
  [ "$status" -eq 0 ]
  [[ "$output" == *"empty-val"* ]]

  # Capitalization variations are NOT idle.
  DMAC_RUNTIME_MODE="IDLE" run "$ENTRYPOINT" sh -c 'echo upper-IDLE'
  [ "$status" -eq 0 ]
  [[ "$output" == *"upper-IDLE"* ]]

  # Arbitrary value is NOT idle.
  DMAC_RUNTIME_MODE="container_cc" run "$ENTRYPOINT" sh -c 'echo cc-val'
  [ "$status" -eq 0 ]
  [[ "$output" == *"cc-val"* ]]
}
