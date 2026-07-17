"""
Base interface for a screen mode.

This is intentionally empty of any real logic -- fill in render() later
with whatever fetches/draws you want for each sport. For now it just
returns a plain placeholder frame so the app runs end-to-end.
"""
from PIL import Image
from applog import log


class Mode:
    key: str = "base"          # unique id used in the UI/URLs
    label: str = "Base"        # human-readable name shown as a button
    poll_interval: int = 20    # seconds before the next render(); a mode
                                # may reassign self.poll_interval inside
                                # render() to change its own next delay
                                # (used by CricketMode's frame rotation)

    def render(self) -> Image.Image:
        """
        Return a 32x32 RGB PIL Image to send to the matrix.
        Replace this in each subclass with real data + drawing.
        """
        return Image.new("RGB", (32, 32), (0, 0, 0))

    def safe_render(self) -> Image.Image:
        """Wraps render() so one bad mode doesn't kill the worker loop."""
        try:
            return self.render()
        except Exception as e:
            log.error(f"[{self.key}] render failed: {e}")
            return Image.new("RGB", (32, 32), (40, 0, 0))
