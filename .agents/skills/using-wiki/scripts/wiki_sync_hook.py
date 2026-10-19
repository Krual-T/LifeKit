#!/usr/bin/env python3
"""Adapt Codex PostToolUse to this worktree's wiki-index ensure command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def context(message: str) -> dict[str, Any]:
    # Informational feedback preserves the original tool result, including in code mode.
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}


def run_hook(payload: dict[str, Any], project_root: Path = PROJECT_ROOT) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PostToolUse" or payload.get("tool_name") not in {"apply_patch", "Bash"}:
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("PostToolUse is missing an absolute session cwd")
    # Scope follows the session worktree, not keywords in a shell command.
    if not Path(cwd).resolve().is_relative_to(project_root):
        return None
    root = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=3,
    )
    if root.returncode or Path(root.stdout.strip()).resolve() != project_root:
        return None
    command = subprocess.run(
        ["uv", "run", "--offline", "--script",
         str(project_root / ".agents/skills/using-wiki/scripts/wiki_index.py"),
         "ensure", "--project-root", str(project_root), "--timeout", "20"],
        cwd=project_root, capture_output=True, text=True, timeout=25,
    )
    try:
        result = json.loads(command.stdout)
        if not isinstance(result, dict):
            raise ValueError("expected an ensure result object")
    except ValueError as exc:
        raise RuntimeError("ensure 未返回结果：" + (command.stderr.strip() or str(exc))[:1600]) from exc
    paths = result.get("navigation_changed", [])
    if command.returncode or result.get("ok") is not True or result.get("fresh") is not True:
        message = f"Wiki 自动同步未完成（{result.get('stage', 'unknown')}）：{str(result.get('error', 'fresh=false'))[:1600]}。"
        message += f" 已生成导航：{', '.join(paths) if paths else '无已报告路径'}。"
        message += " 检索数据库若已发布则保留；修正本次问题后运行 wiki-index ensure，成功前勿将 Wiki 同步标为完成或提交本次 Wiki 成果。"
    elif paths or result.get("retrieval_changed"):
        message = "Wiki 导航与检索同步完成（fresh=true）。"
        if paths:
            message += " 生成文件：" + ", ".join(paths) + "。审阅归属后仅提交本任务文件；.okf/ 不提交。"
    else:
        return None
    if result.get("recent"):
        message += "\n当前近期入口：\n" + result["recent"]
    return context(message)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("expected a Hook event object")
        output = run_hook(payload)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        output = context(
            f"Wiki 自动同步未确认完成（Hook 启动或执行失败）：{str(exc)[:1600]}。"
            "可能已有部分导航或检索输出；请显式运行 wiki-index ensure 确认，成功前勿提交本次 Wiki 成果。"
        )
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
