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


@app.route("/preview.png")
def preview():
    data = controller.get_preview_bytes()
    if not data:
        return "", 204
    return Response(data, mimetype="image/png")


if __name__ == "__main__":
    controller.start()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False, use_reloader=False)
