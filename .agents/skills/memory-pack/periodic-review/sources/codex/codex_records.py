"""Read Codex JSONL evidence, without local imports or filesystem writes.

Windows are timezone-aware and half-open. session_roots may name a Codex home
(sessions and archived_sessions are scanned) or individual session directories.
Only the selected copy of each thread is fully read: most envelope lines wins,
with path as deterministic tie-breaker. The metadata pass skips unused bodies;
the selected copy is validated in the evidence pass. Diagnostics never contain
raw log text.
"""

import argparse
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys


def _time(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return result


def _belongs(cwd, root):
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return False
    return Path(cwd).resolve().is_relative_to(root)


_SECRET_KEY = r"(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|passwd|credential)[\w-]*|token|cookie|authorization)"
_ASSIGNMENT = re.compile(
    r'''(?i)(["']?\b''' + _SECRET_KEY + r'''["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)'''
)
_INJECTION = re.compile(
    r"<(environment_context|permissions instructions|app-context|skills_instructions|INSTRUCTIONS|system-reminder|developer_instructions|user_instructions)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
# Recognize only the usual top-level header orders. Unusual layouts fall back
# to JSON parsing; a nested payload field cannot be mistaken for an envelope.
_HEADER = re.compile(
    rb'^\s*\{\s*(?:"timestamp"\s*:\s*"(?P<time_before>[0-9TtZz:+. -]+)"\s*,\s*"type"\s*:\s*"(?P<type_after>[a-z_]+)"'
    rb'|"type"\s*:\s*"(?P<type_before>[a-z_]+)"\s*,\s*"timestamp"\s*:\s*"(?P<time_after>[0-9TtZz:+. -]+)")\s*,\s*"payload"\s*:'
)


def _redact(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)", "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?im)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+", r"\1: [REDACTED]", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda m: m[1] + '"[REDACTED]"', text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b", "[REDACTED]", text)
    text = re.sub(r"(\w+://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    return text


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part.get("text", "") for part in value
                         if isinstance(part, dict) and part.get("type") in ("input_text", "output_text", "text")
                         and isinstance(part.get("text"), str))
    return json.dumps(value, ensure_ascii=False)


def _visible(payload):
    kind = payload.get("type")
    if not isinstance(kind, str):
        return None
    if kind == "message" and payload.get("role") in ("user", "assistant"):
        if payload.get("role") == "assistant" and "analysis" in (payload.get("channel"), payload.get("phase")):
            return None
        text = _text(payload.get("content", ""))
        # The generated AGENTS preamble is not a user request. Other injected
        # blocks can share a message with real text, so remove blocks only.
        if text.lstrip().startswith(("# AGENTS.md instructions for ",
                                     "Another language model started to solve this problem")):
            return None
        text = _INJECTION.sub("", text).strip()
        return (payload["role"], "message", text) if text else None
    if kind in ("function_call", "custom_tool_call", "local_shell_call"):
        args = payload.get("arguments", payload.get("input", payload.get("action", "")))
        return "assistant", "tool_call", str(payload.get("name", kind)) + "\n" + _text(args)
    if kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
        return "tool", "tool_result", _text(payload.get("output", ""))
    return None


def _event_visible(payload):
    role = {"user_message": "user", "agent_message": "assistant"}.get(payload.get("type"))
    if not role or not isinstance(payload.get("message"), str):
        return None
    return _visible({"type": "message", "role": role, "content": payload["message"],
                     "channel": payload.get("channel"), "phase": payload.get("phase")})


