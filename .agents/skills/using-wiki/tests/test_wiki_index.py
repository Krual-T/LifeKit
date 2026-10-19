from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "wiki_index.py"
SPEC = importlib.util.spec_from_file_location("wiki_index", SCRIPT)
assert SPEC and SPEC.loader
wiki_index = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wiki_index
SPEC.loader.exec_module(wiki_index)


class WikiIndexTests(unittest.TestCase):
    def test_cli_add_reorder_evict_remove_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            pages = [self.write_page(root, f"projects/topic-{index}.md") for index in range(6)]
            originals = {page: page.read_bytes() for page in pages}

            def invoke(*args: str, expected: int = 0) -> None:
                result = subprocess.run(
                    [sys.executable, str(SCRIPT.resolve()), *args],
                    cwd=root, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

            invoke("sync")
            self.assertEqual(self.read_cache(root), [])
            for index in range(6):
                invoke("add", f"projects/topic-{index}.md")
            self.assertEqual([entry.wiki_path for entry in self.read_cache(root)], [
                f"projects/topic-{index}.md" for index in range(5, 0, -1)
            ])
            invoke("add", "projects/topic-2.md")
            self.assertEqual(self.read_cache(root)[0].wiki_path, "projects/topic-2.md")
            self.assertEqual(len(self.read_cache(root)), 5)
            pages[5].unlink()
            invoke("remove", "projects/topic-2.md", "projects/topic-5.md")
            invoke("check", "--project-root", str(root))
            self.assertEqual([entry.wiki_path for entry in self.read_cache(root)], [
                "projects/topic-4.md", "projects/topic-3.md", "projects/topic-1.md"
            ])
            before_invalid = self.snapshot_project(root)
            invoke("add", "../outside.md", expected=1)
            invoke("sync", "--note", "Unused", expected=2)
            self.assertEqual(self.snapshot_project(root), before_invalid)
            for page in pages[:5]:
                self.assertEqual(page.read_bytes(), originals[page])
            self.assertEqual((root / "wiki/log.md").read_text(), "# LifeKernel Wiki Update Log\n")

    def make_project(self, root: Path) -> None:
        (root / "wiki").mkdir(parents=True)
        (root / "wiki" / "log.md").write_text("# LifeKernel Wiki Update Log\n", encoding="utf-8")
        marker_start = wiki_index.MARKER_START
        marker_end = wiki_index.MARKER_END
        (root / "AGENTS.md").write_text(
            "# Test\n\n"
            f"{marker_start}\n"
            f"{wiki_index.EMPTY_RECENT}\n"
            f"{marker_end}\n",
            encoding="utf-8",
        )

    def write_page(
        self,
        root: Path,
        relative: str,
        *,
        title: str | None = None,
        description: str | None = None,
        body: str = "Knowledge.\n",
        extra: dict[str, object] | None = None,
    ) -> Path:
        path = root / "wiki" / relative
        frontmatter: dict[str, object] = {
            "type": "Any Open Type",
            "title": title or path.stem,
            "description": description or f"Description for {path.stem}",
            "status": "stable",
        }
        if extra:
            frontmatter.update(extra)
        wiki_index.write_concept(path, frontmatter, body)
        return path

    def set_cache(self, root: Path, entries: list[wiki_index.IndexEntry]) -> None:
        agents = root / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        agents.write_text(
            wiki_index.render_replaced_recent(
                text,
                wiki_index.render_recent(entries, root),
                agents,
            ),
            encoding="utf-8",
        )

    def read_cache(self, root: Path) -> list[wiki_index.IndexEntry]:
        agents = root / "AGENTS.md"
        entries, _ = wiki_index.parse_recent(
            agents.read_text(encoding="utf-8"),
            root,
            agents,
        )
        return entries

    def snapshot_project(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".okf" not in path.relative_to(root).parts
        }

    def test_remove_route_preserves_memory_and_other_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            page = self.write_page(root, "ideas/parked.md")
            self.write_page(root, "projects/current.md")
            before = page.read_bytes()
            self.set_cache(root, [
                wiki_index.IndexEntry("ideas/parked.md"),
                wiki_index.IndexEntry("projects/current.md"),
            ])
            wiki_index.sync(root, remove=["ideas/parked.md"])
            self.assertEqual(page.read_bytes(), before)
            self.assertEqual(self.read_cache(root), [wiki_index.IndexEntry("projects/current.md")])
            self.assertEqual(wiki_index.check_state(root), [])

    def test_remove_missing_routes_and_add_moved_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "ideas/old.md")
            self.write_page(root, "ideas/deleted.md")
            self.set_cache(root, [wiki_index.IndexEntry("ideas/old.md"), wiki_index.IndexEntry("ideas/deleted.md")])
            (root / "wiki/ideas/old.md").rename(root / "wiki/ideas/new.md")
            (root / "wiki/ideas/deleted.md").unlink()
            wiki_index.sync(root, "ideas/new.md", ["ideas/old.md", "ideas/deleted.md"])
            self.assertEqual(self.read_cache(root), [wiki_index.IndexEntry("ideas/new.md")])
            self.assertTrue((root / "wiki/ideas/new.md").is_file())
            self.assertEqual(wiki_index.check_state(root), [])

    def test_invalid_remove_does_not_change_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/current.md")
            self.set_cache(root, [wiki_index.IndexEntry("projects/current.md")])
            before = self.snapshot_project(root)
            for invalid in ("../outside.md", "/outside.md", "index.md", "projects/"):
                with self.subTest(path=invalid):
                    with self.assertRaises(ValueError):
                        wiki_index.sync(root, remove=[invalid])
                    self.assertEqual(self.snapshot_project(root), before)

    def test_add_evicts_oldest_route_but_preserves_all_memory_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            for index in range(6):
                self.write_page(root, f"projects/topic-{index}.md")
            initial = [wiki_index.IndexEntry(f"projects/topic-{index}.md") for index in range(5)]
            self.set_cache(root, initial)

            wiki_index.sync(root, "projects/topic-5.md")

            self.assertEqual(
                [entry.wiki_path for entry in self.read_cache(root)],
                [
                    "projects/topic-5.md",
                    "projects/topic-0.md",
                    "projects/topic-1.md",
                    "projects/topic-2.md",
                    "projects/topic-3.md",
                ],
            )
            for index in range(6):
                self.assertTrue((root / f"wiki/projects/topic-{index}.md").is_file())
            self.assertEqual(wiki_index.check_state(root), [])

    def test_add_protects_fixed_route_and_reorders_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            for index in range(6):
                self.write_page(root, f"projects/topic-{index}.md")
            self.set_cache(
                root,
                [
                    wiki_index.IndexEntry("projects/topic-0.md"),
                    wiki_index.IndexEntry("projects/topic-1.md"),
                    wiki_index.IndexEntry("projects/topic-2.md"),
                    wiki_index.IndexEntry("projects/topic-3.md"),
                    wiki_index.IndexEntry("projects/topic-4.md", fixed=True),
                ],
            )

            wiki_index.sync(root, "projects/topic-5.md")
            entries = self.read_cache(root)

            self.assertEqual(
                [entry.wiki_path for entry in entries],
                [
                    "projects/topic-5.md",
                    "projects/topic-0.md",
                    "projects/topic-1.md",
                    "projects/topic-2.md",
                    "projects/topic-4.md",
                ],
            )

            wiki_index.sync(root, "projects/topic-4.md")
            entries = self.read_cache(root)
            self.assertEqual(entries[0], wiki_index.IndexEntry("projects/topic-4.md", fixed=True))
            self.assertEqual(len(entries), 5)
            self.assertEqual(wiki_index.check_state(root), [])

    def test_check_reports_capacity_and_fixed_slot_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            for index in range(6):
                self.write_page(root, f"projects/topic-{index}.md")
            self.set_cache(root, [wiki_index.IndexEntry(f"projects/topic-{index}.md", fixed=index < 3) for index in range(6)])
            errors = wiki_index.check_state(root)
            self.assertTrue(any("exceeds capacity 5" in error for error in errors))
            self.assertTrue(any("fixed recent memory routes exceed capacity 2" in error for error in errors))

    def test_sync_preserves_order_and_log_while_updating_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            page_a = self.write_page(root, "projects/a.md", title="A", description="Old A")
            self.write_page(root, "projects/b.md", title="B", description="B desc")
            self.set_cache(
                root,
                [wiki_index.IndexEntry("projects/b.md"), wiki_index.IndexEntry("projects/a.md")],
            )
            data, body = wiki_index.parse_concept(page_a)
            data["description"] = "New A"
            wiki_index.write_concept(page_a, data, body)

            wiki_index.sync(root)

            self.assertEqual(
                [entry.wiki_path for entry in self.read_cache(root)],
                ["projects/b.md", "projects/a.md"],
            )
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("[A](wiki/projects/a.md) — New A", agents)
            self.assertEqual((root / "wiki/log.md").read_text(), "# LifeKernel Wiki Update Log\n")

    def test_memory_can_be_an_ordinary_okf_page_at_wiki_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(
                root,
                "idea.md",
                body="# Idea\n\nA passing thought without any next step.\n",
            )

            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])
            wiki_index.sync(root)
            self.assertTrue((root / "wiki/idea.md").is_file())

    def test_add_path_must_be_wiki_root_relative_and_address_an_okf_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md")

            for invalid in (
                "wiki/projects/topic.md",
                "../outside.md",
                "/absolute.md",
                "projects/index.md",
                "projects/missing.md",
            ):
                with self.subTest(invalid=invalid):
                    before = self.snapshot_project(root)
                    with self.assertRaisesRegex(ValueError, "add"):
                        wiki_index.sync(root, invalid)
                    self.assertEqual(self.snapshot_project(root), before)

    def test_custom_status_generated_shape_and_extensions_are_not_governed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(
                root,
                "projects/topic.md",
                extra={
                    "status": "needs-domain-review",
                    "generated": {"by": "test"},
                    "x-lifekernel": {"temporal": {"kind": "anything"}},
                    "x-lifekernel-wiki_index": {
                        "promotion": {"status": "anything", "targets": "not-a-list"}
                    },
                },
            )

            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])

    def test_navigation_preflight_requires_string_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md", extra={"type": 42})

            errors = wiki_index.validate_wiki(root / "wiki")

            self.assertTrue(any("type must be a non-empty string" in error for error in errors))

    def test_check_rejects_duplicate_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            for index in range(6):
                self.write_page(root, f"projects/topic-{index}.md")
            entries = [
                wiki_index.IndexEntry(f"projects/topic-{index}.md")
                for index in range(6)
            ]
            entries[-1] = wiki_index.IndexEntry("projects/topic-0.md")
            self.set_cache(root, entries)

            errors = wiki_index.check_state(root)

            self.assertTrue(any("duplicate Wiki routes" in error for error in errors))

    def test_check_requires_exact_unique_standard_marker_and_current_page_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md", title="Canonical", description="Current")
            self.set_cache(root, [wiki_index.IndexEntry("projects/topic.md")])
            wiki_index.sync(root)
            agents = root / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8").replace("[Canonical]", "[Stale]"),
                encoding="utf-8",
            )

            errors = wiki_index.check_state(root)
            self.assertTrue(any('AGENTS.md "最近" is not synchronized' in error for error in errors))

            agents.write_text(
                agents.read_text(encoding="utf-8")
                + f"\n{wiki_index.MARKER_START}\n{wiki_index.MARKER_END}\n",
                encoding="utf-8",
            )
            before = self.snapshot_project(root)
            with self.assertRaisesRegex(ValueError, "exactly one pair"):
                wiki_index.sync(root)
            self.assertEqual(self.snapshot_project(root), before)

    def test_check_requires_cached_page_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            page = self.write_page(root, "projects/topic.md")
            self.set_cache(root, [wiki_index.IndexEntry("projects/topic.md")])
            page.unlink()

            errors = wiki_index.check_state(root)

            self.assertTrue(any("recent memory route does not exist" in error for error in errors))

    def test_broken_body_links_and_source_resources_are_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            target = self.write_page(root, "projects/target.md")
            self.write_page(
                root,
                "projects/source.md",
                body="[Target](target.md)\n",
                extra={"sources": [{"resource": "target.md"}]},
            )
            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])

            target.unlink()
            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])

    def test_external_and_code_example_links_do_not_require_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(
                root,
                "projects/source.md",
                body=(
                    "[Web](https://example.com/missing.md)\n\n"
                    "Use `[Missing](missing.md)` as an example.\n\n"
                    "```markdown\n[Missing](also-missing.md)\n```\n"
                ),
                extra={"sources": [{"resource": "conversation://topic"}]},
            )

            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])

    def test_sync_never_deletes_wiki_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            for index in range(7):
                self.write_page(root, f"projects/topic-{index}.md")
            stale_directory = root / "wiki/older/2026/08"
            stale_directory.mkdir(parents=True)
            (stale_directory / "index.md").write_text("# stale\n", encoding="utf-8")
            before_paths = {path for path in (root / "wiki").rglob("*.md")}

            wiki_index.sync(root, "projects/topic-6.md")

            self.assertTrue(all(path.exists() for path in before_paths))
            self.assertEqual(
                len(list((root / "wiki/projects").glob("topic-*.md"))),
                7,
            )

    def test_write_failure_rolls_back_all_generated_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md")
            before = self.snapshot_project(root)
            original = wiki_index.atomic_write_text
            calls = 0

            def fail_once(path: Path, text: str, mode: int | None = None) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                original(path, text, mode)

            with mock.patch.object(wiki_index, "atomic_write_text", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    wiki_index.sync(root, "projects/topic.md")

            self.assertEqual(self.snapshot_project(root), before)

    def test_apply_rejects_inputs_changed_after_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md")
            plan = wiki_index.plan_sync(root)
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8") + "\nConcurrent edit.\n", encoding="utf-8")
            before_apply = self.snapshot_project(root)

            with self.assertRaisesRegex(RuntimeError, "inputs changed after planning"):
                wiki_index.apply_plan(plan)

            self.assertEqual(self.snapshot_project(root), before_apply)

    def test_check_detects_unsynchronized_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            self.write_page(root, "projects/topic.md")
            wiki_index.sync(root)
            index = root / "wiki/projects/index.md"
            index.write_text("# stale\n", encoding="utf-8")

            errors = wiki_index.check_state(root)

            self.assertTrue(any("Wiki index is not synchronized" in error for error in errors))

    def test_sources_id_footnotes_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            concept = self.write_page(
                root,
                "projects/example.md",
                body="Claim.[^source]\n\n[^source]: Detail.\n",
            )

            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])

            data, _ = wiki_index.parse_concept(concept)
            wiki_index.write_concept(
                concept,
                data,
                "Use `[^source]` in code.\n\n```markdown\n[^source]: Detail.\n```\n",
            )
            self.assertEqual(wiki_index.validate_wiki(root / "wiki"), [])


if __name__ == "__main__":
    unittest.main()
