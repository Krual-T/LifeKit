#!/usr/bin/env python3
"""
飞书材料读取工具
从明确选择的飞书材料类型中读取指定时间范围的记录，保存为临时 JSON。

用法:
    python export_raw.py \
      --profile YOUR_PROFILE --include tasks \
      --start 2026-08-15T08:05:00+08:00 \
      --end 2026-08-16T08:05:00+08:00 \
      --output-dir ./raw

参数:
    --start             开始时间（含，ISO 8601；兼容 YYYY-MM-DD）
    --end               结束时间（不含，ISO 8601；兼容 YYYY-MM-DD）
    --output-dir        原始数据输出目录, 默认 ./raw
    --profile           已核对身份的 lark-cli profile
    --include           要读取的材料类型，可重复指定；不读取未选类型
    --config-dir        所选联系人/群组的配置目录（读取聊天时必填）
    --timezone          日期和无时区时间的 IANA 时区，默认 UTC
    --max-doc-contents  最多获取文档内容的数量, 默认 20
    --max-doc-comments  最多获取评论明细的文档数量, 默认 20
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("UTC")
LARK_PROFILE = ""

# Fix Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_frontmatter(md_path: str) -> dict:
    """解析 markdown 文件的 YAML frontmatter"""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"  [警告] 无法读取 {md_path}: {e}")
        return {}

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}

    try:
        import yaml
        return yaml.safe_load(match.group(1)) or {}
    except Exception as e:
        print(f"  [警告] 无法解析 frontmatter {md_path}: {e}")
        return {}


def parse_yaml_file(yaml_path: str) -> dict:
    """解析 YAML 文件"""
    try:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"  [警告] 无法解析 YAML {yaml_path}: {e}")
        return {}


def load_configs(config_dir: str) -> tuple[dict, dict]:
    """加载联系人和群组配置"""
    contacts = {}
    groups = {}

    contacts_dir = Path(config_dir) / "联系人"
    groups_dir = Path(config_dir) / "群组"

    if contacts_dir.exists():
        for person_dir in sorted(path for path in contacts_dir.iterdir() if path.is_dir()):
            meta_file = person_dir / "meta.yaml"
            if not meta_file.exists():
                continue
            fm = parse_yaml_file(str(meta_file))
            name = fm.get("name") or fm.get("real_name") or person_dir.name
            open_id = fm.get("open_id")
            if open_id:
                contacts[name] = {
                    "open_id": open_id,
                    "p2p_chat_id": fm.get("p2p_chat_id"),
                    "email": fm.get("email"),
                    "department": fm.get("department"),
                }
        for md_file in sorted(contacts_dir.glob("*.md")):
            fm = parse_frontmatter(str(md_file))
            name = fm.get("name") or fm.get("real_name") or md_file.stem
            open_id = fm.get("open_id")
            if open_id:
                contacts[name] = {
                    "open_id": open_id,
                    "p2p_chat_id": fm.get("p2p_chat_id"),
                    "email": fm.get("email"),
                    "department": fm.get("department"),
                }

    if groups_dir.exists():
        for md_file in sorted(groups_dir.glob("*.md")):
            fm = parse_frontmatter(str(md_file))
            name = fm.get("name") or fm.get("full_name") or md_file.stem
            chat_id = fm.get("chat_id")
            if chat_id:
                groups[name] = {
                    "chat_id": chat_id,
                    "owner": fm.get("owner"),
                    "owner_open_id": fm.get("owner_open_id"),
                }

    return contacts, groups


def run_lark_cli(cmd: list[str]) -> dict:
    """运行 lark-cli 命令并解析 JSON 输出"""
    try:
        if cmd and cmd[0] == "lark-cli":
            cmd = list(cmd)
            cmd[0] = shutil.which("lark-cli") or cmd[0]
            profile = LARK_PROFILE
            if not profile:
                return {"ok": False, "_error": "未指定 --profile"}
            cmd[1:1] = ["--profile", profile]
            if "--as" not in cmd:
                cmd.extend(["--as", "user"])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # 有些命令即使返回非0也有有效stdout
            if not result.stdout.strip():
                print(f"    [错误] lark-cli 失败: {stderr}")
                return {"_error": stderr, "_cmd": " ".join(cmd)}

        stdout = result.stdout.strip()
        if not stdout:
            return {"_error": "空输出", "_cmd": " ".join(cmd)}

        try:
            data = json.loads(stdout)
            if result.returncode != 0:
                if not isinstance(data, dict):
                    data = {"data": data}
                data.update({"ok": False, "_returncode": result.returncode})
                data.setdefault("_error", result.stderr.strip() or "lark-cli returned a nonzero exit status")
            return data
        except json.JSONDecodeError:
            # 可能不是JSON，返回原始文本
            return {"ok": False, "_error": "lark-cli did not return JSON", "_raw": stdout, "_cmd": " ".join(cmd)}
    except Exception as e:
        return {"_error": str(e), "_cmd": " ".join(cmd)}


def to_iso_start(date_str: str) -> str:
    """转换为 lark-cli 接受的 ISO 起始时间。"""
    if "T" in date_str:
        return date_str
    return datetime.fromisoformat(date_str).replace(tzinfo=TIMEZONE).isoformat()


def parse_boundary(value: str) -> datetime:
    parsed = datetime.fromisoformat(to_iso_start(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def parse_item_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            numeric = int(value)
            if numeric > 10**14:
                numeric /= 1_000_000
            elif numeric > 10**11:
                numeric /= 1_000
            return datetime.fromtimestamp(numeric, TIMEZONE)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)
        return parsed.astimezone(TIMEZONE)
    except (OverflowError, TypeError, ValueError):
        return None


def extract_image_keys(content: str) -> list[str]:
    """从消息 content 中提取所有 image key，如 [Image: img_xxx] -> img_xxx"""
    if not content:
        return []
    return re.findall(r"\[Image:\s*([^\]]+)\]", content)


def download_message_images(msg: dict, images_dir: Path) -> list[dict]:
    """下载消息中的图片，返回 [{key, path}]，path 为相对于 output_dir 的路径"""
    message_id = msg.get("message_id", "")
    content = msg.get("content", "")
    image_keys = extract_image_keys(content)
    if not image_keys:
        return []

    results = []
    for key in image_keys:
        safe_name = re.sub(r"[^\w\-]", "_", key)
        output_file = images_dir / f"{safe_name}.png"
        # lark-cli 禁止绝对路径，使用相对路径
        output_rel = os.path.relpath(output_file)

        cmd = [
            "lark-cli", "im", "+messages-resources-download",
            "--message-id", message_id,
            "--file-key", key,
            "--type", "image",
            "--output", output_rel,
        ]
        data = run_lark_cli(cmd)
        if isinstance(data, dict) and data.get("ok"):
            saved = data.get("data", {}).get("saved_path", "")
            if saved:
                results.append({"key": key, "path": str(output_file)})
        else:
            err = data.get("_error", "未知错误") if isinstance(data, dict) else str(data)
            print(f"        [警告] 下载图片失败 {key}: {err}")

    return results


def get_current_user() -> dict:
    """获取当前登录用户信息"""
    data = run_lark_cli(["lark-cli", "contact", "+get-user", "--format", "json"])
    if not data.get("ok"):
        print(f"  [警告] 无法获取当前用户信息: {data.get('_error', '未知错误')}")
        return {}
    return data.get("data", {}).get("user", {})


def enrich_message(msg: dict, current_user_open_id: str):
    """为消息添加发送方向标记，保留引用链字段"""
    sender = msg.get("sender", {}) or {}
    sender_id = sender.get("id") if isinstance(sender, dict) else None
    msg["is_sent_by_me"] = sender_id == current_user_open_id
    # root_id / parent_id 已由 API 返回，无需额外处理


def fetch_messages(cmd: list[str], images_dir: Path = None, current_user_open_id: str = "") -> dict:
    """分页获取聊天消息，并输出 extract_drafts.py 可直接读取的结构。"""
    all_messages = []
    page_token = ""
    page_count = 0

    while True:
        page_cmd = list(cmd)
        if page_token:
            page_cmd.extend(["--page-token", page_token])

        data = run_lark_cli(page_cmd)
        if not data.get("ok"):
            return data

        page_count += 1
        payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        all_messages.extend(payload.get("messages", []))

        page_token = payload.get("page_token") or ""
        if not payload.get("has_more") or not page_token:
            break

    # 增强消息元数据 + 下载图片
    if all_messages:
        for msg in all_messages:
            if current_user_open_id:
                enrich_message(msg, current_user_open_id)
            if images_dir:
                local_images = download_message_images(msg, images_dir)
                if local_images:
                    msg["local_images"] = local_images
        if images_dir:
            img_count = sum(len(m.get("local_images", [])) for m in all_messages)
            if img_count:
                print(f"    -> 下载了 {img_count} 张图片")

    return {
        "ok": True,
        "messages": all_messages,
        "meta": {
            "page_count": page_count,
            "total": len(all_messages),
        },
    }


def fetch_group_messages(chat_id: str, chat_name: str, week_start: str, week_end: str, images_dir: Path = None, current_user_open_id: str = "") -> dict:
    """获取群聊消息"""
    print(f"  采集群聊: {chat_name}")
    cmd = [
        "lark-cli", "im", "+chat-messages-list",
        "--chat-id", chat_id,
        "--start", to_iso_start(week_start),
        "--end", to_iso_start(week_end),
        "--sort", "asc",
        "--page-size", "50",
        "--format", "json",
    ]
    return fetch_messages(cmd, images_dir, current_user_open_id)


def fetch_p2p_messages(open_id: str, contact_name: str, week_start: str, week_end: str, images_dir: Path = None, current_user_open_id: str = "") -> dict:
    """获取私聊消息"""
    print(f"  采集私聊: {contact_name}")
    cmd = [
        "lark-cli", "im", "+chat-messages-list",
        "--user-id", open_id,
        "--start", to_iso_start(week_start),
        "--end", to_iso_start(week_end),
        "--sort", "asc",
        "--page-size", "50",
        "--format", "json",
    ]
    return fetch_messages(cmd, images_dir, current_user_open_id)


def fetch_docs(action: str, week_start: str, week_end: str) -> dict:
    """获取云文档操作记录"""
    print(f"  采集文档: {action}")

    # 构建 lark-cli drive +search 命令
    cmd = ["lark-cli", "drive", "+search", "--query", "", f"--{action}-since", week_start, f"--{action}-until", week_end, "--format", "json", "--page-size", "20"]

    # 对于 created 需要加 --mine
    if action == "created":
        cmd.append("--mine")

    return run_lark_cli(cmd)


def annotate_doc_search_hits(
    data: dict,
    action: str,
    window_start: str,
    window_end: str,
    actor_name: str,
    actor_open_id: str,
) -> dict:
    """Preserve what the Drive search actually proves about an action hit.

    Search result metadata describes the document's current/latest state; for
    example, update_time and edit_user may belong to a later edit by somebody
    else.  The query itself only proves that the current user matched the
    requested action inside this window.  Keep that evidence separate so the
    draft renderer does not invent an exact time or actor from document state.
    """
    if not isinstance(data, dict):
        return data
    payload = data.get("data")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return data
    precision = "hour" if action in {"edited", "commented"} else "window"
    for item in results:
        if not isinstance(item, dict):
            continue
        item["_review_action_hit"] = {
            "action": action,
            "window_start": window_start,
            "window_end": window_end,
            "actor_name": actor_name,
            "actor_open_id": actor_open_id,
            "precision": precision,
        }
    return data


def load_doc_search_results(paths: list[Path]) -> list[dict]:
    """从多个 drive +search 结果中合并文档，保留命中的操作类型。"""
    docs_by_token = {}
    for path in paths:
        action = path.stem.replace("raw_docs_", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                docs_data = json.load(f)
        except Exception as e:
            print(f"    [警告] 无法读取文档列表 {path.name}: {e}")
            continue

        if not isinstance(docs_data, dict):
            continue

        data = docs_data.get("data", {})
        items = data.get("results", []) if isinstance(data, dict) else []
        for item in items:
            meta = item.get("result_meta", {}) if isinstance(item, dict) else {}
            token = meta.get("token") or meta.get("url")
            if not token:
                continue
            if token not in docs_by_token:
                item = dict(item)
                item["_source_actions"] = []
                docs_by_token[token] = item
            docs_by_token[token].setdefault("_source_actions", []).append(action)

    return list(docs_by_token.values())


def resolve_comment_target(item: dict) -> dict:
    """解析评论接口需要的真实 file_token/file_type。Wiki URL 需要先解析 obj_token。"""
    meta = item.get("result_meta", {})
    entity_type = str(item.get("entity_type", "")).upper()
    token = meta.get("token")
    doc_types = str(meta.get("doc_types", "")).lower()

    if entity_type == "WIKI" and token:
        node_data = run_lark_cli([
            "lark-cli", "wiki", "spaces", "get_node",
            "--params", json.dumps({"token": token}, ensure_ascii=False),
            "--format", "json",
        ])
        node = node_data.get("data", {}).get("node", {}) if isinstance(node_data, dict) else {}
        obj_token = node.get("obj_token")
        obj_type = node.get("obj_type")
        if obj_token and obj_type:
            return {
                "ok": True,
                "file_token": obj_token,
                "file_type": obj_type,
                "wiki_token": token,
                "node": node,
            }
        return {
            "ok": False,
            "wiki_token": token,
            "error": node_data.get("_error") or node_data.get("msg") or "无法解析 wiki 节点",
            "raw": node_data,
        }

    if token and doc_types:
        return {
            "ok": True,
            "file_token": token,
            "file_type": doc_types,
        }

    return {"ok": False, "error": "缺少 token 或文档类型"}


def safe_file_ext(mime: str, name: str = "") -> str:
    """根据 MIME 或文件名推断图片扩展名。"""
    suffix = Path(name).suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return suffix
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(mime.lower(), ".png")


def extract_doc_images(content_html: str) -> list[dict]:
    """提取文档正文中的图片节点。"""
    images = []
    for idx, match in enumerate(re.finditer(r"<img\b[^>]*>", content_html or "", flags=re.IGNORECASE)):
        tag = match.group(0)
        attrs = dict(re.findall(r'([:\w-]+)="([^"]*)"', tag))
        href = html_unescape(attrs.get("href", ""))
        src = attrs.get("src", "")
        block_id = attrs.get("id", "")
        mime = attrs.get("mime", "")
        name = attrs.get("name", "")
        images.append({
            "index": idx + 1,
            "block_id": block_id,
            "src": src,
            "name": name,
            "mime": mime,
            "href": href,
            "width": attrs.get("width", ""),
            "height": attrs.get("height", ""),
        })
    return images


def html_unescape(value: str) -> str:
    """轻量 HTML entity 解码，避免在采集脚本额外引入 html 模块的大范围改动。"""
    return (
        value.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


def download_doc_images(content_html: str, token: str, output_dir: Path, max_images: int = 80) -> list[dict]:
    """下载文档正文图片，返回带 local_path 的图片元数据。"""
    images = extract_doc_images(content_html)
    if not images:
        return []

    safe_token = re.sub(r"[^\w\-]", "_", token or "unknown")
    image_dir = output_dir / "doc_images" / safe_token
    image_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for image in images[:max_images]:
        href = image.get("href", "")
        if not href:
            image["download_error"] = "missing href"
            downloaded.append(image)
            continue

        ext = safe_file_ext(image.get("mime", ""), image.get("name", ""))
        stem = image.get("block_id") or image.get("src") or f"image_{image['index']:03d}"
        safe_stem = re.sub(r"[^\w\-]", "_", stem)[:80]
        local_path = image_dir / f"{image['index']:03d}_{safe_stem}{ext}"
        image["local_path"] = str(local_path)

        if local_path.exists():
            downloaded.append(image)
            continue

        try:
            request = urllib.request.Request(href, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                local_path.write_bytes(response.read())
        except Exception as e:
            image["download_error"] = str(e)
        downloaded.append(image)

    if len(images) > max_images:
        downloaded.append({
            "index": max_images + 1,
            "download_error": f"skipped {len(images) - max_images} images due to max_images",
        })

    return downloaded


def fetch_doc_contents(doc_list_paths: list[Path], max_docs: int = 20) -> dict:
    """获取指定时间范围命中文档的当前内容快照。"""
    print("  采集文档内容...")

    items = load_doc_search_results(doc_list_paths)

    results = []
    skipped = 0
    for item in items:
        if len(results) >= max_docs:
            skipped += 1
            continue

        meta = item.get("result_meta", {})
        token = meta.get("token")
        url = meta.get("url")
        doc_types = meta.get("doc_types", "")

        # 跳过不便于文本分析的类型
        if doc_types in ("SHEET", "BITABLE", "MINDNOTE"):
            skipped += 1
            continue

        doc_ref = url or token
        if not doc_ref:
            skipped += 1
            continue

        title = item.get("title_highlighted", "") or token or "unknown"
        print(f"    -> 获取文档: {title[:50]}")
        content_data = run_lark_cli([
            "lark-cli", "docs", "+fetch",
            "--doc", doc_ref,
            "--format", "json",
            "--api-version", "v2",
            "--detail", "with-ids",
        ])
        content_html = ""
        if isinstance(content_data, dict):
            content_html = content_data.get("data", {}).get("document", {}).get("content", "")
        doc_images = download_doc_images(content_html, token or "unknown", output_dir=Path(doc_list_paths[0]).parent)
        if doc_images:
            ok_count = sum(1 for image in doc_images if image.get("local_path") and not image.get("download_error"))
            print(f"      -> 下载文档图片 {ok_count}/{len(doc_images)} 张")

        results.append({
            "token": token,
            "url": url,
            "title": title,
            "doc_types": doc_types,
            "edit_user_name": meta.get("edit_user_name"),
            "update_time_iso": meta.get("update_time_iso"),
            "source_actions": item.get("_source_actions", []),
            "images": doc_images,
            "content": content_data,
        })

    return {
        "ok": True,
        "results": results,
        "meta": {"total": len(results), "skipped": skipped},
    }


def fetch_doc_comments(doc_list_paths: list[Path], max_docs: int = 20) -> dict:
    """获取指定时间范围命中文档的评论卡片和回复内容。默认仅未解决评论。"""
    print("  采集文档评论...")

    items = load_doc_search_results(doc_list_paths)

    results = []
    skipped = 0
    for item in items:
        if len(results) >= max_docs:
            skipped += 1
            continue

        meta = item.get("result_meta", {})
        title = item.get("title_highlighted", "") or meta.get("token") or "unknown"
        target = resolve_comment_target(item)
        if not target.get("ok"):
            skipped += 1
            results.append({
                "token": meta.get("token"),
                "url": meta.get("url"),
                "title": title,
                "source_actions": item.get("_source_actions", []),
                "target": target,
                "comments": {"ok": False, "_error": target.get("error", "无法解析评论目标")},
            })
            continue

        file_type = target.get("file_type")
        if file_type not in ("doc", "docx", "sheet", "file", "slides", "bitable"):
            skipped += 1
            continue

        print(f"    -> 获取评论: {title[:50]}")
        params = {
            "file_token": target["file_token"],
            "file_type": file_type,
            "is_solved": False,
            "page_size": 100,
            "user_id_type": "open_id",
        }
        comments = run_lark_cli([
            "lark-cli", "drive", "file.comments", "list",
            "--params", json.dumps(params, ensure_ascii=False),
            "--page-all",
            "--format", "json",
        ])
        results.append({
            "token": meta.get("token"),
            "url": meta.get("url"),
            "title": title,
            "doc_types": meta.get("doc_types", ""),
            "source_actions": item.get("_source_actions", []),
            "target": target,
            "comments": comments,
        })

    return {
        "ok": True,
        "results": results,
        "meta": {"total": len(results), "skipped": skipped},
    }


def fetch_doc_versions(doc_list_paths: list[Path], max_docs: int = 20, limit: int = 20) -> dict:
    """获取指定时间范围命中文档的飞书 Drive 版本历史元数据。"""
    print("  采集文档版本历史...")

    items = load_doc_search_results(doc_list_paths)
    results = []
    skipped = 0
    for item in items:
        if len(results) >= max_docs:
            skipped += 1
            continue

        meta = item.get("result_meta", {})
        title = item.get("title_highlighted", "") or meta.get("token") or "unknown"
        target = resolve_comment_target(item)
        token = meta.get("token")
        url = meta.get("url")
        row = {
            "token": token,
            "url": url,
            "title": title,
            "doc_types": meta.get("doc_types", ""),
            "source_actions": item.get("_source_actions", []),
            "target": target,
        }
        if not target.get("ok"):
            skipped += 1
            row["versions"] = {"ok": False, "_error": target.get("error", "无法解析版本目标")}
            results.append(row)
            continue

        file_type = str(target.get("file_type", "")).lower()
        file_token = target.get("file_token")
        if not file_token:
            skipped += 1
            row["versions"] = {"ok": False, "_error": "缺少 file_token"}
            results.append(row)
            continue

        print(f"    -> 获取版本: {title[:50]}")
        versions = run_lark_cli([
            "lark-cli", "api", "GET", f"/open-apis/drive/v1/files/{file_token}/versions",
            "--params", json.dumps({
                "page_size": limit,
                "obj_type": file_type,
                "user_id_type": "open_id",
            }, ensure_ascii=False),
        ])
        if isinstance(versions, dict) and versions.get("ok") is False:
            error = versions.get("error", {}) if isinstance(versions.get("error"), dict) else {}
            if error:
                print(f"      [提示] 版本历史不可用: {error.get('message', error.get('type', 'unknown'))}")
        row["file_token"] = file_token
        row["file_type"] = file_type
        row["versions"] = versions
        results.append(row)

    return {
        "ok": True,
        "results": results,
        "meta": {"total": len(results), "skipped": skipped, "limit": limit},
    }


def fetch_tasks(week_start: str, week_end: str) -> dict:
    """获取指定时间范围创建/更新的任务"""
    print("  采集任务...")

    all_tasks = []
    seen_guids = set()
    start = parse_boundary(week_start)
    end = parse_boundary(week_end)
    excluded_without_timestamp = 0
    failures = []

    for cmd_name, extra_args in [
        ("+get-my-tasks", ["--created_at", to_iso_start(week_start)]),
        ("+get-related-tasks", []),
    ]:
        print(f"    -> {cmd_name}")
        cmd = [
            "lark-cli", "task", cmd_name,
            "--page-all",
            "--format", "json",
        ] + extra_args
        data = run_lark_cli(cmd)
        if not data.get("ok"):
            err = data.get("_error") or data.get("error") or data.get("message") or "未知错误"
            failures.append({"command": cmd_name, "error": str(err)})
            print(f"      [警告] {cmd_name} 失败: {err}")
            continue

        items = (data.get("data", {}).get("items") or []) if isinstance(data.get("data"), dict) else []
        for item in items:
            created = parse_item_timestamp(item.get("created_at"))
            if created is None:
                excluded_without_timestamp += 1
                continue
            if not (start <= created < end):
                continue

            guid = item.get("guid")
            if guid and guid in seen_guids:
                continue
            if guid:
                seen_guids.add(guid)

            item["_source"] = cmd_name.lstrip("+")
            all_tasks.append(item)

    return {
        "ok": not failures,
        "failures": failures,
        **({
            "_error": "; ".join(f"{item['command']}: {item['error']}" for item in failures)
        } if failures else {}),
        "tasks": all_tasks,
        "meta": {
            "total": len(all_tasks),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "excluded_without_timestamp": excluded_without_timestamp,
        },
    }


def fetch_calendar(week_start: str, week_end: str) -> dict:
    """获取日历日程"""
    print("  采集日历日程...")
    cmd = [
        "lark-cli", "calendar", "+agenda",
        "--start", to_iso_start(week_start),
        "--end", to_iso_start(week_end),
        "--format", "json",
    ]
    return run_lark_cli(cmd)


def fetch_vc(week_start: str, week_end: str) -> dict:
    """获取视频会议记录"""
    print("  采集会议记录...")
    cmd = [
        "lark-cli", "vc", "+search",
        "--start", to_iso_start(week_start),
        "--end", to_iso_start(week_end),
        "--format", "json",
    ]
    return run_lark_cli(cmd)


def fetch_minutes(week_start: str, week_end: str) -> dict:
    """获取妙记记录"""
    print("  采集妙记...")
    cmd = [
        "lark-cli", "minutes", "+search",
        "--start", to_iso_start(week_start),
        "--end", to_iso_start(week_end),
        "--format", "json",
    ]
    return run_lark_cli(cmd)


def save_json(data: dict, path: str):
    """保存 JSON 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def archive_existing_file(path: Path) -> Path | None:
    """覆盖采集结果前保存上一版，供正文差异提取使用。"""
    if not path.exists():
        return None
    archive_dir = path.parent / "_snapshots"
    archive_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    archived = archive_dir / f"{path.stem}_{timestamp}{path.suffix}"
    shutil.copy2(path, archived)
    return archived


