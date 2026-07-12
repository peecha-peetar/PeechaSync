#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQ="$ROOT/release/requirements-client.txt"
DEST="$ROOT/release/installer/wheels"
mkdir -p "$DEST"
echo "Downloading Windows wheels (cp312) to $DEST ..."
for ver in 312; do
  python3 -m pip download -r "$REQ" -d "$DEST" \
    --platform win_amd64 --python-version "$ver" --implementation cp --only-binary=:all:
done
count="$(find "$DEST" -maxdepth 1 -name '*.whl' | wc -l)"
size="$(du -sh "$DEST" | awk '{print $1}')"
echo "OK: $count wheels ($size)"
