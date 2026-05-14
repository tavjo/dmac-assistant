#!/usr/bin/env python3
"""Render an interactive HTML report from a `run_batch.py` manifest.

The manifest is the JSON `evidence/headless/<run_id>/manifest.json`
produced by `tools/e2e/run_batch.py`. Each entry under `summaries` is a
QueryRecord summary; this script also reads each per-query
`<qid>.record.json` for the full final_answer text.

Output: a single self-contained HTML file (default
`<run_id>/report.html`) with:
  - run header (counts, totals, averages)
  - latency + cost bar charts (Chart.js from CDN)
  - per-query table with answered / error pills
  - click a row to expand the full assistant reply, tool-use breakdown,
    error string, and a link to the raw stdout JSONL

All user-controlled content is rendered via createElement + textContent
(never innerHTML) so corpus query text and assistant replies cannot
inject markup.

USAGE
  tools/e2e/render_report.py --manifest evidence/headless/<run_id>/manifest.json
  tools/e2e/render_report.py --manifest <path> --output <report.html>
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import sys


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DMAC Headless Run __TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {
    --bg: #FFFFFF;
    --surface: #F8F6FC;
    --surface-alt: #F0EDF5;
    --text: #1a1a2e;
    --text-muted: #6b7280;
    --text-light: #9ca3af;
    --accent: #A31F34;
    --accent-light: #c8102e;
    --success: #22c55e;
    --success-light: #dcfce7;
    --warning: #f59e0b;
    --warning-light: #fef3c7;
    --error: #ef4444;
    --error-light: #fee2e2;
    --border: #e5e7eb;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono: 'SF Mono', 'Fira Code', Consolas, monospace;
}
* { box-sizing: border-box; }
body {
    margin: 0; padding: 32px;
    background: var(--surface); color: var(--text);
    font-family: var(--font); font-size: 14px; line-height: 1.55;
}
h1 { margin: 0 0 4px 0; font-size: 22px; }
h2 { margin: 0 0 12px 0; font-size: 16px; color: var(--text-muted); font-weight: 600; }
.container { max-width: 1280px; margin: 0 auto; }
.header {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; margin-bottom: 20px;
}
.header-meta {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 16px; margin-top: 16px;
}
.metric {
    background: var(--surface-alt);
    padding: 12px 16px; border-radius: 8px;
    border-left: 3px solid var(--accent);
}
.metric-label { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.metric-note { font-size: 11px; color: var(--text-muted); margin-top: 2px; font-variant-numeric: tabular-nums; }
.run-meta { font-size: 12px; color: var(--text-muted); margin-top: 12px; font-family: var(--font-mono); }
.charts {
    display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;
}
.chart-card {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; height: 280px; position: relative;
}
.controls {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 16px; margin-bottom: 12px;
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
}
.controls input[type=search] {
    flex: 1; min-width: 240px; padding: 6px 10px;
    border: 1px solid var(--border); border-radius: 6px; font: inherit;
}
.controls label { display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); font-size: 13px; }
.table-card {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; overflow: hidden;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
    padding: 10px 12px; text-align: left; vertical-align: top;
    border-bottom: 1px solid var(--border);
}
th {
    background: var(--surface);
    font-weight: 600; color: var(--text-muted);
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
}
.row-summary { cursor: pointer; }
.row-summary:hover { background: var(--surface); }
.row-detail { display: none; background: var(--surface); }
.row-detail.open { display: table-row; }
.row-detail td { padding: 16px 24px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.detail-block { background: var(--bg); padding: 12px; border-radius: 6px; border: 1px solid var(--border); }
.detail-block h3 { margin: 0 0 6px 0; font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.answer { font-family: var(--font-mono); white-space: pre-wrap; font-size: 12px; max-height: 360px; overflow: auto; background: var(--surface); padding: 10px; border-radius: 4px; }
.tool-row { display: flex; justify-content: space-between; padding: 2px 0; font-family: var(--font-mono); font-size: 12px; }
.tool-row .name { color: var(--text); }
.tool-row .count { color: var(--text-muted); font-variant-numeric: tabular-nums; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
.pill.ok { background: var(--success-light); color: #166534; }
.pill.fail { background: var(--error-light); color: #991b1b; }
.pill.warn { background: var(--warning-light); color: #92400e; }
.pill.muted { background: var(--surface-alt); color: var(--text-muted); }
.qtext { color: var(--text-muted); font-style: italic; max-width: 480px; }
.num { font-variant-numeric: tabular-nums; text-align: right; }
.error-line { color: var(--error); font-family: var(--font-mono); font-size: 12px; margin-top: 4px; }
.path { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); word-break: break-all; }
footer { color: var(--text-light); font-size: 11px; margin-top: 24px; text-align: center; }
@media (max-width: 900px) {
    .charts, .header-meta, .detail-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>DMAC Headless Run __TITLE__</h1>
        <h2>Plugin: nextseek &middot; image __IMAGE__</h2>
        <div class="header-meta">
            <div class="metric">
                <div class="metric-label">Queries</div>
                <div class="metric-value">__N__</div>
                <div class="metric-note">__N_ANSWERED__ answered &middot; __N_ERRORED__ error</div>
            </div>
            <div class="metric">
                <div class="metric-label">Answer Rate</div>
                <div class="metric-value">__ANSWER_RATE__</div>
                <div class="metric-note">__N_TIMED_OUT__ timed out</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Cost</div>
                <div class="metric-value">$__TOTAL_COST__</div>
                <div class="metric-note">avg $__AVG_COST__ / query</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Latency</div>
                <div class="metric-value">__TOTAL_LATENCY__s</div>
                <div class="metric-note">avg __AVG_LATENCY__s / query</div>
            </div>
        </div>
        <div class="run-meta">started __STARTED__ &middot; finished __COMPLETED__ &middot; corpus __CORPUS__ &middot; timeout __TIMEOUT__s &middot; budget $__MAX_BUDGET__</div>
    </div>

    <div class="charts">
        <div class="chart-card"><canvas id="latencyChart"></canvas></div>
        <div class="chart-card"><canvas id="costChart"></canvas></div>
    </div>

    <div class="controls">
        <input type="search" id="search" placeholder="Filter by id or query text...">
        <label><input type="checkbox" id="onlyErrors"> errors only</label>
        <label><input type="checkbox" id="onlyAnswered"> answered only</label>
    </div>

    <div class="table-card">
        <table id="qtable">
            <thead>
                <tr>
                    <th>#</th>
                    <th>ID</th>
                    <th>Query</th>
                    <th class="num">Latency</th>
                    <th class="num">Cost</th>
                    <th class="num">Tools</th>
                    <th>Answered</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="qbody"></tbody>
        </table>
    </div>

    <footer>Generated by tools/e2e/render_report.py &middot; run_id <span class="path">__RUN_ID__</span></footer>
</div>

<script type="application/json" id="manifest">__MANIFEST_JSON__</script>
<script>
(function () {
    // helpers — never set innerHTML on user-controlled content
    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            for (var k in attrs) {
                if (k === 'class') node.className = attrs[k];
                else if (k === 'dataset') {
                    for (var dk in attrs[k]) node.dataset[dk] = attrs[k][dk];
                } else if (k.indexOf('on') === 0) {
                    node.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
                } else if (attrs[k] != null) {
                    node.setAttribute(k, attrs[k]);
                }
            }
        }
        if (children != null) {
            if (typeof children === 'string') node.textContent = children;
            else if (Array.isArray(children)) {
                children.forEach(function (c) {
                    if (c == null) return;
                    if (typeof c === 'string') node.appendChild(document.createTextNode(c));
                    else node.appendChild(c);
                });
            } else node.appendChild(children);
        }
        return node;
    }
    function pillFor(s) {
        if (s.timed_out) return el('span', { class: 'pill warn' }, 'timeout');
        if (s.is_error)  return el('span', { class: 'pill fail' }, s.error || 'error');
        if (s.answer_provided) return el('span', { class: 'pill ok' }, 'ok');
        return el('span', { class: 'pill muted' }, 'no answer');
    }

    var data = JSON.parse(document.getElementById('manifest').textContent);
    var summaries = data.summaries || [];

    // ---- charts ----
    var labels = summaries.map(function (s) { return s.query_id; });
    var latencies = summaries.map(function (s) { return s.latency_seconds || 0; });
    var costs = summaries.map(function (s) { return s.cost_usd || 0; });
    var colorOK = '#22c55e', colorFail = '#ef4444';
    var colors = summaries.map(function (s) { return s.is_error ? colorFail : colorOK; });

    new Chart(document.getElementById('latencyChart'), {
        type: 'bar',
        data: { labels: labels, datasets: [{ label: 'latency (s)', data: latencies, backgroundColor: colors }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, title: { display: true, text: 'Latency per query (s)' } },
            scales: { y: { beginAtZero: true } },
        },
    });
    new Chart(document.getElementById('costChart'), {
        type: 'bar',
        data: { labels: labels, datasets: [{ label: 'cost (USD)', data: costs, backgroundColor: colors }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, title: { display: true, text: 'Cost per query (USD)' } },
            scales: { y: { beginAtZero: true } },
        },
    });

    // ---- table ----
    var tbody = document.getElementById('qbody');
    var detailRows = [];

    summaries.forEach(function (s, i) {
        var idCode = el('code', null, s.query_id || '');
        var summaryRow = el('tr', { class: 'row-summary', dataset: { index: String(i) } }, [
            el('td', { class: 'num' }, String(i + 1)),
            el('td', null, idCode),
            el('td', { class: 'qtext' }, (s.query_text || '').slice(0, 200)),
            el('td', { class: 'num' }, (s.latency_seconds || 0).toFixed(1) + 's'),
            el('td', { class: 'num' }, (s.cost_estimated ? '~$' : '$') + (s.cost_usd || 0).toFixed(4)),
            el('td', { class: 'num' }, String(s.tool_calls_total || 0)),
            el('td', null, s.answer_provided ? '✓' : '—'),
            el('td', null, pillFor(s)),
        ]);

        var toolsBlock = el('div');
        var tools = s.tool_use_summary || [];
        if (tools.length === 0) {
            toolsBlock.appendChild(el('div', { class: 'tool-row' }, [
                el('span', { class: 'name' }, '(no tool calls)'),
            ]));
        } else {
            tools.forEach(function (t) {
                toolsBlock.appendChild(el('div', { class: 'tool-row' }, [
                    el('span', { class: 'name' }, t.tool || ''),
                    el('span', { class: 'count' }, String(t.count || 0)),
                ]));
            });
        }

        var meta = el('div');
        meta.appendChild(el('h3', { style: 'margin-top:12px' }, 'Run metadata'));
        meta.appendChild(el('div', { class: 'tool-row' }, [
            el('span', { class: 'name' }, 'num_turns'),
            el('span', { class: 'count' }, s.num_turns != null ? String(s.num_turns) : '—'),
        ]));
        meta.appendChild(el('div', { class: 'tool-row' }, [
            el('span', { class: 'name' }, 'stop_reason'),
            el('span', { class: 'count' }, s.stop_reason || '—'),
        ]));
        if (s.error) {
            meta.appendChild(el('div', { class: 'error-line' }, 'error: ' + s.error));
        }
        if (s.record_path) {
            meta.appendChild(el('div', { class: 'path', style: 'margin-top:8px' }, s.record_path));
        }

        var detailGrid = el('div', { class: 'detail-grid' }, [
            el('div', { class: 'detail-block' }, [
                el('h3', null, 'Final assistant reply'),
                el('div', { class: 'answer' }, s.final_answer || '(answer not loaded)'),
            ]),
            el('div', { class: 'detail-block' }, [
                el('h3', null, 'Tool use'),
                toolsBlock,
                meta,
            ]),
        ]);
        var detailRow = el('tr', { class: 'row-detail' }, [
            el('td', { colspan: '8' }, detailGrid),
        ]);
        detailRows.push(detailRow);
        tbody.appendChild(summaryRow);
        tbody.appendChild(detailRow);
    });

    tbody.addEventListener('click', function (e) {
        var row = e.target.closest('.row-summary');
        if (!row) return;
        var next = row.nextElementSibling;
        if (next && next.classList.contains('row-detail')) next.classList.toggle('open');
    });

    // ---- filters ----
    var search = document.getElementById('search');
    var onlyErrors = document.getElementById('onlyErrors');
    var onlyAnswered = document.getElementById('onlyAnswered');
    function applyFilters() {
        var q = search.value.toLowerCase();
        var wantErr = onlyErrors.checked;
        var wantAns = onlyAnswered.checked;
        Array.from(tbody.children).forEach(function (row) {
            if (!row.classList.contains('row-summary')) return;
            var i = parseInt(row.dataset.index, 10);
            var s = summaries[i];
            var detail = row.nextElementSibling;
            var show = true;
            if (q && !((s.query_id || '').toLowerCase().includes(q)
                    || (s.query_text || '').toLowerCase().includes(q))) show = false;
            if (wantErr && !s.is_error) show = false;
            if (wantAns && !s.answer_provided) show = false;
            row.style.display = show ? '' : 'none';
            if (detail) {
                if (!show) detail.classList.remove('open');
                detail.style.display = show ? '' : 'none';
            }
        });
    }
    search.addEventListener('input', applyFilters);
    onlyErrors.addEventListener('change', applyFilters);
    onlyAnswered.addEventListener('change', applyFilters);
})();
</script>
</body>
</html>
"""


