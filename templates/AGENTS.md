# LifeKernel 实例入口

开始处理本实例任务时，先读取根目录的 `Assistant.ini.md`，了解助手名称与交流偏好，再读取 `docs/instance-rules.md`，遵守通用协作与数据规则。这是明确的读取要求，不能只看到文件链接就声称已加载正文。

## 记忆地图

- 记住、回忆、纠正或忘记信息：使用 `.agents/skills/using-wiki/SKILL.md`。
- 记忆正文与导航：初始化后查看 `wiki/index.md`；有近期路径就直接读取对应原文。
- 可复用能力：按任务选择 `.agents/skills/` 中的 Skill。

## 个人补充

这里保存本人明确确认、需要跨任务适用的额外约定。身份与经历进入相应 Wiki 页面，再在此加入入口。尚未提供的姓名、账号、关系、偏好和权限保持未知。

## 最近

助手按近期相关性选择入口；容量 5，最多固定 2 个。移出入口不删除 Wiki 原文。下面的区域由 `wiki-index` 维护，使用 `add`、`remove` 和 `ensure` 更新。

<!-- memory-recent:start -->
_暂无近期记忆入口。_
<!-- memory-recent:end -->
