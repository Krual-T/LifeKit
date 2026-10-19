# Third-party notices

This local public candidate does not yet assign a license to LifeKit's original
code and documentation. The notices below retain the applicable terms for
adapted third-party material; they do not license the entire repository.

## qu-ai-wei

Some writing and collaboration principles in the Skills and instance rules are
adapted from [LifelongLazyLearner/qu-ai-wei](https://github.com/LifelongLazyLearner/qu-ai-wei),
v0.9.0, commit `4436e465d43e361a81b2ae41f9c8634b886df281`.

MIT License

Copyright (c) 2026 @LifelongLazyLearner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Other components

- The product-management Skill routes to Dean Peters's
  [Product-Manager-Skills](https://github.com/deanpeters/Product-Manager-Skills),
  pinned at `cfcb697f14b8891d8b3ec43c16c3547df3e70e13`. The reference library is
  downloaded separately under **CC BY-NC-SA 4.0**, with its LICENSE and attribution
  retained. LifeKit's original-content license does not replace those terms.
- The markdown-to-pdf Skill includes Adobe's Source Han Serif and Source Han Sans
  font files under the SIL Open Font License 1.1. The original notices and license
  text are retained beside the font files in that Skill's `assets/fonts/`.
- RustFS is obtained separately from its official release. The deployment scripts
  do not vendor or relicense the RustFS server. Lark CLI and its Skills are also
  installed separately from the official larksuite project.

- The output-style Skill retains its own [third-party notices](.agents/skills/output-style/THIRD_PARTY_NOTICES).
- The OKF format reference is a local usage guide linking to the canonical
  specification; the upstream specification is not bundled.
- PyYAML and the build tools are installed as dependencies. AnyDoc is downloaded
  on demand at the version pinned by its installer. Their packages and licenses
  remain with their respective authors; dependency source is not vendored here.
