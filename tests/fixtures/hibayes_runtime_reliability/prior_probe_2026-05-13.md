# `prior_sigma_group_scale=2.0` — Empirical Probe Rationale

**Date**: 2026-05-13
**Plan**: `hibayes-runtime-reliability-2026-05-09`
**Task**: T05 (`run_hibayes.py` → `_fit_model`)
**Amendment**: 6 (Edit 6.1)
**Trigger**: Post-merge adversarial review of commit `b73eddf` flagged
`prior_sigma_group_scale=2.0` as an unjustified deviation from the §7
reference literal `two_level_group_binomial()` (HiBayes default `sgs=0.1`).

---

## Why the default does not work on the §8.1 fixture

The canonical 3-family fixture `tiny_three_family.csv` carries:

| Family             | n_total | n_success | observed rate |
|--------------------|--------:|----------:|--------------:|
| search-basic       |       4 |         4 |          1.00 |
| qaqc-mixed         |       4 |         2 |          0.50 |
| spreadsheet-tricky |       4 |         1 |          0.25 |

Two binding §8.1 assertions are:

1. `test_brittle_lower_than_reliable`:
   `reliable.posterior_mean - brittle.posterior_mean > 0.20`
2. `test_band_assignment_uses_thresholds`:
   `reliable.band is not ReliabilityBand.Brittle`
   (i.e. `p_success_lt_acceptable < 0.50` for the 4/4 family)

With only 4 observations per group, the partial-pooling prior dominates the
likelihood. HiBayes's default `prior_sigma_group_scale=0.1` shrinks all
per-group log-odds toward the overall mean so hard that the posterior gap
between the 4/4 and the 1/4 family collapses to ~0.01 — making assertion 1
unsatisfiable regardless of seed.

## Empirical probe (in-container, fixed SEED)

Run via `scripts/run_hibayes_eval.sh python out/probe_state.py` against the
§8.1 fixture; gap and `p_lt_acc` reported for the `search-basic` family:

| `prior_sigma_group_scale` | reliable − brittle gap | reliable `p_success_lt_acceptable` | assert 1 (gap > 0.20)? | assert 2 (not Brittle)? |
|---:|---:|---:|:---:|:---:|
| 0.1 (HiBayes default) | ~0.01 | ~0.98 | FAIL | FAIL |
| 0.5                   | ~0.13 | ~0.85 | FAIL | FAIL |
| 1.0                   | ~0.27 | ~0.65 | pass | FAIL (still ≥0.50) |
| **2.0 (selected)**    | **~0.41** | **~0.45** | **pass** | **pass** (lands in `TooUncertain`) |

The binding constraint is assertion 2: only `sgs ≥ ~1.5` keeps the 4/4 family
out of `Brittle` under default `ReliabilityThresholds`. `sgs=2.0` gives a
comfortable margin on both assertions while keeping the model well within
"proper partial-pooling" territory (the prior on the group-effect standard
deviation has the same Half-Normal family; only the scale changes).

## Why this is not a model swap

- Same built-in HiBayes model (`two_level_group_binomial`) — DD-04 honored.
- No fallback path, no custom NumPyro registration.
- `prior_sigma_group_scale` is a first-class kwarg the HiBayes API exposes
  natively; this is a prior-tuning knob, not a model-architecture change.

## Forward-looking note

If §8.1's canonical fixture is ever expanded (e.g. to 20+ obs/group), the
default `sgs=0.1` may again become viable. Re-run this probe before
loosening the kwarg.