def collect_items(data: dict, keys: list[str]) -> list:
    """从 lark-cli 常见嵌套结构中提取列表。"""
    if not isinstance(data, dict):
        return []
    candidates = [data]
    nested = data.get("data")
    if isinstance(nested, dict):
        candidates.insert(0, nested)
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, list):
                return value
    return []


def main(argv=None):
    global LARK_PROFILE, TIMEZONE
    parser = argparse.ArgumentParser(description="读取明确选定的飞书材料，保存临时 JSON")
    parser.add_argument(
        "--start",
        "--week-start",
        dest="start",
        required=True,
        help="开始时间（含，ISO 8601；兼容 YYYY-MM-DD）",
    )
    parser.add_argument(
        "--end",
        "--week-end",
        dest="end",
        required=True,
        help="结束时间（不含，ISO 8601；兼容 YYYY-MM-DD）",
    )
    parser.add_argument("--output-dir", default="./raw", help="输出目录")
    parser.add_argument("--profile", required=True, help="已核对身份的 lark-cli profile")
    parser.add_argument("--include", action="append", required=True,
                        choices=("groups", "contacts", "docs", "tasks", "calendar", "meetings", "minutes"),
                        help="要读取的材料类型，可重复；只读取所选类型")
    parser.add_argument("--config-dir", help="所选联系人/群组配置目录；读取聊天时必填")
    parser.add_argument("--timezone", default="UTC", help="日期/无时区时间的 IANA 时区，默认 UTC")
    parser.add_argument("--max-doc-contents", type=int, default=20, help="最多获取文档内容的数量")
    parser.add_argument("--max-doc-comments", type=int, default=20, help="最多获取评论明细的文档数量")
    args = parser.parse_args(argv)
    LARK_PROFILE = args.profile
    try:
        TIMEZONE = ZoneInfo(args.timezone)
    except (KeyError, ValueError):
        parser.error("--timezone must be a valid IANA timezone")
    selected = set(args.include)
    if selected & {"groups", "contacts"} and not args.config_dir:
        parser.error("reading groups or contacts requires --config-dir")

    start = parse_boundary(args.start)
    end = parse_boundary(args.end)
    if end <= start:
        raise SystemExit("--end must be later than --start")
    week_start = start.isoformat(timespec="seconds")
    week_end = end.isoformat(timespec="seconds")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取范围: {week_start} 至 {week_end}；类型: {', '.join(sorted(selected))}")
    contacts, groups = {}, {}
    if selected & {"groups", "contacts"}:
        config_dir = Path(args.config_dir).resolve()
        if not config_dir.is_dir():
            parser.error("--config-dir must be an existing directory")
        contacts, groups = load_configs(str(config_dir))
        if "contacts" not in selected:
            contacts = {}
        if "groups" not in selected:
            groups = {}

    # 聊天方向和文档操作归属需要当前用户；其他类型不额外读取通讯录。
    current_user = get_current_user() if selected & {"groups", "contacts", "docs"} else {}
    current_user_open_id = current_user.get("open_id", "")
    current_user_name = current_user.get("name", "")
    if selected & {"groups", "contacts", "docs"} and not current_user_open_id:
        raise SystemExit("无法确认当前飞书用户，停止读取；请检查已配置的 profile 和权限")
    images_dir = output_dir / "images"
    if contacts or groups:
        images_dir.mkdir(exist_ok=True)

    failed_outputs = []

    def contains_error(value):
        if isinstance(value, dict):
            return bool(value.get("_error")) or value.get("ok") is False or any(contains_error(item) for item in value.values())
        return isinstance(value, list) and any(contains_error(item) for item in value)

    def save(name, data):
        save_json(data, str(output_dir / name))
        if contains_error(data):
            failed_outputs.append(name)
        print(f"  保存 {name}")

    # 采集群聊
    for name, info in groups.items():
        data = fetch_group_messages(info["chat_id"], name, week_start, week_end, images_dir, current_user_open_id)
        safe_name = re.sub(r'[^\w一-鿿-]', '_', name)
        save(f"raw_group_{safe_name}.json", data)

    # 采集私聊
    for name, info in contacts.items():
        data = fetch_p2p_messages(info["open_id"], name, week_start, week_end, images_dir, current_user_open_id)
        safe_name = re.sub(r'[^\w一-鿿-]', '_', name)
        save(f"raw_p2p_{safe_name}.json", data)

    # 采集文档
    if "docs" in selected:
        doc_action_paths = []
        for action in ("edited", "commented", "created", "opened"):
            data = annotate_doc_search_hits(fetch_docs(action, week_start, week_end), action,
                                           week_start, week_end, current_user_name, current_user_open_id)
            name = f"raw_docs_{action}.json"
            save(name, data)
            doc_action_paths.append(output_dir / name)
        archive_existing_file(output_dir / "raw_doc_contents.json")
        save("raw_doc_contents.json", fetch_doc_contents(doc_action_paths, max_docs=args.max_doc_contents))
        save("raw_doc_comments.json", fetch_doc_comments(doc_action_paths, max_docs=args.max_doc_comments))
        save("raw_doc_versions.json", fetch_doc_versions(doc_action_paths, max_docs=args.max_doc_contents))
    for name, filename, reader in (
        ("tasks", "raw_tasks.json", fetch_tasks),
        ("calendar", "raw_calendar.json", fetch_calendar),
        ("meetings", "raw_vc.json", fetch_vc),
        ("minutes", "raw_minutes.json", fetch_minutes),
    ):
        if name in selected:
            save(filename, reader(week_start, week_end))

    # 保存元数据
    meta = {
        "start": week_start,
        "end": week_end,
        "timezone": TIMEZONE.key,
        "generated_at": datetime.now(TIMEZONE).isoformat(),
        "current_user": {
            "open_id": current_user_open_id,
            "name": current_user_name,
        },
        "contacts": list(contacts.keys()),
        "groups": list(groups.keys()),
        "included": sorted(selected),
        "failed_outputs": failed_outputs,
    }
    save_json(meta, str(output_dir / "_meta.json"))

    print(f"材料保存在: {output_dir.absolute()}")
    if failed_outputs:
        print(f"读取不完整，请检查: {', '.join(failed_outputs)}", file=sys.stderr)
    return 1 if failed_outputs else 0


if __name__ == "__main__":
    sys.exit(main())
