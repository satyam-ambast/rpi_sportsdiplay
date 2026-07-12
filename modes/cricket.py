from PIL import Image
from modes.base import Mode


class CricketMode(Mode):
    key = "cricket"
    label = "Cricket"
    poll_interval = 30

    def render(self) -> Image.Image:
        # TODO: fetch data + draw the frame
        return Image.new("RGB", (32, 32), (0, 0, 0))
