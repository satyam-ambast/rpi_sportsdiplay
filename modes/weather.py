from PIL import Image
from modes.base import Mode


class WeatherMode(Mode):
    key = "weather"
    label = "Weather"
    poll_interval = 300

    def render(self) -> Image.Image:
        # TODO: fetch data + draw the frame
        return Image.new("RGB", (32, 32), (0, 0, 0))
