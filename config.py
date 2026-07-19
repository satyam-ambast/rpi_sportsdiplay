import os

# --- Device ---------------------------------------------------------------
# Find this with: pypixelcolor --scan
DEVICE_ADDRESS = os.environ.get("IPIXEL_ADDRESS", "62:F3:55:69:69:CC")
DEFAULT_BRIGHTNESS = 0  # 0-100
DEFAULT_MODE = "weather"

# The available modes. Each key needs a matching class in modes/.
MODE_KEYS = ["weather", "cricket", "football", "f1"]

# --- Cricket ---------------------------------------------------------------
# Comma-separated, e.g. CRICKET_TEAMS=IND,ENG,AUS
_teams_raw = os.environ.get("CRICKET_TEAMS", os.environ.get("CRICKET_TEAM", "IND"))
CRICKET_TEAMS = [t.strip().upper() for t in _teams_raw.split(",") if t.strip()]

# How often (seconds) to re-check which match each followed team is
# currently in, even mid-rotation. This is a floor, not the only
# trigger -- it also re-checks whenever no match is currently found.
CRICKET_MATCH_REFRESH_SECONDS = int(os.environ.get("CRICKET_MATCH_REFRESH_SECONDS", "300"))

# How often (seconds) to refetch score data for whichever match is
# currently being shown. Decoupled from how long each sub-frame (main/
# batting/bowling) stays on screen -- e.g. you can leave the score
# frame up for 20s while still refreshing the underlying data every 10s
# in case you switch to batting/bowling mid-way.
CRICKET_SCORE_REFRESH_SECONDS = int(os.environ.get("CRICKET_SCORE_REFRESH_SECONDS", "10"))

# --- Weather (Open-Meteo, no API key needed) ------------------------------
WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "52.52"))     # default: Berlin
WEATHER_LON = float(os.environ.get("WEATHER_LON", "13.41"))
WEATHER_UNIT = os.environ.get("WEATHER_UNIT", "celsius")        # "celsius" or "fahrenheit"
WEATHER_REFRESH_SECONDS = int(os.environ.get("WEATHER_REFRESH_SECONDS", "600"))  # weather is slow-moving

# --- Formula 1 (FastF1) -----------------------------------------------------
F1_CACHE_DIR = os.environ.get("F1_CACHE_DIR", os.path.join(os.path.dirname(__file__), ".fastf1_cache"))
F1_SESSION_REFRESH_SECONDS = int(os.environ.get("F1_SESSION_REFRESH_SECONDS", "60"))
F1_PAGE_SECONDS = int(os.environ.get("F1_PAGE_SECONDS", "6"))  # how long each 3-driver page stays up

# --- Server -----------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
