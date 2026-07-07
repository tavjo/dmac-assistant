"""Hermetic $0 batch-upload E2E helpers.

The functions in this module exercise the shipped NExtSEEK batch-upload runner
in-process with ``httpx.MockTransport``. They deliberately do not start the
bridge, call live services, or run paid model traffic.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Any

import httpx
import orjson
import polars as pl

from tools.e2e.ledger import SpendLedger

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
FIXTURE_DIR = REPO_ROOT / "tests" / "unit" / "fixtures" / "ns"
REQUIRED_CHECKS = {"structure", "name_check", "dag"}
BEDROCK_MODEL = "claude-opus-4-8 (Bedrock, via proxy)"
GEMINI_MODEL = "gemini-3.1-pro-preview (GCPReasoner)"


@dataclass
class RunnerResult:
    rc: int
    stdout: str
    marker: dict[str, Any] | None
    artifact: pathlib.Path | None
    validate_posts: list[dict[str, str]]


def run_c8_regression(workdir: pathlib.Path) -> RunnerResult:
    """Drive the shipped runner with an empty create request.

    The runner must refuse locally at ``non_empty`` before any schema or
    validate request can be made.
    """
    rows = [{"UID": "", "SampleType": "TIS", "attributes": {}}]
    transport, calls = _transport({})
    return _run_build_validate(workdir, rows, transport=transport, calls=calls)


def run_create_positive_control(workdir: pathlib.Path) -> RunnerResult:
    rows = [
        {
            "UID": "",
            "SampleType": "TIS",
            "attributes": {"Name": "sample", "Scientist": "Curator", "Parent": "P1"},
        }
    ]
    transport, calls = _transport(_route_table(validate_processed=1))
    return _run_build_validate(workdir, rows, transport=transport, calls=calls)


def run_update_positive_control(workdir: pathlib.Path) -> RunnerResult:
    uid = _probe_uid()
    rows = [
        {
            "UID": uid,
            "SampleType": "TIS",
            "attributes": {"Treatment": "drug"},
            "assay_titles": ["PCR - Data Linked"],
        }
    ]
    transport, calls = _transport(_route_table(validate_processed=1))
    return _run_build_validate(workdir, rows, transport=transport, calls=calls)


def record_bedrock_result(frame: dict[str, Any], ledger: SpendLedger) -> dict[str, Any]:
    result = frame["result"]
    usage = result["usage"]
    total = result["total_cost_usd"]
    ledger.record(
        "bedrock",
        model=result.get("model", BEDROCK_MODEL),
        in_tokens=usage["input_tokens"],
        out_tokens=usage["output_tokens"],
        actual_usd=total,
    )
    return {"model": result.get("model", BEDROCK_MODEL), "usage": usage, "total_cost_usd": total}


def record_gemini_cost(router_usage: dict[str, Any] | None, cc_frame: dict[str, Any]) -> dict[str, Any]:
    if router_usage is None:
        return {"gemini_cost": "unavailable"}
    cost = router_usage["total_cost_usd"]
    if cost == cc_frame.get("result", {}).get("total_cost_usd"):
        raise ValueError("gemini cost source equals CC sentinel")
    return {
        "model": router_usage.get("model", GEMINI_MODEL),
        "usage": router_usage["usage"],
        "total_cost_usd": cost,
    }


def delivery_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    update_rows = sum(1 for row in rows if str(row.get("UID") or "").strip())
    create_rows = len(rows) - update_rows
    return {
        "create_rows": create_rows,
        "update_rows": update_rows,
        "mixed_create_update": bool(create_rows and update_rows),
        "update_existing_note": "update rows require update_existing=true at upload time",
    }


def cost_guard_violations(source: str, function_name: str = "record_bedrock_result") -> list[str]:
    tree = ast.parse(source)
    target = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    literal_names: set[str] = set()
    errors: list[str] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Assign) and _literal_numeric_flow(node.value, literal_names):
            for name in node.targets:
                if isinstance(name, ast.Name):
                    literal_names.add(name.id)
        if isinstance(node, ast.Call) and isinstance(getattr(node.func, "attr", ""), str) and node.func.attr == "record":
            for keyword in node.keywords:
                if keyword.arg in {"in_tokens", "out_tokens"}:
                    if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int):
                        errors.append(f"direct literal for {keyword.arg}")
                    if _literal_numeric_flow(keyword.value, literal_names):
                        errors.append(f"literal-derived name for {keyword.arg}")
                if keyword.arg in {"actual_usd", "total_cost_usd"} and _literal_numeric_flow(keyword.value, literal_names):
                    errors.append(f"literal-derived cost for {keyword.arg}")
        if isinstance(node, ast.Dict):
            literal_keys = {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and key.value in {"input_tokens", "output_tokens", "actual_usd", "total_cost_usd"}
            }
            if literal_keys:
                for value in node.values:
                    if _literal_numeric_flow(value, literal_names):
                        errors.append("literal-derived value in usage/cost dict")
    return errors


def _literal_numeric_flow(node: ast.AST, literal_names: set[str]) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return True
    if isinstance(node, ast.Name):
        return node.id in literal_names
    if isinstance(node, ast.Subscript):
        return _literal_numeric_flow(node.value, literal_names)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _literal_numeric_flow(node.operand, literal_names)
    if isinstance(node, ast.BinOp):
        return _literal_numeric_flow(node.left, literal_names) or _literal_numeric_flow(node.right, literal_names)
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(_literal_numeric_flow(elt, literal_names) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return any(_literal_numeric_flow(value, literal_names) for value in node.values)
    return False


def workbook_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    df = pl.read_excel(path, sheet_name="Samples", engine="calamine")
    return [{column: df[column][idx] for column in df.columns} for idx in range(df.height)]


def _run_build_validate(
    workdir: pathlib.Path,
    rows: list[dict[str, Any]],
    *,
    transport: httpx.MockTransport,
    calls: list[dict[str, str]],
) -> RunnerResult:
    runner = _import_runner()
    workdir.mkdir(parents=True, exist_ok=True)
    rows_path = workdir / "rows.json"
    confirm_path = workdir / "project.json"
    out_dir = workdir / "scratch"
    rows_path.write_text(json.dumps(rows), encoding="utf-8")
    confirm_path.write_text(
        json.dumps({"project_id": 1, "confirmed": True, "accessible_project_ids": [1]}),
        encoding="utf-8",
    )
    env = {
        "NEXTSEEK_URL": "https://nextseek.invalid",
        "NEXTSEEK_USERNAME": "user",
        "NEXTSEEK_PASSWORD": "pass",
    }
    argv = [
        "build-validate",
        "--rows",
        str(rows_path),
        "--project-id",
        "1",
        "--project-confirmation",
        str(confirm_path),
        "--out",
        str(out_dir),
    ]
    with _patched_env(env), contextlib.redirect_stdout(io.StringIO()) as stdout:
        rc = runner.main(argv, transport=transport)
        text = stdout.getvalue()
    marker = _last_json(text)
    artifacts = list(out_dir.glob("payload_flat.xlsx"))
    validate_posts = [call for call in calls if call["path"].endswith("/batch-upload/validate/")]
    return RunnerResult(
        rc=rc,
        stdout=text,
        marker=marker,
        artifact=artifacts[0] if artifacts else None,
        validate_posts=validate_posts,
    )


def _import_runner():
    if str(BIN_DIR) not in sys.path:
        sys.path.insert(0, str(BIN_DIR))
    import _batch_upload_runner

    return _batch_upload_runner


def _last_json(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return None


@contextlib.contextmanager
def _patched_env(values: dict[str, str]):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _probe_uid() -> str:
    rows = _fixture("advanced_search_uid.json")["rows"]
    return rows[0]["json_metadata"]["UID"]


def _route_table(*, validate_processed: int) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        ("GET", "/nextseek_api/sample_types/TIS/"): _fixture("sample_type_TIS.json"),
        ("POST", "/nextseek_api/samples/advanced_search/"): _fixture("advanced_search_uid.json"),
        ("GET", "/nextseek_api/assays/"): _fixture("assays_map.json"),
        ("GET", "/nextseek_api/projects/1/"): _fixture("project_assays.json"),
        ("GET", "/nextseek_api/assays/351/"): _fixture("assay_samples_351.json"),
        ("GET", "/nextseek_api/assays/260/"): _fixture("assay_samples_260.json"),
        ("POST", "/nextseek_api/batch-upload/validate/"): {
            "valid": True,
            "errors": [],
            "checks_run": sorted(REQUIRED_CHECKS),
            "totals": {"processed": validate_processed},
        },
    }


def _transport(routes: dict[tuple[str, str], dict[str, Any]]) -> tuple[httpx.MockTransport, list[dict[str, str]]]:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "content_type": request.headers.get("content-type", ""),
                "body": request.read().decode("utf-8", errors="replace"),
            }
        )
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={"missing": list(key)})
        return httpx.Response(200, content=orjson.dumps(routes[key]))

    return httpx.MockTransport(handler), calls
