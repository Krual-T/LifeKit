from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from okf_retrieval import cli


PAGE = """---
type: Example
title: 火星恢复
description: 火星会话恢复流程
abstract: 断线后从 checkpoint 恢复。
tags: [resume]
aliases: [Mars recovery]
status: stable
---

# 火星恢复

恢复正文。
"""


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.wiki = self.project / "wiki"
        self.wiki.mkdir()
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (self.wiki / "flow.md").write_text(PAGE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, arguments: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous = Path.cwd()
        try:
            if cwd:
                os.chdir(cwd)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(arguments)
        finally:
            os.chdir(previous)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_auto_discovery_json_and_text(self) -> None:
        code, output, error = self.invoke(["query", "火星恢复"], cwd=self.project)
        payload = json.loads(output)
        query_text_code, query_text_output, query_text_error = self.invoke(
            ["query", "火星恢复", "--limit", "3", "--format", "text"], cwd=self.project
        )
        text_code, text_output, _ = self.invoke(
            ["get", "flow.md", "--level", "l1", "--format", "text"], cwd=self.wiki
        )

        self.assertEqual((code, error), (0, ""))
        self.assertEqual(payload["results"][0]["path"], "flow.md")
        self.assertEqual((query_text_code, query_text_error), (0, ""))
        self.assertIn("1. 火星恢复 [flow.md]", query_text_output)
        self.assertIn("status=stable", query_text_output)
        self.assertNotIn('"results"', query_text_output)
        self.assertEqual(text_code, 0)
        self.assertIn("火星会话恢复流程", text_output)

    def test_explicit_root_validate_sync_status_and_errors(self) -> None:
        for command in ("validate", "sync", "status"):
            code, output, error = self.invoke([command, "--wiki-root", str(self.wiki)])
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["schema_version"], 1)
        code, _, error = self.invoke(
            ["get", "../outside.md", "--level", "l2", "--wiki-root", str(self.wiki)]
        )
        self.assertEqual(code, 2)
        self.assertIn("invalid Wiki path", error)

    def test_version(self) -> None:
        with self.assertRaises(SystemExit) as exit_context:
            self.invoke(["--version"])
        self.assertEqual(exit_context.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
