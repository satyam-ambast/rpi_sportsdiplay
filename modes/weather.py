"""
Weather mode, backed by Open-Meteo (https://open-meteo.com) -- free,
no API key required. Rendered with the same crisp proportional pixel
font used by cricket_screens.py (services/pixel_font.py), so weather
matches the rest of the app's visual style instead of using a separate
system font.

Note: the pixel font only defines A-Z, 0-9, space, and a handful of
punctuation (. : - / ' ! ( )) -- no degree symbol or percent sign. An
unsupported character silently renders as blank space rather than
erroring, so rather than have invisible glyphs on the display, this
shows temperature as "18C" (not "18\u00b0C") and humidity as "H:65"
(not "65%").

`current` doesn't include humidity, so it's pulled from `hourly` by
matching the current hour's timestamp -- Open-Meteo doesn't expose a
"current humidity" field directly, this is the standard way to get it
without a second API call.

Location/units/refresh cadence are all in config.py (WEATHER_LAT,
WEATHER_LON, WEATHER_UNIT, WEATHER_REFRESH_SECONDS).
"""
import requests
from PIL import Image

from modes.base import Mode
from applog import log
import config

from services.pixel_font import blit_text, text_width, text_height

API_URL = "https://api.open-meteo.com/v1/forecast"
SIZE = 32

# Try sizes largest-first per row; falls back to a smaller size if the
# text doesn't fit the width at the bigger one (e.g. "-12C" fits large,
# but "104KPH" might not).
SIZE_ORDER = ("large", "medium", "small")


def _fit_size(text, max_w, sizes=SIZE_ORDER):
    for size in sizes:
        if text_width(text, spacing=1, size=size) <= max_w:
            return size
    return sizes[-1]


class WeatherMode(Mode):
    key = "weather"
    label = "Weather"

    def __init__(self):
        self.poll_interval = config.WEATHER_REFRESH_SECONDS

    def _fetch(self):
        params = {
            "latitude": config.WEATHER_LAT,
            "longitude": config.WEATHER_LON,
            "current": "temperature_2m,wind_speed_10m",
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "temperature_unit": "fahrenheit" if config.WEATHER_UNIT.lower().startswith("f") else "celsius",
        }
        resp = requests.get(API_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def render(self) -> Image.Image:
        self.poll_interval = config.WEATHER_REFRESH_SECONDS

        data = self._fetch()
        current = data["current"]
        temp = round(current["temperature_2m"])
        wind = round(current["wind_speed_10m"])

        # Humidity isn't in `current` -- find it in `hourly` by matching timestamps.
        humidity = None
        try:
            hourly_times = data["hourly"]["time"]
            idx = hourly_times.index(current["time"])
            humidity = round(data["hourly"]["relative_humidity_2m"][idx])
        except (KeyError, ValueError):
            log.debug("Weather: couldn't align hourly humidity with current timestamp")

        unit_symbol = "F" if config.WEATHER_UNIT.lower().startswith("f") else "C"

        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))

        max_w = SIZE - 2  # 1px pad each side
        temp_text = f"{temp}{unit_symbol}"
        wind_text = f"{wind}KPH"

        rows = [
            (temp_text, (255, 255, 255), _fit_size(temp_text, max_w, ("large", "medium", "small"))),
            (wind_text, (120, 200, 255), _fit_size(wind_text, max_w, ("small",))),
        ]
        if humidity is not None:
            hum_text = f"H:{humidity}"
            rows.append((hum_text, (150, 150, 160), _fit_size(hum_text, max_w, ("small",))))

        # Top-down layout: each row starts after the previous row's actual
        # measured height + a gap, so rows can't overlap regardless of
        # which size each one ended up fitting at.
        heights = [text_height(sz) for _, _, sz in rows]
        gap = 1
        total_h = sum(heights) + gap * (len(rows) - 1)
        y = max(0, (SIZE - total_h) // 2)

        for (text, color, sz), h in zip(rows, heights):
            w = text_width(text, spacing=1, size=sz)
            x = max(0, (SIZE - w) // 2)
            blit_text(img, x, y, text, color, spacing=1, size=sz)
            y += h + gap

        return img
