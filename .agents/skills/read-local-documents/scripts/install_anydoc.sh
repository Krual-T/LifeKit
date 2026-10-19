#!/usr/bin/env bash
set -euo pipefail

readonly ANYDOC_VERSION="0.2.3"
readonly CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}"
readonly INSTALL_DIR="$CACHE_ROOT/lifekernel/anydoc/$ANYDOC_VERSION"
readonly ANYDOC_BIN="$INSTALL_DIR/node_modules/.bin/anydoc"

if [[ -x "$ANYDOC_BIN" ]]; then
  printf '%s\n' "$ANYDOC_BIN"
  exit 0
fi

command -v node >/dev/null 2>&1 || {
  printf 'read-local-documents: Node.js 20 or newer is required\n' >&2
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  printf 'read-local-documents: npm is required to install AnyDoc\n' >&2
  exit 1
}

readonly NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if (( NODE_MAJOR < 20 )); then
  printf 'read-local-documents: Node.js 20 or newer is required; found %s\n' "$(node --version)" >&2
  exit 1
fi

mkdir -p -- "$INSTALL_DIR"

export npm_config_update_notifier=false
export npm_config_fund=false
export npm_config_audit=false

npm install \
  --prefix "$INSTALL_DIR" \
  --no-save \
  --no-package-lock \
  "@firecrawl/anydoc@$ANYDOC_VERSION" >&2

if [[ ! -x "$ANYDOC_BIN" ]]; then
  printf 'read-local-documents: AnyDoc installation completed without an executable\n' >&2
  exit 1
fi

printf '%s\n' "$ANYDOC_BIN"
