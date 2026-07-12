#!/usr/bin/env bash
# Build PeechaSync-Setup-VERSION-Portable.zip (BAT menu + pyc-only app)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep -E '^APP_VERSION\s*=' "$ROOT/sync_app/core/app_version.py" | sed -E 's/.*"([^"]+)".*/\1/')"
SETUP_NAME="PeechaSync-Setup-${VERSION}-Portable"
OUT_DIR="$ROOT/tools/client-release-deploy"
STAGE_DIR="$OUT_DIR/_setup_build/$SETUP_NAME"
TEMPLATES="$ROOT/release/installer/templates"
REQ_CLIENT="$ROOT/release/requirements-client.txt"

echo "Building $SETUP_NAME ..."

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/engine/app"

copy_templates() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  shopt -s dotglob nullglob
  for item in "$src"/*; do
    local base
    base="$(basename "$item")"
    if [[ -d "$item" ]]; then
      copy_templates "$item" "$dst/$base"
    else
      cp -f "$item" "$dst/$base"
    fi
  done
}

copy_templates "$TEMPLATES" "$STAGE_DIR"

ICON_SRC="$ROOT/release/installer/assets/PeechaSync.ico"
if [[ -f "$ICON_SRC" ]]; then
  cp -f "$ICON_SRC" "$STAGE_DIR/PeechaSync.ico"
fi

APP_DIR="$STAGE_DIR/engine/app"
cp -f "$ROOT/main.py" "$APP_DIR/"
cp -f "$REQ_CLIENT" "$APP_DIR/requirements.txt"

copy_pkg() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  shopt -s dotglob nullglob
  for item in "$src"/*; do
    local base
    base="$(basename "$item")"
    if [[ "$base" == "license_generator.py" || "$base" == "license.json.example" ]]; then
      continue
    fi
    if [[ -d "$item" ]]; then
      copy_pkg "$item" "$dst/$base"
    else
      cp -f "$item" "$dst/$base"
    fi
  done
}

copy_pkg "$ROOT/sync_app" "$APP_DIR/sync_app"

echo "Compiling to .pyc ..."
python3 -m compileall -b -q "$APP_DIR"
find "$APP_DIR" -name '*.py' -delete
find "$APP_DIR" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

if [[ ! -f "$APP_DIR/main.pyc" ]]; then
  echo "ERROR: main.pyc not created"
  exit 1
fi

echo "$VERSION" > "$STAGE_DIR/VERSION.txt"

ZIP_PATH="$OUT_DIR/${SETUP_NAME}.zip"
rm -f "$ZIP_PATH" "$OUT_DIR/latest-portable.zip"
(
  cd "$OUT_DIR/_setup_build"
  zip -r -q "$ZIP_PATH" "$SETUP_NAME"
)
cp -f "$ZIP_PATH" "$OUT_DIR/latest-portable.zip"
rm -rf "$OUT_DIR/_setup_build"

echo "OK: $ZIP_PATH"
ls -lh "$ZIP_PATH"
echo ""
echo "Contents:"
unzip -l "$ZIP_PATH" | head -25
