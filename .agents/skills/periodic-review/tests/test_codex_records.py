import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "sources/codex/codex_records.py"
SPEC = importlib.util.spec_from_file_location("codex_records", SCRIPT)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
START = "2026-09-05T08:05:00+08:00"
END = "2026-09-06T08:05:00+08:00"


def envelope(kind, payload, timestamp=START):
    return {"type": kind, "timestamp": timestamp, "payload": payload}


def message(text, role="user", timestamp=START):
    return envelope("response_item", {"type": "message", "role": role,
                    "content": [{"type": "input_text", "text": text}]}, timestamp)


class CodexRecordsTests(unittest.TestCase):
    def test_phases_turns_and_compaction_injection(self):
        self.write("phases", [
            envelope("turn_context", {"cwd": str(self.project), "turn_id": "turn-one"}),
            message("request"),
            envelope("response_item", {"type": "message", "role": "assistant", "phase": "analysis", "content": "private reasoning"}),
            envelope("event_msg", {"type": "agent_message", "channel": "commentary", "phase": "analysis", "message": "private mirror"}),
            envelope("response_item", {"type": "message", "role": "assistant", "phase": "commentary", "content": "progress"}),
            envelope("response_item", {"type": "message", "role": "assistant", "phase": "final_answer", "content": "done"}),
            message("Another language model started to solve this problem and produced a summary"),
            message("legacy", "assistant")])
        records = self.read()["records"]
        self.assertEqual([r["text"] for r in records], ["request", "progress", "done", "legacy"])
        self.assertEqual([r.get("phase") for r in records], [None, "commentary", "final", "unknown"])
        self.assertTrue(all(r["turn_id"] == "turn-one" for r in records))

    def test_event_mirror_supplies_phase_without_duplicate(self):
        self.write("mirror", [message("done", "assistant"),
            envelope("event_msg", {"type": "agent_message", "message": "done", "phase": "final_answer"})])
        records = self.read()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["phase"], "final")

    def test_same_text_commentary_does_not_swallow_final_event(self):
        self.write("same-text", [
            envelope("response_item", {"type": "message", "role": "assistant", "phase": "commentary", "content": "done"}),
            envelope("event_msg", {"type": "agent_message", "message": "done", "phase": "final_answer"})])
        self.assertEqual([r["phase"] for r in self.read()["records"]], ["commentary", "final"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / "project"
        self.project.mkdir()
        self.sessions = self.home / "sessions"
        self.sessions.mkdir()
        self.config = {"id": "local", "project_root": str(self.project), "session_roots": [str(self.home)]}

    def write(self, thread, rows, *, cwd=None, parent=None, source=None, archive=False, tail="", meta_timestamp=START):
        directory = self.home / "archived_sessions" if archive else self.sessions
        directory.mkdir(exist_ok=True)
        path = directory / f"{thread}.jsonl"
        meta = {"id": thread, "cwd": str(cwd or self.project), "parent_thread_id": parent, "source": source}
        path.write_text("\n".join(row if isinstance(row, str) else json.dumps(row)
                                  for row in [envelope("session_meta", meta, meta_timestamp), *rows]) + "\n" + tail)
        return path

    def read(self, **kwargs):
        return reader.read_records(self.config, START, END, **kwargs)

    def test_half_open_window_and_background_across_days(self):
        self.write("long", [message("old", timestamp="2026-08-01T00:00:00Z"),
                            message("at start"), message("at end", timestamp=END)])
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["old", "at start"])
        self.assertTrue(result["records"][0]["background"])
        self.assertNotIn("background", result["records"][1])

    def test_archive_dedup_and_origin(self):
        self.write("same", [message("a")])
        archive = self.write("same", [message("a"), message("b", "assistant")], archive=True)
        records = self.read()["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["origin"], {"source_id": "local", "file": str(archive), "line": 2})
        self.assertEqual(records[0]["record_id"], "local:same:2")

    def test_strict_metadata_and_turn_cwd(self):
        self.write("outside", [message("outside before"),
                               envelope("turn_context", {"cwd": str(self.project)}), message("joined"),
                               envelope("turn_context", {"cwd": str(self.project) + "-other"}),
                               message("outside after")], cwd=str(self.project) + "-other")
        self.write("inside", [message("yes"), envelope("turn_context", {"cwd": str(self.project) + "-other"}),
                              message("no"), envelope("turn_context", {"cwd": str(self.project / "sub")}), message("yes2")])
        self.assertEqual([r["text"] for r in self.read()["records"]], ["yes", "yes2", "joined"])

    def test_exclusion_descendants_and_automation_not_keyword(self):
        self.write("root", [message("excluded")])
        self.write("child", [message("excluded")], parent="root")
        self.write("grandchild", [message("excluded")], source={"subagent": {"thread_spawn": {"parent_thread_id": "child"}}})
        self.write("auto", [message("Automation: nightly\nAutomation ID: nightly-1\nrun")])
        self.write("auto-child", [message("excluded")], parent="auto")
        self.write("normal", [message("帮我设计日报自动化")])
        self.assertEqual([r["thread_id"] for r in self.read(excluded_thread_ids=["root"])["records"]], ["normal"])

    def test_tools_background_and_missing_call(self):
        self.write("tools", [envelope("response_item", {"type": "function_call", "name": "exec", "arguments": '{"cmd":"ls"}', "call_id": "c"}, "2026-09-04T00:00:00Z"),
                             envelope("response_item", {"type": "function_call_output", "call_id": "c", "output": "ok"}),
                             envelope("response_item", {"type": "custom_tool_call_output", "call_id": "missing", "output": "partial"})])
        result = self.read()
        self.assertEqual([r["kind"] for r in result["records"]], ["tool_call", "tool_result", "tool_result"])
        self.assertTrue(result["records"][0]["background"])
        self.assertEqual(result["context_gaps"][0]["code"], "missing_tool_call")

    def test_visible_only_and_event_fallback_gap(self):
        self.write("visible", [message("hidden", "system"), message("hidden", "developer"),
                               envelope("response_item", {"type": "reasoning", "text": "hidden"}),
                               message("<environment_context>hidden</environment_context>real"),
                               message("# AGENTS.md instructions for /tmp\nhidden"),
                               envelope("event_msg", {"type": "user_message", "message": "real"}),
                               envelope("event_msg", {"type": "agent_message", "message": "missing"})])
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["real", "missing"])
        self.assertTrue(result["records"][1]["fallback"])
        self.assertEqual(result["records"][1]["origin"]["envelope_type"], "event_msg")
        self.assertTrue(result["context_gaps"][0]["recovered"])
        self.assertEqual(result["context_gaps"][0]["code"], "missing_response_items")

    def test_credentials_redacted_in_messages_and_tools(self):
        secret = 'api_key="supersecret" password=hunter2\nAuthorization: Bearer abcdef\nCookie: sid=unsafe; x=y\nhttps://bob:pass@example.com\nsk-abcdefghijk\n-----BEGIN PRIVATE KEY-----\nprivatebytes\n-----END PRIVATE KEY-----'
        self.write("secret", [message(secret), envelope("response_item", {"type": "function_call", "name": "exec", "call_id": "s", "arguments": '{"access_token":"toolsecret"}'})])
        rendered = json.dumps(self.read())
        for value in ("supersecret", "hunter2", "abcdef", "unsafe", "bob:pass", "sk-abcdefghijk", "privatebytes", "toolsecret"):
            self.assertNotIn(value, rendered)

    def test_corrupt_tail_and_unrelated_errors(self):
        self.write("good", [message("preserved")], tail='{"broken":')
        self.write("unrelated", [], cwd="/another-project", tail='{"broken":')
        result = self.read()
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["thread_id"], "good")
        self.assertEqual(result["failures"][0]["origin"]["line"], 3)

    def test_invalid_timestamp_but_unattributed_file_is_not_project_gap(self):
        self.write("badtime", [message("bad", timestamp="yesterday")])
        (self.sessions / "unknown.jsonl").write_bytes(b"\xff\n")
        self.assertEqual({g["code"] for g in self.read()["context_gaps"]}, {"invalid_message_timestamp"})

    def test_analysis_message_hidden_but_tool_calls_and_visible_channels_kept(self):
        analysis = message("private reasoning", "assistant")
        analysis["payload"]["channel"] = "analysis"
        commentary = message("progress", "assistant")
        commentary["payload"]["channel"] = "commentary"
        final = message("answer", "assistant")
        final["payload"]["channel"] = "final"
        self.write("channels", [analysis, commentary, final,
                                envelope("response_item", {"type": "function_call", "name": "exec",
                                         "channel": "analysis", "call_id": "c", "arguments": "ls"})])
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["progress", "answer", "exec\nls"])
        self.assertEqual(result["context_gaps"], [])

    def test_crossing_out_and_back_clears_background_even_without_outside_message(self):
        before = "2026-09-04T12:00:00+08:00"
        self.write("cross", [message("old request", timestamp=before),
                             envelope("response_item", {"type": "function_call", "name": "exec",
                                      "arguments": "ls", "call_id": "c"}, before),
                             envelope("turn_context", {"cwd": "/other"}),
                             envelope("turn_context", {"cwd": str(self.project)}),
                             envelope("response_item", {"type": "function_call_output", "call_id": "c", "output": "result"})],
                   meta_timestamp=before)
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["result"])
        self.assertEqual(result["context_gaps"][0]["code"], "missing_tool_call")

    def test_today_torn_tail_does_not_pollute_historical_window(self):
        self.write("long", [message("historical"), message("today", timestamp="2026-09-06T09:00:00+08:00")], tail='{"broken":')
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["historical"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])

    def test_torn_tail_own_timestamp_can_exclude_it(self):
        self.write("own-time", [message("historical")], tail='{"timestamp":"2026-09-06T09:00:00+08:00","type":')
        result = self.read()
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])

    def test_bounded_old_corruption_not_reported_in_current_window(self):
        before = "2026-09-04T12:00:00+08:00"
        self.write("old", [message("before", timestamp=before), '{"broken":',
                           message("also before", timestamp=before), message("now")], meta_timestamp=before)
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])

    def test_corruption_neighbor_interval_overlapping_window_is_failure(self):
        before = "2026-09-04T12:00:00+08:00"
        self.write("overlap", [message("before", timestamp=before), '{"broken":',
                               message("after", timestamp=END)], meta_timestamp=before)
        result = self.read()
        self.assertEqual(result["failures"][0]["code"], "invalid_jsonl")
        self.assertEqual(result["failures"][0]["origin"]["line"], 3)

    def test_old_open_tail_is_unknown_time_gap_not_failure(self):
        before = "2026-09-04T12:00:00+08:00"
        self.write("open", [message("before", timestamp=before)], meta_timestamp=before, tail='{"broken":')
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"][0]["code"], "invalid_jsonl_time_unknown")

    def test_project_corruption_without_any_timestamp_is_gap(self):
        self.write("untimed", [], meta_timestamp=None, tail='{"broken":')
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"][0]["code"], "invalid_jsonl_time_unknown")

    def test_unclassified_gaps_require_positive_project_attribution(self):
        for index in range(20):
            (self.sessions / f"unknown-{index}.jsonl").write_bytes(b"broken\n")
        self.assertEqual(self.read(), {"records": [], "context_gaps": [], "failures": []})
        (self.sessions / "attributed.jsonl").write_text(json.dumps(envelope("turn_context", {"cwd": str(self.project)})) + "\n")
        self.assertEqual(self.read()["context_gaps"][0]["code"], "unclassified_session")

    def test_errors_after_crossing_out_do_not_affect_project(self):
        self.write("out", [message("inside"), envelope("turn_context", {"cwd": "/other"}),
                           '{"broken":', message("outside")])
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["inside"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])

    def test_malformed_payload_with_outside_timestamp_is_ignored(self):
        self.write("bad-shape-time", [message("visible"), envelope("response_item", {"type": []}, END)])
        result = self.read()
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["context_gaps"], [])

    def test_redaction_only_runs_for_emitted_records_not_historical_tools(self):
        before = "2026-09-04T00:00:00Z"
        self.write("lazy", [message("replaced user", timestamp=before), message("background", timestamp=before),
                            message("old assistant", "assistant", before),
                            envelope("response_item", {"type": "function_call", "name": "exec", "call_id": "old",
                                     "arguments": "unused large arguments " * 1000}, before),
                            envelope("response_item", {"type": "function_call_output", "call_id": "old",
                                     "output": "unused large result " * 1000}, before),
                            message("visible", "assistant"), message("future", "assistant", END)], meta_timestamp=before)
        with patch.object(reader, "_redact", wraps=reader._redact) as redact:
            result = self.read()
        self.assertEqual([call.args[0] for call in redact.call_args_list], ["background", "visible"])
        self.assertEqual([r["text"] for r in result["records"]], ["background", "visible"])

    def test_window_tool_result_is_not_truncated(self):
        text = "完整工具事实，包含输出细节。\n" * 2000
        self.write("large", [envelope("response_item", {"type": "function_call", "name": "exec", "call_id": "c", "arguments": "run"}),
                             envelope("response_item", {"type": "function_call_output", "call_id": "c", "output": text})])
        result = self.read()
        self.assertEqual(result["records"][1]["text"], text)
        self.assertEqual(result["context_gaps"], [])

    def test_metadata_fast_path_skips_bodies_but_falls_back_for_unusual_header_order(self):
        unusual = {"payload": {"type": "message", "role": "assistant", "content": "unusual"},
                   "timestamp": START, "type": "response_item"}
        path = self.write("headers", [message("large body " * 1000), unusual])
        with patch.object(reader.json, "loads", wraps=json.loads) as loads:
            rows = list(reader._lines(path, {"response_item"}))
        self.assertEqual(loads.call_count, 2)  # Metadata and unusual layout only.
        self.assertEqual(rows[1][1]["payload"], {})
        self.assertEqual(rows[2][1]["payload"]["content"], "unusual")

    def test_metadata_skips_outside_bodies_and_resumes_first_user_on_project_entry(self):
        outside = "Automation: outside-only\nAutomation ID: unrelated"
        path = self.write("entry", [message(outside),
                                   envelope("event_msg", {"type": "user_message", "message": outside}),
                                   envelope("turn_context", {"cwd": str(self.project)}),
                                   message("project request"),
                                   envelope("turn_context", {"cwd": "/outside"}),
                                   message("outside again")], cwd="/outside")
        scan_payloads = {}
        original_lines = reader._lines

        def observe_lines(file, skip_payload_types=()):
            metadata_pass = isinstance(skip_payload_types, set)
            for line, item, error in original_lines(file, skip_payload_types):
                if metadata_pass and file == path and item and not error:
                    scan_payloads[line] = item["payload"]
                yield line, item, error

        with patch.object(reader, "_lines", side_effect=observe_lines), patch.object(reader, "_visible", wraps=reader._visible) as visible:
            result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["project request"])
        self.assertEqual([scan_payloads[line] for line in (2, 3, 7)], [{}, {}, {}])
        self.assertEqual(scan_payloads[5]["role"], "user")
        inspected = [reader._text(call.args[0].get("content", "")) for call in visible.call_args_list]
        self.assertNotIn(outside, inspected)
        self.assertNotIn("outside again", inspected)

    def test_first_project_event_user_is_detected_after_outside_user(self):
        self.write("entry-auto", [message("outside normal request"),
                                  envelope("turn_context", {"cwd": str(self.project)}),
                                  envelope("event_msg", {"type": "user_message", "message": "Automation: project\nAutomation ID: project-auto"}),
                                  message("must be excluded", "assistant")], cwd="/outside")
        self.assertEqual(self.read()["records"], [])

    def test_fast_metadata_discovery_does_not_hide_corruption_in_selected_copy(self):
        self.write("broken-body", [message("valid user"),
                                   '{"type":"response_item","timestamp":"2026-09-05T08:05:00+08:00","payload":broken}'])
        result = self.read()
        self.assertEqual(result["records"][0]["text"], "valid user")
        self.assertEqual(result["failures"][0]["code"], "invalid_jsonl")

    def test_event_matching_with_secret_has_no_false_gap(self):
        self.write("secret-event", [message("api_key=privatevalue"),
                                    envelope("event_msg", {"type": "user_message", "message": "api_key=privatevalue"})])
        result = self.read()
        self.assertEqual(result["context_gaps"], [])
        self.assertNotIn("privatevalue", json.dumps(result))

    def test_cli_exit_one_retains_valid_records(self):
        self.write("partial", [message("preserved")], tail='{"broken":')
        run = subprocess.run([sys.executable, str(SCRIPT), "--source-json", json.dumps(self.config),
                              "--start", START, "--end", END], text=True, capture_output=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["records"][0]["text"], "preserved")
        self.assertEqual(result["failures"][0]["code"], "invalid_jsonl")

    def test_invalid_payload_shape_is_partial_not_crash(self):
        self.write("shape", [envelope("response_item", {"type": ["message"]}),
                             envelope("response_item", {"type": "function_call", "call_id": {}}),
                             message("still readable")])
        result = self.read()
        self.assertEqual(len(result["failures"]), 2)
        self.assertEqual(result["records"][0]["text"], "still readable")

    def test_event_gap_not_hidden_by_different_response(self):
        self.write("mismatch", [message("different", "assistant"),
                                envelope("event_msg", {"type": "agent_message", "message": "lost"})])
        self.assertEqual(self.read()["context_gaps"][0]["code"], "missing_response_items")

    def test_event_pairing_is_one_to_one_and_order_independent(self):
        self.write("mirrors", [envelope("event_msg", {"type": "agent_message", "message": "same"}),
                               message("same", "assistant"),
                               envelope("event_msg", {"type": "agent_message", "message": "same"})])
        result = self.read()
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(sum(bool(r.get("fallback")) for r in result["records"]), 1)

    def test_event_pairing_does_not_match_different_explicit_message_ids(self):
        native = message("same", "assistant")
        native["payload"]["id"] = "native"
        self.write("ids", [native, envelope("event_msg", {"type": "agent_message", "id": "different", "message": "same"})])
        self.assertEqual(len(self.read()["records"]), 2)

    def test_event_pairing_does_not_use_text_from_another_turn(self):
        self.write("turns", [message("same", "assistant"), envelope("turn_context", {"cwd": str(self.project)}),
                             envelope("event_msg", {"type": "agent_message", "message": "same"})])
        self.assertEqual(len(self.read()["records"]), 2)

    def test_fallback_obeys_analysis_injection_redaction_and_cwd_rules(self):
        self.write("safe-event", [envelope("event_msg", {"type": "agent_message", "message": "private", "phase": "analysis"}),
                                  envelope("event_msg", {"type": "user_message", "message": "<environment_context>private</environment_context>"}),
                                  envelope("event_msg", {"type": "agent_message", "message": "api_key=secretvalue"}),
                                  envelope("turn_context", {"cwd": "/outside"}),
                                  envelope("event_msg", {"type": "agent_message", "message": "outside"})])
        result = self.read()
        self.assertEqual(len(result["records"]), 1)
        self.assertNotIn("secretvalue", json.dumps(result))
        self.assertTrue(result["records"][0]["fallback"])

    def test_event_only_automation_excluded_with_descendants(self):
        self.write("auto-event", [envelope("event_msg", {"type": "user_message", "message": "Automation: nightly\nAutomation ID: a"})])
        self.write("auto-child", [message("no")], parent="auto-event")
        self.assertEqual(self.read()["records"], [])

    def test_internal_agent_message_is_not_visible(self):
        self.write("internal", [envelope("response_item", {"type": "agent_message", "id": "internal-id",
                                "author": "/root", "recipient": "/root/child", "content": [{"type": "input_text", "text": "internal"}]}),
                                envelope("event_msg", {"type": "agent_message", "message": "public progress", "phase": "commentary"})])
        self.assertEqual([r["text"] for r in self.read()["records"]], ["public progress"])

    def test_cross_thread_message_id_dedup_survives_rewritten_timestamp(self):
        original = message("same identified request")
        original["payload"]["id"] = "msg-stable"
        replay = message("same identified request", timestamp="2026-09-05T09:00:00+08:00")
        replay["payload"]["id"] = "msg-stable"
        self.write("original", [original])
        duplicate_path = self.write("fork", [replay], parent="original")
        result = self.read()
        self.assertEqual(len(result["records"]), 1)
        record = result["records"][0]
        self.assertEqual(record["thread_id"], "original")
        duplicate = record["duplicate_origins"][0]
        self.assertEqual((duplicate["thread_id"], duplicate["file"], duplicate["line"]), ("fork", str(duplicate_path), 2))
        self.assertEqual(duplicate["timestamp"], replay["timestamp"])

    def test_same_text_without_same_id_is_not_cross_thread_deduplicated(self):
        self.write("a", [message("identical")])
        self.write("b", [message("identical")])
        self.assertEqual(len(self.read()["records"]), 2)

    def test_tools_dedup_requires_call_id_kind_and_timestamp(self):
        rows = [envelope("response_item", {"type": "function_call", "name": "exec", "call_id": "c", "arguments": "run"}),
                envelope("response_item", {"type": "function_call_output", "call_id": "c", "output": "result"})]
        self.write("a", rows)
        self.write("b", rows)
        self.write("c", [{**row, "timestamp": "2026-09-05T09:00:00+08:00"} for row in rows])
        result = self.read()
        self.assertEqual(len(result["records"]), 4)
        self.assertEqual(sum(len(r.get("duplicate_origins", [])) for r in result["records"]), 2)

    def test_conflicting_identified_content_is_preserved(self):
        first, second = message("version one"), message("version two")
        first["payload"]["id"] = second["payload"]["id"] = "same-id"
        self.write("a", [first])
        self.write("b", [second])
        result = self.read()
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["context_gaps"][0]["code"], "record_identity_conflict")

    def test_structural_automation_and_parent_retained(self):
        self.write("auto", [message("run something")], source={"automation": {"id": "nightly"}})
        self.write("child", [message("normal")], parent="not-excluded")
        result = self.read()
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["parent_thread_id"], "not-excluded")

    def test_no_early_break_and_missing_context(self):
        self.write("order", [message("future", timestamp=END), message("inside"),
                             envelope("turn_context", {}), message("unknown cwd")])
        result = self.read()
        self.assertEqual([r["text"] for r in result["records"]], ["inside"])
        self.assertEqual(result["context_gaps"][0]["code"], "missing_turn_cwd")

    def test_symlink_cwd_cannot_escape_project(self):
        outside = self.home / "outside"
        outside.mkdir()
        (self.project / "link").symlink_to(outside, target_is_directory=True)
        self.write("escape", [message("no")], cwd=self.project / "link")
        self.assertEqual(self.read()["records"], [])

    def test_config_and_missing_root(self):
        self.assertTrue(reader.read_records(self.config, "2026-09-05", END)["failures"])
        self.config["session_roots"] = [str(self.home / "missing")]
        self.assertEqual(self.read()["failures"][0]["code"], "unavailable_session_root")

    def test_compaction_is_gap_not_visible_injected_summary(self):
        self.write("compact", [envelope("compacted", {"message": "internal summary"}), message("visible")])
        result = self.read()
        self.assertEqual(result["context_gaps"][0]["code"], "compacted_context")
        self.assertEqual([r["text"] for r in result["records"]], ["visible"])

    def test_cli_from_stdin_without_local_imports(self):
        self.write("a", [message("a")])
        args = [sys.executable, "-", "--source-json", json.dumps(self.config), "--start", START,
                "--end", END, "--exclude-thread", "other", "--exclude-thread", "another"]
        run = subprocess.run(args, input=SCRIPT.read_text(), text=True, capture_output=True, cwd=self.temp.name)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(json.loads(run.stdout)["records"]), 1)

    def test_only_explicit_threads_are_included(self):
        self.write("selected", [message("allowed")])
        self.write("child", [message("not implicitly allowed")], parent="selected")
        self.write("other", [message("not selected")])
        result = self.read(included_thread_ids=["selected"])
        self.assertEqual([record["text"] for record in result["records"]], ["allowed"])
        self.assertEqual(self.read(included_thread_ids=["selected"], excluded_thread_ids=["selected"])["records"], [])

    def test_cli_include_threads_from_stdin(self):
        self.write("selected", [message("allowed")])
        self.write("other", [message("not selected")])
        run = subprocess.run(
            [sys.executable, "-", "--source-json", json.dumps(self.config), "--start", START,
             "--end", END, "--include-thread", "selected"],
            input=SCRIPT.read_text(), text=True, capture_output=True, cwd=self.temp.name)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([record["thread_id"] for record in json.loads(run.stdout)["records"]], ["selected"])


if __name__ == "__main__":
    unittest.main()
