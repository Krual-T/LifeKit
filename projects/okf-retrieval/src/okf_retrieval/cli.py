from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .core import discover_wiki_root, get_document, query_index, status_index, sync_index, validate_wiki


def _wiki_root(value: str | None) -> Path:
    return discover_wiki_root(explicit=Path(value) if value else None)


def _render_text(payload: dict[str, Any]) -> str:
    if "content" in payload:
        return str(payload["content"])
    if "results" in payload:
        lines: list[str] = []
        for index, result in enumerate(payload["results"], 1):
            lines.append(f"{index}. {result['title']} [{result['path']}]")
            if result.get("description"):
                lines.append(f"   {result['description']}")
            lines.append(f"   status={result['status']} score={result['scores']['lexical']}")
        lines.extend(f"warning: {warning}" for warning in payload.get("warnings", []))
        return "\n".join(lines) if lines else "No results."
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _emit(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(payload))


def _add_wiki_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wiki-root", help="Wiki root; otherwise discover from the current directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wiki-retrieval")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate Markdown and retrieval configuration")
    _add_wiki_root(validate_parser)
    validate_parser.add_argument("--format", choices=("json", "text"), default="json")

    sync_parser = subparsers.add_parser("sync", help="Synchronize the derived SQLite index")
    _add_wiki_root(sync_parser)
    sync_parser.add_argument("--format", choices=("json", "text"), default="json")

    status_parser = subparsers.add_parser("status", help="Report index state without changing it")
    _add_wiki_root(status_parser)
    status_parser.add_argument("--format", choices=("json", "text"), default="json")

    query_parser = subparsers.add_parser("query", help="Query the Wiki")
    query_parser.add_argument("query")
    _add_wiki_root(query_parser)
    query_parser.add_argument("--limit", type=int, default=5)
    query_parser.add_argument("--path-prefix")
    query_parser.add_argument("--type", dest="concept_type")
    query_parser.add_argument("--include-draft", action="store_true")
    query_parser.add_argument("--include-deprecated", action="store_true")
    query_parser.add_argument("--trace", choices=("summary", "full"), default="summary")
    query_parser.add_argument("--format", choices=("json", "text"), default="json")

    get_parser = subparsers.add_parser("get", help="Read one Wiki document at a derived level")
    get_parser.add_argument("path")
    get_parser.add_argument("--level", choices=("l0", "l1", "l2"), required=True)
    _add_wiki_root(get_parser)
    get_parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = _wiki_root(args.wiki_root)
        if args.command == "validate":
            payload = validate_wiki(root)
            _emit(payload, args.format)
            return 0 if payload["valid"] else 1
        if args.command == "sync":
            _emit(sync_index(root), args.format)
            return 0
        if args.command == "status":
            _emit(status_index(root), args.format)
            return 0
        if args.command == "query":
            payload = query_index(
                root,
                args.query,
                limit=args.limit,
                path_prefix=args.path_prefix,
                concept_type=args.concept_type,
                include_draft=args.include_draft,
                include_deprecated=args.include_deprecated,
                trace_level=args.trace,
            )
            _emit(payload, args.format)
            return 0
        _emit(get_document(root, args.path, args.level), args.format)
        return 0
    except (OSError, ValueError) as exc:
        print(f"wiki-retrieval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
