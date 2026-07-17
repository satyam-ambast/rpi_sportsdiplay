"""
Flask control panel for the iPixel 32x32 LED matrix.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000

Note: debug/reloader is off on purpose -- Flask's reloader spawns a
second process, which would open a second BLE connection.
"""
from flask import Flask, render_template, request, jsonify, Response

import config
from device_controller import DeviceController
from modes import MODES
from applog import setup_logging, get_recent_logs

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
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False, use_reloader=False)
