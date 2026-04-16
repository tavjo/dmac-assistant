"""Stage the nextseek-api plugin into the Docker build_context tree."""
from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("~/.claude/plugins/local/nextseek-api").expanduser()
DEFAULT_DEST = REPO_ROOT / "build_context"

ALLOWLIST: tuple[str, ...] = (
    ".claude-plugin",
    "bin",
    "commands",
    "skills",
    "docs",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "CHANGELOG.md",
)

DENY_DIRS: tuple[str, ...] = (
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
)

DENY_FILE_GLOBS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    ".npmrc",
    ".env",
    ".env.example",
    ".coverage*",
    ".mcp.json",
    "*.pem",
    "*.key",
)


class DenylistViolation(RuntimeError):
    """Raised when staging must refuse a source tree."""


@dataclass(frozen=True)
class ScanReport:
    """Outcome of a source-tree scan."""

    denylist_offenders: tuple[str, ...]
    unexpected_top_level_entries: tuple[str, ...]


def stage(source: Path, dest: Path, *, strict: bool = False) -> None:
    """Scan the plugin source and copy the allowlisted surface into dest."""
    source = Path(source)
    dest = Path(dest)
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_dir():
        raise NotADirectoryError(source)

    report = scan_source(source)

    for entry in report.unexpected_top_level_entries:
        print(
            f"warning: unexpected top-level entry not in ALLOWLIST: {entry}",
            file=sys.stderr,
        )

    if report.denylist_offenders:
        raise DenylistViolation(
            "denylisted path(s) found: " + ", ".join(report.denylist_offenders)
        )

    if strict and report.unexpected_top_level_entries:
        raise DenylistViolation(
            "unexpected top-level entry(s) not in ALLOWLIST: "
            + ", ".join(report.unexpected_top_level_entries)
        )

    perform_stage(source, dest)


def scan_source(source: Path) -> ScanReport:
    """Discover denylisted artifacts and unexpected top-level entries."""
    source = Path(source)
    root = source.resolve()
    denylist_offenders: list[str] = []
    unexpected_top_level_entries: list[str] = []

    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        _scan_entry(
            entry,
            source=source,
            root=root,
            denylist_offenders=denylist_offenders,
            unexpected_top_level_entries=unexpected_top_level_entries,
            top_level=True,
            deny_ancestor=False,
        )

    return ScanReport(
        denylist_offenders=tuple(denylist_offenders),
        unexpected_top_level_entries=tuple(unexpected_top_level_entries),
    )


def perform_stage(source: Path, dest: Path) -> None:
    """Wipe dest and copy the allowlisted source surface into build_context."""
    source = Path(source)
    dest = Path(dest)
    plugin_out = dest / "plugins" / source.name
    docs_out = dest / "docs" / source.name

    if dest.exists():
        shutil.rmtree(dest)

    plugin_out.mkdir(parents=True, exist_ok=True)
    docs_out.mkdir(parents=True, exist_ok=True)

    for entry in ALLOWLIST:
        if entry == "README.md":
            _copy_file(source / entry, docs_out / "README.md")
        elif entry == "docs":
            _copy_tree(source / entry, docs_out / "docs")
        elif entry in {"pyproject.toml", "uv.lock", "CHANGELOG.md"}:
            _copy_file(source / entry, plugin_out / entry)
        else:
            _copy_tree(source / entry, plugin_out / entry)


def _copy_tree(src: Path, dest: Path) -> None:
    shutil.copytree(src, dest, symlinks=False)


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _scan_entry(
    entry: Path,
    *,
    source: Path,
    root: Path,
    denylist_offenders: list[str],
    unexpected_top_level_entries: list[str],
    top_level: bool,
    deny_ancestor: bool,
) -> None:
    rel = entry.relative_to(source).as_posix()
    entry_is_denylisted = deny_ancestor or _is_denylisted_path(entry)

    if top_level and entry.name not in ALLOWLIST and not entry_is_denylisted:
        unexpected_top_level_entries.append(rel)
        if entry.is_dir() and not entry.is_symlink():
            return

    if entry.is_symlink():
        _scan_symlink(
            entry,
            source=source,
            root=root,
            denylist_offenders=denylist_offenders,
            deny_ancestor=deny_ancestor,
        )
        return

    if entry.is_dir():
        if entry_is_denylisted:
            denylist_offenders.append(rel)
        for child in sorted(entry.iterdir(), key=lambda item: item.name):
            _scan_entry(
                child,
                source=source,
                root=root,
                denylist_offenders=denylist_offenders,
                unexpected_top_level_entries=unexpected_top_level_entries,
                top_level=False,
                deny_ancestor=entry_is_denylisted,
            )
        return

    if entry_is_denylisted:
        denylist_offenders.append(rel)


def _scan_symlink(
    path: Path,
    *,
    source: Path,
    root: Path,
    denylist_offenders: list[str],
    deny_ancestor: bool,
) -> None:
    rel = path.relative_to(source).as_posix()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        denylist_offenders.append(f"{rel} (broken symlink)")
        return

    if deny_ancestor or _is_denylisted_path(path):
        denylist_offenders.append(rel)

    if not resolved.is_relative_to(root):
        denylist_offenders.append(f"{rel} -> {resolved.as_posix()}")


def _is_denylisted_path(path: Path) -> bool:
    return _is_denylisted_dir_name(path.name) or _is_denylisted_file_name(path.name)


def _is_denylisted_dir_name(name: str) -> bool:
    return name in DENY_DIRS


def _is_denylisted_file_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in DENY_FILE_GLOBS)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="stage_plugins",
        description="Stage the nextseek-api plugin into build_context.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"plugin source directory (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"build_context destination (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="refuse unexpected top-level entries instead of warning",
    )
    args = parser.parse_args(argv)

    try:
        stage(args.source, args.dest, strict=args.strict)
    except (DenylistViolation, FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
