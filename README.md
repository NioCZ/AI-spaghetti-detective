# AI Spaghetti Detective for Klipper

This is a Klipper `extras` module that checks a webcam snapshot with the OpenAI
Responses API every N layers. It is meant as a practical "spaghetti detective":
your slicer calls a G-code command on layer change, the plugin captures a camera
snapshot, asks a vision-capable OpenAI model for a JSON verdict, and can pause
the print when the model is confident that the print has failed.

It does not train a local model and does not need GPU hardware on the printer
host. It uses only Python standard library modules.

## Files

- `klippy/extras/ai_spaghetti_detective.py` - Klipper plugin module.
- `config/ai_spaghetti_detective.cfg` - example `printer.cfg` section and macros.
- `scripts/install.sh` - Linux install helper for a normal `~/klipper` setup.

## Install

On the Klipper host:

```bash
cd ~/printer_data/config
git clone <this-repo-or-copy-folder> ai-spaghetti-detective
cd ai-spaghetti-detective
bash scripts/install.sh
```

If Klipper is not installed in `~/klipper`:

```bash
KLIPPER_DIR=/path/to/klipper bash scripts/install.sh
```

Then copy the relevant section from `config/ai_spaghetti_detective.cfg` into
`printer.cfg` and restart Klipper.

## API Key

Recommended:

```bash
echo "sk-your-key-here" > ~/printer_data/config/openai_api_key
chmod 600 ~/printer_data/config/openai_api_key
```

The plugin also checks the `OPENAI_API_KEY` environment variable. A direct
`api_key:` config option exists, but putting secrets directly in `printer.cfg`
is usually a bad habit.

## Camera Snapshot

Set one of these in `[ai_spaghetti_detective]`:

```ini
snapshot_url: http://127.0.0.1/webcam/?action=snapshot
# snapshot_url: http://127.0.0.1/webcam/snapshot
# snapshot_path: /tmp/klipper_snapshot.jpg
```

Test the URL from the Klipper host before relying on it:

```bash
curl -o /tmp/test_snapshot.jpg 'http://127.0.0.1/webcam/?action=snapshot'
```

## Slicer Layer Change G-code

Add this to the slicer's "after layer change" or "layer change G-code":

```gcode
AI_SPAGHETTI_CHECK
```

The plugin will count calls and check every `check_every_layers`.

If your slicer can provide a layer number, you can pass it:

```gcode
AI_SPAGHETTI_CHECK LAYER={layer_num}
```

For PrusaSlicer/SuperSlicer/OrcaSlicer you may need the placeholder used by
your slicer profile. If the layer placeholder is uncertain, use the simple
counter form first.

## Useful Commands

```gcode
AI_SPAGHETTI_CHECK FORCE=1
AI_SPAGHETTI_STATUS
AI_SPAGHETTI_ENABLE ENABLE=0
AI_SPAGHETTI_ENABLE ENABLE=1
AI_SPAGHETTI_RESET
```

## Important Settings

```ini
check_every_layers: 5
start_layer: 5
model: gpt-5-mini
image_detail: low
pause_on_failure: True
pause_confidence: 0.75
pause_gcode: PAUSE
fail_open: True
```

`image_detail: low` is usually enough and keeps cost down. Increase to `auto` or
`high` only if the camera view needs more detail. `original` is accepted by the
plugin too, but use it only with OpenAI models that support that detail level.

`fail_open: True` means camera/API errors will not pause the printer. Set it to
`False` if you prefer a conservative pause when checks fail.

## What the Model Returns

The plugin asks for structured JSON:

```json
{
  "status": "ok | warning | failure | unknown",
  "confidence": 0.0,
  "should_pause": false,
  "reason": "short visible evidence",
  "recommended_action": "what to check"
}
```

The printer pauses only when:

- `pause_on_failure` is true,
- `status` is in `pause_statuses`,
- `confidence` is at least `pause_confidence`,
- `should_pause` is true.

## Notes

This is a safety helper, not a guarantee. Keep normal printer safety practices:
good camera lighting, thermal protection, smoke detection where appropriate,
and never treat a cloud model as the only protection for unattended printing.
