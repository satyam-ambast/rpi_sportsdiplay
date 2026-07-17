"""
Central logging setup.

Gives you three places to see what's happening:
  - console (stdout), for when you're running `python app.py` in a terminal
  - ipixel.log, a rotating file, for after-the-fact debugging
  - an in-memory ring buffer, exposed via /api/logs, so the web page
    itself can show a live log without needing terminal access
"""
import logging
from logging.handlers import RotatingFileHandler
from collections import deque

LOG_BUFFER_SIZE = 200
_buffer = deque(maxlen=LOG_BUFFER_SIZE)


class MemoryHandler(logging.Handler):
    """Keeps the last N log records in memory for the /api/logs endpoint."""

    def emit(self, record):
        _buffer.append({
            "time": self.formatter.formatTime(record, "%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        })


def get_recent_logs():
    return list(_buffer)


def setup_logging():
    logger = logging.getLogger("ipixel")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = RotatingFileHandler("ipixel.log", maxBytes=1_000_000, backupCount=2)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    memory = MemoryHandler()
    memory.setFormatter(fmt)
    logger.addHandler(memory)

    return logger


log = logging.getLogger("ipixel")
