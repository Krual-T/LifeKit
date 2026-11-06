#!/usr/bin/env python3
"""
Read an explicitly selected weekly document and/or search Release/MMDD documents.
Neither source is requested unless its corresponding option is supplied.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


LARK_PROFILE = ""


def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def run_lark_cli(cmd: list[str]) -> dict:
    """Run lark-cli and parse its JSON output."""
    try:
        if cmd and cmd[0] == "lark-cli":
            cmd = list(cmd)
            cmd[0] = shutil.which("lark-cli") or cmd[0]
            profile = LARK_PROFILE
            if not profile:
                return {"ok": False, "_error": "未指定 --profile"}
            cmd[1:1] = ["--profile", profile]
            if "--as" not in cmd:
                cmd.extend(["--as", "user"])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except Exception as e:
        return {"ok": False, "_error": str(e), "_cmd": " ".join(cmd)}

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if not stdout:
        return {
            "ok": False,
            "_error": stderr or f"lark-cli exited with {result.returncode}",
            "_cmd": " ".join(cmd),
            "_returncode": result.returncode,
        }

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "_error": "lark-cli did not return JSON",
            "_raw": stdout,
            "_stderr": stderr,
            "_cmd": " ".join(cmd),
            "_returncode": result.returncode,
        }

    if stderr:
        data["_stderr"] = stderr
    if result.returncode != 0 and data.get("ok") is not False:
        data["ok"] = False
        data["_returncode"] = result.returncode
    return data


def strip_highlight(value: str) -> str:
    value = re.sub(r"</?h[b]?>", "", value or "", flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def result_title(item: dict | None) -> str:
    if not item:
        return ""
    return strip_highlight(item.get("title_highlighted", "") or item.get("title", ""))


def result_time(item: dict, field: str) -> int:
    meta = item.get("result_meta", {}) if isinstance(item, dict) else {}
    value = meta.get(field)
    return value if isinstance(value, int) else 0


def search_drive(query: str, page_size: int = 20) -> dict:
    return run_lark_cli([
        "lark-cli", "drive", "+search",
        "--query", query,
        "--doc-types", "wiki,docx",
        "--sort", "edit_time",
        "--page-size", str(page_size),
        "--format", "json",
    ])


def fetch_doc(doc: str, doc_format: str = "markdown", scope: str = "") -> dict:
    cmd = [
        "lark-cli", "docs", "+fetch",
        "--api-version", "v2",
        "--doc", doc,
        "--format", "json",
    ]
    if doc_format:
        cmd.extend(["--doc-format", doc_format])
    if scope == "outline":
        cmd.extend(["--scope", "outline", "--max-depth", "3", "--detail", "with-ids"])
    return run_lark_cli(cmd)


def normalize_keywords(keywords: str) -> list[str]:
    return [part.strip().lower() for part in keywords.split(",") if part.strip()]


def release_mmdd_from_title(title: str) -> str:
    match = re.search(r"Release\s*/\s*(\d{4})", title, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def parse_release_offsets(offsets: str) -> list[int]:
    values = []
    for part in offsets.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values or [6, 4]


def release_score(item: dict, target_mmdds: list[str], keywords: list[str], week_start_dt: datetime) -> tuple[int, int, int]:
    title = result_title(item)
    title_lower = title.lower()
    meta = item.get("result_meta", {}) if isinstance(item, dict) else {}
    create_time = result_time(item, "create_time")
    create_dt = datetime.fromtimestamp(create_time) if create_time else None
    score = 0
    title_mmdd = release_mmdd_from_title(title)
    if title_mmdd in target_mmdds:
        score += 100 - (target_mmdds.index(title_mmdd) * 10)
    if create_dt and week_start_dt.date() <= create_dt.date() <= (week_start_dt + timedelta(days=6)).date():
        score += 40
    if "release" in title_lower:
        score += 20
    score += sum(5 for keyword in keywords if keyword in title_lower)
    if meta.get("doc_types") in {"DOCX", "docx"}:
        score += 1
    return (score, create_time, result_time(item, "update_time"))


def select_release(week_start: str, release_query: str, release_keywords: str, release_offset_days: str) -> dict:
    week_start_dt = parse_date(week_start)
    release_offsets = parse_release_offsets(release_offset_days)
    target_dates = [week_start_dt + timedelta(days=offset) for offset in release_offsets]
    target_mmdds = [target_date.strftime("%m%d") for target_date in target_dates]
    keywords = normalize_keywords(release_keywords)

    def matches_scope(item):
        title = result_title(item).lower()
        return "release" in title and (not keywords or any(keyword in title for keyword in keywords))

    searches = []
    # A date-only query is broader than the caller's explicit query. Use it
    # only when a supplied title keyword can constrain the documents we read.
    exact_queries = [f"intitle:Release/{target_mmdd}" for target_mmdd in target_mmdds] if keywords else []
    for query in [*exact_queries, release_query]:
        data = search_drive(query)
        searches.append({"query": query, "result": data})
        results = data.get("data", {}).get("results", []) if isinstance(data.get("data"), dict) else []
        if any(matches_scope(item) for item in results):
            break

    candidates_by_url = {}
    for search in searches:
        data = search["result"]
        results = data.get("data", {}).get("results", []) if isinstance(data.get("data"), dict) else []
        for item in results:
            meta = item.get("result_meta", {}) if isinstance(item, dict) else {}
            url = meta.get("url") or meta.get("token") or result_title(item)
            candidates_by_url[url] = item

    candidates = list(candidates_by_url.values())
    filtered = [item for item in candidates if matches_scope(item)]
    selected = max(filtered, key=lambda item: release_score(item, target_mmdds, keywords, week_start_dt), default=None)

    return {
        "target_dates": [target_date.strftime("%Y-%m-%d") for target_date in target_dates],
        "target_mmdds": target_mmdds,
        "target_date": target_dates[0].strftime("%Y-%m-%d"),
        "target_mmdd": target_mmdds[0],
        "release_query": release_query,
        "release_keywords": keywords,
        "release_offsets": release_offsets,
        "searches": searches,
        "candidates": candidates,
        "selected": selected,
    }


def document_summary(fetch_result: dict) -> dict:
    doc = fetch_result.get("data", {}).get("document", {}) if isinstance(fetch_result.get("data"), dict) else {}
    return {
        "document_id": doc.get("document_id"),
        "revision_id": doc.get("revision_id"),
        "content": doc.get("content", ""),
    }


def save_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    global LARK_PROFILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week-start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--week-end", required=True, help="End date, exclusive (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default="./raw", help="Output directory, default ./raw")
    parser.add_argument("--profile", required=True, help="Verified lark-cli profile")
    parser.add_argument("--weekly-report-doc", default="", help="Read this document only when supplied")
    parser.add_argument("--release-query", default="", help="Enable Release/MMDD search with this fallback query")
    parser.add_argument("--release-keywords", default="", help="Comma-separated Release title keywords")
    parser.add_argument("--release-offset-days", default="6,4", help="Comma-separated Release title date offsets from week-start, tried in order")
    args = parser.parse_args(argv)
    LARK_PROFILE = args.profile
    if not args.weekly_report_doc and not args.release_query:
        parser.error("select --weekly-report-doc and/or --release-query")
    if parse_date(args.week_end) <= parse_date(args.week_start):
        parser.error("--week-end must be later than --week-start")

    output_dir = Path(args.output_dir)
    output_path = output_dir / "raw_weekly_context.json"
    warnings = []

    weekly_report_fetch = {}
    if args.weekly_report_doc:
        print("  Reading selected weekly document...")
        weekly_report_fetch = fetch_doc(args.weekly_report_doc, doc_format="markdown")
        if not weekly_report_fetch.get("ok"):
            warnings.append(f"weekly_report fetch failed: {weekly_report_fetch.get('_error') or weekly_report_fetch.get('error')}")

    release = {}
    if args.release_query:
        print("  Searching selected Release documents...")
        release = select_release(
            week_start=args.week_start,
            release_query=args.release_query,
            release_keywords=args.release_keywords,
            release_offset_days=args.release_offset_days,
        )
        for search in release.get("searches", []):
            result = search.get("result", {})
            if result.get("ok") is False or result.get("_error"):
                warnings.append(f"release search failed: {result.get('_error') or result.get('error')}")

    release_fetch = {}
    release_outline = {}
    selected = release.get("selected")
    selected_url = ""
    if selected:
        selected_url = selected.get("result_meta", {}).get("url", "")
        print(f"    -> Release: {result_title(selected)}")
        release_fetch = fetch_doc(selected_url, doc_format="markdown")
        release_outline = fetch_doc(selected_url, doc_format="", scope="outline")
        if not release_fetch.get("ok"):
            warnings.append(f"release fetch failed: {release_fetch.get('_error') or release_fetch.get('error')}")
    elif args.release_query:
        warnings.append("release document not found")

    data = {
        "week_start": args.week_start,
        "week_end": args.week_end,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weekly_report": {
            "enabled": bool(args.weekly_report_doc),
            "url": args.weekly_report_doc,
            "fetch": weekly_report_fetch,
            "document": document_summary(weekly_report_fetch),
        },
        "release": {
            "enabled": bool(args.release_query),
            "target_date": release.get("target_date"),
            "target_mmdd": release.get("target_mmdd"),
            "target_dates": release.get("target_dates", []),
            "target_mmdds": release.get("target_mmdds", []),
            "release_offsets": release.get("release_offsets", []),
            "selected_url": selected_url,
            "selected_title": result_title(selected),
            "selected": selected,
            "candidates": release.get("candidates", []),
            "searches": release.get("searches", []),
            "fetch": release_fetch,
            "outline": release_outline,
            "document": document_summary(release_fetch) if release_fetch else {},
        },
        "warnings": warnings,
    }

    save_json(data, output_path)
    print(f"  Saved: {output_path}")
    if warnings:
        print("  [warning] " + "; ".join(warnings))
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
