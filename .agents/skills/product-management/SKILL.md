---
name: product-management
description: 产品经理工作的统一入口，按需使用需求澄清、用户研究、PRD、优先级、路线图和市场分析等子技能；用于产品决策与交付，不用于已定范围的编码或调试。
---

# 产品经理

根据当前要解决的产品问题选择子技能，直接读取其文件。子技能是本入口下的参考材料，不依赖它们出现在宿主技能列表中。

## 按需选择

先复用用户已提供的信息，选择能完成当前交付的最具体方法。通常从一个子技能开始；只有当前步骤确实依赖另一种方法时才继续读取。小需求不必展开完整的产品发现、访谈或 PRD 流程。

| 当前需要 | 先读取 |
| --- | --- |
| 搞清模糊需求背后的问题 | [problem-framing-canvas](references/.library/skills/problem-framing-canvas/SKILL.md) |
| 理解目标用户的任务、痛点与收益 | [jobs-to-be-done](references/.library/skills/jobs-to-be-done/SKILL.md) |
| 准备用户访谈 | [discovery-interview-prep](references/.library/skills/discovery-interview-prep/SKILL.md) |
| 把已有信息整理成 PRD | [prd-development](references/.library/skills/prd-development/SKILL.md) |
| 写具体用户故事和验收条件 | [user-story](references/.library/skills/user-story/SKILL.md) |
| 把过大的需求拆成可交付部分 | [epic-breakdown-advisor](references/.library/skills/epic-breakdown-advisor/SKILL.md) |
| 决定先做什么 | [prioritization-advisor](references/.library/skills/prioritization-advisor/SKILL.md) |
| 规划产品路线图 | [roadmap-planning](references/.library/skills/roadmap-planning/SKILL.md) |
| 比较市场中的竞争方案 | [competitive-research-snapshot](references/.library/skills/competitive-research-snapshot/SKILL.md) |
| 选择最小验证实验 | [pol-probe-advisor](references/.library/skills/pol-probe-advisor/SKILL.md) |

其他任务先查[子技能目录](references/catalog.md)对应领域，包括定位、增长、财务、产品生命周期、利益相关方、AI 产品与 PM 职业发展。用户明确指定子技能名时直接定位它。不要默认读取完整目录、所有子技能或所有模板。

## 读取与衔接

- 子技能入口为 `references/.library/skills/<name>/SKILL.md`；先读所选入口，再按实际需要读同目录的模板、示例及被引用的方法。
- 上游正文中的 `skills/...`、`docs/...`、`scripts/...` 均以 `references/.library/` 为根；以 `../` 开头的链接相对所在文件解析。搜索隐藏库时使用 `rg --hidden` 并限定该目录。
- 上游完整工作流按当前任务规模裁剪。保留事实、假设、待确认信息的区分，不把示例公司的数字当作用户事实，也不照搬示例的日期与流程时长。
- 需求明确后，需要技术方案时转到已有 `write-technical-design`；执行多智能体工程任务使用已有 `orchestrate-subagents`。这里的 AI 产品方法用于产品判断。

## 本地库

`references/.library/` 用于安装固定上游版本的全部 77 个子技能及配套资料。它是隐藏参考目录，避免被 Codex 递归登记为独立技能；不要把其目录改成非隐藏名或把子技能重新放到顶层。

公共仓库只提供本入口和分类目录，第三方库需要按[来源与恢复步骤](references/catalog.md#本地库的来源与恢复)安装。库缺失时先说明缺失，不能只根据目录摘要声称已经执行上游方法。
