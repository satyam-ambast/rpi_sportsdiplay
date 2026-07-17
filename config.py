import os

# --- Device ---------------------------------------------------------------
# Find this with: pypixelcolor --scan
DEVICE_ADDRESS = os.environ.get("IPIXEL_ADDRESS", "62:F3:55:69:69:CC")
DEFAULT_BRIGHTNESS = 60  # 0-100
DEFAULT_MODE = "weather"

# The available modes. Each key needs a matching class in modes/.
MODE_KEYS = ["weather", "cricket", "football", "f1"]

# --- Cricket ---------------------------------------------------------------
# Comma-separated, e.g. CRICKET_TEAMS=IND,ENG,AUS
_teams_raw = os.environ.get("CRICKET_TEAMS", os.environ.get("CRICKET_TEAM", "IND"))
CRICKET_TEAMS = [t.strip().upper() for t in _teams_raw.split(",") if t.strip()]

# --- Server -----------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
