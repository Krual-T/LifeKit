# LifeKit

LifeKit 提供可组合的个人助手模板、记忆工具与 Skills。把个人记忆保存在自己的 Git 仓库中，通过公共上游持续更新功能；助手的名字、人格和日常记录由每个实例自己维护。

公共仓库为 [Krual-T/LifeKit](https://github.com/Krual-T/LifeKit)，首个公开版本为 [`v0.1.0`](https://github.com/Krual-T/LifeKit/tree/v0.1.0)。公共历史独立维护，功能按需使用：

| 能力 | 入口 |
| --- | --- |
| 助手名称、人格和协作约定 | `.codex/templates/` 的三个初始化样板 |
| OKF Wiki 记忆、导航与检索 | [Using Wiki](.agents/skills/using-wiki/SKILL.md) |
| 调研、写作、技术设计、子智能体协作与解释输出 | `.agents/skills/` 中的对应 Skill |
| Word、PDF 等本地文档读取 | [Read Local Documents](.agents/skills/read-local-documents/SKILL.md) |
| 产品需求、研究、PRD 与路线图 | [产品经理](.agents/skills/product-management/SKILL.md) |
| Markdown 转 PDF | [Markdown 转 PDF](.agents/skills/markdown-to-pdf/SKILL.md) |
| 按可选信源进行日、周、月、年复盘 | [周期复盘与初始化](.agents/skills/periodic-review/README.md) |
| S3 上传、直读、显式导出与可选 RustFS 自建 | [存储使用与初始化](scripts/rustfs/README.md) |
| Codex 任务标题自动整理（可选插件） | [原作者插件的安装与配置](#codex-任务标题整理可选) |

LifeKit 提供的原创代码与文档采用 [MIT 许可证](LICENSE)。第三方内容保留各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。实例新增的 Wiki、个人记录和配置由实例维护者自行决定是否公开及如何授权。收藏和 DSH 不属于公共版。

周期复盘按实例登记的阅读方式使用材料。飞书、Codex 对话、Git 的读取脚本可以按需选用；本地笔记或在线文档也可以直接阅读。复盘要求和通知规则由使用者决定，定时调用样板在 Skill 内；原件归档使用下方的通用存储工具。

## 文件归属

| 公共上游维护 | 个人私有 Git 维护 |
| --- | --- |
| `.agents/skills/`、`projects/okf-retrieval/`、`scripts/`、`.codex/agents/`、依赖和忽略规则 | `wiki/`：自己的身份、经历、想法和日常记录 |
| `.codex/templates/AGENTS.ini.md`：入口、协作与数据规则样板 | `AGENTS.md`：实例规则、个人入口与近期记忆索引 |
| `.codex/templates/Assistant.ini.md`：人格样板 | `Assistant.ini.md`：自己的助手名称、人格、语言与偏好 |
| `.codex/templates/config.toml`：宿主配置样板 | `.codex/config.toml`：当前实例启用的宿主配置 |
| Skill 的通用规则、脚本及资产 | 个人字体、排版选择和实际使用成果 |
| 复盘 Skill 内的 `AGENTS.ini.md`、`Registry.ini.md` | 同一 Skill 内实际的 `AGENTS.md`、`Registry.md` 与非秘密来源配置 |

公共提交不占用右侧实例路径，也不忽略上述 Wiki、AGENTS、人格和配置文件。模板只在首次初始化时复制；以后更新模板不会重写个人文件。`AGENTS.ini.md` 和 `Assistant.ini.md` 都是普通 Markdown，`.ini.md` 表示初始化样板。助手默认叫 Assistant，可在个人文件里修改；若也修改人格文件名，同步修改个人 `AGENTS.md` 的读取路径。

## 建立自己的仓库

从公共仓库 **clone**，保留共同历史。准备一个空的私有远程仓库，然后执行下列命令；将 `<YOUR_PRIVATE_REPOSITORY_URL>` 换成自己的私有仓库地址：

```bash
git clone https://github.com/Krual-T/LifeKit.git MyLifeKit
cd MyLifeKit
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPOSITORY_URL>
git config remote.pushDefault origin
```

私人内容只推向自己的 `origin`。GitHub 的模板按钮会创建独立历史，因此这里推荐 clone；GitHub fork 网络也不是普通 Git 合并的前提。

## 初始化

当前面向 Linux、Bash、Git、Python >=3.11、`uv` 与 Codex。Wiki 导航使用 Linux 文件锁。其他系统尚未验收。文档读取另需 Node.js >=20、npm 和 GNU `realpath`，首次转换时下载固定版本 AnyDoc。PDF、飞书和自建存储各自的依赖在下方按需准备。

以下命令在全新实例根目录执行。先创建实例文件；任一目标已存在就退出，不覆盖已有配置：

```bash
(
  set -eu
  for target in AGENTS.md Assistant.ini.md .codex/config.toml wiki; do
    if test -e "$target" || test -L "$target"; then
      printf '初始化停止：%s 已存在，请人工检查。\n' "$target" >&2
      exit 1
    fi
  done
  mkdir -p .codex wiki
  cp .codex/templates/AGENTS.ini.md AGENTS.md
  cp .codex/templates/Assistant.ini.md Assistant.ini.md
  cp .codex/templates/config.toml .codex/config.toml
)
```

编辑 `Assistant.ini.md` 里的默认名称 `Assistant` 和交流偏好。根 `AGENTS.md` 包含实例规则，并明确要求助手读取人格文件；这不是宿主自动展开 Markdown 链接的机制，也没有覆盖 Codex 的内置指令。模板中的示例不应被当成使用者的事实写入 Wiki。

在这个实例内安装工具，避免借用另一份实例的源码：

```bash
uv sync --locked
uv pip install --python .venv/bin/python --no-deps --editable ./projects/okf-retrieval
ln -s ../../.agents/skills/using-wiki/scripts/wiki_index.py .venv/bin/wiki-index
export PATH="$PWD/.venv/bin:$PATH"

uv run --script .agents/skills/using-wiki/scripts/wiki_index.py ensure --project-root .
```

首次 `ensure` 会生成空 Wiki 导航并预热脚本依赖；成功时返回 `ok=true`、`fresh=true`。`.okf/` 为可重建缓存，不提交。每次进入实例后都要让当前进程使用该实例 `.venv/bin`；`uv sync` 后若移除了 editable 包，重新运行上面的 `uv pip install`。

从这个终端启动 `codex`，让宿主继承 PATH。在支持项目 Hooks 的版本中，通过 `/hooks` 审阅并信任项目配置，再开启新会话核对一次实际编辑反馈。Desktop 也需要继承同一工具 PATH；没有启用 Hook 时，使用上面的显式 `ensure` 即可。宿主信任和登录由本人设置，仓库不保存这些状态。配置依据见 [Codex 项目配置](https://learn.chatgpt.com/docs/config-file/config-basic)与[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。

审阅初始化文件与生成导航后，把它们提交到自己的私有仓库：

```bash
git add AGENTS.md Assistant.ini.md .codex/config.toml wiki/index.md
git commit -m "Initialize personal LifeKit instance"
git push -u origin main
```

不要在公共上游的工作目录里开始记录日常内容。

## 按需初始化其他能力

路径以当前实例为准，不设置统一的 LifeKit 根目录变量，也不新增仓库级配置中心。Skill 的必要来源和时间选择放在自己的目录内；公共只跟踪另名初始化样板。重复初始化应保留已经存在的实际配置。

### Codex 任务标题整理（可选）

[Codex Task Title Organizer](https://github.com/znbsf/codex-task-title-organizer) 由原作者 `znbsf` 独立维护，提供标题整理 Skill 和触发检查的 Hook。LifeKit 只提供安装入口，插件代码、版本和运行状态由 Codex 插件系统管理，与 Wiki、复盘和存储能力独立。

宿主需要 Python 3，以及支持插件 Hook 和当前任务改名工具的 Codex。首次安装按[原作者说明](https://github.com/znbsf/codex-task-title-organizer/blob/main/INSTALL.md)执行：

```bash
codex plugin marketplace add znbsf/codex-task-title-organizer --ref main
codex plugin add codex-task-title-organizer@codex-task-title-organizer
```

已有安装时，先用 `codex plugin marketplace list` 和 `codex plugin list` 确认来源，按原作者说明处理。安装后刷新或重启 Codex，开启新任务，在 `/hooks` 中审阅并信任该插件的 `UserPromptSubmit` 和 `PostToolUse` 命令，再确认自动检查生效。只复制 Skill 文件不能启用 Hook。

默认无需配置：插件在观察到第 2、4、10 次用户输入时提示检查标题，第 4、10 次根据任务变化决定是否更新。侧栏分组默认关闭。需要调整检查时机时，在自己的实例根目录创建 `.codex/task-title-organizer.json`：

```json
{
  "enabled": true,
  "checkpoints": [2, 4, 10]
}
```

将 `checkpoints` 改成需要的轮次；每个值为 1–50 的整数，互不重复，最多 8 个。设置 `"enabled": false` 可关闭本项目的自动检查。实际配置由实例维护，可以进入私人 Git；LifeKit 不预置这个生效文件。

命名偏好可以写在实例 `AGENTS.md` 中，例如要求使用项目名和中文工作类型；默认使用颜色块标记。跨项目的检查时机可由 `CODEX_TASK_TITLE_CHECKPOINTS` 环境变量设置，项目文件优先。完整配置优先级和可选侧栏分组见[原作者配置说明](https://github.com/znbsf/codex-task-title-organizer/blob/main/plugins/codex-task-title-organizer/skills/organize-codex-task-titles/references/configuration.md)。

### 产品经理与 PDF

- 产品经理参考库按[固定版本恢复步骤](.agents/skills/product-management/references/catalog.md#本地库的来源与恢复)安装到该 Skill 的 `references/.library/`。这个隐藏目录不进入 Git，也不作为一组顶层 Skills 注册；库的许可与本仓库自有内容分开。
- PDF 按 [Skill 的初始化与导出说明](.agents/skills/markdown-to-pdf/SKILL.md)准备 Python Markdown 解析器、Node/Playwright、Chromium、fontconfig 和 Poppler。可分发字体随 Skill 提供，生成 PDF 时嵌入，无需安装到系统；个人字体与样式使用现有参数覆盖。

### 飞书与周期复盘

飞书使用[官方 lark-cli 与 Skills](https://github.com/larksuite/cli)，不复制作者的全局 Skill、应用或登录态。以下为首次使用者在自己的机器上执行的安装与交互登录步骤；已有 CLI 或登录时先检查现状：

```bash
npx @larksuite/cli@latest install
lark-cli config init
lark-cli auth login --recommend
lark-cli auth status --json --verify
```

按官方安装器完成 Skills 安装，并确认宿主能找到 `lark-suite`。由 Agent 协助登录时，先读该 Skill 的 `lark-shared`，按其授权链接、二维码与分步登录流程操作。选择本人需要的权限；CLI 凭据由宿主管理，不放入 Skill 或 Git。只有选用飞书读取或通知时才需要这项初始化。

按[周期复盘初始化说明](.agents/skills/periodic-review/README.md)在该 Skill 内建立实际 `AGENTS.md` 和 `Registry.md`，填写自己的要求与来源范围。两份样板属于复盘 Skill，与 `.codex/templates/` 中助手整体初始化样板各自维护。`.env.example` 提供临时目录与可选对象存储路径；用本地笔记即可开始，不要求飞书或 S3。定时器只需设置执行项目、时间和调用 Skill 的提示词；通知权限写在实例 AGENTS，初始化不会发送消息或注册任务。

### 对象存储与 RustFS

已有 S3 服务时，按[存储说明](scripts/rustfs/README.md)提供连接配置，使用 `scripts/object_store.py --config <配置路径>`。希望在本机自建时，使用同一说明中的 RustFS 安装入口；它按当前用户生成本机配置与凭据。保持已有配置，不借初始化重启其他实例。

存储沿用组件已有的宿主配置位置。为兼容已有实例，S3 配置、RustFS 服务和 AnyDoc 缓存继续使用原有的 `lifekernel` 名称；LifeKit 改名不搬迁这些运行文件。日常读取使用 S3 引用，显式导出才写本地文件。复盘原件按实例需要归档，确认可回读后再清理临时副本；存储安装不会启用采集、通知或定时任务。

## 使用和更新

记忆格式与维护入口见 [Using Wiki](.agents/skills/using-wiki/SKILL.md)。开始时 Wiki 为空；只保存本人实际提供或核验过的信息。查询示例：

```bash
wiki-retrieval query "要回想的主题" --wiki-root wiki --include-draft --limit 3 --format text
wiki-index ensure --project-root .
```

更新前先提交自己的完整工作，查看公共版本说明，再获取和合并选定版本：

```bash
git fetch upstream
git merge upstream/main
wiki-index ensure --project-root .
```

依赖文件变化时按该版本说明更新本实例环境。工具和 Skills 随合并更新；`AGENTS.md`、`Assistant.ini.md` 和 `.codex/config.toml` 只在初始化时从模板复制，后续指令或配置更新需对照模板差异人工采纳。需要迁移个人文件的版本应明确给出步骤。自己修改公共代码后仍可能出现 Git 冲突，需按实际含义解决。

若曾按提取阶段的根 `templates/` 初始化，本次合并后须将原 `docs/instance-rules.md` 中的规则合入个人 `AGENTS.md`，可对照 `.codex/templates/AGENTS.ini.md` 逐段采纳；同时将个人 AGENTS、人格文件中对旧规则文件的引用改为根 `AGENTS.md` 内的规则。保留个人入口、近期 marker、人格与额外约定。本版已移除 `docs/`，不能继续依赖旧路径，也不要重新运行初始化覆盖已有文件。

## 现有私人实例首次接入

已有私人历史的仓库，可以保留历史并一次性合并独立的公共版本。先在隔离工作树验证；公共候选和私人实例应始终使用不同目录与远程。

1. 确认公共版本从不含私人祖先的独立根提交演进；不要把旧私人仓库的可见性直接改为公开。
2. 记录私人起点 P0，保留一个明确的本地分支作为恢复引用。完成本任务修改的提交，保留其他任务的工作区。
3. 在干净的接入工作树添加公共 `upstream`，获取并选择经过审阅的公共提交。第一次执行 `git merge --no-commit --no-ff --allow-unrelated-histories <PUBLIC_COMMIT>`。后续版本有共同祖先，不再需要这个选项。
4. 逐文件解决共享路径的 add/add 冲突：公共工具采用已验收版本；私人 Wiki、人格、实际 AGENTS、启用配置和未提取模块保留。对照 `.codex/templates/AGENTS.ini.md` 将所需规则合入个人 AGENTS，保留个人入口、近期 marker 与个性化约定；后续规则变化继续按模板差异采纳。忽略规则合并双方真实数据边界。不要用 `-s ours` 或整树覆盖假装完成接入。
5. 新的模板不替换已有文件。当前人格若由其他宿主路径加载，可暂时保留，此时不要再加载 `Assistant.ini.md`。切换到人格模板时明确更新根 AGENTS 的读取路径，并移除旧的加载入口。确认始终只有一份当前人格来源。
6. 在该工作树的独立环境运行记忆、索引和受影响能力测试；比对 P0 下的私人文件与个人配置。验证通过后提交双父合并 M0，确认 P0 与选定公共提交都是 M0 的祖先，再按项目约定合入私人开发分支。

未提交的合并可在这个干净工作树里用 `git merge --abort` 退出；已提交的接入保留历史，通过后续修订处理问题。不要重写或删除旧私人历史。

首次接入完成后，个人日常提交和公共更新可以交替存在：

```text
公共：          C0 ───── C1 ───── C2
                ╲       ╲        ╲
私人：P0 ─────── M0 ─ P1 ─ M1 ─ P2 ─ M2
```

公共分支永远不合入私人分支。需要贡献某项通用改进时，在公共历史的新分支中单独制作并审阅补丁。

## 本地验证

在初始化并激活本实例环境后运行现有测试：

```bash
python -m unittest discover -s .agents/skills/using-wiki/tests -p 'test_*.py'
python -m unittest discover -s projects/okf-retrieval/tests -p 'test_*.py'
```

测试在临时目录创建合成 Wiki，不需要任何个人记忆或账号。首次安装、Hook 触发和上游合并还应在隔离实例中验证；不要在公共候选目录生成正式个人文件。
