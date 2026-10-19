#!/usr/bin/env python3
"""
飞书材料阅读稿生成脚本
从原始 JSON 中提取时间、地点、人物、事件，生成按地点组织的 Markdown 草稿。

用法:
    python extract_drafts.py --raw-dir ./raw --output-dir ./drafts

参数:
    --raw-dir       原始数据目录, 默认 ./raw
    --output-dir    草稿输出目录, 默认 ./drafts
"""

import argparse
import difflib
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def strip_html_tags(text: str) -> str:
    """去除 HTML 标签并解码实体"""
    if not text:
        return ""
    # 去除 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 解码 HTML 实体
    text = html.unescape(text)
    return text.strip()


def format_time(ts: str) -> str:
    """格式化时间字符串"""
    # 输入可能是 "2026-05-11 01:04" 或 ISO 格式
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return ts


def extract_message_content(msg: dict, draft_file: Path = None) -> str:
    """提取消息的可读内容，图片转为 Markdown 格式"""
    msg_type = msg.get("msg_type", "")
    content = msg.get("content", "")
    local_images = msg.get("local_images", [])

    def resolve_image_path(img_path: str) -> str:
        """将绝对路径转为相对于 draft 文件的路径，统一使用正斜杠"""
        if not draft_file or not img_path:
            return img_path
        try:
            rel = os.path.relpath(img_path, draft_file.parent)
            return rel.replace("\\", "/")
        except ValueError:
            return img_path

    if msg_type == "text":
        return strip_html_tags(content)
    elif msg_type == "post":
        # 替换 [Image: key] 为 Markdown 图片格式
        result = content
        for img in local_images:
            key = img["key"]
            path = resolve_image_path(img["path"])
            result = result.replace(f"[Image: {key}]", f"![图片]({path})")
        # 去除未下载成功的残留标记
        result = re.sub(r"\[Image:\s*[^\]]+\]\n?", "", result)
        return result.strip()
    elif msg_type == "image":
        if local_images:
            path = resolve_image_path(local_images[0]["path"])
            return f"![图片]({path})"
        return f"[图片] {content}"
    elif msg_type == "file":
        return f"[文件] {content}"
    elif msg_type == "audio":
        return "[语音]"
    elif msg_type == "video":
        return f"[视频] {content}"
    elif msg_type == "sticker":
        return "[表情]"
    elif msg_type == "interactive":
        return f"[卡片消息] {content[:100]}"
    elif msg_type == "system":
        return f"[系统] {strip_html_tags(content)}"
    elif msg_type == "share_chat":
        return f"[分享群聊] {content}"
    elif msg_type == "share_user":
        return f"[分享名片] {content}"
    else:
        return f"[{msg_type}] {strip_html_tags(str(content))[:200]}"


def parse_messages_json(path: str) -> list[dict]:
    """解析消息 JSON 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [警告] 无法解析 {path}: {e}")
        return []

    if isinstance(data, dict) and "messages" in data:
        return data["messages"]
    return []


def parse_docs_json(path: str) -> list[dict]:
    """解析文档 JSON 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [警告] 无法解析 {path}: {e}")
        return []

    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        return data["data"].get("results", [])
    return []


