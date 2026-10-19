# Codex 对话

可以使用宿主提供的任务读取工具，直接读取 Registry 登记的线程；也可以用本目录的 `codex_records.py` 读取本机或已授权主机上的 Codex JSONL。两种方式都只读选定范围。

## 初始化与范围

在 Skill 的 `Registry.md` 登记项目的绝对路径、可读会话目录、是否只读指定线程，以及排除的线程。远程主机只有在已经登记并授权时才使用。脚本需要 Python 3.10 或更高版本，不依赖其他 Python 包。

脚本的 `--source-json` 只是一次工具调用的参数，**不是 Registry 的格式**。其中 `id` 是本次来源名，`project_root` 是项目绝对路径，`session_roots` 是可读会话目录列表。会话目录可以是 Codex 主目录，也可以直接指向 `sessions/` 或 `archived_sessions/`。

```bash
python3 .agents/skills/periodic-review/sources/codex/codex_records.py \
  --source-json '{"id":"project-a","project_root":"/path/to/project-a","session_roots":["/path/to/codex-home"]}' \
  --start 2026-09-01T00:00:00+08:00 --end 2026-09-08T00:00:00+08:00 \
  --include-thread THREAD_ID
```

时间使用含时区的 ISO 8601，范围含开始、不含结束。`--include-thread` 可以重复，严格选择这些线程，不自动包含子线程；不传时读取属于登记项目的线程。`--exclude-thread` 可以重复，排除该线程及其子线程，且优先于 include。自动化线程默认被排除，避免复盘反复引用自身。

脚本按会话和 turn 的真实 `cwd` 判断项目归属；同名目录不等于同一项目。项目有多个独立工作树时，在 Registry 中明确哪些目录可读，按各目录分别调用，综合阅读时识别同一事件的重复引用。

## 阅读结果

stdout 是 JSON：`records` 为可读记录，`context_gaps` 为上下文缺口，`failures` 为读取失败。记录保留线程 ID、时间、角色、消息或工具内容、原文件和行号；不输出隐藏推理或系统注入文本，常见凭据会被遮蔽。

`background: true` 表示为理解本周期内容带入的较早用户请求或工具调用，不能算成本周期新发生的事情。记录有 `fallback` 或缺口时检查其来源说明。退出码 1 不代表所有内容无效，仍可使用成功读出的记录，但不能说已经完整覆盖。

如需临时文件，把 stdout 保存到 Skill `.env` 指定的临时目录；也可直接阅读输出。脚本不写入原会话、不上传材料。它保持单文件、无本地 import，已授权的远端读取可用 SSH 将脚本送入 `python3 -` 的 stdin，参数中的目录必须是远端真实路径。

对话只能证明当时的请求、说法和可见执行记录。Agent 的总结或“已完成”表述，需要结合后续反馈、工具结果和其他材料判断，不能直接当作本人已经完成的事实。
