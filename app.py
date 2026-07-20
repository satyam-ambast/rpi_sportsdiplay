"""
Flask control panel for the iPixel 32x32 LED matrix.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000

Note: debug/reloader is off on purpose -- Flask's reloader spawns a
second process, which would open a second BLE connection. threaded=True
is on so a slow request (e.g. an 8s BLE scan) doesn't block the rest of
the UI (status polling, log panel, etc.) while it runs.
"""
import asyncio
import os
import signal
import threading
import time

from flask import Flask, render_template, request, jsonify, Response
from bleak import BleakScanner

import config
from device_controller import DeviceController
from modes import MODES
from applog import setup_logging, get_recent_logs, log

setup_logging()

app = Flask(__name__)
controller = DeviceController(config.DEVICE_ADDRESS)


@app.route("/")
def index():
    return render_template("index.html", modes=list(MODES.values()))


@app.route("/api/status")
def status():
    return jsonify(controller.get_status())


@app.route("/api/mode", methods=["POST"])
def set_mode():
    key = request.json.get("mode") if request.is_json else request.form.get("mode")
    try:
        controller.set_mode(key)
        return jsonify({"ok": True, **controller.get_status()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/brightness", methods=["POST"])
def set_brightness():
    value = request.json.get("value") if request.is_json else request.form.get("value")
    controller.set_brightness(value)
    return jsonify({"ok": True, **controller.get_status()})


@app.route("/api/cricket/teams", methods=["GET", "POST"])
def cricket_teams():
    cricket_mode = MODES["cricket"]

    if request.method == "GET":
        return jsonify({"teams": cricket_mode.teams})

    teams = request.json.get("teams") if request.is_json else request.form.get("teams")
    try:
        cricket_mode.set_teams(teams)
        return jsonify({"ok": True, "teams": cricket_mode.teams})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/cricket/matches")
def cricket_matches():
    cricket_mode = MODES["cricket"]
    return jsonify({
        "matches": cricket_mode.list_matches(),
        "forced_match_id": cricket_mode.forced_match_id,
        "forced_view": cricket_mode.forced_view,
    })


@app.route("/api/cricket/select", methods=["POST"])
def cricket_select():
    cricket_mode = MODES["cricket"]
    body = request.get_json(silent=True) or request.form

    try:
        if "match_id" in body:
            cricket_mode.set_forced_match(body.get("match_id"))
        if "view" in body:
            cricket_mode.set_forced_view(body.get("view"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    return jsonify({
        "ok": True,
        "forced_match_id": cricket_mode.forced_match_id,
        "forced_view": cricket_mode.forced_view,
    })


@app.route("/api/ble/scan", methods=["POST"])
def ble_scan():
    """
    Scans for nearby BLE devices (same approach as a standalone
    bleak.BleakScanner.discover() script). Takes ~8s to respond -- the
    UI should show a loading state, not block on it silently.

    Note: scanning while the app's own BLE connection to the matrix is
    active can be flaky depending on your Bluetooth adapter -- some
    adapters don't like scanning and holding a connection open at the
    same time. If the matrix drops out after a scan, that's the
    adapter, not a bug here; just reconnect afterward.
    """
    async def _scan():
        devices = await BleakScanner.discover(timeout=8.0)
        return [{"name": d.name or "(unknown)", "address": d.address} for d in devices]

    try:
        results = asyncio.run(_scan())
    except Exception as e:
        log.error(f"BLE scan failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

    log.info(f"BLE scan found {len(results)} device(s)")
    return jsonify({"ok": True, "devices": results})


@app.route("/api/ble/disconnect", methods=["POST"])
def ble_disconnect():
    controller.disconnect_device()
    return jsonify({"ok": True, **controller.get_status()})


@app.route("/api/ble/connect", methods=["POST"])
def ble_connect():
    body = request.get_json(silent=True) or request.form
    address = body.get("address")
    controller.reconnect_device(address=address)
    return jsonify({"ok": True, **controller.get_status()})


@app.route("/api/weather/location", methods=["GET", "POST"])
def weather_location():
    if request.method == "GET":
        return jsonify({"lat": config.WEATHER_LAT, "lon": config.WEATHER_LON})

    body = request.get_json(silent=True) or request.form
    try:
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "lat/lon must be numbers"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"ok": False, "error": "lat must be -90..90, lon must be -180..180"}), 400

    # WeatherMode reads config.WEATHER_LAT/LON fresh on every fetch, so
    # mutating the config module's attributes here takes effect
    # immediately -- no need to touch the mode itself. This only affects
    # the running process; it doesn't persist across a restart (set
    # WEATHER_LAT/WEATHER_LON as env vars for that).
    config.WEATHER_LAT = lat
    config.WEATHER_LON = lon
    log.info(f"Weather location changed: {lat}, {lon}")
    controller.force_refresh()

    return jsonify({"ok": True, "lat": lat, "lon": lon})


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """
    Stops the BLE connection cleanly, then kills the whole process a
    moment later (after this response has gone out) -- this is meant to
    actually end `python app.py`, not just show a "disconnected" state.
    """
    log.info("Shutdown requested from web UI.")
    controller.stop()

    def _terminate():
        time.sleep(0.5)  # let the HTTP response flush before the process dies
        os._exit(0)

    threading.Thread(target=_terminate, daemon=True).start()
    return jsonify({"ok": True, "message": "Shutting down..."})


@app.route("/api/logs")
def logs():
    return jsonify(get_recent_logs())


@app.route("/preview.png")
def preview():
    data = controller.get_preview_bytes()
    if not data:
        return "", 204
    return Response(data, mimetype="image/png")


if __name__ == "__main__":
    controller.start()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False, use_reloader=False, threaded=True)