def load_json_file(path: Path) -> dict:
    """读取 JSON 文件，失败时返回空 dict。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"  [警告] 无法解析 {path}: {e}")
        return {}


def get_doc_content_html(content_data: dict) -> str:
    """从 docs +fetch 返回值中提取 DocxXML/HTML-like 内容。"""
    if not isinstance(content_data, dict):
        return ""
    data = content_data.get("data", {})
    if not isinstance(data, dict):
        return ""
    document = data.get("document", {})
    if isinstance(document, dict):
        return document.get("content", "") or ""
    return ""


def doc_html_to_lines(content_html: str) -> list[str]:
    """将 DocxXML/HTML-like 内容压平成适合周报阅读和 diff 的文本行。"""
    if not content_html:
        return []

    text = content_html
    text = re.sub(r"<title[^>]*>(.*?)</title>", r"\n# \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", r"\n## \2\n", text, flags=re.DOTALL)
    text = re.sub(r"<checkbox\b([^>]*)>(.*?)</checkbox>", lambda m: "\n- [" + ("x" if 'done="true"' in m.group(1) else " ") + "] " + m.group(2) + "\n", text, flags=re.DOTALL)
    text = re.sub(r"<task\b([^>]*)></task>", lambda m: "\n- [task " + (re.search(r'status="([^"]+)"', m.group(1)).group(1) if re.search(r'status="([^"]+)"', m.group(1)) else "unknown") + "]\n", text)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<tr[^>]*>", "\n", text)
    text = re.sub(r"</td>\s*<td[^>]*>", " | ", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<img\b[^>]*>", " [图片] ", text)
    text = re.sub(r"<figure\b[^>]*>.*?</figure>", " [文件/视频] ", text, flags=re.DOTALL)
    text = re.sub(r'<cite\b[^>]*user-name="([^"]+)"[^>]*/?>', r"@\1", text)
    text = re.sub(r'<cite\b[^>]*title="([^"]+)"[^>]*/?>', r"《\1》", text)
    text = re.sub(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)

    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line in {"|", "-"}:
            continue
        lines.append(line)
    return lines


def normalize_match_text(text: str) -> str:
    """归一化文本，供评论 quote 和正文行做宽松匹配。"""
    text = strip_html_tags(html.unescape(text or ""))
    return re.sub(r"\s+", "", text).lower()


def match_quote_to_doc_line(quote: str, content_item: dict | None) -> str:
    """将评论引用文本匹配到正文中的实际内容行。"""
    if not quote or not content_item:
        return ""
    quote_norm = normalize_match_text(quote)
    if not quote_norm or quote_norm in {"[图片]", "[图片选区]", "[文件]"}:
        return ""

    lines = doc_html_to_lines(get_doc_content_html(content_item.get("content", {})))
    best = ""
    best_score = 0
    for line in lines:
        line_norm = normalize_match_text(line)
        if not line_norm:
            continue
        if quote_norm in line_norm or line_norm in quote_norm:
            score = min(len(quote_norm), len(line_norm))
        else:
            common = len(os.path.commonprefix([quote_norm, line_norm]))
            score = common if common >= 12 else 0
        if score > best_score:
            best = line
            best_score = score
    return best


def resolve_local_path(local_path: str, draft_file: Path | None) -> str:
    """将本地绝对/相对路径转为相对 draft 的 Markdown 路径。"""
    if not local_path or not draft_file:
        return local_path
    try:
        rel = os.path.relpath(local_path, draft_file.parent)
        return rel.replace("\\", "/")
    except ValueError:
        return local_path.replace("\\", "/")


def get_doc_images(content_item: dict | None) -> list[dict]:
    """读取采集阶段保存的文档图片元数据。"""
    if not content_item:
        return []
    images = content_item.get("images", [])
    return images if isinstance(images, list) else []


def image_markdown(image: dict, draft_file: Path | None) -> str:
    """生成文档图片 Markdown。"""
    local_path = image.get("local_path", "")
    if not local_path or image.get("download_error"):
        return ""
    label = f"文档图片 {image.get('index', '')}".strip()
    return f"![{label}]({resolve_local_path(local_path, draft_file)})"


def assign_image_quotes(comment_rows: list[dict], images: list[dict]) -> dict[str, dict]:
    """评论接口没有图片锚点时，按图片引用评论出现顺序给出候选图片。"""
    usable_images = [image for image in images if image.get("local_path") and not image.get("download_error")]
    assignments = {}
    image_idx = 0
    for row in comment_rows:
        quote = row.get("quote", "")
        if quote in {"[图片]", "[图片选区]"} and image_idx < len(usable_images):
            assignments[row.get("row_id", "")] = usable_images[image_idx]
            image_idx += 1
    return assignments


def compact_doc_lines(lines: list[str], max_lines: int = 80) -> list[str]:
    """挑出最有信息量的正文行，避免 draft 被完整文档淹没。"""
    priority_patterns = [
        r"^##?\s",
        r"^\- \[[ x]\]",
        r"^\- \[task ",
        r"P[0-9]",
        r"bug|问题|修复|优化|升级|部署|上线|迁移|解析",
        r"@",
    ]
    selected = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in priority_patterns):
            selected.append(line)
            seen.add(line)
        if len(selected) >= max_lines:
            break

    if selected:
        return selected

    return lines[:max_lines]


def find_previous_doc_snapshot(raw_dir: Path, token: str) -> dict | None:
    """在当前周目录之前的周报 raw_doc_contents.json 中寻找同 token 的上一份快照。"""
    week_dir = raw_dir.parent
    reports_dir = week_dir.parent
    if not reports_dir.exists():
        return None

    candidates = []
    snapshot_dir = raw_dir / "_snapshots"
    if snapshot_dir.exists():
        candidates.extend((path.stat().st_mtime, path) for path in snapshot_dir.glob("raw_doc_contents_*.json"))

    for candidate in reports_dir.glob("*/raw/raw_doc_contents.json"):
        if candidate.resolve() == (raw_dir / "raw_doc_contents.json").resolve():
            continue
        try:
            if candidate.parent.parent.name >= week_dir.name:
                continue
        except Exception:
            continue
        candidates.append((candidate.stat().st_mtime, candidate))

    for _, path in sorted(candidates, reverse=True):
        data = load_json_file(path)
        for item in data.get("results", []):
            if item.get("token") == token:
                item = dict(item)
                item["_snapshot_path"] = str(path)
                return item
    return None


def build_doc_change_summary(raw_dir: Path, token: str, content_item: dict | None) -> dict:
    """生成正文变化摘要。优先输出与上一份快照的新增/删除行。"""
    if not content_item:
        return {"status": "missing_current", "lines": []}

    current_html = get_doc_content_html(content_item.get("content", {}))
    current_lines = doc_html_to_lines(current_html)
    previous = find_previous_doc_snapshot(raw_dir, token)
    if not previous:
        return {
            "status": "no_previous_snapshot",
            "lines": compact_doc_lines(current_lines),
            "current_line_count": len(current_lines),
        }

    previous_html = get_doc_content_html(previous.get("content", {}))
    previous_lines = doc_html_to_lines(previous_html)
    diff = list(difflib.unified_diff(previous_lines, current_lines, lineterm="", n=1))
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]

    return {
        "status": "diff",
        "added": compact_doc_lines(added, max_lines=80),
        "removed": compact_doc_lines(removed, max_lines=40),
        "current_excerpt": compact_doc_lines(current_lines, max_lines=80),
        "previous_snapshot": previous.get("_snapshot_path", ""),
        "current_line_count": len(current_lines),
        "previous_line_count": len(previous_lines),
    }


def parse_doc_contents(raw_dir: Path) -> dict[str, dict]:
    """按 token 索引 raw_doc_contents.json。"""
    data = load_json_file(raw_dir / "raw_doc_contents.json")
    results = data.get("results", []) if isinstance(data, dict) else []
    return {item.get("token"): item for item in results if item.get("token")}


def extract_comment_text(reply: dict) -> str:
    """提取评论/回复正文。"""
    elements = reply.get("content", {}).get("elements") or []
    parts = []
    for element in elements:
        element_type = element.get("type")
        if element_type == "text_run" and element.get("text_run"):
            parts.append(element["text_run"].get("text", ""))
        elif element_type == "docs_link" and element.get("docs_link"):
            parts.append(element["docs_link"].get("url", ""))
        elif element_type == "person" and element.get("person"):
            parts.append("@" + (element["person"].get("name") or element["person"].get("user_id", "")))
    return html.unescape("".join(parts)).strip()


def parse_doc_comments(raw_dir: Path) -> dict[str, dict]:
    """按 token 索引 raw_doc_comments.json。"""
    data = load_json_file(raw_dir / "raw_doc_comments.json")
    results = data.get("results", []) if isinstance(data, dict) else []
    return {item.get("token"): item for item in results if item.get("token")}


def parse_doc_version_records(raw_dir: Path) -> dict[str, dict]:
    """按 token 索引 raw_doc_versions.json。"""
    data = load_json_file(raw_dir / "raw_doc_versions.json")
    results = data.get("results", []) if isinstance(data, dict) else []
    return {item.get("token"): item for item in results if item.get("token")}


def collect_comment_items(comment_item: dict | None) -> list[dict]:
    """展开评论卡片和回复，返回可写入 draft 的列表。"""
    if not comment_item:
        return []

    comments_data = comment_item.get("comments", {})
    data = comments_data.get("data", {}) if isinstance(comments_data, dict) else {}
    cards = data.get("items", []) if isinstance(data, dict) else []
    rows = []
    for card in cards:
        quote = strip_html_tags(card.get("quote", "") or "")
        replies = card.get("reply_list", {}).get("replies", [])
        for reply in replies:
            text = extract_comment_text(reply)
            if not text:
                continue
            ts = reply.get("create_time") or card.get("create_time")
            time_str = ""
            if ts:
                try:
                    time_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = str(ts)
            rows.append({
                "row_id": f"{card.get('comment_id', '')}:{reply.get('reply_id', '')}",
                "time": time_str,
                "user_id": reply.get("user_id") or card.get("user_id", ""),
                "quote": quote,
                "text": text,
                "comment_id": card.get("comment_id", ""),
            })
    return sorted(rows, key=lambda row: row.get("time", ""))


def group_messages_by_date(messages: list[dict]) -> dict[str, list[dict]]:
    """按日期分组消息"""
    groups = {}
    for msg in messages:
        ts = msg.get("create_time", "")
        if isinstance(ts, str) and len(ts) >= 10:
            date = ts[:10]
        else:
            date = "未知日期"
        groups.setdefault(date, []).append(msg)
    return groups


def generate_group_draft(name: str, messages: list[dict], draft_file: Path = None) -> str:
    """生成群聊草稿 Markdown"""
    lines = [
        f"# 群聊: {name}",
        "",
        f"> 来源: 飞书群聊",
        f"> 消息总数: {len(messages)} 条",
        "",
        "---",
        "",
    ]

    by_date = group_messages_by_date(messages)
    for date in sorted(by_date.keys()):
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
        lines.append(f"## {date}（{weekday}）")
        lines.append("")

        for msg in by_date[date]:
            time_str = msg.get("create_time", "")[11:16] if len(msg.get("create_time", "")) >= 16 else ""
            sender = msg.get("sender", {})
            sender_name = sender.get("name", sender.get("id", "未知")) if isinstance(sender, dict) else "未知"
            content = extract_message_content(msg, draft_file)

            # 处理 @提及
            mentions = msg.get("mentions", [])
            if mentions:
                at_str = " ".join([f"@{m.get('name', m.get('id', ''))}" for m in mentions])
                content = f"{at_str} {content}"

            # 多行内容需要缩进以保持列表格式
            content_lines = content.split("\n")
            if len(content_lines) > 1:
                lines.append(f"- **{time_str}** {sender_name}:")
                for cl in content_lines:
                    if cl.strip():
                        lines.append(f"  {cl}")
            else:
                lines.append(f"- **{time_str}** {sender_name}: {content}")

        lines.append("")

    return "\n".join(lines)


def generate_p2p_draft(name: str, messages: list[dict], draft_file: Path = None) -> str:
    """生成私聊草稿 Markdown"""
    lines = [
        f"# 私聊: {name}",
        "",
        f"> 来源: 飞书私聊（P2P）",
        f"> 消息总数: {len(messages)} 条",
        "",
        "---",
        "",
    ]

    by_date = group_messages_by_date(messages)
    for date in sorted(by_date.keys()):
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
        lines.append(f"## {date}（{weekday}）")
        lines.append("")

        for msg in by_date[date]:
            time_str = msg.get("create_time", "")[11:16] if len(msg.get("create_time", "")) >= 16 else ""
            sender = msg.get("sender", {})
            sender_name = sender.get("name", sender.get("id", "未知")) if isinstance(sender, dict) else "未知"
            content = extract_message_content(msg, draft_file)

            # 多行内容需要缩进以保持列表格式
            content_lines = content.split("\n")
            if len(content_lines) > 1:
                lines.append(f"- **{time_str}** {sender_name}:")
                for cl in content_lines:
                    if cl.strip():
                        lines.append(f"  {cl}")
            else:
                lines.append(f"- **{time_str}** {sender_name}: {content}")

        lines.append("")

    return "\n".join(lines)


def build_user_name_map(raw_dir: Path, doc_actions: dict | None = None) -> dict[str, str]:
    """从消息发送者和文档元数据中建立 open_id -> 姓名 映射。"""
    user_names = {}
    meta = load_json_file(raw_dir / "_meta.json")
    current_user = meta.get("current_user", {}) if isinstance(meta, dict) else {}
    if current_user.get("open_id") and current_user.get("name"):
        user_names[current_user["open_id"]] = current_user["name"]

    for json_file in list(raw_dir.glob("raw_group_*.json")) + list(raw_dir.glob("raw_p2p_*.json")):
        for msg in parse_messages_json(str(json_file)):
            sender = msg.get("sender", {})
            if not isinstance(sender, dict):
                continue
            sender_id = sender.get("id")
            sender_name = sender.get("name")
            if sender_id and sender_name:
                user_names[sender_id] = sender_name

    if doc_actions:
        for info in doc_actions.values():
            if info.get("owner_id") and info.get("owner_name"):
                user_names[info["owner_id"]] = info["owner_name"]
            for action_data in info.get("actions", {}).values():
                meta_a = action_data.get("result_meta", {})
                if meta_a.get("owner_id") and meta_a.get("owner_name"):
                    user_names[meta_a["owner_id"]] = meta_a["owner_name"]
                if meta_a.get("edit_user_id") and meta_a.get("edit_user_name"):
                    user_names[meta_a["edit_user_id"]] = meta_a["edit_user_name"]

    return user_names


def display_user(user_id: str, user_names: dict[str, str]) -> str:
    """优先显示姓名，缺失时保留 open_id 作为可追溯信息。"""
    if not user_id:
        return "未知用户"
    return user_names.get(user_id, user_id)


def first_present(data: dict, keys: list[str], default: str = ""):
    """Return the first non-empty value for a list of likely field names."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def format_timestamp(value) -> str:
    """Format ISO strings, millisecond timestamps and second timestamps for drafts."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(value)

    text = str(value)
    if text.isdigit():
        return format_timestamp(int(text))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    if len(text) >= 16 and "T" in text:
        return text[:16].replace("T", " ")
    return text


def compact_value(value, max_len: int = 180) -> str:
    """Convert arbitrary API values into one readable line."""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = strip_html_tags(value)
    elif isinstance(value, list):
        parts = [compact_value(item, max_len=60) for item in value[:8]]
        text = "、".join(part for part in parts if part)
    elif isinstance(value, dict):
        for key in ("name", "summary", "title", "display_name", "email", "id", "open_id", "guid"):
            if value.get(key):
                return compact_value(value.get(key), max_len=max_len)
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def actor_from_meta(meta: dict, action_name: str = "") -> str:
    """Pick the most plausible actor field for a document action."""
    if action_name in {"created"}:
        return first_present(meta, ["owner_name", "creator_name", "edit_user_name", "operator_name"], "未知")
    if action_name in {"opened"}:
        return first_present(meta, ["last_open_user_name", "open_user_name", "edit_user_name", "owner_name"], "未知")
    return first_present(meta, ["edit_user_name", "comment_user_name", "operator_name", "owner_name"], "未知")


def doc_action_time(meta: dict, action_name: str) -> str:
    time_key = {
        "edited": "update_time_iso",
        "commented": "update_time_iso",
        "created": "create_time_iso",
        "opened": "last_open_time_iso",
        "deleted": "update_time_iso",
    }.get(action_name, "update_time_iso")
    return format_timestamp(meta.get(time_key))


def build_doc_action_events(actions: dict) -> list[dict]:
    """Normalize document search hits into a time ordered action timeline."""
    labels = {
        "created": "创建",
        "edited": "编辑",
        "commented": "评论",
        "opened": "打开",
        "deleted": "删除",
    }
    events = []
    for action_name, action_data in actions.items():
        meta_a = action_data.get("result_meta", {}) if isinstance(action_data, dict) else {}
        action_hit = action_data.get("_review_action_hit", action_data.get("_lifekernel_action_hit", {})) if isinstance(action_data, dict) else {}
        if action_hit and action_name != "created":
            precision = action_hit.get("precision")
            time_str = "本窗口内（小时级筛选）" if precision == "hour" else "本窗口内（搜索命中）"
            sort_time = format_timestamp(action_hit.get("window_start")) or "0000-00-00 00:00"
            actor = action_hit.get("actor_name") or actor_from_meta(meta_a, action_name)
        else:
            time_str = doc_action_time(meta_a, action_name) or "未知时间"
            sort_time = time_str if time_str != "未知时间" else "9999-99-99 99:99"
            actor = action_hit.get("actor_name") or actor_from_meta(meta_a, action_name)
        title = strip_html_tags(action_data.get("title_highlighted", "")) if isinstance(action_data, dict) else ""
        details = []
        if action_hit:
            details.append(
                f"搜索窗口: {action_hit.get('window_start', '未知')} 至 {action_hit.get('window_end', '未知')}"
            )
        for label, keys in [
            ("所有者", ["owner_name"]),
            ("文档当前最近编辑者", ["edit_user_name"]),
            ("文档当前更新时间", ["update_time_iso"]),
            ("文档类型", ["doc_types", "doc_type"]),
            ("URL", ["url"]),
        ]:
            value = first_present(meta_a, keys)
            if value:
                details.append(f"{label}: {compact_value(value)}")
        if title:
            details.append(f"标题: {title}")
        events.append({
            "action": action_name,
            "label": labels.get(action_name, action_name),
            "time": time_str,
            "sort_time": sort_time,
            "actor": actor,
            "details": details,
        })
    return sorted(events, key=lambda event: event["sort_time"])


def generate_doc_draft(doc_info: dict, actions: dict, raw_dir: Path, draft_file: Path | None = None, content_item: dict | None = None, comment_item: dict | None = None, user_names: dict[str, str] | None = None) -> str:
    """生成单个云文档草稿 Markdown"""
    user_names = user_names or {}
    meta = doc_info.get("result_meta", {})
    title = strip_html_tags(doc_info.get("title_highlighted", "")) or "未命名文档"
    doc_type = meta.get("doc_types") or meta.get("doc_type", "未知类型")
    url = meta.get("url", "")
    owner = meta.get("owner_name") or meta.get("owner", "未知")
    token = meta.get("token", "")

    lines = [
        f"# 云文档: {title}",
        "",
        f"> 类型: {doc_type}",
        f"> 所有者: {owner}",
        f"> Token: {token}",
        f"> URL: {url}",
        "",
        "---",
        "",
        "## 当日状态概览",
        "",
    ]

    action_events = build_doc_action_events(actions)
    action_names = set(actions.keys())
    created_event = next((event for event in action_events if event["action"] == "created"), None)
    edited_event = next((event for event in reversed(action_events) if event["action"] == "edited"), None)
    commented_event = next((event for event in reversed(action_events) if event["action"] == "commented"), None)
    lines.append(f"- 当日命中操作: {'、'.join(event['label'] for event in action_events) or '无'}")
    if created_event:
        lines.append(f"- 创建记录: **{created_event['time']}** {created_event['actor']} 创建")
    if edited_event:
        lines.append(f"- 最近编辑记录: **{edited_event['time']}** {edited_event['actor']} 编辑")
    if commented_event:
        lines.append(f"- 最近评论记录: **{commented_event['time']}** {commented_event['actor']} 评论")
    if "deleted" in action_names:
        lines.append("- 当日出现删除命中，请结合原始记录确认是否已删除或只是搜索结果命中。")

    lines.extend([
        "",
        "## 操作时间线",
        "",
    ])

    if action_events:
        for event in action_events:
            lines.append(f"- **{event['time']}** | {event['actor']} | {event['label']}本文档")
            for detail in event["details"]:
                lines.append(f"  - {detail}")
    else:
        lines.append("- 未采集到本文档的操作记录。")

    lines.extend([
        "",
        "## 文档正文变化",
        "",
    ])

    change_summary = build_doc_change_summary(raw_dir, token, content_item)
    status = change_summary.get("status")
    if status == "diff":
        previous_snapshot = change_summary.get("previous_snapshot", "")
        lines.append(f"> 对比上一份快照: `{previous_snapshot}`。以下为两次采集快照之间的文本差异，不等同于飞书完整编辑历史。")
        lines.append("")
        added = change_summary.get("added", [])
        removed = change_summary.get("removed", [])
        if added:
            lines.append("### 新增或变更后的关键内容")
            lines.append("")
            for line in added:
                lines.append(f"- {line}")
            lines.append("")
        if removed:
            lines.append("### 删除或改写前的关键内容")
            lines.append("")
            for line in removed:
                lines.append(f"- {line}")
            lines.append("")
        if not added and not removed:
            lines.append("- 未发现可读文本行差异；可能只改了图片、格式、表格结构或权限。")
            current_excerpt = change_summary.get("current_excerpt", [])
            if current_excerpt:
                lines.append("")
                lines.append("### 当前关键内容摘录")
                lines.append("")
                for line in current_excerpt:
                    lines.append(f"- {line}")
    elif status == "no_previous_snapshot":
        if created_event:
            lines.append("> 本文档当日有创建记录，但当前数据只包含采集时正文快照；以下内容可作为“创建后当前样子”的参考，不代表创建瞬间的初始内容。")
        else:
            lines.append("> 未找到上一份可比对快照；以下为当前文档中的关键内容摘录，不等同于精确新增内容。")
        lines.append("")
        for line in change_summary.get("lines", []):
            lines.append(f"- {line}")
        if not change_summary.get("lines"):
            lines.append("- 未提取到可读正文。")
    else:
        lines.append("- 未采集到本文档正文快照。")

    doc_images = get_doc_images(content_item)
    visible_images = [image for image in doc_images if image.get("local_path") and not image.get("download_error")]
    if visible_images:
        lines.extend([
            "",
            "## 文档图片素材",
            "",
        ])
        for image in visible_images[:40]:
            md = image_markdown(image, draft_file)
            if not md:
                continue
            block = image.get("block_id") or image.get("src") or ""
            meta_bits = [f"#{image.get('index')}"]
            if block:
                meta_bits.append(f"`{block}`")
            if image.get("width") and image.get("height"):
                meta_bits.append(f"{image.get('width')}x{image.get('height')}")
            lines.append(f"- {' | '.join(meta_bits)}")
            lines.append(f"  {md}")
        if len(visible_images) > 40:
            lines.append(f"- 还有 {len(visible_images) - 40} 张图片未在草稿中展开，请查看 `raw/doc_images/`。")

    comment_rows = collect_comment_items(comment_item)
    image_assignments = assign_image_quotes(comment_rows, visible_images)
    lines.extend([
        "",
        "## 评论引用与回复内容",
        "",
    ])
    if comment_rows:
        for row in comment_rows[:120]:
            time_str = row.get("time") or "未知时间"
            user = display_user(row.get("user_id", ""), user_names)
            text = row.get("text", "")
            quote = row.get("quote", "")
            if quote:
                quote = re.sub(r"\s+", " ", quote).strip()
                lines.append(f"- **{time_str}** {user}: {text}")
                lines.append(f"  - 引用: {quote[:180]}")
                matched_line = match_quote_to_doc_line(quote, content_item)
                if matched_line:
                    lines.append(f"  - 对应正文: {matched_line[:240]}")
                elif quote in {"[图片]", "[图片选区]"}:
                    image = image_assignments.get(row.get("row_id", ""))
                    if image:
                        lines.append("  - 对应图片: 评论接口未返回精确图片锚点，以下为按出现顺序匹配的候选图。")
                        lines.append(f"    {image_markdown(image, draft_file)}")
                    else:
                        lines.append("  - 对应图片: 评论接口未返回精确图片锚点，且没有可用本地图片候选。")
            else:
                lines.append(f"- **{time_str}** {user}: {text}")
        if len(comment_rows) > 120:
            lines.append(f"- 还有 {len(comment_rows) - 120} 条评论/回复未在草稿中展开，请回查 raw_doc_comments.json。")
    elif comment_item and isinstance(comment_item.get("comments"), dict) and not comment_item["comments"].get("ok", True):
        lines.append(f"- 评论采集失败: {comment_item['comments'].get('_error', '未知错误')}")
    else:
        lines.append("- 未采集到未解决评论或回复。")

    lines.append("")
    return "\n".join(lines)


def collect_items(data: dict, preferred_keys: list[str]) -> list[dict]:
    """Collect item arrays from common lark-cli JSON response shapes."""
    if not isinstance(data, dict):
        return []
    for key in preferred_keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    payload = data.get("data")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in preferred_keys + ["items", "results", "events", "tasks", "meetings"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def nested_value(data: dict, paths: list[list[str] | str], default: str = ""):
    """Read the first present nested value using path candidates."""
    if not isinstance(data, dict):
        return default
    for path in paths:
        keys = path.split(".") if isinstance(path, str) else path
        current = data
        found = True
        for key in keys:
            if not isinstance(current, dict) or current.get(key) in (None, "", [], {}):
                found = False
                break
            current = current.get(key)
        if found:
            return current
    return default


def format_lark_time(value) -> str:
    """Format Lark date/time values that may be nested objects."""
    if isinstance(value, dict):
        return format_timestamp(first_present(value, ["date_time", "datetime", "timestamp", "date", "time"], ""))
    return format_timestamp(value)


def format_time_range(start_value, end_value=None) -> str:
    """Format a compact start/end time range for list records."""
    start = format_lark_time(start_value)
    end = format_lark_time(end_value)
    if start and end:
        return f"{start} ~ {end}"
    return start or end


def format_people(value) -> str:
    """Render attendees/members/users compactly."""
    if not value:
        return ""
    if isinstance(value, dict):
        for key in ("name", "display_name", "summary", "email", "user_id", "open_id", "id"):
            if value.get(key):
                return compact_value(value.get(key), max_len=80)
        return compact_value(value, max_len=120)
    if isinstance(value, list):
        people = []
        for item in value[:12]:
            people.append(format_people(item))
        result = "、".join(person for person in people if person)
        if len(value) > 12:
            result += f" 等 {len(value)} 人"
        return result
    return compact_value(value, max_len=120)


def append_extra_fields(lines: list[str], item: dict, skip_keys: set[str], max_fields: int = 8):
    """Append useful unhandled scalar fields without dumping the full JSON."""
    emitted = 0
    for key in sorted(item.keys()):
        if key in skip_keys or key.startswith("_"):
            continue
        value = item.get(key)
        if isinstance(value, (dict, list)) and key not in {"members", "assignees", "attendees", "participants"}:
            continue
        text = compact_value(value)
        if not text:
            continue
        lines.append(f"  - {key}: {text}")
        emitted += 1
        if emitted >= max_fields:
            break


def generate_tasks_draft(raw_dir: Path) -> str:
    data = load_json_file(raw_dir / "raw_tasks.json")
    collection_meta = load_json_file(raw_dir / "_meta.json")
    window_end_text = str(collection_meta.get("end") or "")
    try:
        window_end = datetime.fromisoformat(window_end_text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        window_end = None
    tasks = collect_items(data, ["tasks", "items", "results"])
    lines = [
        "# 任务记录",
        "",
        "> 来源: `raw_tasks.json`",
        f"> 任务总数: {len(tasks)} 条",
        "",
        "---",
        "",
    ]
    if not tasks:
        lines.append("- 未采集到任务记录。")
        return "\n".join(lines)

    for item in sorted(tasks, key=lambda row: format_timestamp(nested_value(row, ["created_at", "create_time", "updated_at", "update_time", "due.time"], ""))):
        title = compact_value(nested_value(item, ["summary", "title", "name", "content", "subject"], "未命名任务"), max_len=160)
        created = format_lark_time(nested_value(item, ["created_at", "create_time", "create_time_iso"], ""))
        updated = format_lark_time(nested_value(item, ["updated_at", "update_time", "update_time_iso"], ""))
        due = format_lark_time(nested_value(item, ["due", "due_at", "due_time", "deadline"], ""))
        status = compact_value(nested_value(item, ["status", "completed", "is_done", "task_status"], ""))
        completed_at_raw = nested_value(item, ["completed_at", "complete_time", "completed_time"], "")
        completed_at = format_lark_time(completed_at_raw)
        source = compact_value(item.get("_source", ""))
        assignees = format_people(nested_value(item, ["assignees", "members", "followers", "collaborators"], ""))
        lines.append(f"- **{created or updated or due or '未知时间'}** {title}")
        if status:
            lines.append(f"  - 采集时状态: {status}")
        if completed_at:
            completion_label = "完成时间"
            try:
                completion_time = datetime.fromisoformat(str(completed_at_raw).replace("Z", "+00:00"))
                if window_end is not None and completion_time >= window_end:
                    completion_label = "完成时间（日报窗口之后）"
            except (TypeError, ValueError):
                pass
            lines.append(f"  - {completion_label}: {completed_at}")
        if assignees:
            lines.append(f"  - 相关人: {assignees}")
        if due:
            lines.append(f"  - 截止时间: {due}")
        if updated and updated != created:
            lines.append(f"  - 更新时间: {updated}")
        if source:
            lines.append(f"  - 采集来源: {source}")
        append_extra_fields(lines, item, {"summary", "title", "name", "content", "subject", "created_at", "create_time", "create_time_iso", "updated_at", "update_time", "update_time_iso", "completed_at", "complete_time", "completed_time", "due", "due_at", "due_time", "deadline", "status", "completed", "is_done", "task_status", "_source", "assignees", "members", "followers", "collaborators"})
    return "\n".join(lines)


def generate_calendar_draft(raw_dir: Path) -> str:
    data = load_json_file(raw_dir / "raw_calendar.json")
    events = collect_items(data, ["events", "items", "results"])
    lines = [
        "# 日历日程",
        "",
        "> 来源: `raw_calendar.json`",
        f"> 日程总数: {len(events)} 条",
        "",
        "---",
        "",
    ]
    if not events:
        lines.append("- 未采集到日程记录。")
        return "\n".join(lines)

    def event_sort_key(row: dict) -> str:
        return format_lark_time(nested_value(row, ["start_time", "start", "start_at", "begin_time"], ""))

    for item in sorted(events, key=event_sort_key):
        title = compact_value(nested_value(item, ["summary", "title", "name", "subject"], "未命名日程"), max_len=160)
        start = format_lark_time(nested_value(item, ["start_time", "start", "start_at", "begin_time"], ""))
        end = format_lark_time(nested_value(item, ["end_time", "end", "end_at", "finish_time"], ""))
        organizer = format_people(nested_value(item, ["organizer", "creator", "owner"], ""))
        attendees = format_people(nested_value(item, ["attendees", "participants", "members"], ""))
        location = compact_value(nested_value(item, ["location.name", "location", "meeting_room", "room"], ""))
        description = compact_value(nested_value(item, ["description", "desc", "note"], ""), max_len=260)
        time_range = start or "未知时间"
        if end:
            time_range += f" ~ {end}"
        lines.append(f"- **{time_range}** {title}")
        if organizer:
            lines.append(f"  - 组织者: {organizer}")
        if attendees:
            lines.append(f"  - 参会人: {attendees}")
        if location:
            lines.append(f"  - 地点/会议室: {location}")
        if description:
            lines.append(f"  - 描述: {description}")
        append_extra_fields(lines, item, {"summary", "title", "name", "subject", "start_time", "start", "start_at", "begin_time", "end_time", "end", "end_at", "finish_time", "organizer", "creator", "owner", "attendees", "participants", "members", "location", "meeting_room", "room", "description", "desc", "note"})
    return "\n".join(lines)


def generate_vc_draft(raw_dir: Path) -> str:
    data = load_json_file(raw_dir / "raw_vc.json")
    meetings = collect_items(data, ["meetings", "items", "results"])
    lines = [
        "# 视频会议记录",
        "",
        "> 来源: `raw_vc.json`",
        f"> 会议总数: {len(meetings)} 条",
        "",
        "---",
        "",
    ]
    if not meetings:
        lines.append("- 未采集到视频会议记录。")
        return "\n".join(lines)

    for item in sorted(meetings, key=lambda row: format_lark_time(nested_value(row, ["start_time", "start_time_iso", "begin_time", "create_time"], ""))):
        title = compact_value(nested_value(item, ["topic", "title", "summary", "name"], "未命名会议"), max_len=160)
        start = format_lark_time(nested_value(item, ["start_time", "start_time_iso", "begin_time", "create_time"], ""))
        end = format_lark_time(nested_value(item, ["end_time", "end_time_iso", "finish_time"], ""))
        host = format_people(nested_value(item, ["host", "owner", "organizer", "creator"], ""))
        participants = format_people(nested_value(item, ["participants", "attendees", "members"], ""))
        duration = compact_value(nested_value(item, ["duration", "meeting_duration"], ""))
        url = compact_value(nested_value(item, ["url", "meeting_url", "recording_url"], ""))
        time_range = start or "未知时间"
        if end:
            time_range += f" ~ {end}"
        lines.append(f"- **{time_range}** {title}")
        if host:
            lines.append(f"  - 主持/组织者: {host}")
        if participants:
            lines.append(f"  - 参会人: {participants}")
        if duration:
            lines.append(f"  - 时长: {duration}")
        if url:
            lines.append(f"  - 链接: {url}")
        append_extra_fields(lines, item, {"topic", "title", "summary", "name", "start_time", "start_time_iso", "begin_time", "create_time", "end_time", "end_time_iso", "finish_time", "host", "owner", "organizer", "creator", "participants", "attendees", "members", "duration", "meeting_duration", "url", "meeting_url", "recording_url"})
    return "\n".join(lines)


def generate_minutes_draft(raw_dir: Path) -> str:
    data = load_json_file(raw_dir / "raw_minutes.json")
    minutes = collect_items(data, ["minutes", "items", "results"])
    lines = [
        "# 妙记记录",
        "",
        "> 来源: `raw_minutes.json`",
        f"> 妙记总数: {len(minutes)} 条",
        "",
        "---",
        "",
    ]
    if not minutes:
        lines.append("- 未采集到妙记记录。")
        return "\n".join(lines)

    for item in sorted(minutes, key=lambda row: format_lark_time(nested_value(row, ["start_time", "create_time", "created_at", "update_time"], ""))):
        title = compact_value(nested_value(item, ["topic", "title", "summary", "name"], "未命名妙记"), max_len=160)
        created = format_lark_time(nested_value(item, ["create_time", "created_at", "start_time"], ""))
        updated = format_lark_time(nested_value(item, ["update_time", "updated_at"], ""))
        owner = format_people(nested_value(item, ["owner", "creator", "host"], ""))
        participants = format_people(nested_value(item, ["participants", "attendees", "members"], ""))
        duration = compact_value(nested_value(item, ["duration", "media_duration"], ""))
        url = compact_value(nested_value(item, ["url", "minutes_url", "share_url"], ""))
        lines.append(f"- **{created or updated or '未知时间'}** {title}")
        if owner:
            lines.append(f"  - 所有者/创建者: {owner}")
        if participants:
            lines.append(f"  - 参与人: {participants}")
        if duration:
            lines.append(f"  - 时长: {duration}")
        if updated and updated != created:
            lines.append(f"  - 更新时间: {updated}")
        if url:
            lines.append(f"  - 链接: {url}")
        append_extra_fields(lines, item, {"topic", "title", "summary", "name", "create_time", "created_at", "start_time", "update_time", "updated_at", "owner", "creator", "host", "participants", "attendees", "members", "duration", "media_duration", "url", "minutes_url", "share_url"})
    return "\n".join(lines)


def process_activity_sources(raw_dir: Path, output_dir: Path):
    """处理任务、日历、视频会议和妙记记录。"""
    print("\n[2/4] 处理任务、日历与会议记录...")
    generators = [
        ("tasks.md", generate_tasks_draft, raw_dir / "raw_tasks.json"),
        ("calendar.md", generate_calendar_draft, raw_dir / "raw_calendar.json"),
        ("vc.md", generate_vc_draft, raw_dir / "raw_vc.json"),
        ("minutes.md", generate_minutes_draft, raw_dir / "raw_minutes.json"),
    ]
    for filename, generator, source_path in generators:
        if not source_path.exists():
            print(f"  跳过 {filename}: 缺少 {source_path.name}")
            continue
        out_path = output_dir / filename
        md = generator(raw_dir)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  -> 保存 {out_path.name}")


def process_messages(raw_dir: Path, output_dir: Path):
    """处理群聊和私聊消息"""
    print("\n[1/4] 处理消息记录...")

    # 处理群聊
    for json_file in sorted(raw_dir.glob("raw_group_*.json")):
        name = json_file.stem.replace("raw_group_", "")
        print(f"  处理群聊: {name}")
        messages = parse_messages_json(str(json_file))
        if not messages:
            print(f"    -> 无消息，跳过")
            continue
        out_path = output_dir / f"group_{name}.md"
        md = generate_group_draft(name, messages, out_path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"    -> 保存 {out_path.name} ({len(messages)} 条)")

    # 处理私聊
    for json_file in sorted(raw_dir.glob("raw_p2p_*.json")):
        name = json_file.stem.replace("raw_p2p_", "")
        print(f"  处理私聊: {name}")
        messages = parse_messages_json(str(json_file))
        if not messages:
            print(f"    -> 无消息，跳过")
            continue
        out_path = output_dir / f"p2p_{name}.md"
        md = generate_p2p_draft(name, messages, out_path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"    -> 保存 {out_path.name} ({len(messages)} 条)")


def process_docs(raw_dir: Path, output_dir: Path):
    """处理云文档记录"""
    print("\n[3/4] 处理云文档记录...")

    # 收集所有文档的操作记录
    doc_actions = {}  # token -> {title, type, url, owner, actions: {action_name: data}}
    doc_contents = parse_doc_contents(raw_dir)
    doc_comments = parse_doc_comments(raw_dir)

    action_files = {
        "edited": raw_dir / "raw_docs_edited.json",
        "commented": raw_dir / "raw_docs_commented.json",
        "created": raw_dir / "raw_docs_created.json",
        "opened": raw_dir / "raw_docs_opened.json",
        "deleted": raw_dir / "raw_docs_deleted.json",
    }

    for action_name, json_file in action_files.items():
        if not json_file.exists():
            continue
        results = parse_docs_json(str(json_file))
        for result in results:
            meta = result.get("result_meta", {})
            token = meta.get("token", "")
            if not token:
                continue

            if token not in doc_actions:
                doc_actions[token] = {
                    "title": strip_html_tags(result.get("title_highlighted", "")) or "未命名",
                    "token": token,
                    "doc_type": meta.get("doc_types", ""),
                    "doc_types": meta.get("doc_types", ""),
                    "url": meta.get("url", ""),
                    "owner_id": meta.get("owner_id", ""),
                    "owner": meta.get("owner_name", ""),
                    "owner_name": meta.get("owner_name", ""),
                    "actions": {},
                }
            doc_actions[token]["actions"][action_name] = result

    user_names = build_user_name_map(raw_dir, doc_actions)

    # 为每个文档生成草稿
    for token, info in doc_actions.items():
        safe_title = re.sub(r'[^\w一-鿿-]', '_', info["title"])[:50]
        out_path = output_dir / f"doc_{safe_title}.md"
        md = generate_doc_draft(
            {"result_meta": info, "title_highlighted": info["title"]},
            info["actions"],
            raw_dir,
            out_path,
            doc_contents.get(token),
            doc_comments.get(token),
            user_names,
        )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"    -> 保存 {out_path.name} ({len(info['actions'])} 种操作)")

    print(f"  共处理 {len(doc_actions)} 个云文档")


def weekly_context_lines(content: str) -> list[str]:
    """Normalize a weekly context snapshot without dropping document detail."""
    lines = doc_html_to_lines(content)
    result = []
    previous = None
    for line in lines:
        if line == previous:
            continue
        result.append(line)
        previous = line
    return result


def has_meaningful_weekly_content(lines: list[str]) -> bool:
    """A bare Release heading is an entry page, not usable report context."""
    for line in lines:
        normalized = re.sub(r"^[#\s]+", "", line).strip().lower()
        if normalized and normalized != "release":
            return True
    return False


def generate_weekly_context_draft(
    title: str,
    source_name: str,
    entry: dict,
    url: str,
    selected_meta: dict | None = None,
) -> str:
    """Render an explicitly selected context document as readable material."""
    document = entry.get("document", {}) if isinstance(entry, dict) else {}
    fetch = entry.get("fetch", {}) if isinstance(entry, dict) else {}
    content = str(document.get("content") or "") if isinstance(document, dict) else ""
    lines = weekly_context_lines(content)
    meaningful = has_meaningful_weekly_content(lines)
    selected_meta = selected_meta or {}
    fetch_ok = fetch.get("ok") is not False and bool(content.strip())

    output = [
        f"# {title}",
        "",
        f"> 来源: `{source_name}`",
        f"> URL: {url or '未采集'}",
        f"> 文档 ID: {document.get('document_id') or '未采集'}",
        f"> 修订版本: {document.get('revision_id') or '未采集'}",
    ]
    if selected_meta.get("owner_name"):
        output.append(f"> 所有者: {selected_meta['owner_name']}")
    if selected_meta.get("update_time_iso"):
        output.append(f"> 更新时间: {selected_meta['update_time_iso']}")
    output.extend([
        f"> 获取状态: {'成功' if fetch_ok else '失败或缺失'}",
        f"> 可读行数: {len(lines)}",
        "",
        "---",
        "",
        "## 覆盖判断",
        "",
    ])
    if not fetch_ok:
        error = fetch.get("_error") or fetch.get("error") or "未获取到文档正文"
        output.append(f"- 文档获取失败: {error}")
    elif not meaningful:
        output.append("- 仅获取到入口标题，没有可用的周期正文；生成报告时必须记为覆盖缺口。")
    else:
        output.append("- 已获取可用正文；下方保留完整可读快照，未做主题抽样。")

    output.extend(["", "## 正文快照", ""])
    if lines:
        output.extend(lines)
    else:
        output.append("- 无可读正文。")
    return "\n".join(output) + "\n"


def process_weekly_context(raw_dir: Path, output_dir: Path) -> None:
    """Convert selected context snapshots to readable material."""
    source_path = raw_dir / "raw_weekly_context.json"
    if not source_path.exists():
        return

    print("\n[4/4] 处理选定的补充文档...")
    data = load_json_file(source_path)
    weekly_report = data.get("weekly_report", {})
    release = data.get("release", {})
    release_meta = (release.get("selected") or {}).get("result_meta", {})
    drafts = [
        (
            "weekly_report.md",
            "团队周报入口快照",
            weekly_report,
            weekly_report.get("url", ""),
            {},
        ),
        (
            "release.md",
            release.get("selected_title") or "本周 Release 快照",
            release,
            release.get("selected_url", ""),
            release_meta,
        ),
    ]
    for filename, title, entry, url, meta in drafts:
        if entry.get("enabled") is False:
            continue
        output_path = output_dir / filename
        output_path.write_text(
            generate_weekly_context_draft(title, source_path.name, entry, url, meta),
            encoding="utf-8",
        )
        print(f"  -> 保存 {output_path.name}")


def classify_draft(path: Path) -> tuple[str, str]:
    """Return stable type id and display label for a generated draft file."""
    name = path.name
    if name.startswith("group_"):
        return "group", "群聊"
    if name.startswith("p2p_"):
        return "p2p", "私聊"
    if name.startswith("doc_"):
        return "doc", "云文档"
    if name == "tasks.md":
        return "task", "任务"
    if name == "calendar.md":
        return "calendar", "日历"
    if name == "vc.md":
        return "vc", "视频会议"
    if name == "minutes.md":
        return "minutes", "妙记"
    if name in {"weekly_report.md", "release.md"}:
        return "weekly-context", "团队周上下文"
    return "other", "其他"


def markdown_inline(text: str) -> str:
    """Render a small subset of inline Markdown used by generated drafts."""
    text = html.escape(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2" loading="lazy">', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def markdown_to_html(markdown_text: str) -> str:
    """Render generated Markdown drafts to simple, safe HTML."""
    parts = []
    in_list = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        if stripped == "---":
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append("<hr>")
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            if in_list:
                parts.append("</ul>")
                in_list = False
            level = min(len(heading.group(1)) + 1, 5)
            parts.append(f"<h{level}>{markdown_inline(heading.group(2))}</h{level}>")
            continue
        if stripped.startswith(">"):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p class=\"quote\">{markdown_inline(stripped.lstrip('> ').strip())}</p>")
            continue
        item = re.match(r"^(\s*)-\s+(.*)$", raw_line)
        if item:
            if not in_list:
                parts.append("<ul>")
                in_list = True
            depth = max(0, len(item.group(1)) // 2)
            parts.append(f"<li class=\"depth-{min(depth, 3)}\">{markdown_inline(item.group(2))}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        parts.append(f"<p>{markdown_inline(stripped)}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def first_markdown_heading(markdown_text: str, fallback: str) -> str:
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def draft_summary(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">") and ("总数" in stripped or "来源" in stripped):
            return stripped.lstrip("> ").strip()
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return strip_html_tags(stripped[2:])[:120]
    return "无摘要"


def html_escape_text(value) -> str:
    return html.escape(compact_value(value, max_len=2000))


def raw_message_content(msg: dict) -> str:
    """Readable message text for the raw-driven dashboard."""
    msg_type = msg.get("msg_type", "")
    content = msg.get("content", "")
    if msg_type == "text":
        return strip_html_tags(content)
    if msg_type == "post":
        text = re.sub(r"\[Image:\s*[^\]]+\]", "[图片]", content or "")
        return strip_html_tags(text)
    if msg_type == "image":
        return "[图片]"
    if msg_type == "audio":
        return "[语音]"
    if msg_type == "file":
        return f"[文件] {strip_html_tags(content)}"
    if msg_type == "sticker":
        return "[表情]"
    return f"[{msg_type}] {strip_html_tags(str(content))}"


def html_image_strip(images: list[dict], output_dir: Path, limit: int = 4) -> str:
    parts = []
    for image in images[:limit]:
        path = image.get("path") or image.get("local_path")
        if not path:
            continue
        rel = resolve_local_path(path, output_dir / "index.html")
        parts.append(f'<img src="{html.escape(rel)}" alt="图片" loading="lazy">')
    if len(images) > limit:
        parts.append(f'<span class="more-media">+{len(images) - limit}</span>')
    return "".join(parts)


def collect_chat_sources(raw_dir: Path) -> list[dict]:
    sources = []
    for prefix, label in [("raw_group_", "群聊"), ("raw_p2p_", "私聊")]:
        for path in sorted(raw_dir.glob(f"{prefix}*.json")):
            name = path.stem.replace(prefix, "")
            messages = parse_messages_json(str(path))
            sources.append({
                "kind": "group" if prefix == "raw_group_" else "p2p",
                "label": label,
                "name": name,
                "path": path,
                "messages": messages,
            })
    return sources


def chat_stats(source: dict) -> dict:
    participants = {}
    image_count = 0
    my_count = 0
    for msg in source["messages"]:
        sender = msg.get("sender", {})
        name = sender.get("name", "未知") if isinstance(sender, dict) else "未知"
        participants[name] = participants.get(name, 0) + 1
        image_count += len(msg.get("local_images", []) or [])
        if msg.get("is_sent_by_me"):
            my_count += 1
    top = sorted(participants.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "total": len(source["messages"]),
        "my_count": my_count,
        "image_count": image_count,
        "participants": participants,
        "top": top,
    }


def collect_doc_records(raw_dir: Path) -> dict[str, dict]:
    doc_records = {}
    action_files = {
        "edited": raw_dir / "raw_docs_edited.json",
        "commented": raw_dir / "raw_docs_commented.json",
        "created": raw_dir / "raw_docs_created.json",
        "opened": raw_dir / "raw_docs_opened.json",
        "deleted": raw_dir / "raw_docs_deleted.json",
    }
    contents = parse_doc_contents(raw_dir)
    comments = parse_doc_comments(raw_dir)
    version_records = parse_doc_version_records(raw_dir)
    for action, path in action_files.items():
        if not path.exists():
            continue
        for item in parse_docs_json(str(path)):
            meta = item.get("result_meta", {})
            token = meta.get("token")
            if not token:
                continue
            record = doc_records.setdefault(token, {
                "token": token,
                "title": strip_html_tags(item.get("title_highlighted", "")) or token,
                "url": meta.get("url", ""),
                "owner": meta.get("owner_name", ""),
                "doc_type": meta.get("doc_types", ""),
                "actions": {},
                "content_item": contents.get(token),
                "comment_item": comments.get(token),
                "version_item": version_records.get(token),
            })
            record["actions"][action] = item
    return doc_records


def build_doc_card(record: dict, raw_dir: Path, output_dir: Path, idx: int) -> str:
    events = build_doc_action_events(record["actions"])
    change = build_doc_change_summary(raw_dir, record["token"], record.get("content_item"))
    comments = collect_comment_items(record.get("comment_item"))
    images = get_doc_images(record.get("content_item"))
    visible_images = [image for image in images if image.get("local_path") and not image.get("download_error")]
    event_html = "".join(
        f'<li><time>{html.escape(event["time"])}</time><strong>{html.escape(event["label"])}</strong><span>{html.escape(event["actor"])}</span></li>'
        for event in events
    ) or "<li>无操作记录</li>"

    change_bits = []
    if change.get("status") == "diff":
        added = change.get("added", [])
        removed = change.get("removed", [])
        change_bits.append(f'<div class="change-note">对比快照: <code>{html.escape(change.get("previous_snapshot", ""))}</code></div>')
        if added:
            change_bits.append('<div class="change-block added"><h4>新增或变更后</h4>' + "".join(f"<p>{html_escape_text(line)}</p>" for line in added[:12]) + "</div>")
        if removed:
            change_bits.append('<div class="change-block removed"><h4>删除或改写前</h4>' + "".join(f"<p>{html_escape_text(line)}</p>" for line in removed[:8]) + "</div>")
        if not added and not removed:
            change_bits.append('<p class="muted">未发现可读文本行差异，可能是图片、格式、表格结构或权限变化。</p>')
    elif change.get("status") == "no_previous_snapshot":
        lines = change.get("lines", [])
        change_bits.append('<div class="change-note">没有上一版快照；以下是采集时当前内容摘录，不代表完整编辑历史。</div>')
        change_bits.append('<div class="change-block"><h4>当前摘录</h4>' + "".join(f"<p>{html_escape_text(line)}</p>" for line in lines[:16]) + "</div>")
    else:
        change_bits.append('<p class="muted">未采集到正文快照。</p>')

    comment_html = "".join(
        f'<li><time>{html.escape(row.get("time") or "未知时间")}</time><strong>{html_escape_text(row.get("text", ""))}</strong><span>{html_escape_text(row.get("quote", ""))}</span></li>'
        for row in comments[:8]
    ) or '<li class="muted">无未解决评论或回复</li>'

    image_html = html_image_strip(visible_images, output_dir, limit=6)
    title = record["title"]
    text = " ".join([title, record.get("owner", ""), " ".join(row.get("text", "") for row in comments), " ".join(change.get("added", []) or change.get("lines", []) or [])]).lower()
    return f"""
    <article class="panel item-card doc-card" id="doc-{idx}" data-kind="doc" data-text="{html.escape(text)}">
      <div class="panel-head">
        <div>
          <span class="eyebrow">云文档 · {html.escape(record.get("doc_type") or "未知类型")}</span>
          <h3>{html.escape(title)}</h3>
          <p>{html.escape(record.get("owner") or "未知所有者")} · {len(events)} 个当日操作 · {len(comments)} 条评论</p>
        </div>
        <a href="{html.escape(record.get("url") or "#")}" class="open-link">打开</a>
      </div>
      <div class="doc-layout">
        <div>
          <h4>操作时间线</h4>
          <ul class="mini-timeline">{event_html}</ul>
        </div>
        <div>
          <h4>正文变化</h4>
          {''.join(change_bits)}
        </div>
      </div>
      <div class="comment-strip"><h4>评论</h4><ul>{comment_html}</ul></div>
      <div class="media-strip">{image_html}</div>
    </article>
    """


def timeline_event(time_value: str, kind: str, title: str, body: str, source: str, extra: str = "") -> dict:
    return {
        "time": format_timestamp(time_value) or "未知时间",
        "sort": format_timestamp(time_value) or "9999-99-99 99:99",
        "kind": kind,
        "title": title,
        "body": body,
        "source": source,
        "extra": extra,
    }


def generate_dashboard_html_index(output_dir: Path, raw_dir: Path):
    """Generate a raw-driven static dashboard for human inspection."""
    meta = load_json_file(raw_dir / "_meta.json")
    window_start = meta.get("start") or meta.get("week_start", "")
    window_end = meta.get("end") or meta.get("week_end", "")
    generated_at = meta.get("generated_at", "")

    chat_sources = collect_chat_sources(raw_dir)
    doc_records = collect_doc_records(raw_dir)
    tasks = collect_items(load_json_file(raw_dir / "raw_tasks.json"), ["tasks", "items", "results"])
    calendar_events = collect_items(load_json_file(raw_dir / "raw_calendar.json"), ["events", "items", "results"])
    vc_records = collect_items(load_json_file(raw_dir / "raw_vc.json"), ["meetings", "items", "results"])
    minute_records = collect_items(load_json_file(raw_dir / "raw_minutes.json"), ["minutes", "items", "results"])

    all_messages = []
    chat_cards = []
    sender_counts = {}
    for idx, source in enumerate(chat_sources):
        stats = chat_stats(source)
        top_people = "".join(f"<span>{html.escape(name)} {count}</span>" for name, count in stats["top"])
        recent = source["messages"][-5:]
        recent_html = "".join(
            f'<li><time>{html.escape((msg.get("create_time") or "")[5:16])}</time><strong>{html.escape((msg.get("sender") or {}).get("name", "未知"))}</strong><span>{html_escape_text(raw_message_content(msg))}</span></li>'
            for msg in recent
        )
        text = " ".join(raw_message_content(msg) for msg in source["messages"]).lower()
        chat_cards.append(f"""
        <article class="panel item-card source-card" data-kind="{source['kind']}" data-text="{html.escape(text)}">
          <div class="panel-head">
            <div>
              <span class="eyebrow">{html.escape(source['label'])}</span>
              <h3>{html.escape(source['name'])}</h3>
              <p>{stats['total']} 条消息 · 我发出 {stats['my_count']} 条 · {stats['image_count']} 张图片</p>
            </div>
            <a href="{html.escape('group_' + source['name'] + '.md' if source['kind'] == 'group' else 'p2p_' + source['name'] + '.md')}" class="open-link">Markdown</a>
          </div>
          <div class="people-row">{top_people}</div>
          <ul class="recent-list">{recent_html}</ul>
        </article>
        """)
        for msg in source["messages"]:
            sender = msg.get("sender", {})
            sender_name = sender.get("name", "未知") if isinstance(sender, dict) else "未知"
            sender_counts[sender_name] = sender_counts.get(sender_name, 0) + 1
            all_messages.append({**msg, "_source_name": source["name"], "_source_kind": source["kind"]})

    my_messages = [msg for msg in all_messages if msg.get("is_sent_by_me")]
    image_count = sum(len(msg.get("local_images", []) or []) for msg in all_messages)
    doc_comment_count = sum(len(collect_comment_items(record.get("comment_item"))) for record in doc_records.values())
    stat_cards = [
        ("消息", len(all_messages), f"我发出 {len(my_messages)} 条"),
        ("图片", image_count, "来自消息和文档"),
        ("任务", len(tasks), "当日创建/相关"),
        ("日程", len(calendar_events), "日历议程"),
        ("文档", len(doc_records), f"{doc_comment_count} 条评论"),
        ("会议/妙记", len(vc_records) + len(minute_records), f"VC {len(vc_records)} / 妙记 {len(minute_records)}"),
    ]
    stats_html = "".join(f'<div class="stat"><span>{label}</span><strong>{value}</strong><em>{html.escape(note)}</em></div>' for label, value, note in stat_cards)

    events = []
    for msg in all_messages:
        sender = (msg.get("sender") or {}).get("name", "未知")
        events.append(timeline_event(
            msg.get("create_time", ""),
            "chat",
            f"{sender} · {msg['_source_name']}",
            raw_message_content(msg),
            "群聊" if msg["_source_kind"] == "group" else "私聊",
            html_image_strip(msg.get("local_images", []) or [], output_dir, limit=3),
        ))
    for task in tasks:
        events.append(timeline_event(
            nested_value(task, ["created_at", "create_time", "updated_at"], ""),
            "task",
            compact_value(nested_value(task, ["summary", "title", "name"], "未命名任务"), 120),
            compact_value(task.get("url", "")),
            "任务",
        ))
    for event in calendar_events:
        events.append(timeline_event(
            format_lark_time(nested_value(event, ["start_time", "start"], "")),
            "calendar",
            compact_value(nested_value(event, ["summary", "title", "name"], "未命名日程"), 120),
            "组织者: " + format_people(nested_value(event, ["event_organizer", "organizer", "creator"], "")),
            "日历",
        ))
    for record in doc_records.values():
        for action in build_doc_action_events(record["actions"]):
            events.append(timeline_event(action["time"], "doc", record["title"], f"{action['actor']} {action['label']}了文档", "云文档"))
    events = sorted(events, key=lambda event: event["sort"])[:260]
    timeline_html = "".join(
        f'<article class="timeline-item item-card" data-kind="{event["kind"]}" data-text="{html.escape((event["title"] + " " + event["body"] + " " + event["source"]).lower())}"><time>{html.escape(event["time"])}</time><span class="type">{html.escape(event["source"])}</span><h4>{html_escape_text(event["title"])}</h4><p>{html_escape_text(event["body"])}</p><div class="media-strip">{event["extra"]}</div></article>'
        for event in events
    )

    top_senders_html = "".join(
        f'<div class="rank-row"><span>{html.escape(name)}</span><meter min="0" max="{max(sender_counts.values()) if sender_counts else 1}" value="{count}"></meter><strong>{count}</strong></div>'
        for name, count in sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    )

    task_html = "".join(
        f'<article class="work-item item-card" data-kind="task" data-text="{html.escape(compact_value(task).lower())}"><span>任务</span><h4>{html_escape_text(nested_value(task, ["summary", "title", "name"], "未命名任务"))}</h4><p>{html.escape(format_lark_time(nested_value(task, ["created_at", "create_time"], "")) or "未知时间")}</p><a href="{html.escape(task.get("url", "#"))}">打开</a></article>'
        for task in tasks
    ) or '<p class="muted">无任务记录</p>'
    calendar_html = "".join(
        f'<article class="work-item item-card" data-kind="calendar" data-text="{html.escape(compact_value(event).lower())}"><span>日程</span><h4>{html_escape_text(nested_value(event, ["summary", "title", "name"], "未命名日程"))}</h4><p>{html.escape(format_lark_time(nested_value(event, ["start_time", "start"], "")))} · {html_escape_text(format_people(nested_value(event, ["event_organizer", "organizer"], "")))}</p><a href="{html.escape(event.get("app_link", "#"))}">打开</a></article>'
        for event in calendar_events
    ) or '<p class="muted">无日程记录</p>'
    vc_html = "".join(
        f'<article class="work-item item-card" data-kind="vc" data-text="{html.escape(compact_value(record).lower())}"><span>视频会议</span><h4>{html_escape_text(first_present(record, ["display_info", "topic", "title", "name"], "未命名会议"))}</h4><p>{html_escape_text(nested_value(record, ["meta_data.description", "description", "start_time"], ""))}</p><a href="{html.escape(nested_value(record, ["meta_data.app_link", "url", "meeting_url"], "#"))}">打开</a></article>'
        for record in vc_records
    ) or '<p class="muted">无视频会议记录</p>'
    minutes_html = "".join(
        f'<article class="work-item item-card" data-kind="minutes" data-text="{html.escape(compact_value(record).lower())}"><span>妙记</span><h4>{html_escape_text(first_present(record, ["title", "topic", "summary", "name"], "未命名妙记"))}</h4><p>{html.escape(format_lark_time(nested_value(record, ["create_time", "created_at", "start_time"], "")) or "未知时间")}</p><a href="{html.escape(nested_value(record, ["url", "minutes_url", "share_url"], "#"))}">打开</a></article>'
        for record in minute_records
    ) or '<p class="muted">无妙记记录</p>'
    doc_cards_html = "".join(build_doc_card(record, raw_dir, output_dir, idx) for idx, record in enumerate(doc_records.values()))

    filters = [
        ("all", "全部", len(events) + len(doc_records) + len(chat_sources) + len(tasks) + len(calendar_events)),
        ("chat", "聊天", len(all_messages)),
        ("group", "群聊源", sum(1 for source in chat_sources if source["kind"] == "group")),
        ("p2p", "私聊源", sum(1 for source in chat_sources if source["kind"] == "p2p")),
        ("doc", "文档", len(doc_records)),
        ("task", "任务", len(tasks)),
        ("calendar", "日历", len(calendar_events)),
        ("vc", "视频会议", len(vc_records)),
        ("minutes", "妙记", len(minute_records)),
    ]
    filter_buttons = "".join(
        f'<button class="filter{" active" if kind == "all" else ""}" data-kind="{kind}">{label}<span>{count}</span></button>'
        for kind, label, count in filters if count or kind == "all"
    )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>周报信息仪表盘</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #667085; --line: #d8dee8; --accent: #1769e0; --accent-soft: #eaf2ff;
      --green: #16845b; --orange: #a15c07; --red: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); letter-spacing: 0; }}
    .app {{ max-width: 1440px; margin: 0 auto; padding: 22px; }}
    .hero {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 18px; align-items: stretch; }}
    .hero-main, .control-panel, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    .hero-main {{ padding: 22px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; line-height: 1.2; }}
    .subtle, .muted, .hero p, .panel p {{ color: var(--muted); }}
    .stat-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }}
    .stat {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; }}
    .stat span, .eyebrow {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
    .stat strong {{ display: block; font-size: 24px; margin: 5px 0; }}
    .stat em {{ color: var(--muted); font-style: normal; font-size: 12px; }}
    .control-panel {{ padding: 16px; }}
    .search {{ width: 100%; height: 38px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; }}
    .filters {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }}
    .filter {{ min-height: 34px; display: flex; justify-content: space-between; align-items: center; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; padding: 6px 9px; }}
    .filter.active {{ border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }}
    .section {{ margin-top: 18px; }}
    .section-title {{ display: flex; justify-content: space-between; align-items: end; margin: 0 0 10px; }}
    .section-title h2 {{ margin: 0; font-size: 20px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .panel {{ padding: 16px; overflow: hidden; }}
    .panel-head {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .panel h3, .work-item h4, .timeline-item h4 {{ margin: 4px 0 6px; line-height: 1.3; }}
    .open-link, .work-item a {{ color: var(--accent); text-decoration: none; font-size: 13px; white-space: nowrap; }}
    .people-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }}
    .people-row span, .type {{ background: #eef2f7; border-radius: 999px; padding: 3px 8px; font-size: 12px; color: #344054; }}
    .recent-list, .mini-timeline, .comment-strip ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
    .recent-list li, .mini-timeline li, .comment-strip li {{ display: grid; grid-template-columns: 92px 110px minmax(0, 1fr); gap: 8px; font-size: 13px; border-top: 1px solid #eef2f7; padding-top: 8px; }}
    time {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
    .dashboard-grid {{ display: grid; grid-template-columns: minmax(0, 1.3fr) 360px; gap: 14px; }}
    .timeline-list {{ display: grid; gap: 10px; max-height: 760px; overflow: auto; padding-right: 4px; }}
    .timeline-item {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .timeline-item p {{ margin: 6px 0 0; line-height: 1.5; overflow-wrap: anywhere; }}
    .rank-row {{ display: grid; grid-template-columns: 92px 1fr 36px; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; }}
    meter {{ width: 100%; height: 8px; }}
    .doc-layout {{ display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 14px; }}
    .change-block {{ background: #fbfcfe; border: 1px solid #eef2f7; border-radius: 8px; padding: 10px; margin: 8px 0; }}
    .change-block.added {{ border-left: 3px solid var(--green); }}
    .change-block.removed {{ border-left: 3px solid var(--orange); }}
    .change-block h4, .comment-strip h4 {{ margin: 0 0 8px; }}
    .change-block p {{ margin: 6px 0; line-height: 1.5; }}
    .change-note {{ color: var(--muted); font-size: 13px; margin: 6px 0; }}
    code {{ background: #eef2f7; border-radius: 4px; padding: 1px 4px; }}
    .media-strip {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }}
    .media-strip img {{ width: 118px; height: 84px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); }}
    .more-media {{ display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 84px; border-radius: 6px; background: #eef2f7; color: var(--muted); }}
    .work-list {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .work-item, .quiet-source {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fff; }}
    .work-item span {{ color: var(--accent); font-size: 12px; font-weight: 600; }}
    .quiet-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }}
    .quiet-source strong {{ font-size: 22px; }}
    .empty {{ display: none; padding: 24px; text-align: center; color: var(--muted); }}
    @media (max-width: 900px) {{
      .hero, .dashboard-grid, .doc-layout, .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
      .stat-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .work-list {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <section class="hero">
      <div class="hero-main">
        <span class="eyebrow">RAW DRIVEN DASHBOARD</span>
        <h1>周报信息仪表盘</h1>
        <p>时间范围: {html.escape(window_start or '?')} ~ {html.escape(window_end or '?')} · 采集时间: {html.escape(generated_at or '?')}</p>
        <div class="stat-grid">{stats_html}</div>
      </div>
      <div class="control-panel">
      <input id="search" class="search" type="search" placeholder="搜索人名、项目、Bug、文档...">
      <div class="filters">{''.join(filter_buttons)}</div>
      </div>
    </section>

    <section class="section dashboard-grid">
      <div>
        <div class="section-title"><h2>统一时间线</h2><span class="subtle">消息、任务、日程、文档操作按时间合并</span></div>
        <div class="timeline-list" id="cards">{timeline_html}</div>
      </div>
      <aside class="panel">
        <div class="section-title"><h2>参与者热度</h2></div>
        {top_senders_html}
      </aside>
    </section>

    <section class="section">
      <div class="section-title"><h2>聊天来源</h2><span class="subtle">每个群/私聊的消息量、我的参与度、最近片段</span></div>
      <div class="grid-2">{''.join(chat_cards)}</div>
    </section>

    <section class="section">
      <div class="section-title"><h2>云文档变化</h2><span class="subtle">直接基于文档 raw、正文快照和评论 raw</span></div>
      <div class="doc-list">{doc_cards_html}</div>
    </section>

    <section class="section">
      <div class="section-title"><h2>任务、日程与会议</h2><span class="subtle">用于补齐工作事实，不再只藏在 raw JSON</span></div>
      <div class="grid-2">
        <div class="panel"><h3>任务</h3><div class="work-list">{task_html}</div></div>
        <div class="panel"><h3>日程</h3><div class="work-list">{calendar_html}</div></div>
        <div class="panel"><h3>视频会议</h3><div class="work-list">{vc_html}</div></div>
        <div class="panel"><h3>妙记</h3><div class="work-list">{minutes_html}</div></div>
      </div>
    </section>
    <div id="empty" class="empty">没有匹配的记录。</div>
  </div>
  <script>
    const search = document.querySelector('#search');
    const filters = [...document.querySelectorAll('.filter')];
    const cards = [...document.querySelectorAll('.item-card')];
    const empty = document.querySelector('#empty');
    let activeKind = 'all';

    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      cards.forEach(card => {{
        const kindOk = activeKind === 'all' || card.dataset.kind === activeKind;
        const textOk = !query || card.dataset.text.includes(query);
        const show = kindOk && textOk;
        card.style.display = show ? '' : 'none';
        if (show) visible += 1;
      }});
      empty.style.display = visible ? 'none' : 'block';
    }}

    search.addEventListener('input', applyFilters);
    filters.forEach(button => {{
      button.addEventListener('click', () => {{
        filters.forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        activeKind = button.dataset.kind;
        applyFilters();
      }});
    }});
  </script>
</body>
</html>
"""
    out_path = output_dir / "index.html"
    out_path.write_text(page, encoding="utf-8")
    print(f"  -> 保存 {out_path.name} (HTML 可视化总览)")


