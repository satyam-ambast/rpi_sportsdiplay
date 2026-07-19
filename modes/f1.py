"""
Formula 1 mode, backed by FastF1 (https://docs.fastf1.dev).


Multi-page display: 32px only fits 4 short text rows with the pixel
font (same row budget the cricket scorecard uses), and one of those
rows is the header, leaving 3 driver rows per page. Results paginate
automatically -- P1-3 on page 1, P4-6 on page 2, etc. Every page
repeats the header (3-letter event code + session type) so it's always
clear what you're looking at.

Setup:
    pip install fastf1
FastF1 caches downloaded data under config.F1_CACHE_DIR.

NOTE: this is written directly against FastF1's documented API and
DataFrame schemas (verified against the installed package's source),
but hasn't been tested against a real live session, since that needs
network access to F1's live timing backend that isn't available in the
environment this was built in. Treat the first real session as a
shakeout test -- in particular, exact column population can vary a bit
by session type and by how far into a session you are.
"""
import os
import time
import datetime

import pandas as pd
from PIL import Image

from modes.base import Mode
from applog import log
import config

import fastf1

os.makedirs(config.F1_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(config.F1_CACHE_DIR)

from services.pixel_font import blit_text, text_width, text_height

SIZE = 32
ROWS_PER_PAGE = 3  # + 1 header row = 4 lines total, same budget as the cricket scorecard

# FastF1 session name -> short header abbreviation, and the identifier
# string FastF1's get_session() accepts directly.
SESSION_TYPES = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Sprint Qualifying": "SQ",
    "Sprint Shootout": "SQ",
    "Sprint": "S",
    "Qualifying": "Q",
    "Race": "R",
}

# Generous time-window budgets (minutes) for deciding whether a session
# should currently be "live" -- wide enough to cover delays/red flags
# without needing exact end times, which the schedule doesn't provide.
SESSION_DURATION_MIN = {
    "FP1": 75, "FP2": 75, "FP3": 75,
    "SQ": 75, "S": 45, "Q": 90, "R": 165,
}


def _fmt_gap(td):
    """
    Format a Timedelta as a short unsigned gap string, e.g. '0.234' ->
    '0.2'. No leading '+' -- the pixel font has no glyph for it (an
    unsupported character silently renders as blank space rather than
    erroring), so the sign is dropped; gaps are always positive time
    behind the reference driver, which is clear from context (this
    driver's row sits below the reference row).
    """
    if td is None or pd.isna(td):
        return ""
    total = td.total_seconds()
    if total < 0:
        return ""
    if total >= 60:
        m, s = divmod(total, 60)
        return f"{int(m)}:{int(s):02d}"
    return f"{total:.1f}"


def _fmt_laptime(td):
    """Format a Timedelta lap time as e.g. '1:23' (whole seconds -- a
    single pixel-font row has no width budget left for tenths once a
    3-letter driver code is already on the same line)."""
    if td is None or pd.isna(td):
        return "--"
    total = td.total_seconds()
    m, s = divmod(total, 60)
    return f"{int(m)}:{int(s):02d}"


# Status text is free-form from FastF1 (e.g. "Retired", "Collision",
# "+ 1 Lap") -- mapped to short codes that are guaranteed to fit next to
# a driver code at this width, and with no '+' (unsupported glyph, see
# _fmt_gap above).
STATUS_ABBR = {
    "FINISHED": "",
    "RETIRED": "DNF",
    "ACCIDENT": "CRSH",
    "COLLISION": "CRSH",
    "DISQUALIFIED": "DSQ",
    "DID NOT START": "DNS",
    "DID NOT QUALIFY": "DNQ",
    "WITHDREW": "WD",
}


def _fmt_status(status):
    key = status.strip().upper()
    if key in STATUS_ABBR:
        return STATUS_ABBR[key]
    if key.startswith("+") and "LAP" in key:
        digits = "".join(c for c in key if c.isdigit()) or "1"
        return f"{digits}LAP"
    return "".join(c for c in key if c.isalnum())[:4]


def _best_q_time(row):
    """A driver's furthest-reached qualifying segment time (Q3 if they got
    that far, else Q2, else Q1)."""
    for col in ("Q3", "Q2", "Q1"):
        v = row.get(col)
        if v is not None and not pd.isna(v):
            return v
    return None


