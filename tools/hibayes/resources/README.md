# tools/hibayes/resources/

Resource files consumed by Stage A's HiBayes artifact validator.

## `GEO-updated.json`

Canonical GEO sample-template JSON. **In-repo copy** is the runtime authority
for Stage A's GEO `.xlsx` validator (locked-spec DD-39 Option (a) + plan-DD-02).

### When to refresh

When `chat_nextseek` upstream changes the GEO template format (rare).

### How to refresh

1. Ensure the vendored `chat_nextseek` checkout is current: `make sync-vendor-deps`.
2. Resync the in-repo copy:

   ```bash
   cp vendor/chat_nextseek/src/chat_nextseek/reports/GEO-updated.json \
      tools/hibayes/resources/GEO-updated.json
   ```

3. Run the parity test to confirm the copy matches the vendor version:

   ```bash
   uv run pytest tools/hibayes/tests/test_geo_template_parity.py \
       --override-ini="addopts=" \
       --override-ini="testpaths=tools/hibayes/tests" \
       --disable-socket
   ```

4. Commit both the updated JSON and any test/code changes that flow from the
   format change in a single PR.

### Why an in-repo copy?

Per locked-spec DD-39 + plan-DD-02 — CI-portable by construction. The
alternative (resolving the vendor path at runtime + GH-token fallback) was
rejected for ongoing credential-maintenance cost.
