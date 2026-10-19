# wiki-retrieval

`wiki-retrieval` is a profile-independent, deterministic CLI for validating,
indexing, querying, and reading OKF Markdown Wikis. Markdown and YAML
frontmatter remain authoritative; the SQLite index under `.okf/` is derived and
can be deleted at any time.

Validation follows the canonical OKF v0.2 conformance contract: every concept
must have a non-empty string `type`, and OKF-defined timestamp fields must use
ISO 8601 datetimes with an explicit UTC offset (for example,
`2026-08-26T12:00:00+08:00` or `2026-08-26T04:00:00Z`). Unknown types and
extension fields remain valid, and the Markdown body may use standard footnotes.
When present, `generated`, `verified`, and `sources` must follow their OKF
container and required-entry contracts; `Attested Computation` concepts must
declare `runtime`. Reserved `index.md` and `log.md` files receive their basic
structural checks, without treating broken links as validation errors.
The canonical specification is maintained in the
[GoogleCloudPlatform/open-knowledge-format repository](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md).

```bash
uv tool install --editable /path/to/okf-retrieval
wiki-retrieval query "reading plan" --wiki-root /path/to/wiki
wiki-retrieval get notes/reading-plan.md --level l2 \
  --wiki-root /path/to/wiki
```

The commands above are for a standalone installation; replace the example paths
with your own. For a LifeKernel instance, follow the repository
[initialization instructions](../../README.md#初始化) to install into that
instance's virtual environment instead of replacing a user-level command.

The command and distribution are named `wiki-retrieval`; the source directory,
Python module `okf_retrieval`, and existing configuration name are unchanged.

An optional `.okf-retrieval.yaml` can add frontmatter dot paths to the search
corpus or L1 overview:

```yaml
searchable_frontmatter:
  - x-example.card.current
l1_frontmatter:
  - x-example.card.current
```
