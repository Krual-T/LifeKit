# OKF 0.2 存储格式

规范依据：[官方 SPEC.md](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)。本页解释记忆读写所需的格式；有疑义时以官方规范为准。目录分类、AGENTS 索引和本地工具命令属于 LifeKernel，不是 OKF 标准。

## 文件与目录

- **Bundle**：一棵 Markdown 目录树；LifeKernel 的记忆 bundle 是 `wiki/`。
- **Concept**：一篇普通 Markdown 文档，可以记录人物、经历、想法或任务；并不要求抽象成理论，也不要求一条事实一个文件。
- **Concept ID**：相对 bundle 根目录的文件路径去掉 `.md`，因此移动和改名时要同步引用。
- **文件夹**：按内容需要组织页面，名称与层级由使用者决定，无固定分类表。
- **`index.md`**：可选的目录导航，按标题分组，以 Markdown 链接和简短描述列出页面或子目录。仅 bundle 根 `index.md` 可以有 frontmatter，例如 `okf_version: "0.2"`。
- **`log.md`**：可选的更新日志，按 `YYYY-MM-DD` 日期分组，新的在前。

`index.md` 和 `log.md` 是保留文件名，不用来存普通记忆。其余 `.md` 都按 Concept 文档读取。页面关系使用普通 Markdown 链接；相对路径相对于当前文件，以 `/` 开头的路径相对于 bundle 根目录。

## 页面格式

普通页面由 UTF-8 Markdown 和开头的 YAML frontmatter 组成。唯一始终必填的字段是非空 `type`；类型名称开放，不需注册。正文无固定栏目。

```markdown
---
type: Note
title: 周末读书计划
description: 示例读书安排，尚未确定书目
tags: [示例, 阅读]
---

2026-01-01：计划在周末读一本书，书目待定。本例为虚构内容。
```

这个例子展示格式，`Note` 是一种可选类型；实际记录按需补来源等字段。

## 按需字段

| 字段 | 含义 |
| --- | --- |
| `title`、`description` | 显示标题、一句话介绍，便于浏览和找页 |
| `tags` | 跨目录标签，不要求为每个标签建文件夹 |
| `resource` | 页面描述的对象所对应的 URI；没有对应资源可省略 |
| `sources` | 内容来源列表；每项必需 `resource`，可加 `id`、`author`、`title` 等 |
| `generated` | 谁生成当前内容；存在时需有 `by`，`at` 可记录实质修改时间 |
| `verified` | 实际复核事件，每项有 `by` 和 `at`；可以是列表或单个 mapping |
| `status` | `draft` 尚未审阅或可能不完整；`stable` 可供使用，也是缺省值；`deprecated` 不再当前有效但保留历史或链接 |
| `stale_after` | 从何时起需要重新核验，不表示到期删除 |

时间戳使用带时区的 ISO 8601 datetime；只有日期信息就写进正文，不伪造时刻。`sources[].last_modified` 表示来源修改时间，不是记忆失效时间。逐项归因可用与 `sources[].id` 对应的 Markdown 脚注，具体写法见官方 §5.1。

`status` 描述文档生命周期，不是短期/长期、任务待办/完成或想法可行/不可行的开关。可靠地记录“本人曾有某个未验证想法”，可以供以后回忆，同时在正文明确可行性未知。`stable` 也不意味着人工复核；只有真实复核才能写 `verified`。

OKF 允许未知类型和附加字段，未使用可选字段的页面仍然有效。别名、关键词等本地检索字段可以按需使用，不要求每页填满。涉及 `Attested Computation` 等专用类型时再读官方对应章节，不给普通记忆增加这些字段。
