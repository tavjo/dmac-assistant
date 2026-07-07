#!/usr/bin/env python3
"""T9 NExtSEEK plugin image smoke.

Run after ``make image-build``. The manifest comparison is anchored to HEAD via
``git ls-files``/``git show`` so dirty working-copy plugin files cannot make a
stale or locally modified image look correct.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_PREFIX = "build_context/plugins/nextseek"
IMAGE_PLUGIN_ROOT = "/app/plugins/nextseek"
PY_MODULES = [
    "_batch_upload_runner.py",
    "_batch_upload_client.py",
    "_batch_upload_payload.py",
    "_batch_upload_extract.py",
]
NEW_SHIMS = {
    "nextseek-sample-search": "sample-search",
    "nextseek-project-resolve": "project-resolve",
    "nextseek-assay-resolve": "assay-resolve",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="dmac-assistant:poc")
    parser.add_argument("--out", default="out/T9.expected_manifest.json")
    args = parser.parse_args(argv)
    expected = expected_manifest()
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")

    _docker(args.image, "python -c 'import orjson, polars, fastexcel, xlsxwriter, markitdown'")
    _docker(
        args.image,
        "test -f /app/plugins/nextseek/skills/nextseek-batch-upload/SKILL.md "
        "&& test -x /app/plugins/nextseek/bin/nextseek-sample-search "
        "&& test -x /app/plugins/nextseek/bin/nextseek-project-resolve "
        "&& test -x /app/plugins/nextseek/bin/nextseek-assay-resolve "
        "&& ! test -e /app/plugins/nextseek/bin/nextseek-sample-read",
    )
    for shim, subcmd in NEW_SHIMS.items():
        _assert_dispatch(args.image, shim, subcmd)
    plugin_validate = _plugin_validate_or_fallback(args.image)
    _docker(args.image, _compile_modules_script())
    actual = actual_manifest(args.image)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(key for key in set(expected) & set(actual) if expected[key] != actual[key])
        raise SystemExit(
            "image plugin manifest mismatch\n"
            f"missing={missing[:10]}\nextra={extra[:10]}\nchanged={changed[:10]}"
        )
    print(json.dumps({"image": args.image, "plugin_validate": plugin_validate, "files": len(actual)}, sort_keys=True))
    return 0


def expected_manifest() -> dict[str, str]:
    files = _run(["git", "ls-files", PLUGIN_PREFIX], cwd=REPO_ROOT).stdout.splitlines()
    out: dict[str, str] = {}
    for path in files:
        blob = _run(["git", "show", f"HEAD:{path}"], cwd=REPO_ROOT).stdout_bytes
        out[_rel(path)] = hashlib.sha256(blob).hexdigest()
    return out


def actual_manifest(image: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="nextseek-image-") as tmp:
        archive = pathlib.Path(tmp) / "plugin.tar"
        with archive.open("wb") as handle:
            subprocess.run(
                ["docker", "run", "--rm", image, "tar", "-C", "/app/plugins", "-cf", "-", "nextseek"],
                check=True,
                stdout=handle,
            )
        root = pathlib.Path(tmp) / "extract"
        root.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        out: dict[str, str] = {}
        for path in sorted((root / "nextseek").rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root / "nextseek"))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out


def _assert_dispatch(image: str, shim: str, expected: str) -> None:
    script = (
        "tmp=$(mktemp -d); "
        "cat > $tmp/python <<'SH'\n"
        "#!/bin/sh\n"
        "printf '%s\\n' \"$2\" > /tmp/nextseek-dispatch\n"
        "SH\n"
        "chmod +x $tmp/python; "
        f"PATH=$tmp:$PATH {IMAGE_PLUGIN_ROOT}/bin/{shim} --help >/dev/null; "
        f"case {shim} in "
        "nextseek-sample-search) args='--uid U1' ;; "
        "nextseek-project-resolve) args='--project-id 1 --confirmed --out /tmp/project.json' ;; "
        "nextseek-assay-resolve) args='--project-id 1 --title RNA-seq' ;; "
        "esac; "
        f"PATH=$tmp:$PATH {IMAGE_PLUGIN_ROOT}/bin/{shim} $args; "
        f"test \"$(cat /tmp/nextseek-dispatch)\" = {expected!r}"
    )
    _docker(image, script)


def _plugin_validate_or_fallback(image: str) -> str:
    script = (
        "if command -v claude >/dev/null 2>&1; then "
        f"if claude plugin validate {IMAGE_PLUGIN_ROOT} >/tmp/plugin-validate 2>&1; then "
        "cat /tmp/plugin-validate; echo plugin_validate_status=passed; "
        "else cat /tmp/plugin-validate; exit 1; fi; "
        "else "
        "python - <<'PY'\n"
        "import json, pathlib\n"
        "p=pathlib.Path('/app/plugins/nextseek/.claude-plugin/plugin.json')\n"
        "data=json.loads(p.read_text())\n"
        "text=json.dumps(data)\n"
        "assert 'skills/nextseek-batch-upload/SKILL.md' in text or pathlib.Path('/app/plugins/nextseek/skills/nextseek-batch-upload/SKILL.md').exists()\n"
        "PY\n"
        "echo plugin_validate_status=unavailable_fallback; "
        "fi"
    )
    stdout = _docker_output(image, script)
    for line in reversed(stdout.splitlines()):
        if line.startswith("plugin_validate_status="):
            return line.split("=", 1)[1]
    raise RuntimeError("plugin validation status marker missing")


def _compile_modules_script() -> str:
    modules = json.dumps([f"{IMAGE_PLUGIN_ROOT}/bin/{module}" for module in PY_MODULES])
    return (
        "python - <<'PY'\n"
        "import json, pathlib\n"
        f"for path in json.loads({modules!r}):\n"
        "    source = pathlib.Path(path).read_text()\n"
        "    compile(source, path, 'exec')\n"
        "PY\n"
    )


def _docker(image: str, script: str) -> None:
    subprocess.run(["docker", "run", "--rm", image, "sh", "-c", script], check=True)


def _docker_output(image: str, script: str) -> str:
    completed = subprocess.run(
        ["docker", "run", "--rm", image, "sh", "-c", script],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(completed.stdout, end="")
    return completed.stdout


def _rel(path: str) -> str:
    return str(pathlib.Path(path).relative_to(PLUGIN_PREFIX))


class _Result:
    def __init__(self, completed: subprocess.CompletedProcess[bytes]) -> None:
        self.stdout_bytes = completed.stdout
        self.stdout = completed.stdout.decode("utf-8")


def _run(cmd: list[str], *, cwd: pathlib.Path) -> _Result:
    return _Result(subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE))


if __name__ == "__main__":
    raise SystemExit(main())
