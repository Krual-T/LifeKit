"""Exercise real browser PDFs, including the independent page-number font."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from export_pdf import FONTS


SCRIPT = Path(__file__).with_name("export_pdf.py")
SAMPLE = """# 中文标题 Report 2026

中文正文用于检验字体。English body 12345.

| Item | Result |
| --- | --- |
| Example | Complete |

# 第二页 Second page

中文正文结束。End of report 67890.
"""


class ExportPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("node", "fc-scan", "fc-match", "pdffonts", "pdftotext", "pdftohtml"):
            if not shutil.which(tool):
                raise unittest.SkipTest(f"PDF integration tests require {tool}.")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="markdown-to-pdf-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "sample.md"
        self.source.write_text(SAMPLE, encoding="utf-8")
        self.css = self.directory / "sample.css"
        self.css.write_text("h1:not(:first-child) { break-before: page; }", encoding="utf-8")
        self.pdf = self.directory / "sample.pdf"

    def export(self, *arguments, successful=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.source), "--output", str(self.pdf),
             "--css", str(self.css), *map(str, arguments)],
            text=True, capture_output=True,
        )
        if not successful:
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.pdf.exists())
            return result
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def inspect_pdf(self, latin_family):
        fonts = subprocess.check_output(["pdffonts", str(self.pdf)], text=True)
        font_rows = fonts.splitlines()[2:]
        self.assertTrue(font_rows)
        for row in font_rows:
            self.assertEqual(row.split()[-5:-2], ["yes", "yes", "yes"], row)
            self.assertRegex(row.split()[0], r"SourceHan(?:Serif|Sans)SC")
        text = subprocess.check_output(["pdftotext", "-layout", str(self.pdf), "-"], text=True)
        for expected in ("中文标题", "English body 12345", "Complete", "End of report 67890"):
            self.assertIn(expected, text)
        xml = subprocess.check_output(["pdftohtml", "-xml", "-i", "-stdout", str(self.pdf)], text=True)
        document = ET.fromstring(xml)
        families = {font.attrib["id"]: font.attrib["family"] for font in document.iter("fontspec")}
        pages = document.findall("page")
        self.assertEqual(len(pages), 2)
        for number, page in enumerate(pages, 1):
            footer = [item for item in page.findall("text")
                      if float(item.attrib["top"]) > float(page.attrib["height"]) * 0.9]
            self.assertEqual("".join("".join(item.itertext()) for item in footer).replace(" ", ""),
                             f"{number}/2")
            for item in footer:
                self.assertIn(latin_family, families[item.attrib["font"]])
        body = [item for item in pages[0].findall("text") if "English body" in "".join(item.itertext())]
        self.assertTrue(body)
        self.assertIn(latin_family, families[body[0].attrib["font"]])
        chinese_fonts = {families[item.attrib["font"]] for item in pages[0].findall("text")
                         if "中" in "".join(item.itertext())}
        self.assertTrue(any("SourceHanSansSC" in family for family in chinese_fonts))
        self.assertTrue(any("SourceHanSerifSC" in family for family in chinese_fonts))

    def test_bundled_fonts_cover_body_and_page_numbers(self):
        result = self.export()
        self.assertEqual(result["fonts"], ["Source Han Serif SC", "Source Han Sans SC", "Source Han Serif SC"])
        self.assertEqual(result["footer_font"], "Source Han Serif SC")
        self.inspect_pdf("SourceHanSerifSC")

    def test_latin_override_reaches_body_and_page_numbers(self):
        result = self.export("--latin-font", "Source Han Sans SC", "--latin-file", FONTS / "SourceHanSansSC-Regular.otf")
        self.assertEqual(result["footer_font"], "Source Han Sans SC")
        self.inspect_pdf("SourceHanSansSC")

    def test_legacy_file_only_arguments_keep_supplied_font_families(self):
        result = self.export("--song-file", FONTS / "SourceHanSerifSC-Regular.otf",
                             "--hei-file", FONTS / "SourceHanSansSC-Regular.otf",
                             "--latin-file", FONTS / "SourceHanSansSC-Regular.otf")
        self.assertEqual(result["fonts"][-1], "Source Han Sans SC")
        self.inspect_pdf("SourceHanSansSC")

    def test_mismatched_explicit_family_fails_before_printing(self):
        result = self.export("--latin-font", "Times New Roman", "--latin-file",
                             FONTS / "SourceHanSerifSC-Regular.otf", successful=False)
        self.assertIn("does not contain 'Times New Roman'", result.stderr)

    def test_missing_explicit_family_rejects_system_substitution(self):
        result = self.export("--latin-font", "LifeKernelNonexistentTestFont", successful=False)
        self.assertIn("fontconfig substituted", result.stderr)

    def test_missing_explicit_file_fails_before_printing(self):
        result = self.export("--latin-file", self.directory / "missing.ttf", successful=False)
        self.assertIn("missing.ttf", result.stderr)

    def test_long_table_splits_and_repeats_header(self):
        self.source.write_text("# Long table\n\n| Item | Result |\n| --- | --- |\n" +
                               "".join(f"| Row {number:02} | 中文数据 Complete |\n" for number in range(1, 61)),
                               encoding="utf-8")
        self.export()
        text = subprocess.check_output(["pdftotext", "-layout", str(self.pdf), "-"], text=True)
        pages = [page for page in text.split("\f") if page.strip()]
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertIn("Item", page)
            self.assertIn("Result", page)
        for number in range(1, 61):
            self.assertIn(f"Row {number:02}", text)


if __name__ == "__main__":
    unittest.main()
