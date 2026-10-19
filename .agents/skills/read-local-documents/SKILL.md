---
name: read-local-documents
description: Convert and read local Word, PowerPoint, Excel, OpenDocument, RTF, EPUB, CSV, and text-based PDF files as Markdown with the project-pinned AnyDoc runtime. Use when a user attaches or references one of these files and the task requires reading, summarizing, comparing, extracting facts, or preparing searchable text. Do not use for creating or editing office files, or assume it can OCR scanned/image-only PDFs.
---

# Read Local Documents

Convert supported local documents to Markdown with the project-pinned AnyDoc runtime, then inspect only the portions needed for the user's task. Keep source files local and unchanged.

## Requirements

Use Bash and GNU `realpath` (including `-e` and `-m`). The AnyDoc runtime requires Node.js 20 or newer. Its first installation also needs npm and access to the package registry; later conversions can use the cached runtime without downloading packages.

## Supported inputs

- Word: `.doc`, `.docx`, `.docm`
- PowerPoint: `.ppt`, `.pps`, `.pot`, `.pptx`, `.pptm`, `.ppsx`, `.ppsm`
- Excel and CSV: `.xls`, `.xlsx`, `.xlsm`, `.xlsb`, `.csv`
- OpenDocument: `.odt`, `.ods`, `.odp`
- Other: `.rtf`, `.epub`
- PDF: text-based PDFs only

## Workflow

1. Resolve the source to an absolute local path and confirm it is a regular file.
2. For one-off reading, create a unique temporary directory with `mktemp -d` and put the Markdown there. If the user asks to retain derived Markdown, choose an explicit domain-owned project path with them rather than placing it in a generic runtime directory.
3. Run:

```bash
bash .agents/skills/read-local-documents/scripts/convert_document.sh \
  /absolute/path/input.docx /absolute/path/output.md
```

4. Read the Markdown selectively. For large outputs, use `rg`, headings, and bounded `sed` ranges instead of loading the whole file.
5. Check that the output contains plausible document content before treating conversion as successful. Preserve uncertainty when layout, images, charts, formulas, or missing text could change the answer.

The wrapper refuses to overwrite an existing output. Use a new path rather than deleting or replacing prior derived content.

## Quality routing

- Office, OpenDocument, RTF, EPUB, and CSV are the primary path.
- PDF conversion uses `pdf-inspector`. Treat PDF Markdown as an extraction candidate, not proof of complete recovery. Check for empty or sparse text, garbled CJK, collapsed tables, broken reading order, and missing scan content.
- Scanned or image-only PDFs require a separate OCR or visual workflow. AnyDoc does not OCR them; report this boundary instead of silently uploading the file or returning an empty summary.
- Embedded images, diagrams, charts, and slide composition may carry meaning not present in Markdown. When that meaning matters, render or inspect the relevant pages/slides with an available local visual tool.
- Encrypted, malformed, or unsupported documents may fail. Do not infer content from filenames or partial error output.

## Local fallbacks

Use a fallback only when its result could change the answer:

- Text-based PDF: compare with `pdftotext`; use `pdfinfo` for page and encryption metadata.
- Office documents: use headless LibreOffice conversion when AnyDoc fails or clearly loses critical structure.
- If two extractors disagree on material text, explain the discrepancy and do not merge unsupported content.

## Privacy and version boundary

- Conversion is local. Do not send source files to Firecrawl Parse or another hosted service without explicit approval.
- The runtime is fixed at `@firecrawl/anydoc@0.2.3` and installed under `${XDG_CACHE_HOME:-$HOME/.cache}/lifekernel/anydoc/0.2.3/`.
- The installer contacts npm only to acquire the pinned package when the local runtime is absent; document conversion itself invokes the installed local binary.
- Do not change the pinned version, install a global package, or add OCR/cloud integration without explicit approval.
- Do not add source documents or generated Markdown to Git unless the repository policy and user intent explicitly require it.

## Scripts

- `scripts/install_anydoc.sh`: install the pinned runtime into the local cache and print its executable path on stdout; installation logs go to stderr.
- `scripts/convert_document.sh`: convert one local document to a new Markdown file and reject empty output.
