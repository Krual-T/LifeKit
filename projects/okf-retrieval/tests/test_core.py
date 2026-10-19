from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

from okf_retrieval import core


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temporary.name) / "knowledge"
        self.wiki.mkdir()
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (self.wiki / "log.md").write_text("# Log\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_page(
        self,
        relative: str,
        *,
        title: str,
        description: str,
        body: str,
        page_type: str = "Completely Custom Type",
        abstract: str = "",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
        status: str = "stable",
        verified: object | None = None,
        stale_after: str | None = None,
        extra: dict | None = None,
    ) -> Path:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter: dict = {
            "type": page_type,
            "title": title,
            "description": description,
            "abstract": abstract,
            "tags": tags or [],
            "keywords": keywords or [],
            "aliases": aliases or [],
            "status": status,
            "generated": {"by": "test"},
            "sources": [{"resource": "test://fixture"}],
        }
        if verified is not None:
            frontmatter["verified"] = verified
        if stale_after:
            frontmatter["stale_after"] = stale_after
        if extra:
            frontmatter.update(extra)
        yaml_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
        path.write_text(f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n", encoding="utf-8")
        return path

    def test_path_prefix_treats_wildcards_literally(self) -> None:
        for directory in ("team_a", "teamXa", "team%a", "teama", "teamXYa", "team!a", "team_a-extra"):
            for name in ("page.md", "nested/page.md"):
                self.write_page(
                    f"{directory}/{name}", title="Scope needle",
                    description="Scope needle", body="# Scope needle",
                )

        for prefix in ("team_a", "team%a", "team!a"):
            for value in (prefix, prefix + "/"):
                with self.subTest(prefix=value):
                    result = core.query_index(self.wiki, "Scope needle", path_prefix=value)
                    self.assertEqual(
                        {item["path"] for item in result["results"]},
                        {f"{prefix}/page.md", f"{prefix}/nested/page.md"},
                    )
            with self.subTest(exact_path=prefix):
                result = core.query_index(
                    self.wiki, "Scope needle", path_prefix=f"{prefix}/page.md"
                )
                self.assertEqual(
                    [item["path"] for item in result["results"]], [f"{prefix}/page.md"]
                )

    def test_ranking_considers_more_than_500_candidates_before_limit(self) -> None:
        for index in range(500):
            self.write_page(
                f"a{index:03}.md", title=f"Precision needle note {index}",
                description="Precision needle", body="# Note",
            )
        self.write_page(
            "z.md", title="Precision needle", description="Precision needle", body="# Note"
        )

        complete = core.query_index(self.wiki, "Precision needle", limit=1000)
        self.assertEqual(len(complete["results"]), 501)
        self.assertEqual(complete["results"][0]["path"], "z.md")
        self.assertIn("exact-title-or-alias", complete["results"][0]["matched"])
        for limit in (1, 5, 500, 501):
            with self.subTest(limit=limit):
                result = core.query_index(self.wiki, "Precision needle", limit=limit)
                self.assertEqual(result["results"], complete["results"][:limit])
                lexical = next(stage for stage in result["trace"] if stage["stage"] == "lexical")
                self.assertEqual(lexical["candidate_count"], 501)
        for limit in (0, -1):
            with self.subTest(invalid_limit=limit):
                with self.assertRaisesRegex(ValueError, "limit must be at least 1"):
                    core.query_index(self.wiki, "Precision needle", limit=limit)

    def base_pages(self) -> None:
        self.write_page(
            "odd-taxonomy/runtime.md",
            title="AssistantDefinition and Bundle",
            description="Defines the distinction between an assistant definition and its resolved bundle",
            abstract="AssistantDefinition is declarative input; Bundle is the resolved runtime package.",
            aliases=["助手定义与运行包", "Assistant Definition"],
            tags=["runtime", "bundle"],
            body=(
                "# AssistantDefinition and Bundle\n\n"
                "The definition is stored configuration.\n\n"
                "## Resolution\n\nThe bundle contains resolved prompts, skills, and tools."
            ),
            verified={"by": "test", "at": "2026-08-26T00:00:00Z"},
        )
        self.write_page(
            "arbitrary/skill.md",
            title="Skill runtime",
            description="Skill mounting and runtime gating",
            aliases=["技能挂载"],
            body="# Skill runtime\n\nSkills are mounted after policy checks.\n\n## Gate\n\nThe gate filters disabled skills.",
        )

    def test_explicit_root_needs_no_index_and_auto_discovery_supports_both_shapes(self) -> None:
        (self.wiki / "index.md").unlink()
        self.write_page("custom/page.md", title="Page", description="A page", body="# Page\n\nBody")
        self.assertEqual(core.discover_wiki_root(explicit=self.wiki), self.wiki.resolve())
        with self.assertRaisesRegex(ValueError, "could not discover"):
            core.discover_wiki_root(start=self.wiki / "custom")

        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        self.assertEqual(core.discover_wiki_root(start=self.wiki / "custom"), self.wiki.resolve())
        project = Path(self.temporary.name) / "project"
        nested = project / "wiki"
        nested.mkdir(parents=True)
        (nested / "index.md").write_text("# Index\n", encoding="utf-8")
        self.assertEqual(core.discover_wiki_root(start=project), nested.resolve())

    def test_l0_l1_l2_and_nested_config_are_profile_independent(self) -> None:
        (self.wiki / ".okf-retrieval.yaml").write_text(
            "searchable_frontmatter:\n  - x-project.card.current\n"
            "l1_frontmatter:\n  - x-project.card.current\n  - x-project.card.next\n",
            encoding="utf-8",
        )
        page = self.write_page(
            "made-up/now.md",
            title="Runtime state",
            description="Current runtime state",
            body="# Runtime state\n\nRoot first paragraph.\n\n## Detail\n\nDetail first paragraph.\n\nSecond paragraph.",
            page_type="My Unregistered Taxonomy",
            extra={"x-project": {"card": {"current": "正在联调火星协议", "next": "验证恢复"}}},
        )

        l0 = core.get_document(self.wiki, "made-up/now.md", "l0")
        l1 = core.get_document(self.wiki, "made-up/now.md", "l1")
        l2 = core.get_document(self.wiki, "made-up/now.md", "l2")
        query = core.query_index(self.wiki, "火星协议")

        self.assertIn("type: My Unregistered Taxonomy", l0["content"])
        self.assertIn("正在联调火星协议", l1["content"])
        self.assertIn("验证恢复", l1["content"])
        self.assertIn("Root first paragraph", l1["content"])
        self.assertEqual(l2["content"], page.read_text(encoding="utf-8"))
        self.assertEqual(query["results"][0]["path"], "made-up/now.md")

    def test_title_alias_chinese_english_and_filters(self) -> None:
        self.base_pages()
        title = core.query_index(self.wiki, "AssistantDefinition and Bundle 有什么区别")
        alias = core.query_index(self.wiki, "助手定义与运行包")
        filtered = core.query_index(
            self.wiki,
            "runtime",
            path_prefix="odd-taxonomy",
            concept_type="Completely Custom Type",
        )

        self.assertEqual(title["results"][0]["path"], "odd-taxonomy/runtime.md")
        self.assertEqual(alias["results"][0]["path"], "odd-taxonomy/runtime.md")
        self.assertEqual(filtered["results"][0]["path"], "odd-taxonomy/runtime.md")
        self.assertIsNone(title["semantic"])
        self.assertEqual(title["schema_version"], 1)

    def test_multi_term_body_evidence_is_recalled_but_incidental_match_is_not(self) -> None:
        self.write_page(
            "policy/memory.md",
            title="Knowledge policy",
            description="Governance rules",
            body="# Policy\n\n正式记忆需要人工批准，检索结果不能自动回写。",
        )
        self.write_page(
            "notes/color.md",
            title="Image note",
            description="An unrelated image note",
            body="# Image\n\n正文顺带提到颜色，但没有偏好记录。",
        )
        self.write_page(
            "notes/approval.md",
            title="Release approval",
            description="正式发布需要批准",
            body="# Release\n\n正式源码切换需要用户批准，但不涉及记忆治理。",
        )

        policy = core.query_index(self.wiki, "正式记忆为什么必须人工批准")
        unknown = core.query_index(self.wiki, "我最喜欢什么颜色")

        self.assertEqual(policy["results"][0]["path"], "policy/memory.md")
        self.assertEqual(unknown["results"], [])

    def test_named_relationship_subject_must_match_the_candidate(self) -> None:
        # Synthetic names keep relationship matching independent of any user's Wiki.
        self.write_page(
            "people/partner.md",
            title="示例乙",
            description="示例甲的女朋友和长期伴侣",
            aliases=["示例甲的对象", "我的女朋友"],
            body="# 示例乙\n\n示例乙是示例甲的女朋友。",
        )

        matching = core.query_index(self.wiki, "示例甲的女朋友是谁")
        unrelated = core.query_index(self.wiki, "示例丙的女朋友是谁")

        self.assertEqual(matching["results"][0]["path"], "people/partner.md")
        self.assertEqual(unrelated["results"], [])

    def test_draft_deprecated_stale_and_custom_status(self) -> None:
        self.write_page(
            "custom/draft.md", title="量子茶壶草稿", description="量子茶壶", body="# Draft", status="draft"
        )
        self.write_page(
            "custom/old.md", title="量子茶壶旧版", description="量子茶壶", body="# Old", status="deprecated"
        )
        self.write_page(
            "custom/review.md",
            title="量子茶壶评审",
            description="量子茶壶",
            body="# Review",
            status="needs-domain-review",
            stale_after="2020-01-01T00:00:00Z",
        )

        normal = core.query_index(self.wiki, "量子茶壶")
        all_results = core.query_index(
            self.wiki, "量子茶壶", include_draft=True, include_deprecated=True
        )

        self.assertEqual([item["path"] for item in normal["results"]], ["custom/review.md"])
        self.assertEqual(len(all_results["results"]), 3)
        self.assertTrue(normal["results"][0]["governance"]["stale"])
        self.assertTrue(any("stale after" in warning for warning in normal["warnings"]))

    def test_incremental_update_delete_corrupt_rebuild_and_config_change(self) -> None:
        self.base_pages()
        first = core.sync_index(self.wiki)
        page = self.wiki / "arbitrary/skill.md"
        page.write_text(page.read_text(encoding="utf-8").replace("disabled", "unavailable"), encoding="utf-8")
        (self.wiki / "odd-taxonomy/runtime.md").unlink()
        second = core.sync_index(self.wiki)
        _, database, _ = core.runtime_paths(self.wiki)
        database.write_bytes(b"broken")
        rebuilt = core.sync_index(self.wiki)
        (self.wiki / ".okf-retrieval.yaml").write_text(
            "searchable_frontmatter:\n  - x-any.value\n", encoding="utf-8"
        )
        config_changed = core.sync_index(self.wiki)

        self.assertEqual((first["changed"], first["removed"]), (2, 0))
        self.assertEqual((second["changed"], second["removed"]), (1, 1))
        self.assertEqual(rebuilt["documents"], 1)
        self.assertEqual(config_changed["changed"], 1)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_invalid_source_preserves_last_good_index(self) -> None:
        self.base_pages()
        core.sync_index(self.wiki)
        _, database, _ = core.runtime_paths(self.wiki)
        original = database.read_bytes()
        (self.wiki / "bad.md").write_text("no frontmatter", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Wiki validation failed"):
            core.sync_index(self.wiki)

        self.assertEqual(database.read_bytes(), original)
        self.assertFalse(core.status_index(self.wiki)["fresh"])

    def test_okf_requires_a_non_empty_string_type(self) -> None:
        cases = ((None, "missing"), ("   ", "blank"), (42, "non-string"))
        for value, name in cases:
            with self.subTest(name=name):
                page = self.write_page(
                    f"invalid/{name}.md",
                    title="Invalid type",
                    description="Invalid type fixture",
                    body="# Invalid",
                    page_type="temporary",
                )
                frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
                if value is None:
                    frontmatter.pop("type")
                else:
                    frontmatter["type"] = value
                yaml_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
                page.write_text(f"---\n{yaml_text}\n---\n\n# Invalid\n", encoding="utf-8")

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(any("type must be a non-empty string" in error for error in validation["errors"]))
                page.unlink()

    def test_okf_frontmatter_must_be_a_mapping(self) -> None:
        (self.wiki / "invalid.md").write_text("---\n- not\n- a\n- mapping\n---\n\n# Invalid\n", encoding="utf-8")

        validation = core.validate_wiki(self.wiki)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("frontmatter must be a mapping" in error for error in validation["errors"]))

    def test_okf_timestamp_fields_require_an_explicit_utc_offset(self) -> None:
        cases = {
            "generated": {"generated": {"by": "test", "at": "2026-08-26T12:00:00"}},
            "verified": {"verified": {"by": "human:test", "at": "2026-08-26"}},
            "stale-after": {"stale_after": "2026-09-01"},
            "legacy-timestamp": {"timestamp": "2026-08-26T12:00:00"},
            "usage-from": {"usage_window": {"from": "2026-08-01", "to": "2026-08-31T00:00:00Z"}},
            "source-modified": {
                "sources": [{"resource": "test://fixture", "last_modified": "2026-08-26"}]
            },
            "source-usage-to": {
                "sources": [
                    {
                        "resource": "test://fixture",
                        "usage_window": {
                            "from": "2026-08-01T00:00:00+08:00",
                            "to": "not-a-timestamp",
                        },
                    }
                ]
            },
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                page = self.write_page(
                    f"invalid/{name}.md",
                    title="Invalid timestamp",
                    description="Invalid timestamp fixture",
                    body="# Invalid",
                    extra=extra,
                )

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any("ISO 8601 datetime with an explicit UTC offset" in error for error in validation["errors"])
                )
                page.unlink()

    def test_generated_requires_a_mapping_and_non_empty_by(self) -> None:
        cases = {
            "not-mapping": {"generated": "test"},
            "missing-by": {"generated": {"at": "2026-08-26T00:00:00Z"}},
            "blank-by": {"generated": {"by": "   "}},
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                page = self.write_page(
                    f"invalid/generated-{name}.md",
                    title="Invalid generated",
                    description="Invalid generated fixture",
                    body="# Invalid",
                    extra=extra,
                )

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(any("generated" in error for error in validation["errors"]))
                page.unlink()

    def test_sources_require_a_list_of_mappings_with_resources(self) -> None:
        cases = {
            "not-list": {"sources": {"resource": "test://fixture"}},
            "item-not-mapping": {"sources": ["test://fixture"]},
            "missing-resource": {"sources": [{"title": "Fixture"}]},
            "blank-resource": {"sources": [{"resource": "   "}]},
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                page = self.write_page(
                    f"invalid/sources-{name}.md",
                    title="Invalid sources",
                    description="Invalid sources fixture",
                    body="# Invalid",
                    extra=extra,
                )

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(any("sources" in error for error in validation["errors"]))
                page.unlink()

    def test_verified_accepts_bare_mapping_or_list_and_requires_complete_events(self) -> None:
        self.write_page(
            "valid/bare-verifier.md",
            title="Bare verifier",
            description="Bare verifier fixture",
            body="# Valid",
            verified={"by": "human:test", "at": "2026-08-26T00:00:00Z"},
        )
        self.write_page(
            "valid/verifier-list.md",
            title="Verifier list",
            description="Verifier list fixture",
            body="# Valid",
            verified=[
                {"by": "process:first", "at": "2026-08-26T00:00:00Z"},
                {"by": "human:second", "at": "2026-08-26T08:00:00+08:00"},
            ],
        )
        self.assertTrue(core.validate_wiki(self.wiki)["valid"])

        cases = {
            "not-container": {"verified": "human:test"},
            "item-not-mapping": {"verified": ["human:test"]},
            "missing-by": {"verified": {"at": "2026-08-26T00:00:00Z"}},
            "blank-by": {"verified": {"by": " ", "at": "2026-08-26T00:00:00Z"}},
            "missing-at": {"verified": {"by": "human:test"}},
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                page = self.write_page(
                    f"invalid/verified-{name}.md",
                    title="Invalid verified",
                    description="Invalid verified fixture",
                    body="# Invalid",
                    extra=extra,
                )

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(any("verified" in error for error in validation["errors"]))
                page.unlink()

    def test_attested_computation_requires_a_non_empty_runtime(self) -> None:
        for name, extra in (("missing", {}), ("blank", {"runtime": "   "})):
            with self.subTest(name=name):
                invalid = self.write_page(
                    f"invalid/computation-{name}.md",
                    title="Invalid computation",
                    description="Missing runtime",
                    body="# Computation\n\n```sql\nSELECT 1\n```",
                    page_type="Attested Computation",
                    extra=extra,
                )
                validation = core.validate_wiki(self.wiki)
                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any("runtime must be a non-empty string" in error for error in validation["errors"])
                )
                invalid.unlink()

        self.write_page(
            "valid/computation.md",
            title="Valid computation",
            description="Has runtime",
            body="# Computation\n\n```sql\nSELECT 1\n```",
            page_type="Attested Computation",
            extra={"runtime": "bigquery"},
        )
        self.assertTrue(core.validate_wiki(self.wiki)["valid"])

    def test_reserved_index_frontmatter_is_limited_to_the_bundle_root(self) -> None:
        (self.wiki / "index.md").write_text(
            "---\nokf_version: '0.2'\n---\n\n# Index\n\n[Missing](missing.md)\n",
            encoding="utf-8",
        )
        nested = self.wiki / "nested"
        nested.mkdir()
        (nested / "index.md").write_text("# Nested\n", encoding="utf-8")
        self.assertTrue(core.validate_wiki(self.wiki)["valid"])

        (nested / "index.md").write_text("---\ncustom: value\n---\n\n# Nested\n", encoding="utf-8")
        validation = core.validate_wiki(self.wiki)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("bundle-root index.md" in error for error in validation["errors"]))

        (nested / "index.md").write_text("# Nested\n", encoding="utf-8")
        (self.wiki / "index.md").write_text("---\n- not\n- a\n- mapping\n---\n\n# Index\n", encoding="utf-8")
        validation = core.validate_wiki(self.wiki)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("frontmatter must be a mapping" in error for error in validation["errors"]))

    def test_reserved_log_requires_valid_iso_date_group_headings(self) -> None:
        (self.wiki / "log.md").write_text(
            "---\nowner: test\n---\n\n# Log\n\n## 2026-08-26\n* Update\n\n"
            "```markdown\n## This heading is inside a fence\n```\n",
            encoding="utf-8",
        )
        self.assertTrue(core.validate_wiki(self.wiki)["valid"])

        (self.wiki / "log.md").write_text(
            "----\n\n# Log\n\n## 2026-08-26\n* A leading thematic break is not frontmatter.\n",
            encoding="utf-8",
        )
        self.assertTrue(core.validate_wiki(self.wiki)["valid"])

        for heading in ("August 26, 2026", "2026-02-30"):
            with self.subTest(heading=heading):
                (self.wiki / "log.md").write_text(f"# Log\n\n## {heading}\n* Update\n", encoding="utf-8")

                validation = core.validate_wiki(self.wiki)

                self.assertFalse(validation["valid"])
                self.assertTrue(any("log date heading" in error for error in validation["errors"]))

    def test_valid_okf_timestamps_and_markdown_footnotes_are_accepted(self) -> None:
        self.write_page(
            "valid/provenance.md",
            title="Timestamp and footnote example",
            description="Exercises all standard OKF timestamp locations",
            body=(
                "# Claim\n\nThe claim has per-source attribution.[^fixture]\n\n"
                "[^fixture]: Fixture source."
            ),
            stale_after="2026-09-01T00:00:00Z",
            extra={
                "timestamp": "2026-08-26T03:30:00+00:00",
                "generated": {"by": "test", "at": "2026-08-26T11:30:00+08:00"},
                "verified": [
                    {"by": "process:test", "at": "2026-08-26T03:31:00Z"},
                    {"by": "human:test", "at": "2026-08-26T11:32:00+08:00"},
                ],
                "usage_window": {
                    "from": "2026-08-01T00:00:00Z",
                    "to": "2026-08-26T00:00:00Z",
                },
                "sources": [
                    {
                        "id": "fixture",
                        "resource": "test://fixture",
                        "last_modified": "2026-08-25T23:59:59-04:00",
                        "usage_window": {
                            "from": "2026-08-01T00:00:00-04:00",
                            "to": "2026-08-25T23:59:59-04:00",
                        },
                    }
                ],
                "x-example": {"observed_on": "2026-08-26"},
            },
        )

        validation = core.validate_wiki(self.wiki)

        self.assertTrue(validation["valid"], validation["errors"])

    def test_hidden_and_symlink_sources_are_excluded_and_get_rejects_escape(self) -> None:
        self.base_pages()
        hidden = self.wiki / ".private"
        hidden.mkdir()
        (hidden / "secret.md").write_text("secret", encoding="utf-8")
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        link = self.wiki / "arbitrary/link.md"
        link.symlink_to(outside)

        state = core.sync_index(self.wiki)

        self.assertEqual(state["documents"], 2)
        with self.assertRaisesRegex(ValueError, "invalid Wiki path"):
            core.resolve_document_path(self.wiki, "../outside.md")
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            core.resolve_document_path(self.wiki, "arbitrary/link.md")

    def test_permissions_trace_and_no_query_log(self) -> None:
        self.base_pages()
        payload = core.query_index(self.wiki, "技能挂载", trace_level="full")
        runtime, database, lock = core.runtime_paths(self.wiki)

        self.assertEqual(os.stat(runtime).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(database).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(lock).st_mode & 0o777, 0o600)
        self.assertEqual([item["stage"] for item in payload["trace"]], ["scope", "lexical", "rank", "candidates"])
        self.assertEqual({path.name for path in runtime.iterdir()}, {"index.sqlite3", "build.lock"})
        json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
