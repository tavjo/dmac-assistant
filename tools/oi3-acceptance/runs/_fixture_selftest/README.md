# `_fixture_selftest/` — synthetic PASS fixture for `validate_acceptance.py`

This directory is **NOT a real acceptance run**. It is a committed, hand-built
fixture whose artifacts satisfy all seven T6 success conditions, used to prove
`validate_acceptance.py` returns exit 0 on a well-formed run **without spending
any money / making any Bedrock call**.

Every sentinel and token value here is an **obvious fake**
(`00000000-fake-fake-fake-000000000000`); no real secret is present (R-8).

- Real authorized runs land in sibling timestamped dirs `runs/<ts>/` written by
  `run_acceptance.py` on an authorized invocation.
- The hermetic test `tests/unit/test_validate_acceptance.py` exercises the
  validator against this PASS fixture **and** against programmatically-mutated
  FAILING variants, so the validator's gate logic is covered by the hermetic
  suite with zero spend.
