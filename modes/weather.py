"""
Weather mode, backed by Open-Meteo (https://open-meteo.com) -- free,
no API key required.

Uses the same endpoint/params you tested by hand:
  https://api.open-meteo.com/v1/forecast
    ?latitude=..&longitude=..
    &current=temperature_2m,wind_speed_10m
    &hourly=temperature_2m,relative_humidity_2m,wind_speed_10m

`current` doesn't include humidity, so it's pulled from `hourly` by
matching the current hour's timestamp -- Open-Meteo doesn't expose a
"current humidity" field directly, this is the standard way to get it
without a second API call.

Location/units/refresh cadence are all in config.py (WEATHER_LAT,
WEATHER_LON, WEATHER_UNIT, WEATHER_REFRESH_SECONDS).
"""
import requests
from PIL import Image, ImageDraw, ImageFont

from modes.base import Mode
from applog import log
import config

API_URL = "https://api.open-meteo.com/v1/forecast"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def _load_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()  # older Pillow without the size= kwarg


def _text_size(draw, text, font):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _fit_font_box(draw, text, max_w, max_h, start_size=16, min_size=5):
    for size in range(start_size, min_size - 1, -1):
        font = _load_font(size)
        w, h = _text_size(draw, text, font)
        if w <= max_w and h <= max_h:
            return font
    return _load_font(min_size)


def _draw_text_hard(img, pos, text, font, fill, threshold=100):
    """Hard (non-anti-aliased) text -- see prior discussion on why this
    matters for LED matrices: soft-edged text blurs into gray on-device."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(pos, text, font=font, fill=255)
    mask = mask.point(lambda p: 255 if p >= threshold else 0)
    color_layer = Image.new("RGB", img.size, fill)
    img.paste(color_layer, (0, 0), mask)


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

        img = Image.new("RGB", (32, 32), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        temp_text = f"{temp}\u00b0{unit_symbol}"
        temp_font = _fit_font_box(draw, temp_text, 30, 16, start_size=16, min_size=8)
        tw, th = _text_size(draw, temp_text, temp_font)
        _draw_text_hard(img, ((32 - tw) // 2, 2), temp_text, temp_font, (255, 255, 255))

        wind_text = f"{wind}km/h"
        wind_font = _fit_font_box(draw, wind_text, 30, 8, start_size=8, min_size=5)
        ww, wh = _text_size(draw, wind_text, wind_font)
        wind_y = th + 4
        _draw_text_hard(img, ((32 - ww) // 2, wind_y), wind_text, wind_font, (120, 200, 255))

        if humidity is not None:
            hum_text = f"{humidity}%"
            hum_font = _fit_font_box(draw, hum_text, 30, 8, start_size=8, min_size=5)
            hw, hh = _text_size(draw, hum_text, hum_font)
            _draw_text_hard(img, ((32 - hw) // 2, 32 - hh - 1), hum_text, hum_font, (150, 150, 160))

        return img