def _unmatched_events(events, messages):
    """Pair event/response mirrors one-to-one, not similar messages.

    Explicit message IDs take precedence. ID-less mirrors require exact text,
    role and turn segment in the same thread; repeated occurrences are counted.
    These text keys are never used for cross-thread deduplication.
    """
    by_id, by_text = defaultdict(list), defaultdict(list)
    used = set()
    for index, (segment, record) in enumerate(messages):
        if record.get("message_id"):
            by_id[record["message_id"]].append(index)
        by_text[(segment, record["role"], record["text"])].append(index)
    for event in events:
        segment, record, _ = event
        message_id = record.get("message_id")
        candidates = by_id.get(message_id, []) if message_id else []
        candidates = candidates + by_text.get((segment, record["role"], record["text"]), [])
        for index in candidates:
            other = messages[index][1]
            if index in used or other["role"] != record["role"] or other["text"] != record["text"]:
                continue
            if message_id and other.get("message_id") and message_id != other["message_id"]:
                continue
            if (record.get("phase") in ("final", "commentary")
                    and other.get("phase") in ("final", "commentary")
                    and record["phase"] != other["phase"]):
                continue
            if other.get("phase") == "unknown" and record.get("phase") in ("final", "commentary"):
                other["phase"] = record["phase"]
            used.add(index)
            break
        else:
            yield event


def _parent(meta):
    parent = meta.get("parent_thread_id") or meta.get("parent_thread")
    source = meta.get("source")
    if not parent and isinstance(source, dict):
        subagent = source.get("subagent", {})
        spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, dict) else {}
        if isinstance(spawn, dict):
            parent = spawn.get("parent_thread_id")
    return parent if isinstance(parent, str) else None


def _automation(meta, text=""):
    source = meta.get("source")
    if meta.get("automation_id"):
        return True
    if isinstance(source, str) and source in ("automation", "scheduled"):
        return True
    if isinstance(source, dict) and any(k in source for k in ("automation", "scheduled")):
        return True
    return bool(re.search(r"(?m)^Automation(?: ID| id):\s*\S+", text)
                and re.search(r"(?m)^Automation:\s*\S+", text))


def _lines(path, skip_payload_types=()):
    """Yield line-local errors; a torn tail cannot erase preceding evidence."""
    try:
        with path.open("rb") as stream:
            for number, raw in enumerate(stream, 1):
                item = None
                if skip_payload_types:
                    header = _HEADER.match(raw)
                    kind = (header["type_after"] or header["type_before"]).decode("ascii") if header else None
                    if kind in skip_payload_types and raw[-64:].rstrip().endswith(b"}"):
                        # Metadata discovery does not need the body here.
                        # This is not validation: _located_lines reads the full
                        # selected file again and locates any damaged rows.
                        timestamp = (header["time_before"] or header["time_after"]).decode("ascii")
                        yield number, {"type": kind, "timestamp": timestamp, "payload": {}}, None
                        continue
                try:
                    item = json.loads(raw)
                    if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                        raise ValueError("invalid envelope")
                    payload = item["payload"]
                    if not isinstance(item.get("type"), str):
                        raise ValueError("invalid envelope type")
                    if any(key in payload and payload[key] is not None and not isinstance(payload[key], str)
                           for key in ("type", "role", "call_id", "id")):
                        raise ValueError("invalid payload identifiers")
                    yield number, item, None
                except (ValueError, UnicodeError):
                    # A malformed payload can still have a usable envelope time.
                    # For a torn JSON line, accept only a complete leading time
                    # field, not a timestamp mentioned inside message text.
                    hint = item.get("timestamp") if isinstance(item, dict) else None
                    if hint is None:
                        match = re.match(rb'\s*\{\s*"timestamp"\s*:\s*("(?:\\.|[^"\\])*")', raw)
                        if match:
                            try:
                                hint = json.loads(match[1])
                            except (ValueError, UnicodeError):
                                pass
                    yield number, {"timestamp": hint}, "invalid_jsonl"
    except OSError:
        yield 0, None, "unreadable_session"


def _located_lines(path):
    """Locate untimed rows between nearest usable envelope timestamps.

    Only an untimed run is buffered, never the full session history. The final
    open interval has no upper bound; an old tail is not evidence of today's
    failure, whereas a tail starting after the window cannot affect it.
    """
    previous = None
    pending = []
    for line, item, error in _lines(path):
        try:
            timestamp = _time(item.get("timestamp"))
        except (TypeError, ValueError, AttributeError):
            pending.append((line, item, error))
            continue
        for row in pending:
            yield (*row, previous, timestamp)
        pending.clear()
        yield line, item, error, timestamp, timestamp
        previous = timestamp
    for row in pending:
        yield (*row, previous, None)


