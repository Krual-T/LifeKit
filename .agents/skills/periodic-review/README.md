# 初始化周期复盘

这个 Skill 根据实例登记的阅读方式使用信源，支持日、周、月、年复盘。可以只用本地笔记，也可以组合飞书、指定项目的 Codex 对话、Git 或其他资料。每个信源的脚本均可按需使用。

```text
periodic-review/
├── SKILL.md
├── AGENTS.ini.md       个人复盘要求样板
├── Registry.ini.md     信源登记样板
├── .env.example        临时目录和可选对象存储路径
├── references/         可改用的写法示例
└── sources/            阅读说明、初始化步骤与可选工具
```

## 初始化

在自己的仓库根目录执行；已有文件会保留：

```bash
review_skill=.agents/skills/periodic-review
test -e "$review_skill/AGENTS.md" || cp "$review_skill/AGENTS.ini.md" "$review_skill/AGENTS.md"
test -e "$review_skill/Registry.md" || cp "$review_skill/Registry.ini.md" "$review_skill/Registry.md"
```

编辑 `AGENTS.md`，写清想怎样复盘、保存在哪里、是否需要通知。编辑 `Registry.md`，启用需要的来源并填写真实范围。Agent 使用本 Skill 时显式读取这两个文件；Registry 是普通 Markdown，不经过固定类型注册器或自动执行其中的命令。

实际 AGENTS、Registry 和非秘密来源配置可随个人私有 Git 保存。公共上游只提供样板；以后合并更新时人工采纳样板变化，保留自己的配置。

不需要先安装所有读取工具；按 [来源说明](sources/README.md)准备选中的来源。飞书登录、S3 服务和定时器均按需设置。

## 路径与存储

需要更改路径时，将 `.env.example` 复制为同目录的 `.env`：

- `PERIODIC_REVIEW_TMP_ROOT`：临时导出目录，默认 `tmp/periodic-review`。
- `PERIODIC_REVIEW_OBJECT_CONFIG`：可选的对象存储配置文件路径；未填时不要求对象存储。
- `PERIODIC_REVIEW_OBJECT_PREFIX`：选择归档时使用的对象 key 前缀，默认 `periodic-review`。

这些值是数据，相对路径以当前仓库根为基准；不要用 shell `source` 执行 `.env`。Agent 读取所需路径后，把它们传给对应工具的输出或配置参数。不同工具保留各自接口；配置存储路径本身不代表要复制全部材料。

有网页、应用或本地文件入口时可以直接阅读和引用。确需 S3 归档时，使用[通用存储工具](../../../scripts/rustfs/README.md)并显式传入配置；保存完成后核实可回读，再按实例约定处理临时副本。账户密钥继续由该工具的私有凭据文件管理。

报告与续聊草稿保存在 AGENTS 指定的持久位置；`tmp/` 只保存可清理的工作文件。

## 定时调用

在自己的调度工具中填写执行项目、时间和提示词。例如：

> 使用 $periodic-review，按照该 Skill 的 AGENTS.md 和 Registry.md，准备今天的复盘材料，并按我的通知规则执行。

> 使用 $periodic-review，按照实例约定回顾上周，读取已启用信源中与这一周相关的材料，整理周复盘。

月、年同样指定目标时期。定时器不复制账号、来源列表或长流程，也不会自动赋予通知权限。本仓库不注册定时任务；使用者可按需要设置。

## 添加来源

在 `sources/` 中写一份阅读说明，或链接到已安装工具的说明，再在 Registry 中登记定位与范围。Agent 据此读取。需要重复执行的机械读取才增加脚本；只有说明、链接或人工提供文件也能成为信源。