def doc_content_to_html(content_item: dict | None, output_dir: Path) -> str:
    """Render DocxXML/HTML-like content into inspectable HTML for the location viewer."""
    if not content_item:
        return '<p class="muted">未采集到正文快照。</p>'
    content_html = get_doc_content_html(content_item.get("content", {}))
    if not content_html:
        return '<p class="muted">正文快照为空。</p>'

    image_by_src = {}
    for image in get_doc_images(content_item):
        local_path = image.get("local_path")
        if not local_path or image.get("download_error"):
            continue
        src = image.get("src") or image.get("block_id") or f"image-{image.get('index')}"
        image_by_src[src] = resolve_local_path(local_path, output_dir / "index.html")

    def replace_img(match):
        tag = match.group(0)
        attrs = dict(re.findall(r'([:\w-]+)="([^"]*)"', tag))
        src = attrs.get("src") or attrs.get("id") or ""
        local = image_by_src.get(src)
        if not local and image_by_src:
            try:
                local = list(image_by_src.values())[int(attrs.get("index", "1")) - 1]
            except Exception:
                local = ""
        if local:
            alt = html.escape(attrs.get("name", "文档图片"))
            src = html.escape(local)
            return f'<a href="{src}" target="_blank" rel="noreferrer"><img src="{src}" alt="{alt}" loading="lazy"></a>'
        return '<span class="doc-image-missing">[图片]</span>'

    text = content_html
    text = re.sub(r"<title[^>]*>(.*?)</title>", r"<h1>\1</h1>", text, flags=re.DOTALL)
    text = re.sub(r"<checkbox\b([^>]*)>(.*?)</checkbox>", lambda m: '<label class="doc-check"><input type="checkbox" disabled ' + ("checked" if 'done=\"true\"' in m.group(1) else "") + "> " + m.group(2) + "</label>", text, flags=re.DOTALL)
    text = re.sub(r"<task\b([^>]*)></task>", lambda m: '<span class="doc-task">task ' + html.escape(re.search(r'status="([^"]+)"', m.group(1)).group(1) if re.search(r'status="([^"]+)"', m.group(1)) else "unknown") + "</span>", text)
    text = re.sub(r"<img\b[^>]*>", replace_img, text, flags=re.IGNORECASE)
    text = re.sub(r'<cite\b[^>]*user-name="([^"]+)"[^>]*/?>', r'<span class="mention">@\1</span>', text)
    text = re.sub(r'<cite\b[^>]*title="([^"]+)"[^>]*/?>', r'<span class="doc-ref">《\1》</span>', text)
    text = re.sub(r'<a\b([^>]*)href="([^"]+)"([^>]*)>(.*?)</a>', r'<a href="\2">\4</a>', text, flags=re.DOTALL)
    allowed = {
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
        "strong", "b", "em", "i", "u", "s", "a", "img", "blockquote", "pre", "code", "span", "label", "input"
    }

    def sanitize_tag(match):
        tag = match.group(1)
        name = tag.strip().split()[0].strip("/").lower()
        if name in allowed:
            return "<" + tag + ">"
        return ""

    return re.sub(r"<([^>]+)>", sanitize_tag, text)


