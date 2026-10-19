# LifeKernel

把个人记忆保存在自己的 Git 仓库中，通过公共上游持续更新记忆工具与 Skills。助手的名字、人格和日常记录由每个实例自己维护。

这是首批 T0 本地候选。包含 OKF Wiki 导航与检索、调研、写作、技术设计、子智能体协作、解释输出和本地文档读取。周期复盘采集、账号连接、通知与定时任务不在本批范围内。公开发布前仍需确定自有内容的许可证和发布仓库；随附第三方内容按各自的版权声明处理，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 文件归属

| 公共上游维护 | 个人私有 Git 维护 |
| --- | --- |
| `.agents/skills/`、`projects/okf-retrieval/`、`.codex/agents/`、依赖和忽略规则 | `wiki/`：自己的身份、经历、想法和日常记录 |
| `.codex/templates/AGENTS.ini.md`：入口、协作与数据规则样板 | `AGENTS.md`：实例规则、个人入口与近期记忆索引 |
| `.codex/templates/Assistant.ini.md`：人格样板 | `Assistant.ini.md`：自己的助手名称、人格、语言与偏好 |
| `.codex/templates/config.toml`：宿主配置样板 | `.codex/config.toml`：当前实例启用的宿主配置 |

公共提交不占用右侧实例路径，也不忽略上述 Wiki、AGENTS、人格和配置文件。模板只在首次初始化时复制；以后更新模板不会重写个人文件。`AGENTS.ini.md` 和 `Assistant.ini.md` 都是普通 Markdown，`.ini.md` 表示初始化样板。助手默认叫 Assistant，可在个人文件里修改；若也修改人格文件名，同步修改个人 `AGENTS.md` 的读取路径。

## 建立自己的仓库

从公共仓库 **clone**，保留共同历史。准备一个空的私有远程仓库，然后执行下列命令；将两个占位地址换成实际地址：

```bash
git clone <PUBLIC_REPOSITORY_URL> MyLifeKernel
cd MyLifeKernel
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPOSITORY_URL>
git config remote.pushDefault origin
```

私人内容只推向自己的 `origin`。GitHub 的模板按钮会创建独立历史，因此这里推荐 clone；GitHub fork 网络也不是普通 Git 合并的前提。

## 初始化

本批面向 Linux、Bash、Git、Python >=3.11、`uv` 与 Codex。Wiki 导航使用 Linux 文件锁。其他系统尚未验收。文档转换另需 Node.js >=20、npm 和 GNU `realpath`，仅在首次转换时下载固定版本 AnyDoc。

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

在这个实例内安装工具，避免借用另一份 LifeKernel 的源码：

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
git commit -m "Initialize personal LifeKernel instance"
git push -u origin main
```

不要在公共上游的工作目录里开始记录日常内容。

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

若曾按旧版 T0 的根 `templates/` 初始化，本次合并后须将原 `docs/instance-rules.md` 中的规则合入个人 `AGENTS.md`，可对照 `.codex/templates/AGENTS.ini.md` 逐段采纳；同时将个人 AGENTS、人格文件中对旧规则文件的引用改为根 `AGENTS.md` 内的规则。保留个人入口、近期 marker、人格与额外约定。本版已移除 `docs/`，不能继续依赖旧路径，也不要重新运行初始化覆盖已有文件。

## 现有私人实例首次接入

已有私人历史的仓库，可以保留历史并一次性合并独立的公共版本。先在隔离工作树验证；公共候选和私人实例应始终使用不同目录与远程。

1. 确认公共版本从不含私人祖先的独立根提交 T0 演进；不要把旧私人仓库的可见性直接改为公开。
2. 记录私人起点 P0，保留一个明确的本地分支作为恢复引用。完成本任务修改的提交，保留其他任务的工作区。
3. 在干净的接入工作树添加公共 `upstream`，获取并选择经过审阅的公共提交。第一次执行 `git merge --no-commit --no-ff --allow-unrelated-histories <PUBLIC_COMMIT>`。后续版本有共同祖先，不再需要这个选项。
4. 逐文件解决共享路径的 add/add 冲突：公共工具采用已验收版本；私人 Wiki、人格、实际 AGENTS、启用配置和未提取模块保留。对照 `.codex/templates/AGENTS.ini.md` 将所需规则合入个人 AGENTS，保留个人入口、近期 marker 与个性化约定；后续规则变化继续按模板差异采纳。忽略规则合并双方真实数据边界。不要用 `-s ours` 或整树覆盖假装完成接入。
5. 新的模板不替换已有文件。当前人格若由其他宿主路径加载，可暂时保留，此时不要再加载 `Assistant.ini.md`。切换到人格模板时明确更新根 AGENTS 的读取路径，并移除旧的加载入口。确认始终只有一份当前人格来源。
6. 在该工作树的独立环境运行记忆、索引和受影响能力测试；比对 P0 下的私人文件与个人配置。验证通过后提交双父合并 M0，确认 P0 与选定公共提交都是 M0 的祖先，再按项目约定合入私人开发分支。

未提交的合并可在这个干净工作树里用 `git merge --abort` 退出；已提交的接入保留历史，通过后续修订处理问题。不要重写或删除旧私人历史。

首次接入完成后，个人日常提交和公共更新可以交替存在：

```text
公共：          T0 ───── T1 ───── T2
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
