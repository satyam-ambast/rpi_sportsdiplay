import os

# --- Device ---------------------------------------------------------------
# Find this with: pypixelcolor --scan
DEVICE_ADDRESS = os.environ.get("IPIXEL_ADDRESS", "30:E1:AF:BD:5F:D0")
DEFAULT_BRIGHTNESS = 60  # 0-100
DEFAULT_MODE = "weather"

# The available modes. Each key needs a matching class in modes/.
MODE_KEYS = ["weather", "cricket", "football", "f1"]

# --- Server -----------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
