"""
Live cricket score mode, supporting multiple followed teams, manual
match selection, and pinning to a single view (score/batting/bowling).

Depends on your own scraper/rendering modules in services/:
    - services/cricbuzz_scraper.py  (get_match_details_for_team, get_scorecard_by_id)
    - services/cricket_screens.py   (create_scorecard_image, create_batting_scorecard_image,
                                      create_bowling_scorecard_image, create_standby_image)

Three independent things are happening here, on purpose:

1. WHICH MATCHES EXIST: self.teams (a list) each resolve to a match id.
   Two followed teams playing each other dedupe to one match. Refreshed
   on a slow timer (config.CRICKET_MATCH_REFRESH_SECONDS) independent
   of everything else below.

2. WHAT DATA A MATCH HAS: each match's scorecard is refetched on its
   own fast timer (config.CRICKET_SCORE_REFRESH_SECONDS), gated by
   compare_overs so a stale/glitched scrape can't overwrite good data.
   This is decoupled from which sub-view is on screen -- data can keep
   refreshing underneath even while pinned to one view.

3. WHAT'S ON SCREEN RIGHT NOW: normally auto-cycles through all active
   matches (main->batting->bowling->main each, 20/10/10/30s). You can
   override this two ways, independently:
     - set_forced_match(match_id): pin to one specific match instead of
       cycling through all of them. Pass None to go back to auto.
     - set_forced_view(view): pin to one specific sub-view ("main",
       "batting", or "bowling") instead of cycling through all three.
       Pass None to go back to cycling.
   Both together = single match, single view, permanently (until
   changed or that match ends).
"""
import time

from PIL import Image

from modes.base import Mode
from applog import log
import config

from services.cricbuzz_scraper import get_match_details_for_team, get_scorecard_by_id
from services.cricket_screens import (
    create_scorecard_image,
    create_batting_scorecard_image,
    create_bowling_scorecard_image,
    create_standby_image,
)

VIEWS = ("main", "batting", "bowling")

# (view, seconds to display before advancing) -- used only in auto-cycle mode
SEQUENCE = [
    ("main", 20),
    ("batting", 10),
    ("bowling", 10),
    ("main", 30),
]

NO_MATCH_RETRY_SECONDS = 60
FAILED_MATCH_RETRY_SECONDS = 5


def compare_overs(current, new):
    """
    True if `new` overs is at or past `current` overs -- a genuine
    forward-moving update worth accepting. False if `new` is behind
    (e.g. a stale/glitched scrape), in which case the caller should
    keep the previously cached data instead of overwriting it.
    """
    def to_balls(overs_str):
        parts = str(overs_str).split(".")
        whole = int(parts[0]) if parts[0] else 0
        balls = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        return whole * 6 + balls

    current_balls = to_balls(current)
    new_balls = to_balls(new)
    log.debug(f"Cricket: compare_overs current={current_balls} new={new_balls}")
    return new_balls >= current_balls


