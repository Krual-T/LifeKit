#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )); then
  printf 'usage: %s INPUT_FILE OUTPUT_MD\n' "${0##*/}" >&2
  exit 2
fi

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! INPUT_FILE="$(realpath -e -- "$1" 2>/dev/null)"; then
  printf 'read-local-documents: input does not exist: %s\n' "$1" >&2
  exit 1
fi
readonly INPUT_FILE

OUTPUT_FILE="$(realpath -m -- "$2")"
readonly OUTPUT_FILE

if [[ ! -f "$INPUT_FILE" ]]; then
  printf 'read-local-documents: input is not a regular file: %s\n' "$INPUT_FILE" >&2
  exit 1
fi
if [[ "$INPUT_FILE" == "$OUTPUT_FILE" ]]; then
  printf 'read-local-documents: input and output paths must differ\n' >&2
  exit 2
fi
if [[ -e "$OUTPUT_FILE" ]]; then
  printf 'read-local-documents: refusing to overwrite existing output: %s\n' "$OUTPUT_FILE" >&2
  exit 2
fi

readonly OUTPUT_DIR="$(dirname -- "$OUTPUT_FILE")"
mkdir -p -- "$OUTPUT_DIR"

readonly ANYDOC_BIN="$(bash "$SCRIPT_DIR/install_anydoc.sh")"

if ! "$ANYDOC_BIN" "$INPUT_FILE" -o "$OUTPUT_FILE"; then
  rm -f -- "$OUTPUT_FILE"
  exit 1
fi

if [[ ! -s "$OUTPUT_FILE" ]]; then
  rm -f -- "$OUTPUT_FILE"
  printf 'read-local-documents: conversion produced empty Markdown\n' >&2
  exit 1
fi

printf '%s\n' "$OUTPUT_FILE"
