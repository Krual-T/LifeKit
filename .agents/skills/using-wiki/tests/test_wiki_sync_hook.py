from __future__ import annotations

import fcntl
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_wiki_index as fixtures


wiki_index = fixtures.wiki_index
HOOK = Path(__file__).parents[1] / "scripts/wiki_sync_hook.py"
SPEC = importlib.util.spec_from_file_location("wiki_sync_hook", HOOK)
assert SPEC and SPEC.loader
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


class WikiSyncTests(unittest.TestCase):
    make_project = fixtures.WikiIndexTests.make_project
    write_page = fixtures.WikiIndexTests.write_page
    set_cache = fixtures.WikiIndexTests.set_cache

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.make_project(self.root)
        self.page = self.write_page(self.root, "projects/topic.md")

    def ensure(self) -> dict:
        result = wiki_index.ensure(self.root)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["fresh"], result)
        return result

    def test_unchanged_navigation_and_database_keep_mtimes(self) -> None:
        first = self.ensure()
        self.assertTrue(first["navigation_changed"])
        self.assertTrue(first["retrieval_changed"])
        paths = [self.root / "AGENTS.md", *self.root.glob("wiki/**/index.md"), self.root / "wiki/.okf/index.sqlite3"]
        before = {path: path.stat().st_mtime_ns for path in paths}
        second = self.ensure()
        self.assertEqual(second["navigation_changed"], [])
        self.assertFalse(second["retrieval_changed"])
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in paths})

    def test_body_title_move_and_delete_reach_search_and_navigation(self) -> None:
        self.ensure()
        self.write_page(self.root, "projects/topic.md", title="Updated", body="Quasarneedle.\n")
        changed = self.ensure()
        self.assertIn("wiki/projects/index.md", changed["navigation_changed"])
        query = subprocess.run(
            ["wiki-retrieval", "query", "Quasarneedle", "--wiki-root", str(self.root / "wiki")],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(query.stdout)["results"][0]["path"], "projects/topic.md")
        moved = self.root / "wiki/other/moved.md"
        moved.parent.mkdir()
        self.page.rename(moved)
        self.ensure()
        self.assertIn("moved.md", (moved.parent / "index.md").read_text())
        self.assertNotIn("topic.md", (self.root / "wiki/projects/index.md").read_text())
        moved.unlink()
        self.ensure()
        self.assertNotIn("moved.md", (moved.parent / "index.md").read_text())

    def test_validation_failure_reports_partial_navigation_and_recovers(self) -> None:
        self.ensure()
        database = self.root / "wiki/.okf/index.sqlite3"
        before = database.read_bytes()
        self.write_page(self.root, "projects/topic.md", title="New title", extra={"generated": {"by": "test", "at": "2026-10-19"}})
        failed = wiki_index.ensure(self.root)
        self.assertFalse(failed["ok"], failed)
        self.assertEqual(failed["stage"], "retrieval")
        self.assertIn("wiki/projects/index.md", failed["navigation_changed"])
        self.assertEqual(database.read_bytes(), before)
        self.write_page(self.root, "projects/topic.md", title="New title")
        self.ensure()

    def test_planning_snapshot_precedes_reads_and_tracks_file_set(self) -> None:
        real_render = wiki_index.render_indexes

        def edit_during_plan(root):
            rendered = real_render(root)
            self.write_page(self.root, "projects/added.md")
            return rendered

        with mock.patch.object(wiki_index, "render_indexes", side_effect=edit_during_plan):
            plan = wiki_index.plan_sync(self.root)
        with self.assertRaises(wiki_index.InputsChanged):
            wiki_index.apply_plan(plan)
        self.assertFalse((self.root / "wiki/index.md").exists())

    def test_retry_once_after_concurrent_addition_and_fail_if_unstable(self) -> None:
        real_run = subprocess.run
        calls = 0

        def change_after_retrieval(*args, **kwargs):
            nonlocal calls
            result = real_run(*args, **kwargs)
            calls += 1
            if calls == 1:
                self.write_page(self.root, "projects/concurrent.md")
            return result

        with mock.patch.object(wiki_index.subprocess, "run", side_effect=change_after_retrieval):
            result = self.ensure()
        self.assertEqual(result["attempts"], 2)
        self.assertIn("concurrent.md", (self.root / "wiki/projects/index.md").read_text())

        def always_change(*args, **kwargs):
            result = real_run(*args, **kwargs)
            self.page.write_text(self.page.read_text() + "\nConcurrent edit.\n")
            return result

        with mock.patch.object(wiki_index.subprocess, "run", side_effect=always_change):
            result = wiki_index.ensure(self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "concurrency")
        self.assertEqual(result["attempts"], 2)

    def test_fresh_false_keeps_published_database_and_reports_navigation(self) -> None:
        real_run = subprocess.run

        def fresh_false(*args, **kwargs):
            result = real_run(*args, **kwargs)
            payload = json.loads(result.stdout)
            payload["fresh"] = False
            result.stdout = json.dumps(payload)
            return result

        with mock.patch.object(wiki_index.subprocess, "run", side_effect=fresh_false):
            result = wiki_index.ensure(self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["navigation_changed"])
        self.assertTrue((self.root / "wiki/.okf/index.sqlite3").is_file())
        self.assertIn("retained", result["error"])

    def test_rollback_preserves_other_writer_and_untouched_files(self) -> None:
        self.set_cache(self.root, [wiki_index.IndexEntry("projects/topic.md")])
        self.write_page(self.root, "projects/topic.md", title="Renamed")
        agents = self.root / "AGENTS.md"
        index = self.root / "wiki/index.md"
        real_write = wiki_index.atomic_write_text

        def fail_after_external_edit(path, text, mode=None):
            if path == index:
                agents.write_text(agents.read_text() + "\nAnother writer.\n")
                index.write_text("Other writer's index\n")
                raise OSError("injected write failure")
            real_write(path, text, mode)

        with mock.patch.object(wiki_index, "atomic_write_text", side_effect=fail_after_external_edit):
            with self.assertRaisesRegex(RuntimeError, "preserved"):
                wiki_index.sync(self.root)
        self.assertIn("Another writer.", agents.read_text())
        self.assertEqual(index.read_text(), "Other writer's index\n")

    def test_navigation_and_retrieval_lock_waits_are_bounded(self) -> None:
        self.ensure()
        for name, stage in [("navigation.lock", "lock"), ("build.lock", "retrieval")]:
            with self.subTest(name=name), (self.root / "wiki/.okf" / name).open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                started = time.monotonic()
                result = wiki_index.ensure(self.root, timeout=0.25)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["stage"], stage)
                self.assertLess(time.monotonic() - started, 2)

    def test_parallel_ensure_processes_and_separate_worktrees(self) -> None:
        command = [sys.executable, str(fixtures.SCRIPT.resolve()), "ensure", "--project-root", str(self.root)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            results.append(json.loads(stdout))
        self.assertEqual(sum(bool(result["navigation_changed"]) for result in results), 1)
        with tempfile.TemporaryDirectory() as other:
            other_root = Path(other)
            self.make_project(other_root)
            self.write_page(other_root, "unrelated.md")
            self.assertTrue(wiki_index.ensure(other_root)["ok"])
        self.assertNotIn("unrelated", (self.root / "wiki/index.md").read_text())

    def test_missing_retrieval_and_timeout_keep_navigation_feedback(self) -> None:
        for error in [FileNotFoundError("wiki-retrieval missing"), subprocess.TimeoutExpired("wiki-retrieval", 1)]:
            with self.subTest(error=type(error).__name__):
                self.write_page(self.root, "projects/topic.md", title=str(error))
                with mock.patch.object(wiki_index.subprocess, "run", side_effect=error):
                    result = wiki_index.ensure(self.root)
                self.assertFalse(result["ok"])
                self.assertEqual(result["stage"], "retrieval")
                self.assertIn("wiki/projects/index.md", result["navigation_changed"])

    def test_real_hook_process_syncs_and_reports_failure_without_blocking(self) -> None:
        scripts = self.root / ".agents/skills/using-wiki/scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(fixtures.SCRIPT, scripts / "wiki_index.py")
        shutil.copy2(HOOK, scripts / "wiki_sync_hook.py")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": "exit 1"}, "tool_response": {"exit_code": 1}}

        def invoke():
            result = subprocess.run([sys.executable, str(scripts / "wiki_sync_hook.py")], input=json.dumps(event), capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        first = json.loads(invoke())
        self.assertEqual(set(first), {"hookSpecificOutput"})
        self.assertIn("fresh=true", first["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(invoke(), "")
        self.write_page(self.root, "projects/topic.md", extra={"generated": {"by": "test", "at": "bad-date"}})
        error = json.loads(invoke())
        self.assertEqual(set(error), {"hookSpecificOutput"})
        self.assertIn("未完成", error["hookSpecificOutput"]["additionalContext"])
        explicit = subprocess.run([sys.executable, str(scripts / "wiki_index.py"), "ensure", "--project-root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(explicit.returncode, 1, explicit.stdout)
        self.write_page(self.root, "projects/topic.md")
        self.assertIn("fresh=true", json.loads(invoke())["hookSpecificOutput"]["additionalContext"])


class HookAdapterTests(unittest.TestCase):
    def event(self, tool="Bash"):
        return {"hook_event_name": "PostToolUse", "tool_name": tool, "cwd": str(hook.PROJECT_ROOT), "tool_response": {"exit_code": 1}}

    def call(self, result, tool="Bash", exit_code=0):
        root = subprocess.CompletedProcess([], 0, str(hook.PROJECT_ROOT), "")
        ensure = subprocess.CompletedProcess([], exit_code, json.dumps(result), "")
        with mock.patch.object(hook.subprocess, "run", side_effect=[root, ensure]) as run:
            output = hook.run_hook(self.event(tool))
            self.assertEqual(run.call_count, 2)
        return output

    def test_noop_is_silent_and_failed_tool_still_triggers_sync(self) -> None:
        self.assertIsNone(self.call({"ok": True, "fresh": True, "navigation_changed": [], "retrieval_changed": False}))
        output = self.call({"ok": True, "fresh": True, "navigation_changed": ["wiki/index.md"], "retrieval_changed": True})
        self.assertIn("wiki/index.md", output["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(set(output), {"hookSpecificOutput"})

    def test_apply_patch_feedback_includes_recent_and_failure_preserves_tool_result(self) -> None:
        output = self.call({"ok": False, "stage": "retrieval", "error": "bad page.md", "navigation_changed": ["AGENTS.md"], "recent": "New entry"}, "apply_patch", 1)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("bad page.md", context)
        self.assertIn("New entry", context)
        self.assertEqual(set(output), {"hookSpecificOutput"})

    def test_other_event_tool_and_repository_are_ignored(self) -> None:
        cases = [self.event("mcp__anything"), self.event() | {"hook_event_name": "Stop"}, self.event() | {"cwd": "/tmp"}]
        with mock.patch.object(hook.subprocess, "run") as run:
            for case in cases:
                self.assertIsNone(hook.run_hook(case))
            run.assert_not_called()
        nested_repo = subprocess.CompletedProcess([], 0, str(hook.PROJECT_ROOT / "projects/other"), "")
        with mock.patch.object(hook.subprocess, "run", return_value=nested_repo) as run:
            self.assertIsNone(hook.run_hook(self.event()))
            self.assertEqual(run.call_count, 1)

    def test_malformed_input_exits_zero_with_informational_context(self) -> None:
        result = subprocess.run([sys.executable, str(HOOK)], input="invalid", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(json.loads(result.stdout)), {"hookSpecificOutput"})


if __name__ == "__main__":
    unittest.main()