class F1Mode(Mode):
    key = "f1"
    label = "F1"
    poll_interval = 6  # reassigned from config.F1_PAGE_SECONDS in __init__/render

    def __init__(self):
        self.poll_interval = config.F1_PAGE_SECONDS
        self._rows = []       # list of (pos_str, driver_code, info_str)
        self._header = ""     # e.g. "BAH R"
        self._page = 0
        self._last_load_time = 0

    # ---- schedule lookup ----

    def _find_session(self):
        """
        Return (year, round_number, session_type, event, is_live) for
        whichever session should be shown right now: the currently
        active one if any, else the most recently completed one.
        """
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        year = now.year
        schedule = fastf1.get_event_schedule(year, include_testing=False)

        live = None
        most_recent = None  # (start, year, round, session_type, event)

        for _, event in schedule.sort_values("EventDate").iterrows():
            for i in range(1, 6):
                sess_name = event.get(f"Session{i}")
                sess_start = event.get(f"Session{i}DateUtc")
                if not isinstance(sess_name, str) or sess_name not in SESSION_TYPES:
                    continue
                if sess_start is None or pd.isna(sess_start):
                    continue

                session_type = SESSION_TYPES[sess_name]
                start = sess_start.to_pydatetime()
                duration = SESSION_DURATION_MIN.get(session_type, 90)
                end = start + datetime.timedelta(minutes=duration)

                if start <= now <= end:
                    live = (year, int(event["RoundNumber"]), session_type, event)
                elif end < now:
                    if most_recent is None or start > most_recent[0]:
                        most_recent = (start, year, int(event["RoundNumber"]), session_type, event)

        if live:
            return (*live, True)
        if most_recent:
            _, yr, rnd, stype, ev = most_recent
            return (yr, rnd, stype, ev, False)

        # Nothing found this year at all (e.g. first days of January before
        # the new schedule is published) -- fall back to last season's finale.
        prev_schedule = fastf1.get_event_schedule(year - 1, include_testing=False)
        last_event = prev_schedule.sort_values("EventDate").iloc[-1]
        return (year - 1, int(last_event["RoundNumber"]), "R", last_event, False)

    # ---- data loading ----

    def _load(self):
        year, round_no, session_type, event, is_live = self._find_session()

        log.info(
            f"F1: showing {event['Location']} {session_type} "
            f"({'live window' if is_live else 'most recent completed'})"
        )

        session = fastf1.get_session(year, round_no, session_type)
        session.load(
            laps=(session_type in ("FP1", "FP2", "FP3")),
            telemetry=False,
            weather=False,
            messages=False,
        )

        rows = []

        if session_type in ("FP1", "FP2", "FP3"):
            # No official Position for practice -- rank by best lap instead.
            best = session.laps.groupby("Driver")["LapTime"].min().dropna().sort_values()
            if len(best):
                fastest = best.iloc[0]
                for pos, (code, lap) in enumerate(best.items(), start=1):
                    info = _fmt_laptime(lap) if pos == 1 else _fmt_gap(lap - fastest)
                    rows.append((str(pos), code, info))

        else:
            results = session.results.dropna(subset=["Position"]).sort_values("Position")
            pole_q = _best_q_time(results.iloc[0]) if len(results) and session_type in ("Q", "SQ") else None

            for _, r in results.iterrows():
                pos_str = str(int(r["Position"]))
                code = r.get("Abbreviation", "???")

                if session_type in ("Q", "SQ"):
                    own_q = _best_q_time(r)
                    if pos_str == "1" or pole_q is None or own_q is None:
                        info = _fmt_laptime(own_q)
                    else:
                        info = _fmt_gap(own_q - pole_q)

                else:  # Race / Sprint
                    status = str(r.get("Status") or "")
                    time_val = r.get("Time")
                    if pos_str == "1":
                        # Leader's absolute race time (h:mm:ss) doesn't fit
                        # next to a driver code at this width -- "LEAD" does.
                        info = "LEAD"
                    elif time_val is not None and not pd.isna(time_val):
                        info = _fmt_gap(time_val)
                    elif status:
                        info = _fmt_status(status)
                    else:
                        info = ""

                rows.append((pos_str, code, info))

        self._rows = rows
        self._header = f"{str(event['Location'])[:3].upper()} {session_type}"
        self._last_load_time = time.time()
        self._page = 0

    # ---- rendering ----

    def render(self) -> Image.Image:
        now = time.time()

        if not self._rows or (now - self._last_load_time) >= config.F1_SESSION_REFRESH_SECONDS:
            self._load()

        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))

        if not self._rows:
            no_data_text = "NO DATA"
            w = text_width(no_data_text, spacing=1, size="small")
            blit_text(img, max(0, (SIZE - w) // 2), 12, no_data_text, (120, 120, 130), spacing=1, size="small")
            self.poll_interval = config.F1_SESSION_REFRESH_SECONDS
            return img

        row_h = text_height("small")
        gap = 2
        y = 0

        total_pages = max(1, -(-len(self._rows) // ROWS_PER_PAGE))  # ceil division
        page = self._page % total_pages
        start = page * ROWS_PER_PAGE
        page_rows = self._rows[start:start + ROWS_PER_PAGE]

        # Position digits don't fit alongside a driver code + gap/laptime
        # at this width (measured: a single 2-digit position pushes every
        # realistic row over 32px) -- so instead the header shows which
        # position range this page covers, when there's room for it.
        # Falls back to just event+session if the range would overflow
        # (e.g. a 20-driver practice page like "18-20").
        if page_rows:
            first_pos = page_rows[0][0]
            last_pos = page_rows[-1][0]
            range_suffix = first_pos if first_pos == last_pos else f"{first_pos}-{last_pos}"
            header_full = f"{self._header} {range_suffix}"
        else:
            header_full = self._header

        max_w = SIZE - 2
        header_text = header_full if text_width(header_full, spacing=1, size="small") <= max_w else self._header

        hw = text_width(header_text, spacing=1, size="small")
        blit_text(img, max(0, (SIZE - hw) // 2), y, header_text, (255, 30, 30), spacing=1, size="small")
        y += row_h + gap

        for pos, code, info in page_rows:
            line = f"{code}{info}".strip()
            color = (255, 215, 0) if pos == "1" else (200, 200, 210)
            blit_text(img, 0, y, line, color, spacing=1, size="small")
            y += row_h + gap

        self._page += 1
        self.poll_interval = config.F1_PAGE_SECONDS
        return img
