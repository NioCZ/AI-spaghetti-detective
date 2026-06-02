#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
TARGET_DIR="$KLIPPER_DIR/klippy/extras"
TARGET_FILE="$TARGET_DIR/ai_spaghetti_detective.py"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Klipper extras directory not found: $TARGET_DIR" >&2
  echo "Set KLIPPER_DIR=/path/to/klipper and run again." >&2
  exit 1
fi

install -m 0644 "$SOURCE_DIR/klippy/extras/ai_spaghetti_detective.py" "$TARGET_FILE"

echo "Installed: $TARGET_FILE"
echo
echo "Next steps:"
echo "  1. Add config/ai_spaghetti_detective.cfg content to printer.cfg."
echo "  2. Put your API key in ~/printer_data/config/openai_api_key."
echo "  3. Restart Klipper."
