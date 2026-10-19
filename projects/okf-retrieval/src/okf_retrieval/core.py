from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = "1"
RESERVED_MARKDOWN = {"index.md", "log.md"}
CONFIG_NAME = ".okf-retrieval.yaml"
DEFAULT_L1_LIMIT = 2400
SECTION_EXCERPT_LIMIT = 320
LATIN_RE = re.compile(r"[a-z0-9]+(?:[._+:/-][a-z0-9]+)*", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
FENCE_LINE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
CODE_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
WHITESPACE_RE = re.compile(r"\s+")
GENERIC_QUERY_WORDS = ("为什么", "什么", "怎么", "如何", "哪个", "哪些", "那个")
GENERIC_QUERY_MODALS = ("必须", "需要", "应该", "请问")
RELATIONSHIP_SUBJECT_RE = re.compile(
    r"(?P<subject>[\u3400-\u4dbf\u4e00-\u9fff]{2,8})的"
    r"(?:对象|女朋友|男朋友|伴侣|恋人|妻子|丈夫)"
)
GENERIC_RELATIONSHIP_SUBJECTS = {"我们", "你们", "他们", "她们", "大家", "自己"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


@dataclass(frozen=True)
class Config:
    searchable_frontmatter: tuple[str, ...] = ()
    l1_frontmatter: tuple[str, ...] = ()

    def serialized(self) -> str:
        return json.dumps(
            {
                "searchable_frontmatter": list(self.searchable_frontmatter),
                "l1_frontmatter": list(self.l1_frontmatter),
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative: str
    mtime_ns: int
    size: int


@dataclass
class Document:
    source: SourceFile
    frontmatter: dict[str, Any]
    raw: str
    body: str
    title: str
    description: str
    abstract: str
    concept_type: str
    tags: list[str]
    keywords: list[str]
    aliases: list[str]
    status: str
    verified: bool
    stale_after: str
    generated: Any
    headings: list[str]
    configured_search: list[str]
    configured_l1: list[str]
    l0: str
    l1: str


def discover_wiki_root(start: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Wiki root is not a directory: {root}")
        return root
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "index.md").is_file():
            return candidate
        nested = candidate / "wiki"
        if (nested / "index.md").is_file():
            return nested.resolve()
    raise ValueError(f"could not discover Wiki root from {current}; pass --wiki-root")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [normalize_space(serialize_scalar(item)) for item in value if normalize_space(serialize_scalar(item))]
    text = normalize_space(serialize_scalar(value))
    return [text] if text else []


def serialize_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=serialize_scalar, sort_keys=True)
    return str(value)


def normalize_space(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def plain_markdown(text: str) -> str:
    text = CODE_FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(lambda match: match.group(1), text)
    text = MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)
    text = re.sub(r"^[ \t]*(?:[-*+] |\d+[.)] |>+\s*)", "", text, flags=re.MULTILINE)
    return normalize_space(re.sub(r"[*_~]", "", text))


def search_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [match.group(0) for match in LATIN_RE.finditer(lowered)]
    for match in CJK_RE.finditer(lowered):
        sequence = match.group(0)
        if len(sequence) == 1:
            tokens.append(sequence)
        else:
            if len(sequence) <= 8:
                tokens.append(sequence)
            tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
            if len(sequence) >= 3:
                tokens.extend(sequence[index : index + 3] for index in range(len(sequence) - 2))
    return list(dict.fromkeys(token for token in tokens if token))


def query_tokens(text: str) -> list[str]:
    cleaned = text
    for phrase in GENERIC_QUERY_WORDS:
        cleaned = cleaned.replace(phrase, " ")
    return search_tokens(cleaned)


def query_phrases(text: str) -> list[str]:
    cleaned = text.lower()
    for phrase in (*GENERIC_QUERY_WORDS, *GENERIC_QUERY_MODALS):
        cleaned = cleaned.replace(phrase, " ")
    phrases = [match.group(0) for match in LATIN_RE.finditer(cleaned)]
    phrases.extend(match.group(0) for match in CJK_RE.finditer(cleaned) if len(match.group(0)) >= 3)
    return list(dict.fromkeys(phrases))


def search_document(text: str) -> str:
    return " ".join(search_tokens(text))


def parse_markdown(path: Path) -> tuple[dict[str, Any], str, str]:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError("missing YAML frontmatter")
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a mapping")
    _validate_okf_frontmatter(loaded)
    return loaded, raw[match.end() :], raw


def _parse_okf_timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be an ISO 8601 datetime with an explicit UTC offset")
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError as exc:
            raise ValueError(
                f"{field} must be an ISO 8601 datetime with an explicit UTC offset"
            ) from exc
    else:
        raise ValueError(f"{field} must be an ISO 8601 datetime with an explicit UTC offset")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be an ISO 8601 datetime with an explicit UTC offset")
    return parsed


def _validate_usage_window(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        return
    for key in ("from", "to"):
        if key in value:
            _parse_okf_timestamp(value[key], f"{field}.{key}")


def _validate_okf_frontmatter(frontmatter: dict[str, Any]) -> None:
    errors: list[str] = []

    def validate_timestamp(value: Any, field: str) -> None:
        try:
            _parse_okf_timestamp(value, field)
        except ValueError as exc:
            errors.append(str(exc))

    concept_type = frontmatter.get("type")
    if not isinstance(concept_type, str) or not concept_type.strip():
        errors.append("type must be a non-empty string")

    generated = frontmatter.get("generated")
    if "generated" in frontmatter:
        if not isinstance(generated, dict):
            errors.append("generated must be a mapping")
        elif not isinstance(generated.get("by"), str) or not generated["by"].strip():
            errors.append("generated.by must be a non-empty string")

    sources = frontmatter.get("sources")
    if "sources" in frontmatter:
        if not isinstance(sources, list):
            errors.append("sources must be a list")
        else:
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    errors.append(f"sources[{index}] must be a mapping")
                elif not isinstance(source.get("resource"), str) or not source["resource"].strip():
                    errors.append(f"sources[{index}].resource must be a non-empty string")

    verified = frontmatter.get("verified")
    verification_events: list[Any] = []
    if "verified" in frontmatter:
        if isinstance(verified, dict):
            verification_events = [verified]
        elif isinstance(verified, list):
            verification_events = verified
        else:
            errors.append("verified must be a mapping or a list of mappings")
    for index, event in enumerate(verification_events):
        suffix = f"[{index}]" if isinstance(verified, list) else ""
        if not isinstance(event, dict):
            errors.append(f"verified{suffix} must be a mapping")
            continue
        if not isinstance(event.get("by"), str) or not event["by"].strip():
            errors.append(f"verified{suffix}.by must be a non-empty string")
        if "at" not in event:
            errors.append(f"verified{suffix}.at is required")
        else:
            validate_timestamp(event["at"], f"verified{suffix}.at")

    if isinstance(concept_type, str) and concept_type.strip() == "Attested Computation":
        runtime = frontmatter.get("runtime")
        if not isinstance(runtime, str) or not runtime.strip():
            errors.append("runtime must be a non-empty string for type Attested Computation")

    for field in ("stale_after", "timestamp"):
        if field in frontmatter:
            validate_timestamp(frontmatter[field], field)

    if isinstance(generated, dict) and "at" in generated:
        validate_timestamp(generated["at"], "generated.at")

    try:
        _validate_usage_window(frontmatter.get("usage_window"), "usage_window")
    except ValueError as exc:
        errors.append(str(exc))
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            if "last_modified" in source:
                validate_timestamp(source["last_modified"], f"sources[{index}].last_modified")
            try:
                _validate_usage_window(source.get("usage_window"), f"sources[{index}].usage_window")
            except ValueError as exc:
                errors.append(str(exc))

    if errors:
        raise ValueError("; ".join(errors))


def _parse_optional_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str]:
    raw = path.read_text(encoding="utf-8")
    if not re.match(r"\A---[ \t]*(?:\n|\Z)", raw):
        return None, raw
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError("invalid or unterminated YAML frontmatter")
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a mapping")
    return loaded, raw[match.end() :]


def _validate_log_body(body: str) -> None:
    fence: str | None = None
    for line_number, line in enumerate(body.splitlines(), start=1):
        fence_match = FENCE_LINE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = HEADING_RE.match(line)
        if not heading or len(heading.group(1)) != 2:
            continue
        value = heading.group(2)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"line {line_number}: log date heading must use ## YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"line {line_number}: invalid log date heading: {value}") from exc


def validate_reserved_file(source: SourceFile) -> None:
    frontmatter, body = _parse_optional_frontmatter(source.path)
    if source.path.name == "index.md":
        if frontmatter is not None and source.relative != "index.md":
            raise ValueError("frontmatter is only permitted in the bundle-root index.md")
        return
    _validate_log_body(body)


def load_config(wiki_root: Path) -> Config:
    path = wiki_root / CONFIG_NAME
    if not path.exists():
        return Config()
    if path.is_symlink():
        raise ValueError(f"configuration must not be a symbolic link: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid {CONFIG_NAME}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{CONFIG_NAME} must contain a mapping")
    searchable = _validate_dot_paths(loaded.get("searchable_frontmatter"), "searchable_frontmatter")
    l1 = _validate_dot_paths(loaded.get("l1_frontmatter"), "l1_frontmatter")
    unknown = sorted(set(loaded) - {"searchable_frontmatter", "l1_frontmatter"})
    if unknown:
        raise ValueError(f"unknown {CONFIG_NAME} keys: {', '.join(unknown)}")
    return Config(tuple(searchable), tuple(l1))


def _validate_dot_paths(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of frontmatter dot paths")
    result: list[str] = []
    for raw in value:
        item = raw.strip()
        if not item or item.startswith(".") or item.endswith(".") or ".." in item:
            raise ValueError(f"invalid frontmatter dot path in {field}: {raw!r}")
        result.append(item)
    return list(dict.fromkeys(result))


def frontmatter_value(frontmatter: dict[str, Any], dotted: str) -> Any:
    current: Any = frontmatter
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def flatten_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        result: list[str] = []
        for key in sorted(value):
            result.extend(flatten_value(value[key]))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(flatten_value(item))
        return result
    text = normalize_space(serialize_scalar(value))
    return [text] if text else []


def parse_headings(body: str) -> list[str]:
    return [
        f"{'#' * len(match.group(1))} {plain_markdown(match.group(2))}"
        for line in body.splitlines()
        if (match := HEADING_RE.match(line))
    ]


def split_sections(body: str) -> list[tuple[str, int, str]]:
    sections: list[tuple[str, int, str]] = []
    heading = "Body"
    level = 0
    lines: list[str] = []
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            content = "\n".join(lines).strip()
            if content:
                sections.append((heading, level, content))
            heading = plain_markdown(match.group(2))
            level = len(match.group(1))
            lines = []
        else:
            lines.append(line)
    content = "\n".join(lines).strip()
    if content:
        sections.append((heading, level, content))
    return sections


def first_excerpt(markdown: str, limit: int = SECTION_EXCERPT_LIMIT) -> str:
    for block in re.split(r"\n\s*\n", markdown.strip()):
        cleaned = plain_markdown(block)
        if cleaned:
            return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"
    return ""


def build_l0(document: Document) -> str:
    lines = [
        f"path: {document.source.relative}",
        f"title: {document.title}",
        f"type: {document.concept_type}",
        f"status: {document.status}",
        f"verified: {'true' if document.verified else 'false'}",
    ]
    if document.description:
        lines.append(f"description: {document.description}")
    if document.abstract:
        lines.append(f"abstract: {document.abstract}")
    if document.tags:
        lines.append(f"tags: {', '.join(document.tags)}")
    if document.aliases:
        lines.append(f"aliases: {', '.join(document.aliases)}")
    if document.stale_after:
        lines.append(f"stale_after: {document.stale_after}")
    return "\n".join(lines)


def build_l1(document: Document, limit: int = DEFAULT_L1_LIMIT) -> str:
    parts: list[str] = []
    parts.extend(value for value in (document.description, document.abstract) if value)
    parts.extend(document.configured_l1)
    if document.headings:
        parts.append("Outline: " + "; ".join(heading.lstrip("# ") for heading in document.headings))
    for heading, level, content in split_sections(document.body):
        if level not in {1, 2}:
            continue
        excerpt = first_excerpt(content)
        if excerpt:
            parts.append(f"{heading}: {excerpt}")
    rendered = "\n".join(dict.fromkeys(part for part in parts if part)).strip()
    if len(rendered) > limit:
        return rendered[: limit - 16].rstrip() + "\n[overview truncated]"
    return rendered


def load_document(source: SourceFile, config: Config) -> Document:
    frontmatter, body, raw = parse_markdown(source.path)
    title = normalize_space(serialize_scalar(frontmatter.get("title"))) or source.path.stem
    description = normalize_space(serialize_scalar(frontmatter.get("description")))
    abstract = normalize_space(serialize_scalar(frontmatter.get("abstract")))
    verified_value = frontmatter.get("verified")
    document = Document(
        source=source,
        frontmatter=frontmatter,
        raw=raw,
        body=body,
        title=title,
        description=description,
        abstract=abstract,
        concept_type=normalize_space(serialize_scalar(frontmatter.get("type"))),
        tags=_string_list(frontmatter.get("tags")),
        keywords=_string_list(frontmatter.get("keywords")),
        aliases=_string_list(frontmatter.get("aliases")),
        status=normalize_space(serialize_scalar(frontmatter.get("status"))) or "stable",
        verified=bool(verified_value),
        stale_after=normalize_space(serialize_scalar(frontmatter.get("stale_after"))),
        generated=frontmatter.get("generated"),
        headings=parse_headings(body),
        configured_search=[
            item
            for dotted in config.searchable_frontmatter
            for item in flatten_value(frontmatter_value(frontmatter, dotted))
        ],
        configured_l1=[
            item
            for dotted in config.l1_frontmatter
            for item in flatten_value(frontmatter_value(frontmatter, dotted))
        ],
        l0="",
        l1="",
    )
    document.l0 = build_l0(document)
    document.l1 = build_l1(document)
    return document


def _contains_symlink(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def discover_sources(wiki_root: Path) -> list[SourceFile]:
    root = wiki_root.resolve(strict=True)
    sources: list[SourceFile] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and not (directory_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = directory_path / filename
            if filename in RESERVED_MARKDOWN or filename.startswith(".") or path.suffix.lower() != ".md":
                continue
            if path.is_symlink():
                continue
            resolved = path.resolve(strict=True)
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(f"Wiki path escapes root: {path}") from exc
            stat = resolved.stat()
            sources.append(SourceFile(resolved, relative, stat.st_mtime_ns, stat.st_size))
    return sources


def discover_reserved_files(wiki_root: Path) -> list[SourceFile]:
    root = wiki_root.resolve(strict=True)
    sources: list[SourceFile] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and not (directory_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = directory_path / filename
            if filename not in RESERVED_MARKDOWN or path.is_symlink():
                continue
            resolved = path.resolve(strict=True)
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(f"Wiki path escapes root: {path}") from exc
            stat = resolved.stat()
            sources.append(SourceFile(resolved, relative, stat.st_mtime_ns, stat.st_size))
    return sources


def validate_wiki(wiki_root: Path) -> dict[str, Any]:
    root = discover_wiki_root(explicit=wiki_root)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_config(root)
    except ValueError as exc:
        config = Config()
        errors.append(str(exc))
    sources = discover_sources(root)
    for source in sources:
        try:
            document = load_document(source, config)
            if document.stale_after:
                _parse_stale_after(document.stale_after)
        except ValueError as exc:
            errors.append(f"{source.relative}: {exc}")
    for source in discover_reserved_files(root):
        try:
            validate_reserved_file(source)
        except ValueError as exc:
            errors.append(f"{source.relative}: {exc}")
    return {
        "schema_version": SCHEMA_VERSION,
        "wiki_root": str(root),
        "valid": not errors,
        "documents": len(sources),
        "errors": errors,
        "warnings": warnings,
    }


def runtime_paths(wiki_root: Path) -> tuple[Path, Path, Path]:
    runtime = wiki_root / ".okf"
    return runtime, runtime / "index.sqlite3", runtime / "build.lock"


def secure_runtime(runtime: Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, factory=ClosingConnection)
    else:
        connection = sqlite3.connect(path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            concept_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            abstract TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            keywords_json TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            status TEXT NOT NULL,
            verified INTEGER NOT NULL,
            stale_after TEXT NOT NULL,
            generated_json TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            l0 TEXT NOT NULL,
            l1 TEXT NOT NULL,
            headings_json TEXT NOT NULL,
            searchable_extra TEXT NOT NULL,
            body_text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
            document_id UNINDEXED,
            title,
            aliases,
            metadata,
            headings,
            body,
            path,
            tokenize='unicode61'
        );
        """
    )


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}


def db_is_usable(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with connect(path, read_only=True) as connection:
            return (
                connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and _metadata(connection).get("index_schema_version") == INDEX_SCHEMA_VERSION
            )
    except sqlite3.Error:
        return False


def _snapshot(connection: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    return {
        row["path"]: (int(row["mtime_ns"]), int(row["size"]))
        for row in connection.execute("SELECT path, mtime_ns, size FROM documents")
    }


def _sources_fresh(path: Path, sources: list[SourceFile], config: Config, wiki_root: Path) -> bool:
    if not db_is_usable(path):
        return False
    wanted = {source.relative: (source.mtime_ns, source.size) for source in sources}
    try:
        with connect(path, read_only=True) as connection:
            values = _metadata(connection)
            return (
                _snapshot(connection) == wanted
                and values.get("config") == config.serialized()
                and values.get("wiki_root") == str(wiki_root.resolve())
            )
    except sqlite3.Error:
        return False


def _upsert_document(connection: sqlite3.Connection, document: Document) -> None:
    row = connection.execute("SELECT id FROM documents WHERE path = ?", (document.source.relative,)).fetchone()
    values = (
        document.concept_type,
        document.title,
        document.description,
        document.abstract,
        json.dumps(document.tags, ensure_ascii=False),
        json.dumps(document.keywords, ensure_ascii=False),
        json.dumps(document.aliases, ensure_ascii=False),
        document.status,
        int(document.verified),
        document.stale_after,
        json.dumps(document.generated, ensure_ascii=False, default=serialize_scalar, sort_keys=True),
        document.source.mtime_ns,
        document.source.size,
        document.l0,
        document.l1,
        json.dumps(document.headings, ensure_ascii=False),
        "\n".join(document.configured_search),
        document.body,
    )
    if row:
        document_id = int(row["id"])
        connection.execute("DELETE FROM search WHERE rowid = ?", (document_id,))
        connection.execute(
            """UPDATE documents SET concept_type=?, title=?, description=?, abstract=?, tags_json=?,
            keywords_json=?, aliases_json=?, status=?, verified=?, stale_after=?, generated_json=?,
            mtime_ns=?, size=?, l0=?, l1=?, headings_json=?, searchable_extra=?, body_text=? WHERE id=?""",
            (*values, document_id),
        )
    else:
        cursor = connection.execute(
            """INSERT INTO documents(path, concept_type, title, description, abstract, tags_json,
            keywords_json, aliases_json, status, verified, stale_after, generated_json, mtime_ns,
            size, l0, l1, headings_json, searchable_extra, body_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document.source.relative, *values),
        )
        document_id = int(cursor.lastrowid)
    metadata_text = " ".join(
        [document.description, document.abstract, *document.tags, *document.keywords, document.concept_type, *document.configured_search]
    )
    connection.execute(
        """INSERT INTO search(rowid, document_id, title, aliases, metadata, headings, body, path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            document_id,
            document_id,
            search_document(document.title),
            search_document(" ".join(document.aliases)),
            search_document(metadata_text),
            search_document(" ".join(document.headings)),
            search_document(document.body),
            search_document(document.source.relative),
        ),
    )


def sync_index(wiki_root: Path) -> dict[str, Any]:
    root = discover_wiki_root(explicit=wiki_root)
    validation = validate_wiki(root)
    if not validation["valid"]:
        raise ValueError("Wiki validation failed:\n" + "\n".join(validation["errors"]))
    config = load_config(root)
    sources = discover_sources(root)
    runtime, database, lock = runtime_paths(root)
    secure_runtime(runtime)
    with lock.open("a+", encoding="utf-8") as lock_handle:
        os.chmod(lock, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        sources = discover_sources(root)
        if _sources_fresh(database, sources, config, root):
            return status_index(root, changed=0, removed=0)
        old_snapshot: dict[str, tuple[int, int]] = {}
        reusable = db_is_usable(database)
        old_config = ""
        if reusable:
            with connect(database, read_only=True) as current:
                old_snapshot = _snapshot(current)
                old_config = _metadata(current).get("config", "")
        with tempfile.NamedTemporaryFile(prefix="index-", suffix=".sqlite3", dir=runtime, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            if reusable:
                with connect(database, read_only=True) as source, connect(temporary) as target:
                    source.backup(target)
            with connect(temporary) as connection:
                create_schema(connection)
                wanted = {source.relative: (source.mtime_ns, source.size) for source in sources}
                removed_paths = sorted(set(old_snapshot) - set(wanted))
                for relative in removed_paths:
                    row = connection.execute("SELECT id FROM documents WHERE path = ?", (relative,)).fetchone()
                    if row:
                        connection.execute("DELETE FROM search WHERE rowid = ?", (int(row["id"]),))
                        connection.execute("DELETE FROM documents WHERE id = ?", (int(row["id"]),))
                if old_config != config.serialized():
                    changed_sources = sources
                else:
                    changed_sources = [
                        source for source in sources if old_snapshot.get(source.relative) != wanted[source.relative]
                    ]
                for source in changed_sources:
                    _upsert_document(connection, load_document(source, config))
                connection.executemany(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                    (
                        ("index_schema_version", INDEX_SCHEMA_VERSION),
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("built_at", datetime.now().astimezone().isoformat(timespec="seconds")),
                        ("wiki_root", str(root.resolve())),
                        ("config", config.serialized()),
                    ),
                )
                connection.commit()
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("new index failed SQLite integrity_check")
            os.chmod(temporary, 0o600)
            os.replace(temporary, database)
            os.chmod(database, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
        return status_index(root, changed=len(changed_sources), removed=len(removed_paths))


def status_index(
    wiki_root: Path,
    *,
    changed: int | None = None,
    removed: int | None = None,
) -> dict[str, Any]:
    root = discover_wiki_root(explicit=wiki_root)
    sources = discover_sources(root)
    config = load_config(root)
    _, database, _ = runtime_paths(root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "wiki_root": str(root),
        "index_path": str(database),
        "exists": database.exists(),
        "fresh": False,
        "built_at": None,
        "documents": 0,
        "source_documents": len(sources),
    }
    if db_is_usable(database):
        with connect(database, read_only=True) as connection:
            values = _metadata(connection)
            payload["built_at"] = values.get("built_at")
            payload["documents"] = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        payload["fresh"] = _sources_fresh(database, sources, config, root)
    if changed is not None:
        payload["changed"] = changed
    if removed is not None:
        payload["removed"] = removed
    return payload


def _fts_expression(tokens: list[str]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _parse_stale_after(value: str) -> datetime:
    return _parse_okf_timestamp(value, "stale_after")


def is_stale(value: str, now: datetime | None = None) -> bool:
    if not value:
        return False
    parsed = _parse_stale_after(value)
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.astimezone()
    return parsed <= current


def _field_tokens(row: sqlite3.Row) -> dict[str, set[str]]:
    metadata_text = " ".join(
        [
            row["description"],
            row["abstract"],
            row["concept_type"],
            " ".join(json.loads(row["tags_json"])),
            " ".join(json.loads(row["keywords_json"])),
            row["searchable_extra"],
        ]
    )
    return {
        "title": set(search_tokens(row["title"])),
        "aliases": set(search_tokens(" ".join(json.loads(row["aliases_json"])))),
        "metadata": set(search_tokens(metadata_text)),
        "headings": set(search_tokens(" ".join(json.loads(row["headings_json"])))),
        "body": set(search_tokens(row["body_text"])),
        "path": set(search_tokens(row["path"])),
    }


def _lexical_score(row: sqlite3.Row, query: str, tokens: list[str]) -> tuple[float, list[str], bool]:
    weights = {"title": 0.72, "aliases": 0.68, "metadata": 0.42, "headings": 0.25, "body": 0.10, "path": 0.08}
    fields = _field_tokens(row)
    wanted = set(tokens)
    score = 0.0
    reasons: list[str] = []
    strong = False
    for field, weight in weights.items():
        matched = wanted & fields[field]
        if not matched:
            continue
        coverage = len(matched) / max(1, len(wanted))
        score += weight * min(1.0, coverage * 2.0)
        reasons.append(field)
        if field in {"title", "aliases", "metadata", "headings"}:
            strong = True
        elif field == "body" and len(matched) >= 2 and coverage >= 0.20:
            strong = True
    normalized_query = normalize_space(query).lower()
    title = normalize_space(row["title"]).lower()
    aliases = [normalize_space(item).lower() for item in json.loads(row["aliases_json"])]
    exact = normalized_query == title or normalized_query in aliases
    contained = (title and title in normalized_query) or any(alias and alias in normalized_query for alias in aliases)
    if exact:
        score += 2.0
        reasons.append("exact-title-or-alias")
        strong = True
    elif contained:
        score += 1.0
        reasons.append("title-or-alias-phrase")
        strong = True
    phrase_fields = {
        "title": title,
        "aliases": "\n".join(aliases),
        "metadata": "\n".join(
            [
                row["description"].lower(),
                row["abstract"].lower(),
                row["searchable_extra"].lower(),
            ]
        ),
        "body": row["body_text"].lower(),
    }
    phrase_weights = {"title": 0.40, "aliases": 0.40, "metadata": 0.25, "body": 0.20}
    for phrase in query_phrases(query):
        for field in ("title", "aliases", "metadata", "body"):
            if phrase in phrase_fields[field]:
                score += phrase_weights[field]
                reasons.append(f"{field}-phrase")
                strong = True
                break
    return score, reasons, strong


def relationship_subjects(query: str) -> tuple[str, ...]:
    """Return explicit named subjects whose relationship must not leak across people."""

    return tuple(
        dict.fromkeys(
            match.group("subject")
            for match in RELATIONSHIP_SUBJECT_RE.finditer(query)
            if match.group("subject") not in GENERIC_RELATIONSHIP_SUBJECTS
        )
    )


def _row_contains_subject(row: sqlite3.Row, subject: str) -> bool:
    searchable = "\n".join(
        (
            row["title"],
            row["description"],
            row["abstract"],
            " ".join(json.loads(row["aliases_json"])),
            " ".join(json.loads(row["tags_json"])),
            " ".join(json.loads(row["keywords_json"])),
            row["searchable_extra"],
            row["body_text"],
        )
    )
    return subject.lower() in searchable.lower()


def _safe_filter_path(value: str, field: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid {field}: {value}")
    return path.as_posix()


def query_index(
    wiki_root: Path,
    query: str,
    *,
    limit: int = 5,
    path_prefix: str | None = None,
    concept_type: str | None = None,
    include_draft: bool = False,
    include_deprecated: bool = False,
    trace_level: str = "summary",
) -> dict[str, Any]:
    root = discover_wiki_root(explicit=wiki_root)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if trace_level not in {"summary", "full"}:
        raise ValueError("trace must be summary or full")
    sync_index(root)
    _, database, _ = runtime_paths(root)
    tokens = query_tokens(query)
    required_relationship_subjects = relationship_subjects(query)
    trace: list[dict[str, Any]] = [{"stage": "scope", "wiki_root": str(root)}]
    if not tokens:
        return {
            "schema_version": SCHEMA_VERSION,
            "query": query,
            "semantic": None,
            "results": [],
            "warnings": ["query produced no searchable tokens"],
            "trace": trace,
        }
    filters = ["search MATCH ?"]
    parameters: list[Any] = [_fts_expression(tokens)]
    normalized_prefix = None
    if path_prefix:
        normalized_prefix = _safe_filter_path(path_prefix, "path-prefix")
        escaped_prefix = normalized_prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        filters.append("(documents.path = ? OR documents.path LIKE ? ESCAPE '!')")
        parameters.extend([normalized_prefix, escaped_prefix + "/%"])
    if concept_type:
        filters.append("documents.concept_type = ?")
        parameters.append(concept_type)
    if not include_draft:
        filters.append("lower(documents.status) != 'draft'")
    if not include_deprecated:
        filters.append("lower(documents.status) != 'deprecated'")
    sql = (
        "SELECT documents.* FROM search JOIN documents ON documents.id = search.document_id WHERE "
        + " AND ".join(filters)
    )
    with connect(database, read_only=True) as connection:
        rows = list(connection.execute(sql, parameters))
    ranked: list[tuple[float, sqlite3.Row, list[str], bool]] = []
    for row in rows:
        if required_relationship_subjects and any(
            not _row_contains_subject(row, subject) for subject in required_relationship_subjects
        ):
            continue
        lexical, reasons, strong = _lexical_score(row, query, tokens)
        stale = is_stale(row["stale_after"])
        governance = 0.0
        if row["verified"]:
            governance += 0.08
            reasons.append("verified")
        if stale:
            governance -= 0.22
            reasons.append("stale")
        if row["status"].lower() == "draft":
            governance -= 0.12
            reasons.append("draft")
        if row["status"].lower() == "deprecated":
            governance -= 0.30
            reasons.append("deprecated")
        score = lexical + governance
        if strong or lexical >= 0.20:
            ranked.append((score, row, reasons, stale))
    ranked.sort(key=lambda item: (-item[0], item[1]["path"]))
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    for score, row, reasons, stale in ranked[:limit]:
        status = row["status"]
        if stale:
            warnings.append(f"{row['path']} is stale after {row['stale_after']}")
        if status.lower() in {"draft", "deprecated"}:
            warnings.append(f"{row['path']} is a {status.lower()} document")
        results.append(
            {
                "path": row["path"],
                "title": row["title"],
                "type": row["concept_type"],
                "description": row["description"],
                "abstract": row["abstract"],
                "aliases": json.loads(row["aliases_json"]),
                "status": status,
                "recommended_level": "l2",
                "l0": row["l0"],
                "l1": row["l1"],
                "governance": {"verified": bool(row["verified"]), "stale": stale, "stale_after": row["stale_after"] or None},
                "scores": {"lexical": round(score, 6), "semantic": None},
                "matched": list(dict.fromkeys(reasons)),
            }
        )
    if not results:
        warnings.append("no sufficiently relevant Wiki document found")
    trace.append(
        {
            "stage": "lexical",
            "tokens": tokens,
            "candidate_count": len(rows),
            "path_prefix": normalized_prefix,
            "type": concept_type,
        }
    )
    trace.append({"stage": "rank", "result_count": len(results)})
    if trace_level == "full":
        trace.append(
            {
                "stage": "candidates",
                "items": [
                    {"path": row["path"], "score": round(score, 6), "matched": reasons}
                    for score, row, reasons, _ in ranked
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "query": query,
        "semantic": None,
        "results": results,
        "warnings": list(dict.fromkeys(warnings)),
        "trace": trace,
    }


def resolve_document_path(wiki_root: Path, requested: str) -> Path:
    root = discover_wiki_root(explicit=wiki_root)
    normalized = requested.replace("\\", "/").strip()
    if normalized.startswith("wiki/") and root.name == "wiki":
        normalized = normalized[5:]
    relative = _safe_filter_path(normalized, "Wiki path")
    candidate = root / relative
    if _contains_symlink(candidate, root):
        raise ValueError(f"Wiki retrieval rejects symbolic links: {candidate}")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"Wiki document does not exist: {requested}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside Wiki root: {requested}") from exc
    if resolved.suffix.lower() != ".md" or resolved.name in RESERVED_MARKDOWN:
        raise ValueError(f"path is not a retrievable Markdown document: {requested}")
    return resolved


def get_document(wiki_root: Path, requested: str, level: str) -> dict[str, Any]:
    if level not in {"l0", "l1", "l2"}:
        raise ValueError("level must be l0, l1, or l2")
    root = discover_wiki_root(explicit=wiki_root)
    path = resolve_document_path(root, requested)
    stat = path.stat()
    source = SourceFile(path, path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size)
    document = load_document(source, load_config(root))
    content = {"l0": document.l0, "l1": document.l1, "l2": document.raw}[level]
    return {
        "schema_version": SCHEMA_VERSION,
        "path": source.relative,
        "level": level,
        "semantic": None,
        "content": content,
    }
