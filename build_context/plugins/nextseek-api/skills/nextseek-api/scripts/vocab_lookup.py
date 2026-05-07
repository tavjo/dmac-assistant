"""Backing CLI for `nextseek-vocab` shim: list/search/resolve the cached entity tree."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.cache_paths import resolve_plugin_cache_base
from lib.entity_tree_schemas import EntityTree


def _load_tree(env: str, cache_base: Path | None = None) -> EntityTree:
    base = cache_base if cache_base is not None else resolve_plugin_cache_base()
    p = base / env / "entity_tree.json"
    if not p.exists():
        print(
            f"entity tree cache missing at {p} — run nextseek-init --env {env}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return EntityTree.model_validate_json(p.read_text())


def _cmd_list(args: argparse.Namespace, cache_base: Path | None) -> int:
    tree = _load_tree(args.env, cache_base)
    for n in tree.nodes:
        if args.clade and n.clade != args.clade:
            continue
        print(f"{n.node}\t{n.description or ''}")
    return 0


def _cmd_search(args: argparse.Namespace, cache_base: Path | None) -> int:
    tree = _load_tree(args.env, cache_base)
    q = args.query.lower()
    for n in tree.nodes:
        hay = " ".join(
            filter(None, [n.node, n.description, n.clade, n.metadata_fields])
        ).lower()
        if q in hay:
            print(json.dumps(n.model_dump(), default=str))
    return 0


def _cmd_resolve(args: argparse.Namespace, cache_base: Path | None) -> int:
    tree = _load_tree(args.env, cache_base)
    exact = [n for n in tree.nodes if n.node == args.term]
    if exact:
        print(json.dumps(exact[0].model_dump(), default=str, indent=2))
        return 0
    q = args.term.lower()
    ranked = [
        n
        for n in tree.nodes
        if q in (n.node or "").lower() or q in (n.description or "").lower()
    ]
    if not ranked:
        print(f"no vocab match for '{args.term}'", file=sys.stderr)
        return 1
    ranked = ranked[:5]
    print(json.dumps([n.model_dump() for n in ranked], default=str, indent=2))
    return 0


def main(argv: list[str] | None = None, *, cache_base: Path | None = None) -> int:
    p = argparse.ArgumentParser(
        description="List/search/resolve NExtSEEK vocab terms from the cached entity tree."
    )
    p.add_argument("--env", choices=["prod", "dev"], default="prod")
    sub = p.add_subparsers(dest="cmd", required=True)
    # Every subparser also accepts --env so callers may place it either
    # before or after the subcommand (tests + docs use the latter form).
    pl = sub.add_parser("list")
    pl.add_argument("--env", choices=["prod", "dev"], default=argparse.SUPPRESS)
    pl.add_argument("--clade")
    ps = sub.add_parser("search")
    ps.add_argument("--env", choices=["prod", "dev"], default=argparse.SUPPRESS)
    ps.add_argument("query")
    pr = sub.add_parser("resolve")
    pr.add_argument("--env", choices=["prod", "dev"], default=argparse.SUPPRESS)
    pr.add_argument("term")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    try:
        if args.cmd == "list":
            return _cmd_list(args, cache_base)
        if args.cmd == "search":
            return _cmd_search(args, cache_base)
        if args.cmd == "resolve":
            return _cmd_resolve(args, cache_base)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
