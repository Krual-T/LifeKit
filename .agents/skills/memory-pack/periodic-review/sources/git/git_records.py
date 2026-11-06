"""Read local Git evidence with the standard library; also runs as python -.

The caller executes this script on source.host (SSH transport is not provided
here). git.repo_root defaults to project_root and must resolve to that exact
repository root. git.timeout_seconds is the per-command timeout (default 60).
No fetch, checkout, temporary file, object write, or repository dependency is
needed. scope is private acquisition metadata: keep it in ignored inputs, not
in published report prose. Complete means only the frozen local reachability
scope, never all work or commits by a particular person.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


# Kept identical to codex_records._redact so stdin execution has no local import.
_SECRET_KEY = r"(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|passwd|credential)[\w-]*|token|cookie|authorization)"
_ASSIGNMENT = re.compile(
    r'''(?i)(["']?\b''' + _SECRET_KEY + r'''["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)'''
)
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _redact(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)", "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?im)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+", r"\1: [REDACTED]", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = _ASSIGNMENT.sub(lambda m: m[1] + '"[REDACTED]"', text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16})\b", "[REDACTED]", text)
    text = re.sub(r"(\w+://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    return text


def _safe(value):
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    return value


def _time(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone required")
    return result


class _GitError(Exception):
    def __init__(self, code):
        self.code = code


class _Git:
    def __init__(self, root, timeout):
        self.root, self.timeout = root, timeout
        self.git_dir = None
        # Do not inherit GIT_DIR, index/alternate-object overrides, config
        # injection, tracing to files, or execution hooks from the SSH session.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update({
            "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "", "GIT_PAGER": "cat", "LC_ALL": "C",
        })

    def run(self, *args, data=None, allowed=(0,), attr_source=None):
        env = dict(self.env)
        object_only = ["--git-dir=" + self.git_dir, "--bare"] if self.git_dir else []
        # Unlike an unknown environment variable, an unsupported CLI option
        # fails explicitly instead of silently applying HEAD/worktree attrs.
        attributes = ["--attr-source=" + attr_source] if attr_source else []
        command = ["git", "--no-pager", "--no-replace-objects", *object_only, *attributes,
                   "-c", "core.hooksPath=" + os.devnull,
                   "-c", "core.fsmonitor=false", "-c", "core.attributesFile=" + os.devnull,
                   "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                   "-c", "protocol.allow=never", "-c", "diff.ignoreSubmodules=none",
                   *args]
        try:
            result = subprocess.run(command, cwd=self.git_dir or self.root, env=env, input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise _GitError("git_timeout") from None
        except OSError:
            raise _GitError("git_unavailable") from None
        if result.returncode not in allowed:
            # Neither stderr nor the command arguments are safe diagnostics.
            raise _GitError("git_command_failed")
        return result


def _identity(raw, encoding):
    match = re.fullmatch(rb"(.*) <([^<>]*)> (-?\d+) ([+-])(\d{2})(\d{2})", raw)
    if not match or int(match[6]) > 59:
        raise ValueError("invalid identity")
    offset = timedelta(hours=int(match[5]), minutes=int(match[6]))
    if match[4] == b"-":
        offset = -offset
    zone = timezone(offset)
    stamp = datetime.fromtimestamp(int(match[3]), zone)
    return match[1].decode(encoding), match[2].decode(encoding), stamp.isoformat()


def _commit(raw):
    header, separator, body = raw.partition(b"\n\n")
    if not separator:
        raise ValueError("invalid commit")
    fields = {}
    for line in header.splitlines():
        if line.startswith(b" "):  # continuation of gpgsig/mergetag
            continue
        key, _, value = line.partition(b" ")
        fields.setdefault(key, []).append(value)
    encoding = fields.get(b"encoding", [b"utf-8"])[0].decode("ascii")
    parents = [item.decode("ascii") for item in fields.get(b"parent", [])]
    tree = fields[b"tree"][0].decode("ascii")
    if not all(_OID.fullmatch(oid) for oid in [tree, *parents]):
        raise ValueError("invalid object id")
    author_name, author_email, author_time = _identity(fields[b"author"][0], encoding)
    committer_name, committer_email, committer_time = _identity(fields[b"committer"][0], encoding)
    return {"parents": parents, "tree": tree, "author_name": author_name,
            "author_email": author_email, "author_time": author_time,
            "committer_name": committer_name, "committer_email": committer_email,
            "committer_time": committer_time, "encoding": encoding}, body.decode(encoding)


def _batch_objects(output, requested):
    """Parse sized cat-file output; never split commit bodies on delimiters."""
    position = 0
    for oid in requested:
        stop = output.find(b"\n", position)
        if stop < 0:
            raise ValueError("incomplete batch")
        header = output[position:stop].decode("ascii").split()
        position = stop + 1
        if header == [oid, "missing"]:
            yield oid, None
            continue
        if len(header) != 3 or header[:2] != [oid, "commit"]:
            raise ValueError("invalid batch object")
        size = int(header[2])
        if size < 0 or output[position + size:position + size + 1] != b"\n":
            raise ValueError("incomplete batch object")
        yield oid, output[position:position + size]
        position += size + 1
    if position != len(output):
        raise ValueError("trailing batch output")


def read_git_records(config, start, end):
    """Read all authors in [start, end); failures/gaps always mean partial.

    git may be omitted, true, or an object with repo_root/timeout_seconds.
    An explicit false or enabled:false returns a disabled (not complete) scope.
    A failed patch retains the commit metadata with patch_complete:false.
    """
    scope = {"observed_at": datetime.now(timezone.utc).isoformat(),
             "frozen_refs": [], "time_basis": "committer_time",
             "limitations": [
                 "Only frozen local refs/heads, refs/remotes and registered worktree HEAD reachability; no fetch.",
                 "Tags, stash, reflog, unreachable commits, index and working tree are excluded.",
                 "All authors are included; identities do not establish user ownership or effort.",
                 "Merge patches compare only the first parent, not independent original work.",
                 "Binary payloads are omitted; textual patches and metadata are credential-redacted.",
                 "Ref reads are sequential, not an atomic repository snapshot; remote refs may be stale.",
                 "Repository attributes may affect binary classification; external drivers never run.",
             ], "complete": False, "status": "partial"}
    result = {"records": [], "failures": [], "context_gaps": [], "scope": scope}

    def issue(bucket, code, operation, oid=None):
        item = {"code": code, "operation": operation}
        if oid:
            item["commit"] = oid
        result[bucket].append(item)

    try:
        if not isinstance(config, dict):
            raise ValueError("invalid source")
        source = config["id"]
        if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", source):
            raise ValueError("invalid source id")
        start, end = _time(start), _time(end)
        if start >= end:
            raise ValueError("invalid window")
        settings = config.get("git", {})
        if settings is False or (isinstance(settings, dict) and settings.get("enabled") is False):
            scope["status"] = "disabled"
            return result
        if settings is True:
            settings = {}
        if not isinstance(settings, dict):
            raise ValueError("invalid git settings")
        project = Path(config["project_root"])
        root = Path(settings.get("repo_root", project))
        if not project.is_absolute() or not root.is_absolute() or root.resolve() != project.resolve():
            raise ValueError("repo root must match project root")
        root = root.resolve(strict=True)
        timeout = float(settings.get("timeout_seconds", 60))
        if not math.isfinite(timeout) or timeout <= 0 or not root.is_dir():
            raise ValueError("invalid git settings")
        scope.update({"source_id": source, "host": config.get("host", "local"),
                      "project_root": str(root), "start": start.isoformat(), "end": end.isoformat()})
    except (KeyError, TypeError, ValueError, OSError, AttributeError, OverflowError):
        issue("failures", "invalid_git_config_or_window", "configuration")
        return _safe(result)

    git = _Git(root, timeout)
    try:
        bare = git.run("rev-parse", "--is-bare-repository").stdout.strip() == b"true"
        location = git.run("rev-parse", "--absolute-git-dir" if bare else "--show-toplevel").stdout.decode().rstrip("\n")
        if Path(location).resolve() != root:
            issue("failures", "repository_root_mismatch", "repository")
            return _safe(result)
        scope["bare"] = bare
        # Even diff-tree may reuse a matching worktree file for a missing
        # blob. Disable the worktree after validating the exact source root.
        git.git_dir = git.run("rev-parse", "--absolute-git-dir").stdout.decode().rstrip("\n")
        shallow = git.run("rev-parse", "--is-shallow-repository").stdout.strip() == b"true"
        scope["shallow"] = shallow
        if shallow:
            issue("context_gaps", "shallow_repository", "reachability")
    except (_GitError, UnicodeError) as error:
        issue("failures", getattr(error, "code", "invalid_git_output"), "repository")
        return _safe(result)

    refs = []
    try:
        raw_refs = git.run("for-each-ref", "--format=%(refname)%00%(objectname)", "refs/heads/", "refs/remotes/").stdout
        for line in raw_refs.decode("utf-8").splitlines():
            ref, oid = line.split("\0")
            if not _OID.fullmatch(oid):
                raise ValueError("invalid ref oid")
            refs.append({"ref": ref, "oid": oid})
    except (_GitError, ValueError) as error:
        issue("failures", getattr(error, "code", "invalid_git_output"), "freeze_refs")
    try:
        head = git.run("rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1))
        if head.returncode == 0:
            oid = head.stdout.decode("ascii").strip()
            if not _OID.fullmatch(oid):
                raise ValueError("invalid HEAD")
            refs.append({"ref": "HEAD", "oid": oid})
        else:
            symbolic = git.run("symbolic-ref", "--quiet", "HEAD").stdout.decode("utf-8").strip()
            exists = git.run("show-ref", "--verify", "--quiet", symbolic, allowed=(0, 1))
            if exists.returncode != 1:
                raise ValueError("unresolvable HEAD")
            scope["unborn_head"] = True
    except (_GitError, ValueError) as error:
        issue("failures", getattr(error, "code", "invalid_git_output"), "freeze_head")
    try:
        worktrees = git.run("worktree", "list", "--porcelain", "-z").stdout.decode("utf-8")
        for entry in worktrees.split("\0\0"):
            fields = dict(field.split(" ", 1) for field in entry.split("\0") if " " in field)
            path, oid = fields.get("worktree"), fields.get("HEAD")
            if oid is None or Path(path).resolve() == root:
                continue
            if not _OID.fullmatch(oid):
                raise ValueError("invalid worktree HEAD")
            if set(oid) != {"0"}:
                refs.append({"ref": "worktree:" + path + ":HEAD", "oid": oid})
    except (_GitError, UnicodeError, TypeError, ValueError) as error:
        issue("failures", getattr(error, "code", "invalid_git_output"), "freeze_worktree_heads")
    scope["frozen_refs"] = refs
    scope["frozen_at"] = datetime.now(timezone.utc).isoformat()
    tips = sorted({entry["oid"] for entry in refs})
    pending = list(tips)
    if tips:
        try:
            # No --since/--until, ordering cutoff, max-count, or author filter.
            output = git.run("rev-list", "--stdin", data=("\n".join(tips) + "\n").encode()).stdout
            enumerated = output.decode("ascii").splitlines()
            if not all(_OID.fullmatch(oid) for oid in enumerated):
                raise ValueError("invalid rev-list")
            pending = list(dict.fromkeys([*enumerated, *tips]))
        except (_GitError, ValueError) as error:
            issue("failures", getattr(error, "code", "invalid_git_output"), "enumerate_commits")
            # Raw-parent traversal below still salvages unaffected commits.

    seen, selected = set(), []
    while pending:
        batch = list(dict.fromkeys(oid for oid in pending[:256] if oid not in seen))
        del pending[:256]
        if not batch:
            continue
        seen.update(batch)
        objects = []
        try:
            output = git.run("cat-file", "--batch", data=("\n".join(batch) + "\n").encode()).stdout
            # Keep already parsed objects even if the trailing output is bad.
            for item in _batch_objects(output, batch):
                objects.append(item)
        except (_GitError, ValueError) as error:
            issue("failures", getattr(error, "code", "invalid_git_output"), "read_commits")
            # A corrupt object can terminate cat-file for the entire batch.
            # Retry only unread objects individually, retaining other commits.
            for oid in batch[len(objects):]:
                try:
                    objects.append((oid, git.run("cat-file", "commit", oid).stdout))
                except _GitError as read_error:
                    issue("failures", read_error.code, "read_commit", oid)
        for oid, raw in objects:
            if raw is None:
                issue("failures", "missing_commit_object", "read_commit", oid)
                continue
            # Traverse actual stored parents, including shallow boundaries;
            # rev-list's shallow/graft interpretation cannot hide a gap.
            header = raw.partition(b"\n\n")[0]
            for line in header.splitlines():
                if line.startswith(b"parent "):
                    parent = line[7:].decode("ascii", errors="replace")
                    if _OID.fullmatch(parent) and parent not in seen:
                        pending.append(parent)
            try:
                metadata, message = _commit(raw)
                if start <= _time(metadata["committer_time"]) < end:
                    selected.append((oid, metadata, message))
            except (ValueError, KeyError, LookupError, OverflowError, OSError):
                issue("failures", "invalid_commit_object", "parse_commit", oid)
    scope["visited_commit_count"] = len(seen)

    for oid, metadata, message in selected:
        parents = metadata["parents"]
        baseline = {"kind": "first_parent" if parents else "empty_tree",
                    "commit": parents[0] if parents else None}
        metadata.update({"commit": oid, "baseline": baseline, "is_merge": len(parents) > 1,
                         "patch_complete": False, "binary_payloads_included": False})
        note = ("First-parent merge diff; not independent original work."
                if len(parents) > 1 else "Diff against first parent." if parents else "Root commit: diff against empty tree.")
        text = message + "\n\n" + note
        try:
            revisions = [parents[0], oid] if parents else ["--root", oid]
            # --raw/--numstat/--summary describe modes, rename/delete, binary
            # changes. No --binary: Git emits a marker, never binary payloads.
            patch = git.run("diff-tree", "--no-commit-id", "-r", "-M", "--no-ext-diff",
                            "--no-textconv", "--no-color", "--no-relative", "--ignore-submodules=none",
                            "--submodule=short", "--src-prefix=a/", "--dst-prefix=b/",
                            "--full-index", "--raw", "--numstat", "--summary", "--patch",
                            "--unified=3", *revisions, "--", attr_source=oid).stdout
            # Do not silently replace undecodable text: retain the commit and
            # explicitly report inability to produce its full textual patch.
            text += "\n\nFile changes and full text patch (binary bodies excluded):\n" + patch.decode("utf-8")
            metadata["patch_complete"] = True
        except (_GitError, UnicodeError) as error:
            issue("failures", getattr(error, "code", "invalid_patch_encoding"), "read_patch", oid)
            text += "\n\nPatch unavailable; see acquisition failures."
        result["records"].append({
            "record_id": source + ":git:" + oid, "thread_id": "git:" + source,
            "parent_thread_id": None, "timestamp": metadata["committer_time"],
            "role": "tool", "kind": "git_commit", "call_id": None, "text": text,
            "origin": {"source_id": source, "file": "git/" + oid, "line": 1, "commit": oid},
            "git": metadata,
        })
    result["records"].sort(key=lambda record: (_time(record["timestamp"]), record["git"]["commit"]))
    scope["complete"] = not result["failures"] and not result["context_gaps"]
    scope["status"] = "complete" if scope["complete"] else "partial"
    return _safe(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", required=True, help="Inline JSON source configuration")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.source_json)
    except ValueError:
        config = None
    result = read_git_records(config, args.start, args.end)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["scope"]["complete"] or result["scope"]["status"] == "disabled" else 1


if __name__ == "__main__":
    sys.exit(main())