class CricketMode(Mode):
    key = "cricket"
    label = "Cricket"
    poll_interval = 20  # reassigned dynamically after every render()

    def __init__(self):
        self.teams = list(config.CRICKET_TEAMS)
        self._active_matches = []      # ordered, deduped list of match ids
        self._match_state = {}         # match_id -> {"data", "last_overs", "last_fetch_time"}
        self._match_cursor = 0         # which match in _active_matches is showing (auto mode)
        self._step_index = 0           # which SEQUENCE step is showing (auto mode)
        self._last_resolve_time = 0    # for the time-based re-resolve floor

        self.forced_match_id = None    # set via set_forced_match(); None = auto-cycle matches
        self.forced_view = None        # set via set_forced_view(); None = auto-cycle views

    # ---- public API, called from the /api/cricket/* routes ----

    def set_teams(self, teams):
        if isinstance(teams, str):
            teams = teams.split(",")
        teams = [t.strip().upper() for t in teams if t.strip()]
        if not teams:
            raise ValueError("At least one team code is required")
        self.teams = teams
        self._active_matches = []
        self._match_state = {}
        self._match_cursor = 0
        self._step_index = 0
        self._last_resolve_time = 0
        log.info(f"Cricket: now following {self.teams}")

    def set_forced_match(self, match_id):
        """Pin display to one specific match id, or None to resume auto-cycling matches."""
        self.forced_match_id = match_id or None
        self._step_index = 0
        log.info(f"Cricket: forced match = {self.forced_match_id or 'auto'}")

    def set_forced_view(self, view):
        """Pin display to one specific view ('main'/'batting'/'bowling'), or None for auto-cycle."""
        if view and view not in VIEWS:
            raise ValueError(f"view must be one of {VIEWS} or empty")
        self.forced_view = view or None
        log.info(f"Cricket: forced view = {self.forced_view or 'auto'}")

    def list_matches(self):
        """Lightweight match list for a UI picker: id + whatever data is cached so far."""
        out = []
        for mid in self._active_matches:
            data = self._match_state.get(mid, {}).get("data")
            if data:
                label = f"{data.get('team1', '?')} vs {data.get('team2', '?')}"
                score = f"{data.get('score', '')} ({data.get('overs', '')} ov)"
            else:
                label, score = mid, "loading..."
            out.append({"match_id": mid, "label": label, "score": score})
        return out

    # ---- internals ----

    def _resolve_matches(self):
        """Look up each followed team's current match id and dedupe into a rotation list."""
        active = []
        for team in self.teams:
            try:
                match_id = get_match_details_for_team(team)
            except Exception as e:
                log.debug(f"Cricket: no live match for {team}: {e}")
                match_id = None
            if match_id and match_id not in active:
                active.append(match_id)

        self._active_matches = active
        # drop cached state for matches no longer active
        self._match_state = {mid: s for mid, s in self._match_state.items() if mid in active}
        if self._match_cursor >= len(active):
            self._match_cursor = 0
        self._last_resolve_time = time.time()
        log.info(f"Cricket: active matches = {self._active_matches or 'none'}")

    def _drop_match(self, match_id):
        """Remove a match from rotation (e.g. it just ended) and recover gracefully."""
        log.warning(f"Cricket: dropping match {match_id} from rotation (fetch failed)")
        if match_id in self._active_matches:
            idx = self._active_matches.index(match_id)
            self._active_matches.pop(idx)
            if self._match_cursor > idx:
                self._match_cursor -= 1
            elif self._active_matches:
                self._match_cursor %= len(self._active_matches)
            else:
                self._match_cursor = 0
        self._match_state.pop(match_id, None)
        self._step_index = 0
        if self.forced_match_id == match_id:
            log.warning("Cricket: forced match ended, reverting to auto-cycle")
            self.forced_match_id = None

    def _pick_match_id(self):
        """Which match should be on screen right now, given forced/auto state."""
        if self.forced_match_id and self.forced_match_id in self._active_matches:
            return self.forced_match_id
        if not self._active_matches:
            return None
        self._match_cursor %= len(self._active_matches)
        return self._active_matches[self._match_cursor]

    def _refresh_data(self, match_id, state, now):
        """Refetch this match's scorecard if it's due, gated by compare_overs."""
        due = state["data"] is None or (now - state["last_fetch_time"]) >= config.CRICKET_SCORE_REFRESH_SECONDS
        if not due:
            return True  # cached data is still fresh enough, nothing to do

        try:
            new_data = get_scorecard_by_id(match_id)
        except Exception as e:
            log.warning(f"Cricket: fetch failed for {match_id}: {e}")
            return False

        state["last_fetch_time"] = now
        new_overs = new_data.get("overs", "0")
        if state["data"] is None or compare_overs(state["last_overs"] or "0", new_overs):
            state["data"] = new_data
            state["last_overs"] = new_overs
            log.info(f"Cricket: {match_id} updated, overs={new_overs}")
        else:
            log.debug(
                f"Cricket: {match_id} overs did not progress "
                f"({state['last_overs']} -> {new_overs}), keeping cached data"
            )
        return True

    def _draw(self, view, data):
        if view == "main":
            return create_scorecard_image(
                team1=data["team1"],
                team2=data["team2"],
                score=data["score"],
                overs=data["overs"],
                inns=data.get("innings_id", 1),
                match_type=data.get("match_format", "T"),
                day=data.get("day_number"),
                trail=data.get("trail"),
                lead=data.get("lead"),
                bat_team=data.get("batting_team_short"),
                bowl_team=data.get("bowling_team_short"),
                state=data.get("state"),
                target=data.get("target"),
                filename="scoreboard_live.png",
            )

        if view == "batting":
            return create_batting_scorecard_image(
                striker=data["striker"],
                non_striker=data["non_striker"],
                filename="batter_live.png",
            )

        return create_bowling_scorecard_image(
            bowler1=data["bowler"],
            bowler2=data["second_bowler"],
            filename="bowler_live.png",
        )

    def render(self) -> Image.Image:
        now = time.time()

        if not self._active_matches or (now - self._last_resolve_time) >= config.CRICKET_MATCH_REFRESH_SECONDS:
            self._resolve_matches()

        match_id = self._pick_match_id()
        if match_id is None:
            self.poll_interval = NO_MATCH_RETRY_SECONDS
            return create_standby_image("NO LIVE MATCH")

        state = self._match_state.setdefault(match_id, {"data": None, "last_overs": None, "last_fetch_time": 0})

        if not self._refresh_data(match_id, state, now):
            self._drop_match(match_id)
            self.poll_interval = FAILED_MATCH_RETRY_SECONDS
            return create_standby_image("MATCH ENDED")

        if state["data"] is None:
            self.poll_interval = FAILED_MATCH_RETRY_SECONDS
            return create_standby_image("LOADING...")

        # Which view to draw, and how long to leave it up
        if self.forced_view:
            view = self.forced_view
            duration = config.CRICKET_SCORE_REFRESH_SECONDS
        else:
            view, duration = SEQUENCE[self._step_index]

        frame = self._draw(view, state["data"])

        # Advance the auto-cycle position, even if forced settings mean it's
        # not currently being used -- so switching a forced setting off
        # resumes from a sane place instead of a stale index.
        self._step_index += 1
        if self._step_index >= len(SEQUENCE):
            self._step_index = 0
            if not self.forced_match_id and self._active_matches:
                self._match_cursor = (self._match_cursor + 1) % len(self._active_matches)

        self.poll_interval = duration
        return frame
