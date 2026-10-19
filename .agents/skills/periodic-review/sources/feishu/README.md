# 飞书材料

飞书是一种可选信源。优先按已安装的官方 `lark-suite` Skill 及对应子能力直接读取；本目录的脚本只帮助批量读取或把 JSON 转成便于阅读的材料。读取飞书材料不代表允许发送通知。

## 初始化

1. 按官方 `lark-suite` 的 `lark-shared` 说明安装和配置 `lark-cli`、登录所需账号；只开通将要读取的业务域。已有授权可直接复用。
2. 在本 Skill 的 `Registry.md` 登记 profile、身份核对依据、允许的群/联系人/文档/材料类型和日期范围。初始化时核对应用与用户身份，`open_id` 与应用绑定，不能只按显示名判断。
3. 调用工具前读取涉及的子能力说明：消息用 `lark-im`，文档用 `lark-doc`/`lark-drive`，任务用 `lark-task`，日历用 `lark-calendar`，会议与妙记用 `lark-meeting`。以当前安装版本的说明和 `--help` 为准。出现鉴权或权限错误，按官方说明处理。

脚本需要 Python 3.10 或更高版本。只有联系人/群配置使用 YAML 时才需要 PyYAML。账号密钥和 token 由 CLI 管理，不写入 Registry、公共模板或 `.env`。具体 profile 和来源列表保留在使用者的私人实例中。

## 直接阅读

Registry 可以只放某份文档链接，Agent 按 `lark-doc` 读取正文并保留链接即可；不需要先运行采集脚本，也不要求导出到本地。只允许某些任务、某份文档或某个会议时，直接使用官方工具精确读取这些对象。

## 可选：按类型读取活动

`export_raw.py` 只读取 `--include` 明确选择的类型。示例从仓库根运行；输出目录按本 Skill `.env` 的临时路径调整：

```bash
python3 .agents/skills/periodic-review/sources/feishu/export_raw.py \
  --profile YOUR_PROFILE --include tasks --include calendar \
  --start 2026-09-01T00:00:00+08:00 --end 2026-09-08T00:00:00+08:00 \
  --timezone Asia/Shanghai --output-dir tmp/periodic-review/example/raw
```

| `--include` | 实际范围 |
| --- | --- |
| `groups` | `--config-dir` 中登记的群聊天 |
| `contacts` | `--config-dir` 中登记的联系人私聊 |
| `docs` | 当前用户在窗口内创建、编辑、评论、打开过的文档候选及其当前内容/评论/可见版本 |
| `tasks` | 任务接口可读、且在本周期创建的任务候选；不覆盖只在本周期更新或完成的旧任务 |
| `calendar` | 当前用户本周期日历 |
| `meetings` | 当前用户本周期会议记录 |
| `minutes` | 本周期可见妙记候选 |

只有 Registry 允许上述完整类型范围时才使用对应选项。`--include` 可重复，未选类型不调用。时间含开始、不含结束；日期和无时区时间用 `--timezone` 解释，默认 UTC。按日、周、月、年调用都使用相同时间参数。

读取群/私聊时，`--config-dir` 必填。建立只含获准对象的配置目录：

```text
<私人配置目录>/
├── 联系人/<自定名称>/meta.yaml   # name、open_id
└── 群组/<自定名称>.md           # YAML frontmatter: name、chat_id
```

联系人也支持以 Markdown frontmatter 提供 `name`、`open_id`。这些文件只登记对象，不保存鉴权信息。配置目录中的每个对象都会被读取，所以不要把包含额外联系人的目录传入。

工具输出 `raw_*.json`、`_meta.json` 和按需下载的图片；`_meta.json` 记录窗口和所选类型。原始响应可能包含个人内容，应放临时目录或用户选择的私人存储，不能提交到公共仓库。接口错误保留在响应中；发生可识别读取失败时返回非零退出码。还需检查分页、条数限制、`skipped`、图片下载失败等返回信息；脚本执行完成不等于所有历史材料均已读全。文档内容是读取时的当前快照，搜索命中不能证明精确编辑时间或每一处修改属于本人。

## 可选：补充周期文档

`fetch_weekly_context.py` 可读取指定周报文档，或按 `Release/MMDD` 标题寻找补充材料。没有内置文档链接或项目关键词：

```bash
python3 .agents/skills/periodic-review/sources/feishu/fetch_weekly_context.py \
  --profile YOUR_PROFILE --week-start 2026-09-01 --week-end 2026-09-08 \
  --weekly-report-doc 'https://example.feishu.cn/docx/DOCUMENT_TOKEN' \
  --output-dir tmp/periodic-review/example/raw
```

只有传了 `--weekly-report-doc` 才读该固定文档；只有传了 `--release-query` 才搜索 Release，二者可独立选用。没有 `--release-keywords` 时只执行明确传入的查询，不额外使用日期做全域搜索。传入关键词后，先按 `Release/MMDD` 标题日期找匹配关键词的候选，无匹配再执行明确传入的查询；两者都没有匹配时不读取其他文档。多个逗号分隔关键词表示命中任意一个；把允许读取的项目条件写入查询或关键词。

`--release-offset-days` 默认 `6,4`，表示相对开始日期的标题日期偏移。输出保留候选、选中项、正文和警告。标题与日期只帮助定位，复盘仍需结合正文判断材料对应的时期与事实。普通在线文档无须使用这个专门工具。

## 可选：转成阅读稿

```bash
python3 .agents/skills/periodic-review/sources/feishu/extract_drafts.py \
  --raw-dir tmp/periodic-review/example/raw \
  --output-dir tmp/periodic-review/example/readable
```

它只读本地 JSON，生成按聊天、文档或活动组织的 Markdown 和 HTML 阅读页，不访问飞书、不生成最终复盘结论。使用一个新的输出目录处理一次范围，避免旧材料混入本次阅读。阅读稿保留原始入口和缺口；需要确认时回到原响应或在线正文。

通知规则由本 Skill 的实际 `AGENTS.md` 单独指定。需要通知时依 `lark-im` 和现有授权执行，不通过信源读取脚本发送消息。
