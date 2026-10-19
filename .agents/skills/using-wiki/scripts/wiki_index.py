#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6.0.2"]
# ///
"""Sync Wiki navigation and manage AGENTS.md recent memory links."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml


MAX_RECENT = 5
MAX_FIXED = 2
MARKER_START = "<!-- memory-recent:start -->"
MARKER_END = "<!-- memory-recent:end -->"
FIXED_MARKER = "<!-- memory-recent:fixed -->"
EMPTY_RECENT = "_暂无近期记忆入口。_"
RESERVED_MARKDOWN = {"index.md", "log.md"}
INDEX_LINE_RE = re.compile(
    r"^- \[(?P<title>[^\]\n]+)\]\((?P<link>[^)\n]+)\) — "
    r"(?P<description>.+?)(?: (?P<fixed><!-- memory-recent:fixed -->))?$"
)


@dataclass(frozen=True)
class IndexEntry:
    """One Wiki link selected for AGENTS.md."""

    wiki_path: str
    fixed: bool = False


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes
    mode: int
    mtime_ns: int


@dataclass
class IndexPlan:
    writes: dict[Path, str]
    preconditions: dict[Path, FileSnapshot | None] = field(default_factory=dict)
    project_root: Path | None = None
    applied: dict[Path, FileSnapshot] = field(default_factory=dict)


class InputsChanged(RuntimeError):
    """Retry a plan whose source files changed while it was being processed."""


def wiki_markdown(wiki_root: Path) -> set[Path]:
    return {path for path in wiki_root.rglob("*.md") if ".okf" not in path.relative_to(wiki_root).parts}


def input_paths(project_root: Path) -> set[Path]:
    return {project_root / "AGENTS.md", project_root / "wiki/.okf-retrieval.yaml", *wiki_markdown(project_root / "wiki")}


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Wiki synchronization time budget exhausted")
    return seconds


@contextmanager
def navigation_lock(project_root: Path, deadline: float):
    wiki_root = project_root / "wiki"
    if not wiki_root.is_dir() or not (project_root / "AGENTS.md").is_file():
        raise ValueError(f"not a Wiki project: {project_root}")
    runtime = wiki_root / ".okf"
    runtime.mkdir(mode=0o700, exist_ok=True)
    lock = runtime / "navigation.lock"
    with lock.open("a+") as handle:
        os.chmod(lock, 0o600)
        while True:
            remaining(deadline)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.05, remaining(deadline)))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def parse_concept(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing YAML frontmatter: {path}")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter must be a mapping: {path}")
    return data, text[match.end() :]


def write_concept(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    rendered = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{rendered}\n---\n\n{body.lstrip()}", encoding="utf-8")


def _reference_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def validate_wiki(wiki_root: Path) -> list[str]:
    """Check the page structure required to generate Wiki navigation.

    Canonical OKF conformance belongs to ``wiki-retrieval sync``. Keeping this
    preflight deliberately narrow prevents the index tool from growing a
    second, drifting implementation of the OKF specification.
    """

    errors: list[str] = []
    for path in sorted(wiki_markdown(wiki_root)):
        if path.name in RESERVED_MARKDOWN:
            continue
        try:
            data, body = parse_concept(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))
            continue
        concept_type = data.get("type")
        if not isinstance(concept_type, str) or not concept_type.strip():
            errors.append(f"type must be a non-empty string: {path}")
    return errors


def _marker_region(
    text: str,
    path: Path,
) -> tuple[int, int, str, str, str]:
    standard_counts = (text.count(MARKER_START), text.count(MARKER_END))
    if standard_counts == (1, 1):
        start_marker, end_marker = MARKER_START, MARKER_END
    elif standard_counts == (0, 0):
        raise ValueError(f"recent memory markers are missing: {path}")
    else:
        raise ValueError(f"recent memory markers must form exactly one pair: {path}")
    start = text.index(start_marker)
    end_start = text.index(end_marker)
    if end_start < start:
        raise ValueError(f"recent memory markers are out of order: {path}")
    end = end_start + len(end_marker)
    return start, end, text[start:end], start_marker, end_marker


def _wiki_relative_from_link(link: str, project_root: Path) -> str:
    target = _reference_target(link)
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        raise ValueError(f"recent memory route must be a local Wiki Markdown path: {link!r}")
    candidate = Path(unquote(parsed.path))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"recent memory route must be project-relative: {link!r}")
    parts = candidate.parts
    if not parts or parts[0] != "wiki" or candidate.suffix != ".md":
        raise ValueError(f"recent memory route must point to wiki/*.md: {link!r}")
    wiki_relative = Path(*parts[1:])
    if not wiki_relative.parts or wiki_relative.name in RESERVED_MARKDOWN:
        raise ValueError(f"recent memory route must point to an OKF page: {link!r}")
    resolved = (project_root / "wiki" / wiki_relative).resolve()
    if not resolved.is_relative_to((project_root / "wiki").resolve()):
        raise ValueError(f"recent memory route escapes the Wiki root: {link!r}")
    return wiki_relative.as_posix()


def _parse_index(content: str, project_root: Path) -> list[IndexEntry] | None:
    lines = [line for line in content.splitlines() if line.strip()]
    if lines == [EMPTY_RECENT] or not lines:
        return []
    entries: list[IndexEntry] = []
    for line in lines:
        match = INDEX_LINE_RE.fullmatch(line)
        if not match:
            return None
        entries.append(
            IndexEntry(
                _wiki_relative_from_link(match.group("link"), project_root),
                match.group("fixed") is not None,
            )
        )
    return entries


def parse_recent(
    text: str,
    project_root: Path,
    agents_path: Path,
) -> tuple[list[IndexEntry], str]:
    _, _, region, start_marker, end_marker = _marker_region(
        text,
        agents_path,
    )
    content = region[len(start_marker) : -len(end_marker)].strip("\n")
    entries = _parse_index(content, project_root)
    if entries is None:
        raise ValueError("recent memory index is not in one-line format")
    return entries, region


def validate_index_entries(entries: list[IndexEntry], project_root: Path) -> list[str]:
    errors: list[str] = []
    if len(entries) > MAX_RECENT:
        errors.append(f"recent memory index exceeds capacity {MAX_RECENT}: {len(entries)}")
    fixed_count = sum(entry.fixed for entry in entries)
    if fixed_count > MAX_FIXED:
        errors.append(f"fixed recent memory routes exceed capacity {MAX_FIXED}: {fixed_count}")
    paths = [entry.wiki_path for entry in entries]
    if len(paths) != len(set(paths)):
        errors.append("recent memory index contains duplicate Wiki routes")
    wiki_root = project_root / "wiki"
    for entry in entries:
        page = wiki_root / entry.wiki_path
        if not page.is_file():
            errors.append(f"recent memory route does not exist: {page}")
            continue
        try:
            data, _ = parse_concept(page)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))
            continue
        for field in ("title", "description"):
            value = str(data.get(field, "")).strip()
            if not value:
                errors.append(f"recent memory page is missing {field}: {page}")
            elif "\n" in value or "\r" in value:
                errors.append(f"recent memory page {field} must fit on one line: {page}")
        title = str(data.get("title", ""))
        if "]" in title:
            errors.append(f"recent memory page title contains unsupported ']': {page}")
        if FIXED_MARKER in str(data.get("description", "")):
            errors.append(f"recent memory page description contains the fixed marker: {page}")
    return errors


def _render_index_line(entry: IndexEntry, project_root: Path) -> str:
    page = project_root / "wiki" / entry.wiki_path
    data, _ = parse_concept(page)
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    suffix = f" {FIXED_MARKER}" if entry.fixed else ""
    return f"- [{title}](wiki/{entry.wiki_path}) — {description}{suffix}"


def render_recent(entries: list[IndexEntry], project_root: Path) -> str:
    lines = [MARKER_START]
    if entries:
        lines.extend(_render_index_line(entry, project_root) for entry in entries)
    else:
        lines.append(EMPTY_RECENT)
    lines.append(MARKER_END)
    return "\n".join(lines)


def render_replaced_recent(text: str, recent: str, agents_path: Path) -> str:
    start, end, _, _, _ = _marker_region(text, agents_path)
    return text[:start] + recent + text[end:]


def normalize_add_path(path: str, project_root: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".md":
        raise ValueError(f"add requires a Wiki-root-relative Markdown path: {path!r}")
    if not candidate.parts or candidate.name in RESERVED_MARKDOWN:
        raise ValueError(f"add must point to an OKF page: {path!r}")
    wiki_root = (project_root / "wiki").resolve()
    resolved = (wiki_root / candidate).resolve()
    if not resolved.is_relative_to(wiki_root):
        raise ValueError(f"add path escapes the Wiki root: {path!r}")
    if not resolved.is_file():
        raise ValueError(f"add page does not exist: {resolved}")
    return candidate.as_posix()


def add_to_index(entries: list[IndexEntry], wiki_path: str) -> list[IndexEntry]:
    existing = next((entry for entry in entries if entry.wiki_path == wiki_path), None)
    updated = [entry for entry in entries if entry.wiki_path != wiki_path]
    updated.insert(0, existing or IndexEntry(wiki_path))
    while len(updated) > MAX_RECENT:
        victim = next((index for index in range(len(updated) - 1, -1, -1) if not updated[index].fixed), None)
        if victim is None:
            raise ValueError(f"cannot reduce recent memory index to capacity {MAX_RECENT}")
        updated.pop(victim)
    return updated


def render_indexes(wiki_root: Path) -> dict[Path, str]:
    concept_paths = [
        path for path in wiki_markdown(wiki_root) if path.name not in RESERVED_MARKDOWN
    ]
    content_directories = {
        parent
        for path in concept_paths
        for parent in path.parents
        if parent == wiki_root or parent.is_relative_to(wiki_root)
    }
    indexed_directories = {
        path.parent for path in wiki_markdown(wiki_root) if path.name == "index.md"
    }
    directories = {wiki_root} | content_directories | indexed_directories
    writes: dict[Path, str] = {}
    for directory in sorted(directories, key=lambda item: (len(item.parts), item.as_posix()), reverse=True):
        concepts = []
        for path in sorted(directory.glob("*.md")):
            if path.name in RESERVED_MARKDOWN:
                continue
            data, _ = parse_concept(path)
            concepts.append(
                (
                    path.name,
                    str(data.get("title") or path.stem),
                    str(data.get("description") or ""),
                )
            )
        children = [
            child
            for child in sorted(directory.iterdir())
            if child.is_dir() and child in content_directories
        ]
        index_path = directory / "index.md"
        if directory == wiki_root:
            lines = ["---", 'okf_version: "0.2"', "---", "", "# Wiki", ""]
        else:
            lines = [f"# {directory.name}", ""]
        if children:
            lines.extend(["## 目录", ""])
            for child in children:
                lines.append(f"* [{child.name}]({child.name}/)")
            lines.append("")
        if concepts:
            lines.extend(["## 文档", ""])
            for filename, title, description in concepts:
                suffix = f" - {description}" if description else ""
                lines.append(f"* [{title}]({filename}){suffix}")
            lines.append("")
        writes[index_path] = "\n".join(lines).rstrip() + "\n"
    return writes


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        target_mode = mode
        if target_mode is None:
            target_mode = path.stat().st_mode & 0o7777 if path.exists() else 0o644
        os.chmod(temporary_path, target_mode)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def capture_files(paths: set[Path]) -> dict[Path, FileSnapshot | None]:
    snapshots: dict[Path, FileSnapshot | None] = {}
    for path in paths:
        if path.exists():
            stat = path.stat()
            snapshots[path] = FileSnapshot(path.read_bytes(), stat.st_mode & 0o7777, stat.st_mtime_ns)
        else:
            snapshots[path] = None
    return snapshots


def restore_files(
    snapshots: dict[Path, FileSnapshot | None], applied: dict[Path, FileSnapshot],
) -> list[str]:
    errors: list[str] = []
    for path in sorted(list(applied)):
        snapshot = snapshots[path]
        try:
            if capture_files({path})[path] != applied[path]:
                errors.append(f"{path}: changed by another writer; preserved")
                continue
            if snapshot is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, snapshot.content.decode("utf-8"), snapshot.mode)
            del applied[path]
        except (OSError, UnicodeError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def changed_inputs(plan: IndexPlan, *, after_apply: bool = False) -> list[Path]:
    expected = plan.preconditions | (plan.applied if after_apply else {})
    paths = set(expected)
    if plan.project_root is not None:
        paths |= input_paths(plan.project_root)
    current = capture_files(paths)
    return [path for path in sorted(paths) if current[path] != expected.get(path)]


def apply_plan(plan: IndexPlan) -> None:
    if plan.preconditions:
        changed = changed_inputs(plan)
        if changed:
            labels = ", ".join(str(path) for path in sorted(changed))
            raise InputsChanged(f"maintenance inputs changed after planning: {labels}")
    snapshots = (
        {path: plan.preconditions.get(path) for path in plan.writes}
        if plan.preconditions else capture_files(set(plan.writes))
    )
    try:
        for path, content in sorted(plan.writes.items()):
            before = snapshots[path]
            if before is not None and before.content == content.encode("utf-8"):
                continue
            if capture_files({path})[path] != before:
                raise InputsChanged(f"navigation output changed before writing: {path}")
            atomic_write_text(path, content)
            written = capture_files({path})[path]
            if written is None or written.content != content.encode("utf-8"):
                raise InputsChanged(f"navigation output changed after writing: {path}")
            plan.applied[path] = written
    except BaseException as exc:
        rollback_errors = restore_files(snapshots, plan.applied)
        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise RuntimeError(f"maintenance failed ({exc}); rollback incomplete: {details}") from exc
        raise


def _load_and_validate_index(
    project_root: Path,
    *,
    remove: list[str] | None = None,
) -> tuple[Path, str, list[IndexEntry], str]:
    agents_path = project_root / "AGENTS.md"
    agents_text = agents_path.read_text(encoding="utf-8")
    entries, region = parse_recent(
        agents_text,
        project_root,
        agents_path,
    )
    for path in remove or []:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(f"remove requires a Wiki-root-relative Markdown path: {path!r}")
        wiki_path = _wiki_relative_from_link(f"wiki/{path}", project_root)
        entries = [entry for entry in entries if entry.wiki_path != wiki_path]
    errors = validate_index_entries(entries, project_root)
    if errors:
        raise ValueError("\n".join(errors))
    return agents_path, agents_text, entries, region


def plan_sync(
    project_root: Path,
    add: str | None = None,
    remove: list[str] | None = None,
) -> IndexPlan:
    wiki_root = project_root / "wiki"
    preconditions = capture_files(input_paths(project_root))
    errors = validate_wiki(wiki_root)
    if errors:
        raise ValueError("\n".join(errors))
    agents_path, agents_text, entries, _ = _load_and_validate_index(
        project_root,
        remove=remove,
    )
    if add is not None:
        entries = add_to_index(entries, normalize_add_path(add, project_root))
        index_errors = validate_index_entries(entries, project_root)
        if index_errors:
            raise ValueError("\n".join(index_errors))
    writes = render_indexes(wiki_root)
    writes[agents_path] = render_replaced_recent(
        agents_text,
        render_recent(entries, project_root),
        agents_path,
    )
    for path in writes:
        preconditions.setdefault(path, None)
    return IndexPlan(writes=writes, preconditions=preconditions, project_root=project_root)


def sync(
    project_root: Path,
    add: str | None = None,
    remove: list[str] | None = None,
) -> None:
    with navigation_lock(project_root, time.monotonic() + 20):
        plan = plan_sync(project_root, add, remove)
        apply_plan(plan)


def ensure(project_root: Path, *, timeout: float = 20) -> dict[str, Any]:
    """Maintain both indexes; report partial navigation writes even on failure."""
    result: dict[str, Any] = {
        "ok": False, "project_root": str(project_root), "fresh": False,
        "navigation_changed": [], "retrieval_changed": False, "stage": "lock",
    }
    plans: list[IndexPlan] = []
    deadline = time.monotonic() + timeout
    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        with navigation_lock(project_root, deadline):
            for attempt in range(2):
                result["attempts"] = attempt + 1
                try:
                    result["stage"] = "navigation"
                    remaining(deadline)
                    plan = plan_sync(project_root)
                    plans.append(plan)
                    apply_plan(plan)
                    result["stage"] = "retrieval"
                    database = project_root / "wiki/.okf/index.sqlite3"
                    before = database.stat().st_mtime_ns if database.exists() else None
                    command = subprocess.run(
                        ["wiki-retrieval", "sync", "--wiki-root", str(project_root / "wiki")],
                        capture_output=True, text=True, timeout=remaining(deadline),
                    )
                    if command.returncode:
                        raise RuntimeError(command.stderr.strip() or command.stdout.strip() or f"wiki-retrieval exited {command.returncode}")
                    retrieval = json.loads(command.stdout)
                    if not isinstance(retrieval, dict):
                        raise ValueError("wiki-retrieval did not return a JSON object")
                    after = database.stat().st_mtime_ns if database.exists() else None
                    result["retrieval_changed"] |= before != after
                    result["stage"] = "concurrency"
                    if retrieval.get("fresh") is not True:
                        raise InputsChanged("wiki-retrieval returned fresh=false; published database, if any, is retained")
                    result["stage"] = "navigation-check"
                    errors = check_state(project_root)
                    result["stage"] = "concurrency"
                    changed = changed_inputs(plan, after_apply=True)
                    if changed:
                        raise InputsChanged("Wiki inputs changed during synchronization: " + ", ".join(str(path) for path in changed))
                    if errors:
                        result["stage"] = "navigation-check"
                        raise RuntimeError("\n".join(errors))
                    remaining(deadline)
                    result.update(ok=True, fresh=True, stage="complete")
                    break
                except InputsChanged:
                    result["stage"] = "concurrency"
                    if attempt == 1:
                        raise
    except (OSError, RuntimeError, ValueError, yaml.YAMLError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
    # Keep writes from earlier attempts, including when retrieval failed later.
    changed_paths = sorted({path for plan in plans for path in plan.applied})
    result["navigation_changed"] = [str(path.relative_to(project_root)) for path in changed_paths]
    if project_root / "AGENTS.md" in changed_paths:
        try:
            result["recent"] = _marker_region((project_root / "AGENTS.md").read_text(encoding="utf-8"), project_root / "AGENTS.md")[2]
        except (OSError, ValueError):
            pass
    return result


def check_state(project_root: Path) -> list[str]:
    wiki_root = project_root / "wiki"
    agents_path = project_root / "AGENTS.md"
    errors = validate_wiki(wiki_root)
    if not agents_path.exists():
        errors.append(f"missing {agents_path}")
    else:
        text = agents_path.read_text(encoding="utf-8")
        try:
            entries, region = parse_recent(
                text,
                project_root,
                agents_path,
            )
            index_errors = validate_index_entries(entries, project_root)
            errors.extend(index_errors)
            if not index_errors:
                try:
                    expected = render_recent(entries, project_root)
                    if region != expected:
                        errors.append('AGENTS.md "最近" is not synchronized')
                except (OSError, ValueError, yaml.YAMLError) as exc:
                    errors.append(str(exc))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))
    try:
        index_writes = render_indexes(wiki_root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(str(exc))
    else:
        for path, expected in sorted(index_writes.items()):
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                errors.append(f"Wiki index is not synchronized: {path}")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wiki-index", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "ensure": "Synchronize navigation, validate OKF and refresh the search index",
        "sync": "Update Wiki navigation and recent link titles without changing their order",
        "add": "Add a Wiki page to the recent index or move it to the front",
        "remove": "Remove recent links without deleting Wiki pages",
        "check": "Check Wiki navigation and recent links",
    }
    for command, description in descriptions.items():
        child = commands.add_parser(command, help=description, description=description)
        child.add_argument("--project-root", default=".", help="Wiki project root (default: current directory)")
        if command == "ensure":
            child.add_argument("--timeout", type=float, default=20, help="Total lock and subprocess budget in seconds (default: 20)")
        elif command == "add":
            child.add_argument("path", help="Markdown path relative to wiki/")
        elif command == "remove":
            child.add_argument("paths", nargs="+", help="Markdown paths relative to wiki/")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    try:
        if args.command == "ensure":
            result = ensure(project_root, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 1
        elif args.command == "check":
            errors = check_state(project_root)
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("wiki-index check passed")
        else:
            sync(
                project_root,
                add=args.path if args.command == "add" else None,
                remove=args.paths if args.command == "remove" else None,
            )
            print("Wiki navigation and recent index synchronized")
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
