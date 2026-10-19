# Git 历史

可直接使用 Git 只读命令阅读 Registry 登记的仓库，也可以用本目录的 `git_records.py` 批量读取本周期提交和文本 diff。先确认需要的是哪个仓库、哪个时间范围，再决定是否运行工具。

## 初始化与范围

在 Skill 的 `Registry.md` 写入仓库绝对路径、可用主机和允许读取的范围。脚本需要 Python 3.10 或更高版本，以及支持 `--attr-source` 的 Git；不需要第三方 Python 包。

```bash
python3 .agents/skills/periodic-review/sources/git/git_records.py \
  --source-json '{"id":"project-a","project_root":"/path/to/project-a"}' \
  --start 2026-09-01T00:00:00+08:00 --end 2026-09-08T00:00:00+08:00
```

`--source-json` 只承载这次调用参数，不要求把 Registry 写成 JSON。`project_root` 必须是准确的仓库根目录。可选 `git.timeout_seconds` 指定每条 Git 命令的超时秒数，默认 60。

时间含开始、不含结束，按 committer time 筛选。工具读取所有作者，在本地分支、远端跟踪分支和已登记工作树 HEAD 可达的提交中查找；不会执行 fetch、checkout 或仓库写入。它不读取工作区未提交内容、暂存区、stash、reflog、仅由标签可达的提交或不可达提交。若 Registry 只允许某个分支或作者，使用范围明确的 Git 命令直接阅读，不运行这个全仓库工具。

## 阅读结果

stdout 的 `records` 保留提交、作者、提交者、时间、父提交和文本 diff；不带二进制文件内容。合并提交只比较第一父提交，不能当作独立新增工作。每条记录保留可回查的提交 ID。

`scope` 解释本次实际可见范围；`failures` 和 `context_gaps` 指出失败与缺口。浅克隆、缺失对象、旧 Git 不支持所需选项、diff 无法读取等情况会返回部分结果及退出码 1。保留能读到的内容，明确缺口，不把失败解释成“没有提交”。本地远端跟踪分支可能过时；工具不会为了扩大范围自行联网。

可直接阅读 JSON，也可保存到 Skill `.env` 指定的临时目录。脚本不依赖本地模块，可在已授权主机通过 SSH stdin 运行。提交作者和提交数量不能单独证明本人贡献、投入时间或工作质量；复盘时结合对话、反馈和本人说明。
