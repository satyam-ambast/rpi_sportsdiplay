"""
Live cricket score mode, supporting multiple followed teams.

Depends on your own scraper/rendering modules in services/:
    - services/cricbuzz_scraper.py  (get_match_details_for_team, get_scorecard_by_id)
    - services/cricket_screens.py   (create_scorecard_image, create_batting_scorecard_image,
                                      create_bowling_scorecard_image)

How multi-team cycling works:
  - self.teams is a list (e.g. ["IND", "ENG", "AUS"]).
  - Each team is resolved to a match id. If two followed teams are
    playing each other, they resolve to the same match id and it's
    only shown once (deduped into self._active_matches).
  - The rotation is two nested loops: for the current match, cycle its
    own main(20s) -> batting(10s) -> bowling(10s) -> main(30s) sequence
    same as before; once that finishes, move to the next match in
    self._active_matches. After the last match, wrap back to the first
    AND re-resolve every team's match id (picks up new matches
    starting, teams finishing, etc).
  - Each match keeps its own cached data + last_overs, gated by
    compare_overs, so matches don't interfere with each other's state.
  - If a fetch fails for the match currently on screen (e.g. it just
    ended), that match is dropped from the rotation and we move on to
    the next one, rather than getting stuck retrying it forever.
  - If none of the followed teams have a live match, a small "no live
    match" placeholder is shown and match resolution is retried on a
    slower cadence instead of hammering the lookup.
"""
from PIL import Image, ImageDraw, ImageFont

from modes.base import Mode
from applog import log
import config

from services.cricbuzz_scraper import get_match_details_for_team, get_scorecard_by_id
from services.cricket_screens import (
    create_scorecard_image,
    create_batting_scorecard_image,
    create_bowling_scorecard_image,
    create_standby_image
)

# (step name, seconds to display before advancing to the next step)
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


def _placeholder_frame(line1, line2=""):
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((2, 10), line1, fill=(120, 120, 130), font=font)
    if line2:
        draw.text((2, 19), line2, fill=(120, 120, 130), font=font)
    return img


class CricketMode(Mode):
    key = "cricket"
    label = "Cricket"
    poll_interval = 20  # reassigned dynamically after every render()

    def __init__(self):
        self.teams = list(config.CRICKET_TEAMS)
        self._active_matches = []      # ordered, deduped list of match ids
        self._match_state = {}         # match_id -> {"data":..., "last_overs":...}
        self._match_cursor = 0         # which match in _active_matches is showing
        self._step_index = 0           # which sub-step within that match's SEQUENCE

    # ---- public API, called from the /api/cricket/teams route ----

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
        log.info(f"Cricket: now following {self.teams}")

    # ---- internals ----

    def _resolve_matches(self):
        """Look up each followed team's current match id and dedupe into a rotation list."""
        active = []
        for team in self.teams:
            print(team)
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
        self._match_cursor = 0
        self._step_index = 0
        log.info(f"Cricket: active matches = {self._active_matches or 'none'}")

    def _drop_current_match(self):
        """Remove the currently-showing match from rotation (e.g. it just ended)."""
        if not self._active_matches:
            return
        dead = self._active_matches[self._match_cursor]
        log.warning(f"Cricket: dropping match {dead} from rotation (fetch failed)")
        self._active_matches.pop(self._match_cursor)
        self._match_state.pop(dead, None)
        if self._active_matches:
            self._match_cursor %= len(self._active_matches)
        else:
            self._match_cursor = 0
        self._step_index = 0

    def render(self) -> Image.Image:
        # Resolve (or re-resolve) matches whenever we don't have any yet,
        # or we've wrapped back around to the start of a full cycle.
        if not self._active_matches or (self._match_cursor == 0 and self._step_index == 0):
            self._resolve_matches()

        if not self._active_matches:
            self.poll_interval = NO_MATCH_RETRY_SECONDS
            return create_standby_image("NO LIVE MATCH")

        match_id = self._active_matches[self._match_cursor]
        state = self._match_state.setdefault(match_id, {"data": None, "last_overs": None})
        step_name, duration = SEQUENCE[self._step_index]

        if self._step_index == 0 or state["data"] is None:
            try:
                new_data = get_scorecard_by_id(match_id)
            except Exception as e:
                log.warning(f"Cricket: fetch failed for {match_id}: {e}")
                self._drop_current_match()
                self.poll_interval = FAILED_MATCH_RETRY_SECONDS
                return create_standby_image("MATCH  ENDED")

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

        data = state["data"]
        

        if step_name == "main":
            frame=create_scorecard_image(
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
            #frame = Image.open("scoreboard_live.png").convert("RGB")

        elif step_name == "batting":
            frame=create_batting_scorecard_image(
                striker=data["striker"],
                non_striker=data["non_striker"],
                filename="batter_live.png",
            )
            #frame = Image.open("batter_live.png").convert("RGB")

        else:  # "bowling"
            frame=create_bowling_scorecard_image(
                bowler1=data["bowler"],
                bowler2=data["second_bowler"],
                filename="bowler_live.png",
            )
            #frame = Image.open("bowler_live.png").convert("RGB")

        # Advance within the current match's sequence; once it's finished,
        # move on to the next match in the rotation.
        self._step_index += 1
        if self._step_index >= len(SEQUENCE):
            self._step_index = 0
            self._match_cursor = (self._match_cursor + 1) % len(self._active_matches)

        self.poll_interval = duration
        return frame
