# NExtSEEK Docs Markdown-Page Diagnosis — 2026-05-04

## Verdict

**PASS.** GitBook `site-index` plus per-page Markdown is a stable replacement for the nondeterministic PDF/`markitdown` export path.

## Source

- Site index: `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/site-index`
- Pages discovered: 10
- Canonical order:
  1. Overview
  2. Using SEEK and NExtSEEK
  3. Uploading
  4. Searching / Downloading
  5. Admin Pages
  6. Useful Links
  7. Installation
  8. SEEK
  9. NExtSEEK
  10. Contact / Staff

## Resolution Rules Confirmed

- Normal and nested pages resolve as `pathname + ".md"`.
- The root page pathname `/mit-data-management-analysis-core` must use the title-slug fallback:
  - `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/overview.md`
- Direct root `.md` (`/mit-data-management-analysis-core.md`) redirects to GitBook app HTML and must not be used.

## Stability Evidence

Every resource below was fetched three times and returned identical SHA-256 hashes, byte counts, and valid content shape.

| Resource | Bytes | SHA-256 |
|---|---:|---|
| site-index | 2318 | `5d7b6398ae6b97493cabd86ab28cd70af46c0112e9721baa7a312309ad5f5461` |
| Overview | 4198 | `08896c96a89442ecd9f3beb91da3b38664b5b3a9fe5c922785734118ff26f592` |
| Using SEEK and NExtSEEK | 11851 | `20fcd9b464a554eaa936fa92065a12c7db294cac840ca9f684c9ac8d7f459ea5` |
| Uploading | 11447 | `de81bff8249b96706869130f6d4c0245da0c03b9130bcfaa5e406578295cb1f9` |
| Searching / Downloading | 8079 | `e9b2d1d8b3696edb0c9f2b5936e424b21e58c9006c87becbecd58b5544a2a02f` |
| Admin Pages | 2080 | `3041a60a516f06fdbb6cc92adf7bf18df0b7c790bb9c396097f2935b475489ad` |
| Useful Links | 1412 | `40a354ff4a28c30e21da1579171dfeeb3d7632ee7b9e998ff8514ffef2ff4158` |
| Installation | 1238 | `6cde3c056c55954ece1e2510a67a526a5769ff6281f8ebf337ec8bdad06e6901` |
| SEEK | 13901 | `d42143a3a87ff90f9a242e2a55b6580e83cfa753bbf50c4dad5a7a659be9419f` |
| NExtSEEK | 11598 | `6eef9c1f2a9b7f3e17abea74a0345817d27a1659f85732223e65a5fa7acf2331` |
| Contact / Staff | 2191 | `8fdcca00b72f09f934ed8701ccc555d3c8d7dae61a12ecae1c3fd300dcb95842` |

## Implementation Direction

Proceed with the site-index plus per-page Markdown loader. The old PDF/`markitdown` source is superseded for normal ingest.
