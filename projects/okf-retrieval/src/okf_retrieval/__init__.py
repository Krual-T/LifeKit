"""Deterministic retrieval for OKF Markdown Wikis."""

from .core import (
    Config,
    discover_wiki_root,
    get_document,
    query_index,
    status_index,
    sync_index,
    validate_wiki,
)

__all__ = [
    "Config",
    "discover_wiki_root",
    "get_document",
    "query_index",
    "status_index",
    "sync_index",
    "validate_wiki",
]

__version__ = "0.1.0"
