"""Render local Markdown as PDF with configurable Chinese and Latin fonts."""

import argparse
import html
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "assets/fonts"
LOCAL_RUNTIME = HERE.parent / "node_modules/playwright/index.mjs"
HOST_RUNTIME = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs"
DEFAULT_RUNTIME = LOCAL_RUNTIME if LOCAL_RUNTIME.is_file() else HOST_RUNTIME
DEFAULT_SONG = ("Source Han Serif SC", FONTS / "SourceHanSerifSC-Regular.otf")
DEFAULT_HEI = ("Source Han Sans SC", FONTS / "SourceHanSansSC-Regular.otf")
LATIN_CSS_FAMILY = "Markdown Latin"


def require_font(family):
    resolved = subprocess.check_output(
        ["fc-match", "--format=%{family}", family], text=True
    ).strip()
    if family.casefold() not in {s.strip().casefold() for s in resolved.split(",")}:
        raise SystemExit(f"Missing font {family!r}; fontconfig substituted {resolved!r}. "
                         "Provide --*-file or explicitly choose another font family.")
    return Path(subprocess.check_output(
        ["fc-match", "--format=%{file}", family], text=True
    ).strip()).resolve(strict=True)


def select_font(family, font_file, default):
    if font_file is None:
        font_file = default[1] if family is None or family.casefold() == default[0].casefold() else require_font(family)
        family = family or default[0]
    path = font_file.resolve(strict=True)
    families = subprocess.check_output(
        ["fc-scan", "--format=%{family}\\n", str(path)], text=True
    ).strip()
    if not families:
        raise SystemExit(f"No font family found in {path}.")
    # File-only overrides retain the family in the supplied font, including the
    # legacy SimSun / SimHei / Times New Roman file arguments.
    family = family or families.splitlines()[0].split(",")[0].strip()
    if family.casefold() not in {s.strip().casefold() for line in families.splitlines()
                                for s in line.split(",")}:
        raise SystemExit(f"{path} does not contain {family!r}; found {families!r}.")
    return family, path


def font_css(family, path, latin=False):
    # A CJK font used for Latin must not take over Chinese headings merely
    # because it precedes the selected Hei family in the font stack.
    css_family = LATIN_CSS_FAMILY if latin else family
    unicode_range = " unicode-range: U+0000-024F, U+1E00-1EFF, U+2000-206F, U+20A0-20CF, U+FB00-FB06;" if latin else ""
    return "@font-face { font-family: " + json.dumps(css_family) + "; src: url(" \
           + json.dumps(path.as_uri()) + "); font-weight: 400; font-style: normal;" \
           + unicode_range + " }\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--song-font", help="Chinese body family; default: Source Han Serif SC")
    parser.add_argument("--hei-font", help="Chinese heading family; default: Source Han Sans SC")
    parser.add_argument("--latin-font", help="Latin text and page number family; default: Source Han Serif SC")
    parser.add_argument("--song-file", type=Path, help="Chinese body font file; default: bundled Source Han Serif")
    parser.add_argument("--hei-file", type=Path, help="Chinese heading font file; default: bundled Source Han Sans")
    parser.add_argument("--latin-file", type=Path, help="Latin font file; default: bundled Source Han Serif")
    parser.add_argument("--css", type=Path)
    parser.add_argument("--chrome", default=shutil.which("google-chrome") or shutil.which("chromium"))
    parser.add_argument("--playwright-module", type=Path,
                        default=Path(os.environ.get("CODEX_PLAYWRIGHT_MODULE", DEFAULT_RUNTIME)))
    args = parser.parse_args()
    song = select_font(args.song_font, args.song_file, DEFAULT_SONG)
    hei = select_font(args.hei_font, args.hei_file, DEFAULT_HEI)
    latin = select_font(args.latin_font, args.latin_file, DEFAULT_SONG)
    faces = font_css(*song) + font_css(*hei) + font_css(*latin, latin=True)
    if not args.chrome or not args.playwright_module.is_file():
        parser.error("Chrome and Playwright must be available; pass --chrome / --playwright-module.")

    source = args.source.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    md = MarkdownIt("commonmark").enable("table")
    content = source.read_text(encoding="utf-8")
    # Wiki metadata describes the source; it is not part of the printed report.
    content = re.sub(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", "", content, count=1, flags=re.S)
    tokens = md.parse(content)
    title = source.stem
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1":
            title = tokens[index + 1].content
            break
    image_count = 0
    for token in tokens:
        for child in token.children or []:
            if child.type != "image":
                continue
            ref = child.attrGet("src")
            url = urlsplit(ref)
            if not url.scheme:
                local = source.parent / unquote(url.path)
                vector = local.with_suffix(".svg")
                if vector.is_file():
                    local = vector
                if not local.is_file():
                    raise FileNotFoundError(local)
                child.attrSet("src", local.resolve().as_uri())
            image_count += 1
    css = faces + ":root { --song-font: " + json.dumps(song[0]) + "; --hei-font: " \
          + json.dumps(hei[0]) + "; --latin-font: " + json.dumps(LATIN_CSS_FAMILY) + "; }\n"
    css += (HERE.parent / "assets/print.css").read_text(encoding="utf-8")
    if args.css:
        css += "\n" + args.css.read_text(encoding="utf-8")
    html_path = output.with_suffix(".html")
    html_path.write_text('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                         '<title>' + html.escape(title) + '</title><style>' + css
                         + '</style></head><body>' + md.renderer.render(tokens, md.options, {})
                         + '</body></html>', encoding="utf-8")
    subprocess.run(["node", str(HERE / "print_pdf.mjs"), args.playwright_module.resolve().as_uri(),
                    args.chrome, html_path.as_uri(), str(output), latin[0], str(latin[1])], check=True)
    print(json.dumps({"pdf": str(output), "images": image_count,
                      "fonts": [song[0], hei[0], latin[0]],
                      "footer_font": latin[0]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
