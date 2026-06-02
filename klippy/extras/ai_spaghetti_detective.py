# AI Spaghetti Detective for Klipper
#
# Install this file into: ~/klipper/klippy/extras/ai_spaghetti_detective.py
#
# The module is intentionally dependency-free. It captures a webcam snapshot,
# sends it to the OpenAI Responses API, and optionally pauses the print when the
# model returns a confident failure classification.

import base64
import json
import logging
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.request


_DEFAULT_API_URL = "https://api.openai.com/v1/responses"
_DEFAULT_MODEL = "gpt-5-mini"
_DEFAULT_SNAPSHOT_URL = "http://127.0.0.1/webcam/?action=snapshot"
_VALID_IMAGE_DETAIL = set(["low", "high", "auto", "original"])
_VALID_STATUSES = set(["ok", "warning", "failure", "unknown"])


class AISpaghettiDetective:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")

        self.enabled = config.getboolean("enabled", True)
        self.check_every_layers = config.getint(
            "check_every_layers", 5, minval=1
        )
        self.start_layer = config.getint(
            "start_layer", self.check_every_layers, minval=0
        )
        self.capture_delay = config.getfloat("capture_delay", 0.0, minval=0.0)
        self.snapshot_timeout = config.getfloat(
            "snapshot_timeout", 8.0, minval=1.0
        )
        self.api_timeout = config.getfloat("api_timeout", 45.0, minval=5.0)
        self.max_image_bytes = config.getint(
            "max_image_bytes", 8 * 1024 * 1024, minval=1024
        )

        configured_snapshot_url = config.get("snapshot_url", None)
        self.snapshot_path = config.get("snapshot_path", None)
        self.snapshot_url = configured_snapshot_url
        if not self.snapshot_url and not self.snapshot_path:
            self.snapshot_url = _DEFAULT_SNAPSHOT_URL

        self.api_url = config.get("api_url", _DEFAULT_API_URL)
        self.model = config.get("model", _DEFAULT_MODEL)
        self.api_key = config.get("api_key", None)
        self.api_key_path = config.get(
            "api_key_path", "~/printer_data/config/openai_api_key"
        )
        self.image_detail = config.get("image_detail", "low").lower()
        if self.image_detail not in _VALID_IMAGE_DETAIL:
            raise config.error("image_detail must be one of: low, high, auto, original")

        self.pause_on_failure = config.getboolean("pause_on_failure", True)
        self.pause_confidence = config.getfloat(
            "pause_confidence", 0.75, minval=0.0, maxval=1.0
        )
        pause_statuses = config.get("pause_statuses", "failure")
        self.pause_statuses = set(
            [s.strip().lower() for s in pause_statuses.split(",") if s.strip()]
        )
        unknown_statuses = self.pause_statuses - _VALID_STATUSES
        if unknown_statuses:
            raise config.error(
                "pause_statuses contains unknown values: %s"
                % ", ".join(sorted(unknown_statuses))
            )
        self.pause_gcode = config.get("pause_gcode", "PAUSE").strip()
        self.report_prefix = config.get("report_prefix", "AI spaghetti").strip()
        self.fail_open = config.getboolean("fail_open", True)

        self.prompt = config.get("prompt", None)
        if self.prompt is None:
            self.prompt = self._default_prompt()

        self._lock = threading.Lock()
        self._active = False
        self._layer_calls = 0
        self._last_result = {
            "status": "unknown",
            "confidence": 0.0,
            "should_pause": False,
            "reason": "No check has run yet.",
            "recommended_action": "",
        }
        self._last_error = None
        self._last_checked_layer = None
        self._last_checked_at = None

        self.gcode.register_command(
            "AI_SPAGHETTI_CHECK",
            self.cmd_AI_SPAGHETTI_CHECK,
            desc="Capture a snapshot and ask OpenAI to check for spaghetti failure",
        )
        self.gcode.register_command(
            "AI_SPAGHETTI_ENABLE",
            self.cmd_AI_SPAGHETTI_ENABLE,
            desc="Enable or disable AI spaghetti detection",
        )
        self.gcode.register_command(
            "AI_SPAGHETTI_STATUS",
            self.cmd_AI_SPAGHETTI_STATUS,
            desc="Report the last AI spaghetti detection result",
        )
        self.gcode.register_command(
            "AI_SPAGHETTI_RESET",
            self.cmd_AI_SPAGHETTI_RESET,
            desc="Reset AI spaghetti detection layer counter and last result",
        )

    def _default_prompt(self):
        return (
            "You are inspecting a single webcam snapshot of an active FDM/FFF "
            "3D printer. Decide whether the visible print looks normal or shows "
            "a spaghetti failure. Classify detached parts, loose filament nests, "
            "large blobs around the nozzle, toolhead dragging a failed part, "
            "smoke, or fire as failure. Use warning for minor visible defects or "
            "weak evidence. Use unknown when the image is too dark, blurry, "
            "occluded, or does not show the print. Be conservative about pausing: "
            "set should_pause true only when there is strong visual evidence of a "
            "real failure. Return only the requested JSON."
        )

    def get_status(self, eventtime):
        return {
            "enabled": self.enabled,
            "active": self._active,
            "layer_calls": self._layer_calls,
            "check_every_layers": self.check_every_layers,
            "start_layer": self.start_layer,
            "last_checked_layer": self._last_checked_layer,
            "last_checked_at": self._last_checked_at,
            "last_error": self._last_error,
            "last_result": self._last_result,
        }

    def cmd_AI_SPAGHETTI_CHECK(self, gcmd):
        force = bool(gcmd.get_int("FORCE", 0, minval=0, maxval=1))
        layer = gcmd.get_int("LAYER", None, minval=0)

        if layer is None:
            self._layer_calls += 1
            layer = self._layer_calls
            should_run = (
                self._layer_calls >= self.start_layer
                and self._layer_calls % self.check_every_layers == 0
            )
        else:
            self._layer_calls = max(self._layer_calls, layer)
            should_run = (
                layer >= self.start_layer
                and (layer - self.start_layer) % self.check_every_layers == 0
            )

        if not self.enabled and not force:
            gcmd.respond_info("%s: disabled" % self.report_prefix)
            return
        if not force and not should_run:
            return

        with self._lock:
            if self._active:
                gcmd.respond_info("%s: check already running; skipped" % self.report_prefix)
                return
            self._active = True

        thread = threading.Thread(
            target=self._run_check,
            args=(layer, force),
            name="ai_spaghetti_detective",
        )
        thread.daemon = True
        thread.start()
        gcmd.respond_info("%s: check queued for layer %s" % (self.report_prefix, layer))

    def cmd_AI_SPAGHETTI_ENABLE(self, gcmd):
        self.enabled = bool(gcmd.get_int("ENABLE", 1, minval=0, maxval=1))
        gcmd.respond_info(
            "%s: %s" % (self.report_prefix, "enabled" if self.enabled else "disabled")
        )

    def cmd_AI_SPAGHETTI_STATUS(self, gcmd):
        result = self._last_result or {}
        msg = (
            "%s: enabled=%s active=%s layers=%s last_layer=%s "
            "status=%s confidence=%.2f pause=%s reason=%s"
            % (
                self.report_prefix,
                self.enabled,
                self._active,
                self._layer_calls,
                self._last_checked_layer,
                result.get("status", "unknown"),
                float(result.get("confidence", 0.0) or 0.0),
                result.get("should_pause", False),
                result.get("reason", ""),
            )
        )
        if self._last_error:
            msg += " last_error=%s" % self._last_error
        gcmd.respond_info(msg)

    def cmd_AI_SPAGHETTI_RESET(self, gcmd):
        with self._lock:
            self._layer_calls = 0
            self._last_error = None
            self._last_checked_layer = None
            self._last_checked_at = None
            self._last_result = {
                "status": "unknown",
                "confidence": 0.0,
                "should_pause": False,
                "reason": "Reset.",
                "recommended_action": "",
            }
        gcmd.respond_info("%s: reset" % self.report_prefix)

    def _run_check(self, layer, force):
        try:
            if self.capture_delay:
                time.sleep(self.capture_delay)
            api_key = self._get_api_key()
            image_url = self._capture_image_data_url()
            result = self._ask_openai(api_key, image_url, layer)
            result = self._normalize_result(result)
            self._last_result = result
            self._last_error = None
            self._last_checked_layer = layer
            self._last_checked_at = time.time()

            self._report_result(layer, result)
            if self._should_pause(result):
                self._dispatch_gcode(self.pause_gcode)
        except Exception as exc:
            logging.exception("AI spaghetti check failed")
            self._last_error = str(exc)
            self._last_result = {
                "status": "unknown",
                "confidence": 0.0,
                "should_pause": False,
                "reason": str(exc),
                "recommended_action": "Check plugin configuration and camera/API access.",
            }
            if not self.fail_open and self.pause_on_failure:
                self._respond(
                    "%s: check failed and fail_open is false; pausing: %s"
                    % (self.report_prefix, exc)
                )
                self._dispatch_gcode(self.pause_gcode)
            else:
                self._respond("%s: check failed: %s" % (self.report_prefix, exc))
        finally:
            with self._lock:
                self._active = False

    def _get_api_key(self):
        if self.api_key:
            return self.api_key.strip()
        env_key = os.environ.get("OPENAI_API_KEY")
        if env_key:
            return env_key.strip()
        path = os.path.expanduser(self.api_key_path)
        try:
            with open(path, "r") as key_file:
                key = key_file.read().strip()
        except IOError:
            key = ""
        if not key:
            raise RuntimeError(
                "OpenAI API key not found; set api_key_path or OPENAI_API_KEY"
            )
        return key

    def _capture_image_data_url(self):
        if self.snapshot_url:
            image_bytes, mime_type = self._fetch_snapshot_url()
        else:
            image_bytes, mime_type = self._read_snapshot_path()

        if not image_bytes:
            raise RuntimeError("snapshot is empty")
        if len(image_bytes) > self.max_image_bytes:
            raise RuntimeError(
                "snapshot is too large (%d bytes > %d)"
                % (len(image_bytes), self.max_image_bytes)
            )
        if not mime_type:
            mime_type = self._guess_mime_type(image_bytes, self.snapshot_path)

        encoded = base64.b64encode(image_bytes).decode("ascii")
        return "data:%s;base64,%s" % (mime_type, encoded)

    def _fetch_snapshot_url(self):
        request = urllib.request.Request(
            self.snapshot_url,
            headers={
                "User-Agent": "klipper-ai-spaghetti-detective/1.0",
                "Accept": "image/*",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.snapshot_timeout
            ) as response:
                image_bytes = response.read(self.max_image_bytes + 1)
                mime_type = response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            raise RuntimeError("snapshot HTTP error %s" % exc.code)
        except urllib.error.URLError as exc:
            raise RuntimeError("snapshot URL error: %s" % exc.reason)
        return image_bytes, mime_type

    def _read_snapshot_path(self):
        path = os.path.expanduser(self.snapshot_path)
        try:
            with open(path, "rb") as image_file:
                image_bytes = image_file.read(self.max_image_bytes + 1)
        except IOError as exc:
            raise RuntimeError("snapshot_path read failed: %s" % exc)
        mime_type = mimetypes.guess_type(path)[0]
        return image_bytes, mime_type

    def _guess_mime_type(self, image_bytes, path=None):
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        if path:
            guessed = mimetypes.guess_type(path)[0]
            if guessed:
                return guessed
        return "image/jpeg"

    def _ask_openai(self, api_key, image_url, layer):
        payload = {
            "model": self.model,
            "instructions": self.prompt,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Inspect this 3D printer snapshot. "
                                "Layer marker: %s. Return the JSON verdict."
                            )
                            % layer,
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                            "detail": self.image_detail,
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "spaghetti_detection_verdict",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["ok", "warning", "failure", "unknown"],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "should_pause": {"type": "boolean"},
                            "reason": {"type": "string"},
                            "recommended_action": {"type": "string"},
                        },
                        "required": [
                            "status",
                            "confidence",
                            "should_pause",
                            "reason",
                            "recommended_action",
                        ],
                    },
                }
            },
            "max_output_tokens": 300,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.api_timeout) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", "replace")
            raise RuntimeError("OpenAI HTTP error %s: %s" % (exc.code, error_body))
        except urllib.error.URLError as exc:
            raise RuntimeError("OpenAI URL error: %s" % exc.reason)

        try:
            response_json = json.loads(response_body.decode("utf-8"))
        except ValueError as exc:
            raise RuntimeError("OpenAI returned invalid JSON: %s" % exc)

        return self._extract_structured_result(response_json)

    def _extract_structured_result(self, response_json):
        output_text = response_json.get("output_text")
        if output_text:
            parsed = self._parse_json_text(output_text)
            if parsed is not None:
                return parsed

        for candidate in self._walk_response(response_json):
            if isinstance(candidate, dict) and "status" in candidate:
                return candidate
            if isinstance(candidate, str):
                parsed = self._parse_json_text(candidate)
                if parsed is not None and "status" in parsed:
                    return parsed

        raise RuntimeError("OpenAI response did not contain a verdict")

    def _walk_response(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                for item in self._walk_response(child):
                    yield item
        elif isinstance(value, list):
            for child in value:
                for item in self._walk_response(child):
                    yield item
        else:
            yield value

    def _parse_json_text(self, text):
        text = text.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _normalize_result(self, result):
        status = str(result.get("status", "unknown")).lower()
        if status not in _VALID_STATUSES:
            status = "unknown"
        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return {
            "status": status,
            "confidence": confidence,
            "should_pause": bool(result.get("should_pause", False)),
            "reason": str(result.get("reason", "")).strip(),
            "recommended_action": str(result.get("recommended_action", "")).strip(),
        }

    def _should_pause(self, result):
        if not self.pause_on_failure:
            return False
        if result["status"] not in self.pause_statuses:
            return False
        if result["confidence"] < self.pause_confidence:
            return False
        return bool(result["should_pause"])

    def _report_result(self, layer, result):
        message = (
            "%s: layer=%s status=%s confidence=%.2f pause=%s reason=%s"
            % (
                self.report_prefix,
                layer,
                result["status"],
                result["confidence"],
                result["should_pause"],
                result["reason"],
            )
        )
        if result["recommended_action"]:
            message += " action=%s" % result["recommended_action"]
        self._respond(message)

    def _respond(self, message):
        def callback(eventtime):
            try:
                self.gcode.respond_info(message)
            except Exception:
                logging.exception("Unable to report AI spaghetti status")

        self.reactor.register_async_callback(callback)

    def _dispatch_gcode(self, script):
        if not script:
            return

        def callback(eventtime):
            try:
                self.gcode.run_script_from_command(script)
            except Exception:
                logging.exception("Unable to run AI spaghetti pause_gcode")

        self.reactor.register_async_callback(callback)


def load_config(config):
    return AISpaghettiDetective(config)
