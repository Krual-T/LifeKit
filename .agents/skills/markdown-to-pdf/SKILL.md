---
name: markdown-to-pdf
description: 将本地 Markdown 汇报或中文文稿导出为 PDF，支持可配置字体、打印样式、图片和跨页表格。用于 Markdown 转 PDF 或复用正式文稿排版；不用于任意 PDF 编辑或幻灯片。
---

# Markdown 转 PDF

复用本技能的转换脚本和打印样式。用户当次要求优先；不因排版擅自改写正文、删除内容或给标题添加“草稿”和整理日期。

## 默认格式

- 中文正文用随附的思源宋体，中文标题用思源黑体；英文、数字与页码默认用思源宋体的拉丁字形。字体文件直接加载，无需安装进系统。
- 正文 12 pt、1.5 倍行距，普通段落首行缩进 `2em`；标题、图片、表格、图注和列表不套用正文缩进。
- A4 纵向，大标题居中。表格使用三线表：顶线、底线各 1.5 pt，表头下方线 0.75 pt；无竖线、内行线、底色和斑马纹。
- 图片按 Markdown 所在目录解析，优先使用同名 SVG。已转为路径的图中文字不会随正文 CSS 改字体。

这些是可覆盖的排版默认值；通过 `--css` 加载文稿专用样式。随附样式见 [print.css](assets/print.css)。

## 依赖初始化

需要 Python 的 `markdown_it`、Node.js、Playwright、Chrome 或 Chromium，以及 fontconfig；验收另需 Poppler 的 `pdffonts`、`pdftotext`、`pdftohtml` 和 `pdftoppm`。先复用宿主已有工具。缺失时在用户授权的初始化范围内准备依赖，不因转换一份文稿擅自修改宿主环境。

以下命令从仓库根目录执行，为本技能建立隔离的 Python 和 Node 依赖：

```bash
pdf_skill="$PWD/.agents/skills/markdown-to-pdf"
uv venv "$pdf_skill/.venv"
uv pip install --python "$pdf_skill/.venv/bin/python" 'markdown-it-py==3.0.0'
npm install --prefix "$pdf_skill" --no-save --package-lock=false playwright
```

Linux 上可通过发行版包管理器安装 `fontconfig`、`poppler-utils` 和 `chromium`；例如 Debian 使用 `sudo apt-get install fontconfig poppler-utils chromium`。使用已有 Chrome 时无需再装 Chromium。另一种方式是 `npx --prefix "$pdf_skill" playwright install chromium`，随后将 Playwright 报告的浏览器可执行文件路径传给 `--chrome`。

脚本先找本技能的 `node_modules/playwright/index.mjs`，再兼容 Codex 已有 runtime。`--playwright-module` 或 `CODEX_PLAYWRIGHT_MODULE` 可指定其他模块；`--chrome` 可指定浏览器。

## 导出与字体覆盖

```bash
"$pdf_skill/.venv/bin/python" "$pdf_skill/scripts/export_pdf.py" /absolute/path/report.md \
  --output /absolute/path/export/report.pdf
```

输出 PDF 和同目录同名 HTML。脚本等待图片、正文及页脚字体加载后打印，并输出包含实际选择的字体族名和页脚族名的 JSON。

`--song-font` / `--song-file` 控制中文正文，`--hei-font` / `--hei-file` 控制中文标题，`--latin-font` / `--latin-file` 控制英文、数字和页码。只给文件时读取其真实 family；同时给族名和文件时必须匹配。只给非默认族名时从系统字体解析，并拒绝 fontconfig 的字体替换。指定文件缺失或族名不匹配会失败，不自动改用其他字体。

旧的 `--song-file`、`--hei-file`、`--latin-file`、`--song-font`、`--hei-font`、`--css`、浏览器和 runtime 参数保持可用。原版字体留在实例本地；例如：

```bash
python3 "$pdf_skill/scripts/export_pdf.py" /absolute/path/report.md \
  --output /absolute/path/report.pdf \
  --song-font SimSun --song-file /private/fonts/simsun.ttc \
  --hei-font SimHei --hei-file /private/fonts/SimHei.ttf \
  --latin-font 'Times New Roman' --latin-file '/private/fonts/Times New Roman.ttf'
```

用户明确要求某种字体而当前缺失时，继续完成源文件和样式，说明缺项，等待可读取的字体路径；不能把替代字体版交付为完成品。字体选择覆盖独立打印页脚，不依赖正文 CSS 继承。

## 随附字体

以下文件直接来自 Adobe 官方仓库的固定版本，未修改字体内容：

| 文件 | 上游版本与来源 | 原始许可证 |
| --- | --- | --- |
| `assets/fonts/SourceHanSerifSC-Regular.otf` | [Source Han Serif 2.003R](https://github.com/adobe-fonts/source-han-serif/blob/2.003R/OTF/SimplifiedChinese/SourceHanSerifSC-Regular.otf) | [LICENSE-SourceHanSerif.txt](assets/fonts/LICENSE-SourceHanSerif.txt) |
| `assets/fonts/SourceHanSansSC-Regular.otf` | [Source Han Sans 2.004R](https://github.com/adobe-fonts/source-han-sans/blob/2.004R/OTF/SimplifiedChinese/SourceHanSansSC-Regular.otf) | [LICENSE-SourceHanSans.txt](assets/fonts/LICENSE-SourceHanSans.txt) |

两套字体适用 SIL Open Font License 1.1。分发本技能时保留各自版权声明与许可证；生成的文稿不因此变为 OFL 文稿。只有上述两份字体二进制进入 Git，其他自行提供的字体保持本地。

## 交付验证

用 `pdffonts` 检查实际嵌入字体，用 `pdftotext -layout` 检查标题、正文、表格和页码；用 `pdftoppm` 渲染并查看相关页面，检查截断、空白页、标题孤悬、图文分离及表格分页。修改字体或打印逻辑时，用 `pdftohtml -xml` 的文本位置与 fontspec 核对底部页码和正文的字体，不能仅检查 CSS 字符串。

较短表格保持完整；长表允许跨页并重复表头，不能为压进一页而缩小正文。检查实际 PDF 的表线和字体。

源 Markdown 和图片保持便于一起携带的结构。PDF、HTML、预览图等可重建产物不默认入库。脚本回归可用 `python3 -m unittest discover -s "$pdf_skill/scripts" -p 'test_*.py'`，需要上述转换和验收依赖。
