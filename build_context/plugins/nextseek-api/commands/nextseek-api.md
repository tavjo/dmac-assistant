---
description: >
  Interactive NExtSEEK API query plugin. Asks for dev vs prod selection and .env
  location, bootstraps a SchemaRAG session, caches the minimal endpoint catalog,
  then enables live queries against any NExtSEEK endpoint with static validation
  and 3-layer write-safety enforcement. Use whenever you need to look up samples,
  projects, studies, or any NExtSEEK metadata without writing bespoke curl calls.
argument-hint: "[question] — describe what to query, or leave empty to start bootstrap"
---

# /nextseek-api

You have been invoked via the `/nextseek-api` command. Load the `nextseek-api` skill
and begin its bootstrap workflow.

The `nextseek-api` skill contains the full interactive flow. Start at its **Quick Start**
section: the three-command happy-path is `nextseek-init` -> `nextseek-spec` -> `nextseek-call`
(the unified resolve+validate+execute shim — preferred over invoking `nextseek-validate` and
`nextseek-exec` separately). Use `nextseek-vocab resolve <TERM>` (or Read the cached
`entity_tree.json`) when building `advanced_search` bodies, and `nextseek-session` to inspect
the current session TTL and cache paths.

The skill documents the write-safety rules (including the AskUserQuestion requirement before
any non-GET, non-`schema_rag` call), the env-var precedence (`NEXTSEEK_BASE_URL` >
`API_BASE_URL` > `BASE_URL`, with `USE_DEV_API=1` as a hard override), the v2 cache layout,
pagination (`--auto-paginate`, `page[size]` / `page[number]`), and three worked example
transcripts. Refer to its troubleshooting section for common errors (auth failure, cache
miss, session expiry).

If `$ARGUMENTS` contains a question, carry it into the first per-query loop iteration
after bootstrap completes. Otherwise, start at the dev/prod selection step.
