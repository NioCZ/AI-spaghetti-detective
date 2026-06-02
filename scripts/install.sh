#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
REQUESTED_PRINTER_CONFIG_DIR="${PRINTER_CONFIG_DIR:-}"
PRINTER_CONFIG_DIR="${REQUESTED_PRINTER_CONFIG_DIR:-$HOME/printer_data/config}"
PRINTER_CFG="${PRINTER_CFG:-}"
TARGET_DIR="$KLIPPER_DIR/klippy/extras"
TARGET_FILE="$TARGET_DIR/ai_spaghetti_detective.py"
INCLUDE_LINE="[include ai_spaghetti_detective.cfg]"

if [[ -z "$REQUESTED_PRINTER_CONFIG_DIR" && ! -d "$PRINTER_CONFIG_DIR" && -d "$HOME/klipper_config" ]]; then
  PRINTER_CONFIG_DIR="$HOME/klipper_config"
fi

CONFIG_FILE="$PRINTER_CONFIG_DIR/ai_spaghetti_detective.cfg"
API_KEY_FILE="$PRINTER_CONFIG_DIR/openai_api_key"
DEFAULT_API_KEY_FILE="$HOME/printer_data/config/openai_api_key"
if [[ -z "$PRINTER_CFG" ]]; then
  PRINTER_CFG="$PRINTER_CONFIG_DIR/printer.cfg"
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Klipper extras directory not found: $TARGET_DIR" >&2
  echo "Set KLIPPER_DIR=/path/to/klipper and run again." >&2
  exit 1
fi

if [[ ! -d "$PRINTER_CONFIG_DIR" ]]; then
  echo "Printer config directory not found: $PRINTER_CONFIG_DIR" >&2
  echo "Set PRINTER_CONFIG_DIR=/path/to/printer_data/config and run again." >&2
  exit 1
fi

install -m 0644 "$SOURCE_DIR/klippy/extras/ai_spaghetti_detective.py" "$TARGET_FILE"
install -m 0644 "$SOURCE_DIR/config/ai_spaghetti_detective.cfg" "$CONFIG_FILE"

if [[ "$API_KEY_FILE" != "$DEFAULT_API_KEY_FILE" ]]; then
  SED_API_KEY_FILE="${API_KEY_FILE//\\/\\\\}"
  SED_API_KEY_FILE="${SED_API_KEY_FILE//&/\\&}"
  SED_API_KEY_FILE="${SED_API_KEY_FILE//#/\\#}"
  sed -i "s#^api_key_path: .*#api_key_path: $SED_API_KEY_FILE#" "$CONFIG_FILE"
fi

KEY_READY=0
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  umask 077
  printf "%s\n" "$OPENAI_API_KEY" > "$API_KEY_FILE"
  chmod 600 "$API_KEY_FILE" 2>/dev/null || true
  KEY_STATUS="Saved API key to: $API_KEY_FILE"
  KEY_READY=1
elif [[ -f "$API_KEY_FILE" ]]; then
  KEY_STATUS="API key already exists: $API_KEY_FILE"
  KEY_READY=1
else
  KEY_STATUS="API key not found yet: $API_KEY_FILE"
fi

if [[ -f "$PRINTER_CFG" ]]; then
  if grep -Eq '^[[:space:]]*\[include[[:space:]]+ai_spaghetti_detective\.cfg\][[:space:]]*$' "$PRINTER_CFG"; then
    INCLUDE_STATUS="Already included in: $PRINTER_CFG"
  else
    BACKUP_FILE="$PRINTER_CFG.bak.ai_spaghetti_detective.$(date +%Y%m%d%H%M%S)"
    cp "$PRINTER_CFG" "$BACKUP_FILE"
    printf "\n%s\n" "$INCLUDE_LINE" >> "$PRINTER_CFG"
    INCLUDE_STATUS="Added include to: $PRINTER_CFG (backup: $BACKUP_FILE)"
  fi
else
  INCLUDE_STATUS="printer.cfg was not found. Add this line manually: $INCLUDE_LINE"
fi

echo "Installed: $TARGET_FILE"
echo "Installed: $CONFIG_FILE"
echo "$INCLUDE_STATUS"
echo "$KEY_STATUS"
echo
echo "Next steps:"
if [[ "$KEY_READY" -eq 1 ]]; then
  echo "  1. Restart Klipper."
  echo "  2. Add AI_SPAGHETTI_LAYER to your slicer layer-change G-code."
else
  echo "  1. Put your API key in: $API_KEY_FILE"
  echo "  2. Restart Klipper."
  echo "  3. Add AI_SPAGHETTI_LAYER to your slicer layer-change G-code."
fi
