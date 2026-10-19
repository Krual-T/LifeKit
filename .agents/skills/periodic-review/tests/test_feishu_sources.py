"""Source scope tests: fake CLI responses and temporary files only."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "sources" / "feishu"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load("export_raw")
weekly = load("fetch_weekly_context")
drafts = load("extract_drafts")


class FeishuSourceTests(unittest.TestCase):
    def test_release_keyword_miss_continues_to_explicit_query(self):
        unrelated = {"title": "Other Release/0907", "result_meta": {"url": "https://example.test/other"}}
        selected = {"title": "Project-A Release/0907", "result_meta": {"url": "https://example.test/allowed"}}

        def search(query):
            return {"ok": True, "data": {"results": [selected if query == "Project-A Release" else unrelated]}}

        with patch.object(weekly, "search_drive", side_effect=search) as read:
            result = weekly.select_release("2026-09-01", "Project-A Release", "Project-A", "6,4")
        self.assertEqual(result["selected"], selected)
        self.assertEqual([call.args[0] for call in read.call_args_list],
                         ["intitle:Release/0907", "intitle:Release/0905", "Project-A Release"])

    def test_release_keyword_miss_never_fetches_unrelated_document(self):
        unrelated = {"title": "Other Release/0907", "result_meta": {"url": "https://example.test/other"}}
        with tempfile.TemporaryDirectory() as directory, patch.object(weekly, "search_drive", return_value={"ok": True, "data": {"results": [unrelated]}}), patch.object(weekly, "fetch_doc", side_effect=AssertionError("out-of-scope document")), redirect_stdout(io.StringIO()):
            code = weekly.main(["--profile", "test-profile", "--week-start", "2026-09-01",
                                "--week-end", "2026-09-08", "--release-query", "Project-A Release",
                                "--release-keywords", "Project-A", "--output-dir", directory])
            self.assertEqual(code, 1)
            result = json.loads((Path(directory) / "raw_weekly_context.json").read_text())
            self.assertIsNone(result["release"]["selected"])
            self.assertEqual(result["warnings"], ["release document not found"])

    def test_release_without_keywords_uses_only_explicit_query(self):
        selected = {"title": "Project-A Release/0907", "result_meta": {"url": "https://example.test/allowed"}}
        with patch.object(weekly, "search_drive", return_value={"ok": True, "data": {"results": [selected]}}) as search:
            result = weekly.select_release("2026-09-01", "Project-A Release", "", "6,4")
        search.assert_called_once_with("Project-A Release")
        self.assertEqual(result["selected"], selected)

    def test_tasks_only_never_reads_other_material_types(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name in ("get_current_user", "load_configs", "fetch_docs", "fetch_doc_contents",
                         "fetch_doc_comments", "fetch_doc_versions", "fetch_calendar", "fetch_vc",
                         "fetch_minutes", "fetch_group_messages", "fetch_p2p_messages"):
                stack.enter_context(patch.object(export, name, side_effect=AssertionError(f"unexpected {name}")))
            tasks = stack.enter_context(patch.object(export, "fetch_tasks", return_value={"tasks": [{"summary": "a task"}]}))
            stack.enter_context(redirect_stdout(io.StringIO()))
            code = export.main(["--profile", "test-profile", "--include", "tasks",
                                "--start", "2026-09-01", "--end", "2026-09-02",
                                "--timezone", "Asia/Shanghai", "--output-dir", directory])
            self.assertEqual(code, 0)
            tasks.assert_called_once_with("2026-09-01T00:00:00+08:00", "2026-09-02T00:00:00+08:00")
            self.assertEqual({path.name for path in Path(directory).iterdir()}, {"_meta.json", "raw_tasks.json"})
            self.assertEqual(json.loads((Path(directory) / "_meta.json").read_text())["included"], ["tasks"])

    def test_reader_failure_is_retained_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(export, "fetch_tasks", return_value={"ok": False, "_error": "no access"}), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = export.main(["--profile", "test-profile", "--include", "tasks",
                                "--start", "2026-09-01", "--end", "2026-09-02", "--output-dir", directory])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads((Path(directory) / "raw_tasks.json").read_text())["_error"], "no access")

    def test_weekly_document_does_not_enable_release_search(self):
        response = {"ok": True, "data": {"document": {"content": "# Weekly notes\nA useful observation."}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(weekly, "fetch_doc", return_value=response) as fetch, patch.object(weekly, "select_release", side_effect=AssertionError("release not selected")), redirect_stdout(io.StringIO()):
            code = weekly.main(["--profile", "test-profile", "--week-start", "2026-09-01",
                                "--week-end", "2026-09-08", "--weekly-report-doc", "https://example.test/doc",
                                "--output-dir", directory])
            self.assertEqual(code, 0)
            fetch.assert_called_once_with("https://example.test/doc", doc_format="markdown")
            self.assertFalse(json.loads((Path(directory) / "raw_weekly_context.json").read_text())["release"]["enabled"])

    def test_release_search_does_not_enable_fixed_document(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(weekly, "fetch_doc", side_effect=AssertionError("no document selected")), patch.object(weekly, "select_release", return_value={"selected": None}) as search, redirect_stdout(io.StringIO()):
            code = weekly.main(["--profile", "test-profile", "--week-start", "2026-09-01",
                                "--week-end", "2026-09-08", "--release-query", "intitle:Release",
                                "--output-dir", directory])
            self.assertEqual(code, 1)
            search.assert_called_once()
            result = json.loads((Path(directory) / "raw_weekly_context.json").read_text())
            self.assertFalse(result["weekly_report"]["enabled"])
            self.assertEqual(result["warnings"], ["release document not found"])

    def test_unselected_weekly_sources_do_not_call_cli(self):
        with patch.object(weekly, "run_lark_cli", side_effect=AssertionError("unexpected CLI")), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                weekly.main(["--profile", "test-profile", "--week-start", "2026-09-01", "--week-end", "2026-09-08"])
            self.assertEqual(raised.exception.code, 2)

    def test_nonzero_cli_exit_is_not_treated_as_empty_success(self):
        result = subprocess.CompletedProcess([], 1, '{"data": {}}', "permission denied")
        with patch.object(export, "LARK_PROFILE", "test-profile"), patch.object(export.subprocess, "run", return_value=result):
            self.assertFalse(export.run_lark_cli(["lark-cli", "test"])["ok"])

    def test_drafts_do_not_create_an_unselected_weekly_document(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            raw = root / "raw"
            output = root / "drafts"
            raw.mkdir()
            output.mkdir()
            (raw / "raw_weekly_context.json").write_text(json.dumps({
                "weekly_report": {"enabled": True, "document": {"content": "# Notes\nAn observation"}, "fetch": {"ok": True}},
                "release": {"enabled": False},
            }))
            drafts.process_weekly_context(raw, output)
            self.assertEqual({path.name for path in output.iterdir()}, {"weekly_report.md"})

    def test_historical_action_hits_keep_window_precision(self):
        hit = {"action": "edited", "window_start": "2026-09-01T00:00:00+08:00",
               "window_end": "2026-09-02T00:00:00+08:00", "actor_name": "Window actor", "precision": "hour"}
        for key in ("_review_action_hit", "_lifekernel_action_hit"):
            with self.subTest(key=key):
                result = drafts.build_doc_action_events({"edited": {
                    key: hit, "result_meta": {"edit_user_name": "Later editor", "update_time_iso": "2026-10-01T08:00:00+08:00"},
                }})
                self.assertEqual(result[0]["time"], "本窗口内（小时级筛选）")
                self.assertEqual(result[0]["actor"], "Window actor")


if __name__ == "__main__":
    unittest.main()
