"""Real-repository tests; all mutations are confined to TemporaryDirectory."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "sources/git/git_records.py"
SPEC = importlib.util.spec_from_file_location("git_records", SCRIPT)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
START = "2026-09-05T08:05:00+08:00"
END = "2026-09-06T08:05:00+08:00"
MID = "2026-09-05T12:00:00+08:00"
OLD = "2020-01-01T00:00:00+00:00"


class GitRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "GIT_AUTHOR_NAME": "Other Author", "GIT_AUTHOR_EMAIL": "other@example.test",
                         "GIT_COMMITTER_NAME": "Committer", "GIT_COMMITTER_EMAIL": "committer@example.test",
                         "GIT_AUTHOR_DATE": MID, "GIT_COMMITTER_DATE": MID})
        self.git("init", "--initial-branch=main")
        self.git("config", "commit.gpgsign", "false")
        self.config = {"id": "fixture", "host": "ssh-fixture", "project_root": str(self.repo), "git": {}}

    def git(self, *args, data=None, env=None, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.repo,
                                env={**self.env, **(env or {})}, input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.decode("utf-8").strip()

    def commit(self, message="change", files=None, stamp=MID, author_stamp=None, author=None):
        for name, content in (files or {}).items():
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                target.unlink()
            elif isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content)
        self.git("add", "--all")
        env = {"GIT_AUTHOR_DATE": author_stamp or stamp, "GIT_COMMITTER_DATE": stamp}
        if author:
            env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = author
        self.git("commit", "--allow-empty", "-m", message, env=env)
        return self.git("rev-parse", "HEAD")

    def read(self, **kwargs):
        return reader.read_git_records(kwargs.get("config", self.config), kwargs.get("start", START), kwargs.get("end", END))

    def records(self):
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])
        self.assertTrue(result["scope"]["complete"])
        return {record["git"]["commit"]: record for record in result["records"]}

    def test_root_record_contract_and_full_patch(self):
        content = "".join("unique-line-%d\n" % n for n in range(2500))
        oid = self.commit("root subject\n\nfull body", {"file.txt": content})
        record = self.records()[oid]
        self.assertEqual(record["record_id"], "fixture:git:" + oid)
        self.assertEqual(record["thread_id"], "git:fixture")
        self.assertIsNone(record["parent_thread_id"])
        self.assertIsNone(record["call_id"])
        self.assertEqual((record["role"], record["kind"]), ("tool", "git_commit"))
        self.assertEqual(record["timestamp"], MID)
        self.assertEqual(record["origin"], {"source_id": "fixture", "file": "git/" + oid, "line": 1, "commit": oid})
        self.assertEqual(record["git"]["parents"], [])
        self.assertEqual(record["git"]["baseline"], {"kind": "empty_tree", "commit": None})
        self.assertTrue(record["git"]["patch_complete"])
        self.assertIn("full body", record["text"])
        self.assertIn("new file mode", record["text"])
        for line in content.splitlines():
            self.assertIn("+" + line + "\n", record["text"])

    def test_merge_is_explicit_first_parent_diff(self):
        root = self.commit("root", {"base.txt": "base\n"})
        self.git("switch", "-c", "side")
        side = self.commit("side", {"side.txt": "side-content\n"})
        self.git("switch", "main")
        main = self.commit("main", {"main.txt": "main-content\n"})
        self.git("merge", "--no-ff", "side", "-m", "merge side")
        merge = self.git("rev-parse", "HEAD")
        records = self.records()
        self.assertEqual(set(records), {root, side, main, merge})
        record = records[merge]
        self.assertEqual(record["git"]["parents"], [main, side])
        self.assertEqual(record["git"]["baseline"], {"kind": "first_parent", "commit": main})
        self.assertTrue(record["git"]["is_merge"])
        self.assertIn("not independent original work", record["text"])
        self.assertIn("+side-content", record["text"])
        self.assertNotIn("+main-content", record["text"])

    def test_rename_delete_and_binary_without_body(self):
        self.commit("root", {"old.txt": "rename-me\n", "gone.txt": "remove-me\n"})
        self.git("mv", "old.txt", "new.txt")
        oid = self.commit("rename delete binary", {"gone.txt": None, "asset.bin": b"\0BINARY-PRIVATE-BODY\xff"})
        text = self.records()[oid]["text"]
        self.assertIn("rename from old.txt", text)
        self.assertIn("rename to new.txt", text)
        self.assertIn("deleted file mode", text)
        self.assertIn("Binary files", text)
        self.assertIn("asset.bin", text)
        self.assertNotIn("BINARY-PRIVATE-BODY", text)
        self.assertNotIn("GIT binary patch", text)

    def test_exact_half_open_window_and_timezone(self):
        before = self.commit("before", stamp="2026-09-05T00:04:59+00:00")
        lower = self.commit("lower", stamp="2026-09-04T17:05:00-07:00")
        upper_inside = self.commit("last", stamp="2026-09-06T00:04:59+00:00")
        upper = self.commit("upper", stamp="2026-09-06T00:05:00+00:00")
        records = self.records()
        self.assertEqual(set(records), {lower, upper_inside})
        self.assertNotIn(before, records)
        self.assertNotIn(upper, records)
        self.assertEqual(records[lower]["timestamp"], "2026-09-04T17:05:00-07:00")
        fractional = self.read(start="2026-09-05T00:05:00.000001+00:00")
        self.assertEqual([r["git"]["commit"] for r in fractional["records"]], [upper_inside])

    def test_old_author_new_committer_and_all_authors(self):
        first = self.commit("old authored", author_stamp=OLD)
        second = self.commit("different author", author=("Unrelated Person", "unrelated@example.test"))
        records = self.records()
        self.assertEqual(set(records), {first, second})
        self.assertEqual(records[first]["git"]["author_time"], OLD)
        self.assertEqual(records[first]["git"]["committer_time"], MID)
        self.assertEqual(records[second]["git"]["author_name"], "Unrelated Person")
        self.assertNotIn("user_owned", records[second]["git"])

    def test_nonmonotonic_ancestor_is_not_pruned(self):
        ancestor = self.commit("in window ancestor", {"first.txt": "first\n"})
        self.commit("out of window old child", stamp=OLD)
        self.commit("another old tip", stamp=OLD)
        self.assertEqual(set(self.records()), {ancestor})

    def test_duplicate_refs_remote_branch_and_detached_head(self):
        root = self.commit("root")
        self.git("branch", "alias")
        self.git("update-ref", "refs/remotes/origin/main", root)
        self.git("switch", "--detach")
        detached = self.commit("detached")
        result = self.read()
        self.assertEqual({r["git"]["commit"] for r in result["records"]}, {root, detached})
        refs = {r["ref"]: r["oid"] for r in result["scope"]["frozen_refs"]}
        self.assertEqual(refs, {"HEAD": detached, "refs/heads/main": root,
                               "refs/heads/alias": root, "refs/remotes/origin/main": root})
        self.assertNotIn("refs/remotes/", json.dumps(result["records"]))
        self.assertIsNotNone(reader._time(result["scope"]["observed_at"]).tzinfo)

    def test_remote_only_commit_is_included(self):
        self.commit("root", stamp=OLD)
        tree = self.git("rev-parse", "HEAD^{tree}")
        remote = self.git("commit-tree", tree, data=b"remote-only\n")
        self.git("update-ref", "refs/remotes/origin/other", remote)
        self.assertEqual(set(self.records()), {remote})

    def test_worktree_listing_failure_marks_collection_partial(self):
        self.commit("still readable")
        original = reader._Git.run

        def fail_listing(instance, *args, **kwargs):
            if args[0] == "worktree":
                raise reader._GitError("git_command_failed")
            return original(instance, *args, **kwargs)

        with patch.object(reader._Git, "run", fail_listing):
            result = self.read()
        self.assertFalse(result["scope"]["complete"])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["failures"], [
            {"code": "git_command_failed", "operation": "freeze_worktree_heads"}])

    def test_all_worktree_heads_are_frozen_and_deduplicated(self):
        root = self.commit("root", {"base.txt": "base\n"})
        branched = self.base / "branch worktree"
        detached = self.base / "detached\nworktree"
        self.git("worktree", "add", "-b", "feature", str(branched))
        self.git("commit", "--allow-empty", "-m", "branch change", cwd=branched)
        branch_oid = self.git("rev-parse", "HEAD", cwd=branched)
        self.git("worktree", "add", "--detach", str(detached), root)
        self.git("commit", "--allow-empty", "-m", "detached change", cwd=detached)
        detached_oid = self.git("rev-parse", "HEAD", cwd=detached)
        (detached / "uncommitted.txt").write_text("private uncommitted content")
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["scope"]["complete"])
        self.assertEqual(len(result["records"]), 3)
        self.assertEqual({r["git"]["commit"] for r in result["records"]},
                         {root, branch_oid, detached_oid})
        refs = {r["ref"]: r["oid"] for r in result["scope"]["frozen_refs"]}
        self.assertEqual(refs["worktree:" + str(detached) + ":HEAD"], detached_oid)
        self.assertNotIn("private uncommitted content", json.dumps(result["records"]))

    def test_tags_stash_reflog_replace_and_unreachable_not_in_scope(self):
        root = self.commit("real root", {"real.txt": "real\n"})
        tree = self.git("rev-parse", "HEAD^{tree}")
        for ref in ("refs/tags/only-tag", "refs/stash", "refs/heads/temporary"):
            hidden = self.git("commit-tree", tree, data=(ref + "-hidden\n").encode())
            self.git("update-ref", ref, hidden)
        self.git("update-ref", "-d", "refs/heads/temporary")
        replacement = self.git("commit-tree", tree, data=b"replacement message\n")
        self.git("replace", root, replacement)
        records = self.records()
        self.assertEqual(set(records), {root})
        self.assertIn("real root", records[root]["text"])
        self.assertNotIn("replacement message", records[root]["text"])

    def test_dirty_index_worktree_and_attributes_are_excluded(self):
        oid = self.commit("tracked", {"file.txt": "committed-content\n", ".gitattributes": "*.txt diff\n"})
        (self.repo / "file.txt").write_text("staged-private\n")
        self.git("add", "file.txt")
        (self.repo / "file.txt").write_text("unstaged-private\n")
        (self.repo / "untracked.txt").write_text("untracked-private\n")
        (self.repo / ".gitattributes").write_text("*.txt binary\n")
        record = self.records()[oid]
        self.assertIn("+committed-content", record["text"])
        for content in ("staged-private", "unstaged-private", "untracked-private"):
            self.assertNotIn(content, json.dumps(record))

    def test_committed_binary_attributes_not_worktree_attributes(self):
        oid = self.commit("binary attribute", {"file.txt": "classified-binary-content\n", ".gitattributes": "*.txt binary\n"})
        self.commit("HEAD attributes differ", {".gitattributes": "*.txt diff\n"})
        (self.repo / ".gitattributes").write_text("*.txt -diff\n")
        record = self.records()[oid]
        self.assertIn("Binary files", record["text"])
        self.assertNotIn("+classified-binary-content", record["text"])

    def test_no_diff_textconv_hooks_fsmonitor_trace_or_writes(self):
        marker = self.base / "executed"
        executable = self.base / "driver"
        executable.write_text("#!/bin/sh\nprintf executed > '" + str(marker) + "'\nexit 1\n")
        executable.chmod(0o700)
        self.commit("attributes", {"file.txt": "textual-evidence\n", ".gitattributes": "*.txt diff=trap\n"})
        self.git("config", "diff.external", str(executable))
        self.git("config", "diff.trap.command", str(executable))
        self.git("config", "diff.trap.textconv", str(executable))
        self.git("config", "diff.trap.cachetextconv", "true")
        self.git("config", "core.fsmonitor", str(executable))
        self.git("config", "core.hooksPath", str(executable))
        before = {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        trace = self.base / "trace"
        with patch.dict(os.environ, {"GIT_EXTERNAL_DIFF": str(executable), "GIT_TRACE": str(trace),
                                     "GIT_DIR": str(self.base / "not-a-repo"), "GIT_CONFIG_COUNT": "1",
                                     "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": str(executable)}):
            records = self.records()
        after = {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(marker.exists())
        self.assertFalse(trace.exists())
        self.assertIn("+textual-evidence", next(iter(records.values()))["text"])
        env = reader._Git(self.repo, 1).env
        for key in ("GIT_OPTIONAL_LOCKS", "GIT_NO_LAZY_FETCH", "GIT_NO_REPLACE_OBJECTS"):
            self.assertEqual(env[key], "0" if key == "GIT_OPTIONAL_LOCKS" else "1")
        self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "")

    def test_reject_parent_repository_and_override(self):
        self.commit()
        subdirectory = self.repo / "subdir"
        subdirectory.mkdir()
        result = self.read(config={**self.config, "project_root": str(subdirectory)})
        self.assertEqual(result["records"], [])
        self.assertEqual(result["failures"][0]["code"], "repository_root_mismatch")
        result = self.read(config={**self.config, "git": {"repo_root": str(self.base)}})
        self.assertFalse(result["scope"]["complete"])
        self.assertTrue(result["failures"])

    def test_empty_repository_is_complete(self):
        result = self.read()
        self.assertEqual(result["records"], [])
        self.assertTrue(result["scope"]["complete"])
        self.assertTrue(result["scope"]["unborn_head"])

    def test_shallow_clone_is_partial_but_tip_retained(self):
        self.commit("parent", {"file.txt": "parent\n"}, stamp=OLD)
        tip = self.commit("tip", {"file.txt": "tip\n"})
        clone = self.base / "shallow"
        self.git("clone", "--depth=1", self.repo.as_uri(), str(clone))
        result = self.read(config={**self.config, "project_root": str(clone)})
        self.assertFalse(result["scope"]["complete"])
        self.assertIn("shallow_repository", {item["code"] for item in result["context_gaps"]})
        self.assertEqual([r["git"]["commit"] for r in result["records"]], [tip])
        self.assertFalse(result["records"][0]["git"]["patch_complete"])
        self.assertTrue(result["failures"])

    def test_missing_blob_retains_other_commits(self):
        first = self.commit("first", {"first.txt": "first\n"})
        damaged = self.commit("damaged", {"second.txt": "second\n"})
        blob = self.git("rev-parse", damaged + ":second.txt")
        (self.repo / ".git/objects" / blob[:2] / blob[2:]).unlink()
        result = self.read()
        records = {r["git"]["commit"]: r for r in result["records"]}
        self.assertEqual(set(records), {first, damaged})
        self.assertTrue(records[first]["git"]["patch_complete"])
        self.assertFalse(records[damaged]["git"]["patch_complete"])
        self.assertFalse(result["scope"]["complete"])

    def test_missing_parent_does_not_lose_good_branch_or_child(self):
        root = self.commit("root")
        self.git("switch", "-c", "broken")
        missing = self.commit("missing parent")
        child = self.commit("preserved child")
        self.git("switch", "main")
        good = self.commit("good branch")
        (self.repo / ".git/objects" / missing[:2] / missing[2:]).unlink()
        result = self.read()
        self.assertEqual({r["git"]["commit"] for r in result["records"]}, {root, child, good})
        self.assertFalse(result["scope"]["complete"])
        self.assertTrue(result["failures"])

    def test_patch_timeout_is_explicit_and_preserves_metadata(self):
        first = self.commit("first")
        second = self.commit("second")
        real_run = subprocess.run

        def timeout_one(command, **kwargs):
            if "diff-tree" in command and second in command:
                raise subprocess.TimeoutExpired(command, 1, stderr=b"password=DO-NOT-EXPOSE")
            return real_run(command, **kwargs)

        with patch.object(reader.subprocess, "run", side_effect=timeout_one):
            result = self.read()
        records = {r["git"]["commit"]: r for r in result["records"]}
        self.assertEqual(set(records), {first, second})
        self.assertTrue(records[first]["git"]["patch_complete"])
        self.assertFalse(records[second]["git"]["patch_complete"])
        self.assertEqual(result["failures"][0]["code"], "git_timeout")
        self.assertNotIn("DO-NOT-EXPOSE", json.dumps(result))

    def test_failed_enumeration_falls_back_to_raw_parent_graph(self):
        first = self.commit("first")
        second = self.commit("second")
        original = reader._Git.run

        def fail_enumeration(instance, *args, **kwargs):
            if args[0] == "rev-list":
                raise reader._GitError("git_command_failed")
            return original(instance, *args, **kwargs)

        with patch.object(reader._Git, "run", fail_enumeration):
            result = self.read()
        self.assertEqual({r["git"]["commit"] for r in result["records"]}, {first, second})
        self.assertFalse(result["scope"]["complete"])

    def test_refs_are_frozen_before_enumeration(self):
        first = self.commit("frozen")
        original = reader._Git.run
        created = []

        def advance_branch(instance, *args, **kwargs):
            if args[0] == "rev-list" and not created:
                created.append(self.commit("later ref movement"))
            return original(instance, *args, **kwargs)

        with patch.object(reader._Git, "run", advance_branch):
            result = self.read()
        self.assertEqual([r["git"]["commit"] for r in result["records"]], [first])
        self.assertEqual({r["oid"] for r in result["scope"]["frozen_refs"]}, {first})
        self.assertTrue(created)

    def test_credentials_redacted_everywhere(self):
        secret = ('api_key="supersecret" password=hunter2\nAuthorization: Bearer abcdef\n'
                  'Cookie: sid=unsafe; x=y\nhttps://bob:pass@example.test\nsk-abcdefghijk\n'
                  '-----BEGIN PRIVATE KEY-----\nprivatebytes\n-----END PRIVATE KEY-----\n')
        self.commit(secret, {"secret.txt": secret}, author=("password=authorsecret", "someone@example.test"))
        rendered = json.dumps(self.read())
        for value in ("supersecret", "hunter2", "abcdef", "unsafe", "bob:pass", "sk-abcdefghijk", "privatebytes", "authorsecret"):
            self.assertNotIn(value, rendered)
        self.assertIn("REDACTED", rendered)

    def test_command_stderr_is_never_returned(self):
        with patch.object(reader.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["git"], 128, stdout=b"", stderr=b"https://bob:credential@example.test private diagnostic")):
            result = self.read()
        self.assertTrue(result["failures"])
        self.assertNotIn("credential", json.dumps(result["failures"]))
        self.assertNotIn("private diagnostic", json.dumps(result))

    def test_invalid_windows_configs_and_disabled(self):
        for start, end in (("2026-09-05", END), (END, START), (START, START), (None, END)):
            with self.subTest(start=start, end=end):
                result = self.read(start=start, end=end)
                self.assertTrue(result["failures"])
                self.assertFalse(result["scope"]["complete"])
        for config in (None, [], {}, {**self.config, "git": {"timeout_seconds": float("nan")}}):
            self.assertTrue(self.read(config=config)["failures"])
        disabled = self.read(config={**self.config, "git": False})
        self.assertEqual(disabled["scope"]["status"], "disabled")
        self.assertFalse(disabled["scope"]["complete"])

    def test_bare_repository_and_linked_worktree(self):
        oid = self.commit("content", {"file.txt": "text\n"})
        bare = self.base / "bare.git"
        self.git("clone", "--bare", str(self.repo), str(bare))
        worktree = self.base / "linked"
        self.git("worktree", "add", "--detach", str(worktree))
        for root in (bare, worktree):
            with self.subTest(root=root):
                result = self.read(config={**self.config, "project_root": str(root)})
                self.assertTrue(result["scope"]["complete"], result["failures"])
                self.assertEqual([r["git"]["commit"] for r in result["records"]], [oid])

    def test_cli_file_and_stdin_are_independent(self):
        oid = self.commit("cli")
        args = ["--source-json", json.dumps(self.config), "--start", START, "--end", END]
        for entry, data in ((str(SCRIPT), None), ("-", SCRIPT.read_bytes())):
            with self.subTest(entry=entry):
                completed = subprocess.run([sys.executable, "-I", "-B", entry, *args], input=data,
                                           cwd=self.base, capture_output=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stderr, b"")
                result = json.loads(completed.stdout)
                self.assertEqual([r["git"]["commit"] for r in result["records"]], [oid])
        invalid = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--source-json", "{",
                                  "--start", START, "--end", END], capture_output=True)
        self.assertEqual(invalid.returncode, 1)
        self.assertTrue(json.loads(invalid.stdout)["failures"])
        self.assertEqual(invalid.stderr, b"")


if __name__ == "__main__":
    unittest.main()
