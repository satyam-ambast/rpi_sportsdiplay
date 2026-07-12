from PIL import Image
from modes.base import Mode


class F1Mode(Mode):
    key = "f1"
    label = "F1"
    poll_interval = 600

    def render(self) -> Image.Image:
        # TODO: fetch data + draw the frame
        return Image.new("RGB", (32, 32), (0, 0, 0))