def _hydrate_summaries(manifest: dict, manifest_dir: pathlib.Path) -> dict:
    """Augment each summary with `final_answer` from its per-query record."""
    for s in manifest.get("summaries", []):
        rp = s.get("record_path")
        if not rp:
            continue
        rec_path = pathlib.Path(rp)
        # record_path in run_batch.py is written relative to CWD (where
        # run_batch was invoked). Try as-is first; if that misses, fall
        # back to looking next to the manifest by basename — this handles
        # both stored-relative and stored-absolute paths, and lets the
        # report be rendered after the run dir was moved.
        candidates = []
        if rec_path.is_absolute():
            candidates.append(rec_path)
        else:
            candidates.append(rec_path)  # relative to CWD
            candidates.append(manifest_dir / rec_path.name)
        rec = None
        for cand in candidates:
            try:
                rec = json.loads(cand.read_text())
                break
            except Exception:
                continue
        if rec is None:
            continue
        s["final_answer"] = rec.get("final_answer")
        s.setdefault("tool_use_summary", rec.get("tool_use_summary", []))
    return manifest


def render(manifest_path: pathlib.Path, output_path: pathlib.Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    manifest = _hydrate_summaries(manifest, manifest_path.parent)

    n = manifest.get("queries_total", 0)
    rate = manifest.get("answer_rate", 0.0)
    rendered = (
        _HTML_TEMPLATE
        .replace("__TITLE__", html.escape(manifest.get("run_id", "")))
        .replace("__IMAGE__", html.escape(manifest.get("image", "")))
        .replace("__N__", str(n))
        .replace("__N_ANSWERED__",
                 str(manifest.get("queries_answered", 0)))
        .replace("__N_ERRORED__",
                 str(manifest.get("queries_errored", 0)))
        .replace("__N_TIMED_OUT__",
                 str(manifest.get("queries_timed_out", 0)))
        .replace("__ANSWER_RATE__", f"{rate * 100:.0f}%")
        .replace("__TOTAL_COST__",
                 f"{manifest.get('total_cost_usd', 0.0):.4f}")
        .replace("__AVG_COST__",
                 f"{manifest.get('avg_cost_usd', 0.0):.4f}")
        .replace("__TOTAL_LATENCY__",
                 f"{manifest.get('total_latency_seconds', 0.0):.1f}")
        .replace("__AVG_LATENCY__",
                 f"{manifest.get('avg_latency_seconds', 0.0):.1f}")
        .replace("__STARTED__",
                 html.escape(manifest.get("started_at", "")))
        .replace("__COMPLETED__",
                 html.escape(manifest.get("completed_at", "")))
        .replace("__CORPUS__", html.escape(
            pathlib.Path(manifest.get("corpus", "")).name or "(unknown)",
        ))
        .replace("__TIMEOUT__", str(manifest.get("timeout_seconds", "")))
        .replace("__MAX_BUDGET__",
                 f"{manifest.get('max_budget_usd', 0.0)}")
        .replace("__RUN_ID__", html.escape(manifest.get("run_id", "")))
        .replace(
            "__MANIFEST_JSON__",
            json.dumps(manifest).replace("</", "<\\/"),
        )
    )
    output_path.write_text(rendered)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    ap.add_argument("--manifest", required=True,
                    help="path to a run_batch manifest.json")
    ap.add_argument("--output",
                    help="output html path "
                         "(default: <manifest_dir>/report.html)")
    args = ap.parse_args()

    manifest_path = pathlib.Path(args.manifest).expanduser().resolve()
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    output_path = (
        pathlib.Path(args.output).expanduser().resolve()
        if args.output
        else manifest_path.parent / "report.html"
    )

    render(manifest_path, output_path)
    print(f"wrote {output_path}", file=sys.stderr)
    print(str(output_path))


if __name__ == "__main__":
    main()
