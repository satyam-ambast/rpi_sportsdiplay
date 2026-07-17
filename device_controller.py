"""
Background worker that owns the single BLE connection to the iPixel
matrix and continuously sends whatever mode is currently selected.

Why a dedicated thread: pypixelcolor.Client is synchronous/blocking, and
BLE connections don't like being shared across requests. Flask routes
never touch the BLE connection directly -- they just flip
`current_mode_key` / `brightness`, and this thread picks up the change
on its next loop iteration.
"""
import threading
import time
import io
import os
import tempfile

import pypixelcolor

import config
from modes import MODES
from applog import log


class DeviceController:
    def __init__(self, address):
        self.address = address
        self.client = None
        self.connected = False

        self._lock = threading.Lock()
        self.current_mode_key = config.DEFAULT_MODE
        self.brightness = config.DEFAULT_BRIGHTNESS

        self.last_frame_bytes = None
        self.last_update = None
        self.last_error = None

        self._stop = threading.Event()
        self._force_refresh = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)

        # Cross-platform scratch file for the frame we send each cycle.
        # (A hardcoded "/tmp/..." path doesn't exist on Windows -- that
        # was previously causing every send to fail right after connecting.)
        self._frame_path = os.path.join(tempfile.gettempdir(), "ipixel_frame.png")

    # ---- public API, called from Flask routes ----

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def set_mode(self, key):
        if key not in MODES:
            raise ValueError(f"Unknown mode: {key}")
        log.info(f"Mode change requested: {self.current_mode_key} -> {key}")
        with self._lock:
            self.current_mode_key = key
        self._force_refresh.set()  # render immediately instead of waiting for poll_interval

    def set_brightness(self, value):
        value = max(0, min(100, int(value)))
        log.info(f"Brightness change requested: {value}")
        with self._lock:
            self.brightness = value
        if self.client and self.connected:
            try:
                self.client.set_brightness(value)
                log.debug(f"Brightness set on device: {value}")
            except Exception as e:
                log.error(f"Failed to set brightness: {e}")
                self.last_error = str(e)

    def get_status(self):
        with self._lock:
            return {
                "mode": self.current_mode_key,
                "connected": self.connected,
                "brightness": self.brightness,
                "last_update": self.last_update,
                "last_error": self.last_error,
                "modes": [{"key": m.key, "label": m.label} for m in MODES.values()],
            }

    def get_preview_bytes(self):
        with self._lock:
            return self.last_frame_bytes

    # ---- worker thread ----

    def _connect(self):
        log.info(f"Connecting to {self.address} ...")
        self.client = pypixelcolor.Client(self.address)
        self.client.connect()
        self.client.set_brightness(self.brightness)
        self.connected = True
        self.last_error = None
        log.info("Connected.")

    def _worker(self):
        log.info("Worker thread started.")
        try:
            self._connect()
        except Exception as e:
            log.error(f"Initial connect failed: {e}")
            self.last_error = f"Connect failed: {e}"
            self.connected = False  # loop below will keep retrying

        next_render_at = 0
        while not self._stop.is_set():
            if not self.connected:
                try:
                    self._connect()
                except Exception as e:
                    log.warning(f"Reconnect failed, retrying in 5s: {e}")
                    self.last_error = f"Reconnect failed: {e}"
                    time.sleep(5)
                    continue

            with self._lock:
                mode = MODES[self.current_mode_key]

            now = time.time()
            due = now >= next_render_at or self._force_refresh.is_set()
            if due:
                self._force_refresh.clear()
                log.debug(f"Rendering frame for mode '{mode.key}'")
                try:
                    frame = mode.safe_render()

                    buf = io.BytesIO()
                    frame.save(buf, format="PNG")

                    frame_path = self._frame_path
                    frame.save(frame_path)
                    self.client.send_image(frame_path, resize_method="fit")

                    with self._lock:
                        self.last_frame_bytes = buf.getvalue()
                        self.last_update = time.strftime("%H:%M:%S")
                    self.last_error = None
                    log.debug(f"Frame sent OK for mode '{mode.key}'")
                except Exception as e:
                    log.error(f"Send failed for mode '{mode.key}': {e}")
                    self.last_error = str(e)
                    self.connected = False  # force reconnect next loop

                next_render_at = now + getattr(mode, "poll_interval", 20)

            time.sleep(1)

        log.info("Worker thread stopping.")
        if self.client and self.connected:
            try:
                self.client.disconnect()
                log.info("Disconnected cleanly.")
            except Exception as e:
                log.warning(f"Error during disconnect: {e}")