def extract_drive_version_items(version_item: dict | None) -> list[dict]:
    if not isinstance(version_item, dict):
        return []
    versions = version_item.get("versions", {})
    if not isinstance(versions, dict):
        return []
    if versions.get("ok") is False or versions.get("_error") or versions.get("error"):
        return []
    data = versions.get("data", {})
    if isinstance(data, dict):
        for key in ("versions", "items", "files", "history"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    for key in ("versions", "items", "files", "history"):
        value = versions.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def describe_drive_version_error(version_item: dict | None) -> str:
    if not isinstance(version_item, dict):
        return ""
    versions = version_item.get("versions", {})
    if not isinstance(versions, dict):
        return ""
    if versions.get("code") == 0 and not versions.get("_error") and not versions.get("error"):
        return ""
    if versions.get("ok") is not False and not versions.get("_error") and not versions.get("error"):
        return ""
    error = versions.get("error", {})
    if isinstance(error, dict):
        return error.get("message") or error.get("type") or json.dumps(error, ensure_ascii=False)
    return versions.get("_error") or "飞书版本接口不可用"


def drive_version_label(item: dict, idx: int) -> str:
    name = first_present(item, ["name", "version", "version_id", "id", "tag"], "")
    time_text = format_lark_time(first_present(item, ["update_time", "created_time", "create_time", "modified_time"], ""))
    if name and time_text:
        return f"飞书版本 {name} · {time_text}"
    if name:
        return f"飞书版本 {name}"
    if time_text:
        return f"飞书版本 {time_text}"
    return f"飞书版本 {idx + 1}"


def collect_doc_versions(raw_dir: Path, output_dir: Path, token: str, current_item: dict | None, version_item: dict | None = None) -> list[dict]:
    versions = []
    snapshot_dir = raw_dir / "_snapshots"
    if snapshot_dir.exists():
        for path in sorted(snapshot_dir.glob("raw_doc_contents_*.json")):
            data = load_json_file(path)
            for item in data.get("results", []):
                if item.get("token") == token:
                    versions.append({
                        "label": path.stem.replace("raw_doc_contents_", "快照 "),
                        "source": str(path),
                        "html": doc_content_to_html(item, output_dir),
                        "kind": "local_snapshot",
                    })
                    break
    if current_item:
        versions.append({
            "label": "当前采集",
            "source": str(raw_dir / "raw_doc_contents.json"),
            "html": doc_content_to_html(current_item, output_dir),
            "kind": "current_snapshot",
        })
    drive_versions = extract_drive_version_items(version_item)
    for idx, item in enumerate(drive_versions):
        versions.append({
            "label": drive_version_label(item, idx),
            "source": str(raw_dir / "raw_doc_versions.json"),
            "kind": "drive_version",
            "html": '<p class="muted">这是飞书 Drive 版本元数据。该版本未下载为可渲染 DocxXML，正文仍以当前采集快照显示。</p>',
            "meta": item,
        })
    drive_error = describe_drive_version_error(version_item)
    if drive_error:
        versions.append({
            "label": "飞书版本接口不可用",
            "source": str(raw_dir / "raw_doc_versions.json"),
            "kind": "drive_version_error",
            "html": f'<p class="muted">飞书版本历史接口返回错误：{html.escape(compact_value(drive_error, 500))}</p>',
        })
    return versions or [{"label": "无正文", "source": "", "html": '<p class="muted">未采集到正文快照。</p>'}]


def make_chat_location(source: dict, output_dir: Path, idx: int) -> dict:
    messages = []
    for msg in source["messages"]:
        sender = msg.get("sender", {}) if isinstance(msg.get("sender"), dict) else {}
        images = []
        for image in msg.get("local_images", []) or []:
            path = image.get("path")
            if path:
                images.append(resolve_local_path(path, output_dir / "index.html"))
        messages.append({
            "time": msg.get("create_time", ""),
            "sender": sender.get("name", "未知"),
            "mine": bool(msg.get("is_sent_by_me")),
            "type": msg.get("msg_type", ""),
            "text": raw_message_content(msg),
            "images": images,
            "link": msg.get("message_app_link", ""),
        })
    label = "群聊" if source["kind"] == "group" else "私聊"
    return {
        "id": f"chat-{idx}",
        "type": "chat",
        "kind": source["kind"],
        "label": label,
        "title": source["name"],
        "subtitle": f"{len(messages)} 条消息",
        "messages": messages,
    }


def make_doc_location(record: dict, raw_dir: Path, output_dir: Path, idx: int) -> dict:
    comments = collect_comment_items(record.get("comment_item"))
    return {
        "id": f"doc-{idx}",
        "type": "doc",
        "label": "文档",
        "title": record["title"],
        "subtitle": f"当前正文 · {len(comments)} 条评论",
        "url": record.get("url", ""),
        "owner": record.get("owner", ""),
        "currentHtml": doc_content_to_html(record.get("content_item"), output_dir),
        "comments": comments,
    }


def list_record_title(item: dict, item_type: str) -> str:
    if item_type == "vc":
        display = strip_html_tags(str(first_present(item, ["display_info"], "")))
        if display:
            return compact_value(display.splitlines()[0], 300)
    return compact_value(nested_value(item, [
        "summary", "title", "topic", "name", "display_info", "meta_data.title"
    ], "未命名"), 300)


def list_record_time(item: dict, item_type: str) -> str:
    if item_type == "calendar":
        return format_time_range(nested_value(item, ["start_time"], ""), nested_value(item, ["end_time"], ""))
    if item_type == "task":
        created = format_lark_time(nested_value(item, ["created_at", "create_time"], ""))
        completed = format_lark_time(nested_value(item, ["completed_at"], ""))
        if completed:
            return f"创建 {created} · 完成 {completed}" if created else f"完成 {completed}"
        return f"创建 {created}" if created else ""
    return format_time_range(nested_value(item, [
        "start_time", "start", "created_at", "create_time", "update_time", "meta_data.start_time"
    ], ""), nested_value(item, ["end_time", "end", "meta_data.end_time"], ""))


def list_record_detail(item: dict, item_type: str) -> str:
    details = []
    if item_type == "calendar":
        organizer = nested_value(item, ["event_organizer.display_name"], "")
        rsvp = nested_value(item, ["self_rsvp_status"], "")
        meeting = nested_value(item, ["vchat.meeting_url"], "")
        if organizer:
            details.append(f"组织者: {compact_value(organizer)}")
        if rsvp:
            details.append(f"RSVP: {compact_value(rsvp)}")
        if meeting:
            details.append(f"会议链接: {meeting}")
    elif item_type == "task":
        status = nested_value(item, ["status"], "")
        source = nested_value(item, ["_source"], "")
        members = format_people(nested_value(item, ["members"], ""))
        if status:
            details.append(f"状态: {compact_value(status)}")
        if source:
            details.append(f"来源: {compact_value(source)}")
        if members:
            details.append(f"成员: {members}")
    elif item_type == "vc":
        description = nested_value(item, ["meta_data.description"], "")
        display = strip_html_tags(str(first_present(item, ["display_info"], "")))
        rest = "\n".join(line for line in display.splitlines()[1:] if line.strip())
        if description:
            details.append(compact_value(description, 300))
        if rest:
            details.append(compact_value(rest, 500))
    else:
        value = nested_value(item, ["description", "meta_data.description"], "")
        if value:
            details.append(compact_value(value, 500))
    if not details:
        fallback = nested_value(item, ["description", "meta_data.description", "url", "app_link"], "")
        if fallback:
            details.append(compact_value(fallback, 500))
    return " · ".join(details)


def make_list_location(location_id: str, label: str, title: str, items: list[dict], item_type: str) -> dict:
    rendered = []
    for item in items:
        rendered.append({
            "title": list_record_title(item, item_type),
            "time": list_record_time(item, item_type),
            "detail": list_record_detail(item, item_type),
            "link": nested_value(item, ["url", "app_link", "meta_data.app_link", "meeting_url", "vchat.meeting_url"], ""),
        })
    return {
        "id": location_id,
        "type": "list",
        "kind": item_type,
        "label": label,
        "title": title,
        "subtitle": f"{len(rendered)} 条记录",
        "items": rendered,
    }


def generate_html_index(output_dir: Path, raw_dir: Path):
    """Generate a location-first static viewer from raw data."""
    meta = load_json_file(raw_dir / "_meta.json")
    locations = []
    for idx, source in enumerate(collect_chat_sources(raw_dir)):
        locations.append(make_chat_location(source, output_dir, idx))
    doc_records = collect_doc_records(raw_dir)
    for idx, record in enumerate(doc_records.values()):
        locations.append(make_doc_location(record, raw_dir, output_dir, idx))

    tasks = collect_items(load_json_file(raw_dir / "raw_tasks.json"), ["tasks", "items", "results"])
    calendar_events = collect_items(load_json_file(raw_dir / "raw_calendar.json"), ["events", "items", "results"])
    vc_records = collect_items(load_json_file(raw_dir / "raw_vc.json"), ["meetings", "items", "results"])
    minute_records = collect_items(load_json_file(raw_dir / "raw_minutes.json"), ["minutes", "items", "results"])
    locations.extend([
        make_list_location("tasks", "任务", "任务记录", tasks, "task"),
        make_list_location("calendar", "日历", "日历日程", calendar_events, "calendar"),
        make_list_location("vc", "会议", "视频会议", vc_records, "vc"),
        make_list_location("minutes", "妙记", "妙记记录", minute_records, "minutes"),
    ])

    data_json = json.dumps({
        "meta": {
            "weekStart": meta.get("start") or meta.get("week_start", ""),
            "weekEnd": meta.get("end") or meta.get("week_end", ""),
            "generatedAt": meta.get("generated_at", ""),
        },
        "locations": locations,
    }, ensure_ascii=False)
    safe_data_json = data_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>周报地点浏览</title>
  <style>
    :root {{
      --bg: #f5f6f8; --panel: #fff; --text: #1f2328; --muted: #667085; --line: #d8dee8;
      --accent: #1769e0; --accent-soft: #eaf2ff; --mine: #dcf7e9; --other: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; letter-spacing: 0; }}
    .app {{ display: grid; grid-template-columns: 320px minmax(0, 1fr); height: 100vh; }}
    .sidebar {{ border-right: 1px solid var(--line); background: #fbfcfe; padding: 16px; overflow: auto; }}
    .brand h1 {{ margin: 0; font-size: 22px; }}
    .brand p {{ margin: 6px 0 14px; color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .search {{ width: 100%; height: 36px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; background: #fff; }}
    .type-tabs {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin: 12px 0; }}
    .type-tabs button {{ border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 6px; cursor: pointer; }}
    .type-tabs button.active {{ border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }}
    .nav {{ display: grid; gap: 6px; }}
    .nav button {{ text-align: left; border: 1px solid transparent; background: #fff; border-radius: 8px; padding: 10px; cursor: pointer; }}
    .nav button.active {{ border-color: var(--accent); background: var(--accent-soft); }}
    .nav strong {{ display: block; font-size: 14px; line-height: 1.3; }}
    .nav span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .content {{ display: grid; grid-template-rows: auto minmax(0, 1fr); min-width: 0; }}
    .topbar {{ border-bottom: 1px solid var(--line); background: var(--panel); padding: 14px 18px; display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    .topbar h2 {{ margin: 0; font-size: 20px; }}
    .topbar p {{ margin: 4px 0 0; color: var(--muted); }}
    .open-link {{ color: var(--accent); text-decoration: none; white-space: nowrap; }}
    .viewer {{ overflow: auto; padding: 18px; }}
    .chat-view {{ max-width: 980px; margin: 0 auto; display: grid; gap: 10px; }}
    .bubble-row {{ display: flex; }}
    .bubble-row.mine {{ justify-content: flex-end; }}
    .bubble {{ max-width: min(680px, 78%); border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; background: var(--other); }}
    .bubble-row.mine .bubble {{ background: var(--mine); }}
    .bubble-meta {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .bubble-text {{ line-height: 1.55; overflow-wrap: anywhere; }}
    .bubble-text p {{ margin: 0 0 7px; }}
    .bubble-text p:last-child {{ margin-bottom: 0; }}
    .bubble-text ul, .bubble-text ol {{ margin: 6px 0; padding-left: 20px; }}
    .bubble-text blockquote {{ margin: 6px 0; padding-left: 9px; border-left: 3px solid var(--line); color: var(--muted); }}
    .bubble-text pre {{ margin: 8px 0; padding: 8px; overflow: auto; background: #f2f4f7; border-radius: 6px; }}
    .bubble-text code {{ background: #f2f4f7; border-radius: 4px; padding: 1px 4px; }}
    .bubble-link-card {{ display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 9px; align-items: center; margin-top: 8px; padding: 9px; border: 1px solid var(--line); border-radius: 8px; background: #f8fafc; color: var(--text); text-decoration: none; }}
    .bubble-link-icon {{ width: 34px; height: 34px; border-radius: 7px; display: grid; place-items: center; background: #e8f1ff; color: var(--accent); font-weight: 700; }}
    .bubble-link-card strong {{ display: block; font-size: 13px; line-height: 1.3; }}
    .bubble-link-card span {{ display: block; margin-top: 4px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
    .bubble-media {{ display: grid; grid-template-columns: repeat(2, minmax(160px, 320px)); gap: 8px; margin-top: 8px; }}
    .bubble-media.single {{ grid-template-columns: minmax(220px, 520px); }}
    .bubble-media img {{ width: 100%; max-height: 520px; object-fit: contain; border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .doc-shell {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; height: 100%; }}
    .doc-main, .doc-side, .list-view {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    .doc-body {{ padding: 22px; line-height: 1.7; }}
    .doc-body img {{ max-width: 100%; border: 1px solid var(--line); border-radius: 6px; }}
    .doc-body table {{ border-collapse: collapse; max-width: 100%; }}
    .doc-body td, .doc-body th {{ border: 1px solid var(--line); padding: 6px; }}
    .mention {{ color: var(--accent); font-weight: 600; }}
    .doc-check {{ display: block; margin: 6px 0; }}
    .doc-side {{ padding: 14px; overflow: auto; display: grid; align-content: start; gap: 18px; }}
    .doc-side h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .comment {{ border-top: 1px solid var(--line); padding: 10px 0; }}
    .comment:first-of-type {{ border-top: 0; }}
    .comment time {{ color: var(--muted); font-size: 12px; }}
    .quote {{ color: var(--muted); border-left: 3px solid var(--line); padding-left: 8px; margin-top: 6px; }}
    .list-view {{ padding: 14px; display: grid; gap: 10px; }}
    .record {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fff; }}
    .record h3 {{ margin: 0 0 6px; }}
    .record p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    @media (max-width: 900px) {{
      .app {{ grid-template-columns: 1fr; height: auto; }}
      .sidebar {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .doc-shell {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <h1>周报地点浏览</h1>
        <p id="meta"></p>
      </div>
      <input id="search" class="search" type="search" placeholder="搜索地点、人员、内容">
      <div class="type-tabs" id="tabs"></div>
      <div class="nav" id="nav"></div>
    </aside>
    <main class="content">
      <header class="topbar">
        <div><h2 id="title"></h2><p id="subtitle"></p></div>
        <a id="openLink" class="open-link" href="#" target="_blank" rel="noreferrer"></a>
      </header>
      <section class="viewer" id="viewer"></section>
    </main>
  </div>
  <script id="report-data" type="application/json">{safe_data_json}</script>
  <script>
    const DATA = JSON.parse(document.getElementById('report-data').textContent);
    const labels = {{ all: '全部', chat: '聊天', doc: '文档', list: '其他' }};
    let activeType = 'all';
    let activeId = DATA.locations[0]?.id;
    const $ = (id) => document.getElementById(id);
    $('meta').textContent = `${{DATA.meta.weekStart || '?'}} ~ ${{DATA.meta.weekEnd || '?'}} · ${{DATA.locations.length}} 个地点`;

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, '&#96;');
    }}
    function inlineMarkdown(text) {{
      let out = escapeHtml(text);
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
      out = out.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      out = out.replace(/(^|[^\\*])\\*([^*]+)\\*/g, '$1<em>$2</em>');
      out = out.replace(/~~([^~]+)~~/g, '<s>$1</s>');
      out = out.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
      out = out.replace(/(^|[\\s(])(https?:\\/\\/[^\\s<)]+)/g, (m, lead, url) => `${{lead}}<a href="${{escapeAttr(url)}}" target="_blank" rel="noreferrer">${{escapeHtml(url)}}</a>`);
      return out;
    }}
    function renderMarkdown(text) {{
      const src = String(text || '').replace(/\\r\\n/g, '\\n');
      const blocks = [];
      const codePattern = /```([\\s\\S]*?)```/g;
      let last = 0;
      let match;
      while ((match = codePattern.exec(src))) {{
        if (match.index > last) blocks.push({{ type: 'text', value: src.slice(last, match.index) }});
        blocks.push({{ type: 'code', value: match[1].replace(/^\\w+\\n/, '') }});
        last = codePattern.lastIndex;
      }}
      if (last < src.length) blocks.push({{ type: 'text', value: src.slice(last) }});
      return blocks.map(block => {{
        if (block.type === 'code') return `<pre><code>${{escapeHtml(block.value.trim())}}</code></pre>`;
        const lines = block.value.split('\\n');
        const htmlParts = [];
        let list = null;
        function flushList() {{
          if (!list) return;
          htmlParts.push(`<${{list.type}}>${{list.items.map(item => `<li>${{inlineMarkdown(item)}}</li>`).join('')}}</${{list.type}}>`);
          list = null;
        }}
        for (const line of lines) {{
          if (!line.trim()) {{ flushList(); continue; }}
          const ordered = line.match(/^\\s*\\d+\\.\\s+(.+)$/);
          const unordered = line.match(/^\\s*[-*]\\s+(.+)$/);
          if (ordered || unordered) {{
            const type = ordered ? 'ol' : 'ul';
            if (!list || list.type !== type) {{ flushList(); list = {{ type, items: [] }}; }}
            list.items.push((ordered || unordered)[1]);
            continue;
          }}
          flushList();
          if (/^\\s*>\\s+/.test(line)) {{
            htmlParts.push(`<blockquote>${{inlineMarkdown(line.replace(/^\\s*>\\s+/, ''))}}</blockquote>`);
          }} else {{
            htmlParts.push(`<p>${{inlineMarkdown(line)}}</p>`);
          }}
        }}
        flushList();
        return htmlParts.join('');
      }}).join('');
    }}
    function extractUrls(text) {{
      return Array.from(new Set(String(text || '').match(/https?:\\/\\/[^\\s<)]+/g) || []));
    }}
    function urlPreview(url) {{
      let host = url;
      let path = url;
      try {{ host = new URL(url).host; }} catch (e) {{}}
      try {{
        const parsed = new URL(url);
        path = parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : parsed.origin;
      }} catch (e) {{}}
      return `<a class="bubble-link-card" href="${{escapeAttr(url)}}" target="_blank" rel="noreferrer"><span class="bubble-link-icon">↗</span><span><strong>${{escapeHtml(host)}}</strong><span>${{escapeHtml(path)}}</span></span></a>`;
    }}
    function visibleMessageText(msg) {{
      let text = String(msg.text || '').trim();
      if (msg.images?.length) {{
        text = text
          .replace(/!\\[[^\\]]*\\]\\([^)]+\\)/g, '')
          .replace(/(?:^|\\n)\\s*\\[图片\\]\\s*(?=\\n|$)/g, '\\n')
          .replace(/\\[Image:\\s*[^\\]]+\\]/g, '')
          .trim();
      }}
      return text;
    }}
    function renderMessageText(msg) {{
      const text = visibleMessageText(msg);
      return text ? `<div class="bubble-text">${{renderMarkdown(text)}}</div>` : '';
    }}
    function renderMessageLinks(msg) {{
      return extractUrls(visibleMessageText(msg)).map(urlPreview).join('');
    }}
    function renderMessageImages(msg) {{
      if (!msg.images?.length) return '';
      const mediaClass = msg.images.length === 1 ? 'bubble-media single' : 'bubble-media';
      return `<div class="${{mediaClass}}">${{msg.images.map(src => `<a href="${{escapeAttr(src)}}" target="_blank"><img src="${{escapeAttr(src)}}" loading="lazy"></a>`).join('')}}</div>`;
    }}
    function locationText(loc) {{
      return JSON.stringify(loc).toLowerCase();
    }}
    function filteredLocations() {{
      const q = $('search').value.trim().toLowerCase();
      return DATA.locations.filter(loc => (activeType === 'all' || loc.type === activeType) && (!q || locationText(loc).includes(q)));
    }}
    function renderTabs() {{
      const types = ['all', 'chat', 'doc', 'list'];
      $('tabs').innerHTML = types.map(type => `<button class="${{activeType === type ? 'active' : ''}}" data-type="${{type}}">${{labels[type]}}</button>`).join('');
      document.querySelectorAll('#tabs button').forEach(btn => btn.onclick = () => {{ activeType = btn.dataset.type; render(); }});
    }}
    function renderNav() {{
      const locs = filteredLocations();
      if (!locs.some(loc => loc.id === activeId)) activeId = locs[0]?.id;
      $('nav').innerHTML = locs.map(loc => `<button class="${{loc.id === activeId ? 'active' : ''}}" data-id="${{loc.id}}"><strong>${{escapeHtml(loc.title)}}</strong><span>${{escapeHtml(loc.label)}} · ${{escapeHtml(loc.subtitle || '')}}</span></button>`).join('');
      document.querySelectorAll('#nav button').forEach(btn => btn.onclick = () => {{ activeId = btn.dataset.id; renderMain(); renderNav(); }});
    }}
    function renderMain() {{
      const loc = DATA.locations.find(item => item.id === activeId);
      if (!loc) {{
        $('title').textContent = '无匹配地点';
        $('subtitle').textContent = '';
        $('viewer').innerHTML = '';
        return;
      }}
      $('title').textContent = loc.title;
      $('subtitle').textContent = `${{loc.label}} · ${{loc.subtitle || ''}}`;
      $('openLink').textContent = loc.url ? '打开飞书' : '';
      $('openLink').href = loc.url || '#';
      if (loc.type === 'chat') renderChat(loc);
      else if (loc.type === 'doc') renderDoc(loc);
      else renderList(loc);
    }}
    function renderChat(loc) {{
      $('viewer').innerHTML = `<div class="chat-view">${{loc.messages.map(msg => `
        <div class="bubble-row ${{msg.mine ? 'mine' : ''}}">
          <div class="bubble">
            <div class="bubble-meta">${{escapeHtml(msg.sender)}} · ${{escapeHtml(msg.time)}} · ${{escapeHtml(msg.type)}}</div>
            ${{renderMessageText(msg)}}
            ${{renderMessageLinks(msg)}}
            ${{renderMessageImages(msg)}}
          </div>
        </div>`).join('')}}</div>`;
    }}
    function renderDoc(loc) {{
      $('viewer').innerHTML = `
        <div class="doc-shell">
          <article class="doc-main">
            <div class="doc-body">${{loc.currentHtml || '<p class="muted">未采集到正文。</p>'}}</div>
          </article>
          <aside class="doc-side">
            <section>
              <h3>评论</h3>
              ${{loc.comments?.length ? loc.comments.map(row => `<div class="comment"><time>${{escapeHtml(row.time || '未知时间')}}</time><p>${{escapeHtml(row.text || '')}}</p>${{row.quote ? `<div class="quote">${{escapeHtml(row.quote)}}</div>` : ''}}</div>`).join('') : '<p class="muted">无未解决评论或回复。</p>'}}
            </section>
          </aside>
        </div>`;
    }}
    function renderList(loc) {{
      $('viewer').innerHTML = `<div class="list-view">${{loc.items?.length ? loc.items.map(item => `<article class="record"><h3>${{escapeHtml(item.title)}}</h3><p>${{escapeHtml(item.time || '')}}</p><p>${{escapeHtml(item.detail || '')}}</p>${{item.link ? `<p><a href="${{escapeHtml(item.link)}}" target="_blank">打开</a></p>` : ''}}</article>`).join('') : '<p class="muted">无记录。</p>'}}</div>`;
    }}
    function render() {{ renderTabs(); renderNav(); renderMain(); }}
    $('search').addEventListener('input', render);
    render();
  </script>
</body>
</html>
"""
    out_path = output_dir / "index.html"
    out_path.write_text(page, encoding="utf-8")
    print(f"  -> 保存 {out_path.name} (HTML 地点浏览)")


def main():
    parser = argparse.ArgumentParser(description="飞书周报草稿提取")
    parser.add_argument("--raw-dir", default="./raw", help="原始数据目录")
    parser.add_argument("--output-dir", default="./drafts", help="草稿输出目录")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)

    if not raw_dir.exists():
        print(f"[错误] 原始数据目录不存在: {raw_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=" * 60)
    print(f"飞书周报草稿提取")
    print(f"原始目录: {raw_dir.absolute()}")
    print(f"输出目录: {output_dir.absolute()}")
    print(f"=" * 60)

    process_messages(raw_dir, output_dir)
    process_activity_sources(raw_dir, output_dir)
    process_docs(raw_dir, output_dir)
    process_weekly_context(raw_dir, output_dir)
    generate_html_index(output_dir, raw_dir)

    # 统计
    draft_files = list(output_dir.glob("*.md"))
    print(f"\n{'=' * 60}")
    print(f"提取完成! 共生成 {len(draft_files)} 个草稿文件，并生成 index.html 可视化总览:")
    for f in sorted(draft_files):
        print(f"  - {f.name}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
