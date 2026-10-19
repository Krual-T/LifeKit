# LifeKernel

把个人记忆保存在自己的 Git 仓库中，通过公共上游持续更新记忆工具与 Skills。助手的名字、人格和日常记录由每个实例自己维护。

这是首批 T0 本地候选。包含 OKF Wiki 导航与检索、调研、写作、技术设计、子智能体协作、解释输出和本地文档读取。周期复盘采集、账号连接、通知与定时任务不在本批范围内。公开发布前仍需确定自有内容的许可证和发布仓库；随附第三方内容按各自的版权声明处理，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 文件归属

| 公共上游维护 | 个人私有 Git 维护 |
| --- | --- |
| `.agents/skills/`、`projects/okf-retrieval/` | `wiki/`：自己的身份、经历、想法和日常记录 |
| `docs/instance-rules.md`：通用协作与数据规则 | `AGENTS.md`：个人入口与近期记忆索引 |
| `templates/`：首次初始化的样板 | `Assistant.ini.md`：自己的助手名称、人格、语言与偏好 |
| `.codex/agents/`、依赖和忽略规则 | `.codex/config.toml`：当前实例启用的宿主配置 |

公共提交不占用右侧路径，也不忽略它们。模板只在首次初始化时复制；以后更新模板不会重写个人文件。`Assistant.ini.md` 是普通 Markdown 指令文件，文件名不参与程序解析，也可以改名为 `Jarvis.ini.md` 或其他名字，并同步修改个人 `AGENTS.md` 的引用。

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
  cp templates/AGENTS.md AGENTS.md
  cp templates/Assistant.ini.md Assistant.ini.md
  cp templates/codex.config.toml .codex/config.toml
)
```

编辑 `Assistant.ini.md` 里的默认名称 `Assistant` 和交流偏好。根 `AGENTS.md` 要求助手读取这份文件及公共规则；这不是宿主自动展开 Markdown 链接的机制，也没有覆盖 Codex 的内置指令。模板中的示例不应被当成使用者的事实写入 Wiki。

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

依赖文件变化时按该版本说明更新本实例环境。公共模板不会自动重建个人配置；需要迁移个人文件的版本应明确给出步骤。自己修改公共代码后仍可能出现 Git 冲突，需按实际含义解决。

已有私人仓库首次接入，见[首次接入说明](docs/existing-instance.md)。向上游贡献时在公共历史的干净分支制作补丁，逐文件检查，避免把私人分支及其祖先推向公共仓库。

## 本地验证

在初始化并激活本实例环境后运行现有测试：

```bash
python -m unittest discover -s .agents/skills/using-wiki/tests -p 'test_*.py'
python -m unittest discover -s projects/okf-retrieval/tests -p 'test_*.py'
```

测试在临时目录创建合成 Wiki，不需要任何个人记忆或账号。首次安装、Hook 触发和上游合并还应在隔离实例中验证；不要在公共候选目录生成正式个人文件。
