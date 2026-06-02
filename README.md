# AI Spaghetti Detective for Klipper

Klipper `extras` module that checks a webcam snapshot with the OpenAI Responses
API and can pause the print when it sees a confident spaghetti failure.

No local AI model, GPU, or Python package install is needed. The plugin uses
only Python standard library modules.

## Quick Setup

Run this on the Klipper host:

```bash
cd ~
git clone https://github.com/NioCZ/AI-spaghetti-detective.git
cd AI-spaghetti-detective

read -rsp "OpenAI API key: " OPENAI_API_KEY
printf '\n'
OPENAI_API_KEY="$OPENAI_API_KEY" bash scripts/install.sh
unset OPENAI_API_KEY

sudo systemctl restart klipper
```

The installer:

- copies the plugin to `~/klipper/klippy/extras/ai_spaghetti_detective.py`
- copies the minimal config to `~/printer_data/config/ai_spaghetti_detective.cfg`
- saves the API key to `~/printer_data/config/openai_api_key` when provided
- keeps `api_key_path` in the copied config aligned with your config directory
- adds `[include ai_spaghetti_detective.cfg]` to `printer.cfg` when missing
- backs up `printer.cfg` before changing it

Then add this to your slicer layer-change G-code:

```gcode
AI_SPAGHETTI_LAYER
```

That is the normal setup.

## Test

After Klipper restarts, run this from the console:

```gcode
AI_SPAGHETTI_TEST
AI_SPAGHETTI_STATUS
```

## Camera

The default camera URL is:

```ini
snapshot_url: http://127.0.0.1/webcam/?action=snapshot
```

If your printer uses a different snapshot URL, edit:

```bash
nano ~/printer_data/config/ai_spaghetti_detective.cfg
```

Common alternatives:

```ini
snapshot_url: http://127.0.0.1/webcam/snapshot
snapshot_path: /tmp/klipper_snapshot.jpg
```

You can test the default URL from the Klipper host:

```bash
curl -o /tmp/test_snapshot.jpg 'http://127.0.0.1/webcam/?action=snapshot'
```

## Custom Paths

If Klipper or `printer.cfg` is not in the default location, set paths before
running the installer:

```bash
KLIPPER_DIR="$HOME/klipper" PRINTER_CONFIG_DIR="$HOME/printer_data/config" bash scripts/install.sh
```

Change the values to match your install.

## Update

```bash
cd ~/AI-spaghetti-detective
git pull
bash scripts/install.sh
sudo systemctl restart klipper
```

## Useful Commands

```gcode
AI_SPAGHETTI_TEST
AI_SPAGHETTI_STATUS
AI_SPAGHETTI_ENABLE ENABLE=0
AI_SPAGHETTI_ENABLE ENABLE=1
AI_SPAGHETTI_RESET
```

## Default Settings

These are already built in:

```ini
check_every_layers: 5
start_layer: 5
api_key_path: ~/printer_data/config/openai_api_key
model: gpt-5-mini
image_detail: low
pause_on_failure: True
pause_confidence: 0.75
pause_gcode: PAUSE
fail_open: True
```

`fail_open: True` means camera/API errors do not pause the printer. Set it to
`False` if you prefer a conservative pause when checks fail.

## Safety

This is a helper, not a guarantee. Keep normal printer safety practices: good
camera lighting, thermal protection, smoke detection where appropriate, and do
not treat a cloud model as the only protection for unattended printing.