def read_records(config, start, end, excluded_thread_ids=(), included_thread_ids=()):
    """Return {records, context_gaps, failures}; any diagnostic means partial.

    A nonempty included_thread_ids selects exactly those threads, not their
    descendants. Exclusions still take precedence. Records retain source/file/1-based
    line provenance. Background includes the
    latest preceding user message and pre-window tool calls whose results fall
    in-window; no after-window content is returned. No completion is inferred.
    """
    result = {"records": [], "context_gaps": [], "failures": []}
    source_id = config.get("id", "unknown")

    def diagnostic(bucket, code, path=None, line=None, thread=None, **details):
        item = {"code": code, "thread_id": thread,
                "origin": {"source_id": source_id, "file": str(path) if path else None, "line": line}, **details}
        if item not in result[bucket]:
            result[bucket].append(item)

    try:
        start, end = _time(start), _time(end)
        if start >= end:
            raise ValueError("empty window")
        project = config["project_root"]
        roots = config["session_roots"]
        if not isinstance(source_id, str) or not source_id or not isinstance(project, str) or not os.path.isabs(project):
            raise ValueError("invalid source")
        if not isinstance(roots, list) or not roots or any(not isinstance(p, str) or not os.path.isabs(p) for p in roots):
            raise ValueError("invalid roots")
        root = Path(project).resolve()
    except (KeyError, TypeError, ValueError, AttributeError):
        diagnostic("failures", "invalid_config_or_window")
        return result

    files = set()
    for location in roots:
        location = Path(location)
        if not location.is_dir():
            diagnostic("failures", "unavailable_session_root", location)
            continue
        def walk_error(error):
            diagnostic("failures", "unreadable_session_directory", error.filename)
        # A configured home only contributes session stores, not unrelated JSONL.
        stores = [location / name for name in ("sessions", "archived_sessions", "archived") if (location / name).is_dir()]
        for store in stores or [location]:
            for directory, _, names in os.walk(store, onerror=walk_error):
                files.update(Path(directory, name).resolve() for name in names if name.endswith(".jsonl"))

    threads = {}
    excluded = set(excluded_thread_ids)
    included = set(included_thread_ids)
    parents = {}
    for path in sorted(files):
        meta, count, automated, first_user = None, 0, False, False
        in_project, matches, relevant_unclassified = False, False, False
        skip_payload_types = {"compacted", "response_item", "event_msg"}
        for line, item, error in _lines(path, skip_payload_types):
            if error:
                continue
            count += 1
            payload = item["payload"]
            if item.get("type") == "session_meta" and meta is None:
                meta = payload
                automated = _automation(meta)
                in_project = _belongs(meta.get("cwd"), root)
                matches |= in_project
            if item.get("type") == "turn_context":
                in_project = _belongs(payload.get("cwd"), root)
                matches |= in_project
            if item.get("type") in ("session_meta", "turn_context"):
                if in_project and not first_user:
                    skip_payload_types.difference_update(("response_item", "event_msg"))
                else:
                    skip_payload_types.update(("response_item", "event_msg"))
            if in_project and (not meta or not isinstance(meta.get("id"), str)):
                try:
                    timestamp = _time(item.get("timestamp"))
                except (TypeError, ValueError, AttributeError):
                    relevant_unclassified = True
                else:
                    relevant_unclassified |= start <= timestamp < end
            if in_project and not first_user and item.get("type") in ("response_item", "event_msg"):
                visible = _visible(payload) if item["type"] == "response_item" else _event_visible(payload)
                if visible and visible[0] == "user":
                    first_user = True
                    automated = automated or _automation({}, visible[2])
                    skip_payload_types.update(("response_item", "event_msg"))
        if not meta or not isinstance(meta.get("id"), str):
            # Without positive project attribution, a broken file in a shared
            # session store says nothing about this project's coverage.
            if matches and relevant_unclassified:
                diagnostic("context_gaps", "unclassified_session", path)
            continue
        thread = meta["id"]
        parent = _parent(meta)
        parents.setdefault(thread, set()).add(parent)
        if automated:
            excluded.add(thread)
        candidate = (count, str(path), meta, matches)
        if thread not in threads or candidate[:2] > threads[thread][:2]:
            threads[thread] = candidate

    while True:
        descendants = {thread for thread, links in parents.items() if links & excluded}
        if descendants <= excluded:
            break
        excluded.update(descendants)

    for thread, (_, filename, meta, matches) in sorted(threads.items()):
        if thread in excluded or not matches or (included and thread not in included):
            continue
        path = Path(filename)
        cwd = meta.get("cwd")
        in_project = _belongs(cwd, root)
        prior_user = None
        calls = {}
        emitted = set()
        events, messages = [], []
        segment = 0
        turn_id = None

        def emit(record, background=False):
            if record["record_id"] not in emitted:
                public = dict(record, text=_redact(record["text"]))
                if background:
                    public["background"] = True
                result["records"].append(public)
                emitted.add(record["record_id"])

        def scoped_diagnostic(bucket, code, line, lower, upper):
            if lower is not None and upper is not None:
                lower, upper = min(lower, upper), max(lower, upper)
                if lower >= end or upper < start:
                    return
            elif lower is not None:
                if lower >= end:
                    return
                if lower < start:
                    bucket, code = "context_gaps", code + "_time_unknown"
            elif upper is not None:
                if upper < start:
                    return
                if upper >= end:
                    bucket, code = "context_gaps", code + "_time_unknown"
            else:
                bucket, code = "context_gaps", code + "_time_unknown"
            diagnostic(bucket, code, path, line, thread)

        for line, item, error, lower, upper in _located_lines(path):
            if error:
                if in_project:
                    scoped_diagnostic("failures", error, line, lower, upper)
                continue
            payload = item["payload"]
            envelope = item.get("type")
            if envelope == "turn_context":
                segment += 1
                turn_id = payload.get("turn_id")
                was_project = in_project
                cwd = payload.get("cwd")
                in_project = _belongs(cwd, root)
                if was_project and (not isinstance(cwd, str) or not os.path.isabs(cwd)):
                    scoped_diagnostic("context_gaps", "missing_turn_cwd", line, lower, upper)
                if not in_project:
                    prior_user, calls = None, {}
                continue
            if not in_project:
                prior_user, calls = None, {}
                continue
            # Do not normalize, strip injections or redact future bodies. Their
            # JSON has still been validated and their time remains an anchor
            # for adjacent corrupt rows. An out-of-order later row is still read.
            if envelope in ("response_item", "event_msg") and lower is not None and lower == upper and lower >= end:
                continue
            if envelope == "response_item" and lower is not None and lower == upper and lower < start:
                # Only user requests and pending calls can become background.
                # Historical outputs merely close calls; assistant prose cannot
                # be needed by this reader's existing background contract.
                payload_kind = payload.get("type")
                if payload_kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                    calls.pop(payload.get("call_id"), None)
                    continue
                if payload_kind == "message" and payload.get("role") != "user":
                    continue
            if envelope == "event_msg" and lower is not None and lower == upper and lower < start and payload.get("type") != "user_message":
                continue
            if envelope == "compacted":
                try:
                    compacted_at = _time(item.get("timestamp"))
                except (TypeError, ValueError, AttributeError):
                    scoped_diagnostic("context_gaps", "invalid_message_timestamp", line, lower, upper)
                else:
                    if start <= compacted_at < end:
                        diagnostic("context_gaps", "compacted_context", path, line, thread)
                continue
            is_event = envelope == "event_msg"
            visible = _event_visible(payload) if is_event else _visible(payload) if envelope == "response_item" else None
            if not visible:
                continue
            try:
                timestamp = _time(item.get("timestamp"))
            except (TypeError, ValueError, AttributeError):
                scoped_diagnostic("context_gaps", "invalid_message_timestamp", line, lower, upper)
                continue
            role, kind, text = visible
            call_id = payload.get("call_id") or (payload.get("id") if kind == "tool_call" else None)
            record = {"record_id": f"{source_id}:{thread}:{line}", "thread_id": thread,
                      "parent_thread_id": _parent(meta), "timestamp": timestamp.isoformat(),
                      "role": role, "kind": kind, "text": text, "call_id": call_id,
                      "origin": {"source_id": source_id, "file": filename, "line": line}}
            message_id = payload.get("message_id") or payload.get("id")
            if kind == "message":
                record["turn_id"] = payload.get("turn_id") or turn_id
                if role == "assistant":
                    # Missing phase is unknown, never inferred from position.
                    phase = payload.get("phase") or payload.get("channel")
                    record["phase"] = "final" if phase in ("final", "final_answer") else "commentary" if phase == "commentary" else "unknown"
            if kind == "message" and isinstance(message_id, str) and message_id:
                record["message_id"] = message_id
            if is_event:
                record["fallback"] = True
                record["origin"]["envelope_type"] = "event_msg"
            if timestamp >= end:
                continue
            if kind == "tool_call" and call_id:
                calls[call_id] = record
            if timestamp < start:
                if role == "user":
                    # Prefer the native response when an event mirrors the
                    # preceding background request; do not redact either yet.
                    if not (is_event and prior_user and not prior_user.get("fallback") and prior_user["text"] == text):
                        prior_user = record
                if kind == "tool_result":
                    calls.pop(call_id, None)
                continue
            if is_event:
                events.append((segment, record, prior_user))
                continue
            if prior_user:
                emit(prior_user, background=True)
            if kind == "message":
                messages.append((segment, record))
            if kind == "tool_result":
                call = calls.pop(call_id, None)
                if call:
                    emit(call, background=_time(call["timestamp"]) < start)
                else:
                    diagnostic("context_gaps", "missing_tool_call", path, line, thread)
            emit(record)
        recovered = []
        for _, record, background in _unmatched_events(events, messages):
            if background:
                emit(background, background=True)
            emit(record)
            recovered.append(record)
        phases = {record["record_id"]: record["phase"] for _, record in messages if "phase" in record}
        for record in result["records"]:
            if record["record_id"] in phases:
                record["phase"] = phases[record["record_id"]]
        if recovered:
            diagnostic("context_gaps", "missing_response_items", path, recovered[0]["origin"]["line"], thread,
                       recovered=True, fallback_record_ids=[record["record_id"] for record in recovered])

    # Forks can rewrite timestamps while retaining original message IDs. Tool
    # calls/results without message IDs require the full call/kind/time key.
    # Never deduplicate across threads by text, or discard conflicting content.
    unique, identities = [], defaultdict(list)
    for record in sorted(result["records"], key=lambda r: (bool(r.get("fallback")), _time(r["timestamp"]), r["thread_id"], r["origin"]["line"])):
        identity = None
        if record.get("message_id"):
            identity = ("message", record["message_id"])
        elif record.get("call_id"):
            identity = ("call", record["call_id"], record["kind"], _time(record["timestamp"]))
        canonical = next((other for other in identities[identity]
                          if other["thread_id"] != record["thread_id"] and other["role"] == record["role"]
                          and other["kind"] == record["kind"] and other["text"] == record["text"]), None) if identity else None
        if canonical:
            canonical.setdefault("duplicate_origins", []).append({**record["origin"], "thread_id": record["thread_id"],
                "parent_thread_id": record["parent_thread_id"], "timestamp": record["timestamp"],
                "record_id": record["record_id"], "background": bool(record.get("background")),
                "fallback": bool(record.get("fallback"))})
        else:
            if identity and identities[identity] and any(other["text"] != record["text"] or other["role"] != record["role"] for other in identities[identity]):
                diagnostic("context_gaps", "record_identity_conflict", record["origin"]["file"], record["origin"]["line"], record["thread_id"])
            unique.append(record)
            if identity:
                identities[identity].append(record)
    result["records"] = unique
    result["records"].sort(key=lambda record: (_time(record["timestamp"]), record["thread_id"], record["origin"]["line"]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", required=True, help="Inline JSON source configuration")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--exclude-thread", action="append", default=[])
    parser.add_argument("--include-thread", action="append", default=[],
                        help="Read only this thread ID; repeat to allow several. Does not include descendants.")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.source_json)
        if not isinstance(config, dict):
            raise ValueError("source must be an object")
        result = read_records(config, args.start, args.end, args.exclude_thread, args.include_thread)
    except ValueError:
        result = {"records": [], "context_gaps": [], "failures": [{"code": "invalid_source_json"}]}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
