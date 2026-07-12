"""
cricbuzz_scraper.py

Two-stage scraper for Cricbuzz live scores, feeding
create_scorecard_image() from scorecard_var_2.py.

Stage 1 - find live match IDs from the listing page
    https://www.cricbuzz.com/cricket-match/live-scores
    by regex-matching /live-cricket-scores/<id>/... links. This is
    more resilient than chasing specific CSS classes, since it only
    depends on the URL pattern, not the page's visual markup.

Stage 2 - for each match ID, fetch its individual match page and
    parse the og:title meta tag, e.g.:
        "IND 245/6 (40.2) ... Kohli 82(64), Rahul 45(38) | ..."
    This technique (og:title + regex, rather than DOM selectors) is
    adapted from mskian/live-cricket-score-api
    (https://github.com/mskian/live-cricket-score-api), an existing
    open-source Cricbuzz scraper - meta tags tend to survive site
    redesigns much better than CSS class names do, so this is a more
    durable approach than guessing at div classes.

Same disclaimer as before: this is unofficial scraping of a third
party site, not an official API. Keep request volume low, check
Cricbuzz's Terms of Service for your use case, and expect this to
need maintenance if Cricbuzz changes their markup.
"""

import re
import time
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.cricbuzz.com/cricket-match/live-scores"
MATCH_URL = "https://www.cricbuzz.com/live-cricket-scores/{match_id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cricbuzz.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

MATCH_ID_RE = re.compile(r"/live-cricket-scores/(\d+)/")
# Captures, for each match-id anchor: an optional title="..." attribute
# (used by the main card list) OR the inline text right after the tag
# closes (used by the top ticker) - whichever is present carries the
# match's status suffix (Preview / Complete / Upcoming Match / "X Won").
STATUS_RE = re.compile(
    r'/live-cricket-scores/(\d+)/[^"]*"'      # id + slug
    r'(?:[^>]*title="([^"]*)")?'              # optional title attr
    r'[^>]*>\s*([^<]*)'                       # or inline text after tag
)
NOT_LIVE_RE = re.compile(
    r"\b(preview|complete|upcoming match|drawn|no result|abandoned|won)\b",
    re.IGNORECASE,
)
CONTEXT_WINDOW = 600  # chars to look ahead, used by find_embedded_json diagnostics

SCORE_RE = re.compile(r"([A-Z]{2,4})\s+(\d+)/(\d+)\s*\(([\d.]+)\)")
BATSMEN_BLOCK_RE = re.compile(r"\((.*?)\)\s*\|")
BATSMAN_RE = re.compile(r"([A-Za-z\s.'-]+)\s+(\d+\(\d+\))")
BOWLER_RE = re.compile(r"Bowler.*?([A-Za-z.'\- ]+?)\s+\d+\s+\d+", re.IGNORECASE)
TARGET_RE = re.compile(r"need\s+(\d+)\s+runs?", re.IGNORECASE)
TRAIL_RE = re.compile(r"trail(?:s|ing)?\s+by\s+(\d+)\s+runs?", re.IGNORECASE)
LEAD_RE = re.compile(r"lead(?:s|ing)?\s+by\s+(\d+)\s+runs?", re.IGNORECASE)



def clean(text):
    return " ".join(text.split()) if text else ""


def get_live_match_ids(debug=False):
    """
    Stage 1: fetch the live-scores listing page and pull out match IDs
    that look actually LIVE (not preview/complete/upcoming), based on
    the status text observed next to each match link (either a
    title="..." attribute or inline text right after the link).

    KNOWN BLIND SPOT: Cricbuzz appears to keep recently-finished
    matches under its "Live" tab for some grace period after the
    result, but their status text still just says "Complete"/"X Won" -
    identical to a match that finished hours ago. There is no way to
    recover that timing distinction from this markup alone, so a
    match that *just* finished may be excluded here even though
    Cricbuzz's own UI still shows it under Live. If you need that
    exact behavior, you'll need Cricbuzz's underlying JSON API (see
    module docstring / find_embedded_json()) rather than this
    text-based heuristic.
    """
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    html = resp.text

    live_ids = []
    seen = set()
    for m in STATUS_RE.finditer(html):
        match_id, title_attr, inline_text = m.groups()
        if match_id in seen:
            continue
        seen.add(match_id)

        status_text = (title_attr or inline_text or "")
        is_live = not NOT_LIVE_RE.search(status_text)

        if debug:
            print(f"[{'LIVE' if is_live else 'skip'}] {match_id}: {clean(status_text)[:120]}")

        if is_live:
            live_ids.append(match_id)

    return live_ids


def find_embedded_json(html):
    """
    Diagnostic helper: many modern sports sites (Cricbuzz likely
    included, since it appears to be a client-rendered SPA-style page)
    embed their initial page data as JSON in a <script> tag, e.g.
    `window.__INITIAL_STATE__ = {...}` or a Next.js `__NEXT_DATA__`
    blob. If present, that JSON almost certainly has an explicit
    per-match status/state field (e.g. "inprogress"/"complete"/
    "upcoming"), which would be a much more reliable filter than
    scanning visible link text.

    Run this against a saved copy of the page and inspect what it
    finds - if there's a usable JSON blob, it's worth switching
    get_live_match_ids() to parse that directly instead of regex.
    """
    candidates = re.findall(
        r"(?:window\.__\w+__|__NEXT_DATA__)\s*=\s*(\{.*?\});?\s*</script>",
        html, re.DOTALL,
    )
    return candidates


# --- rich match-detail parsing (individual match commentary page) ---
#
# Individual match pages embed the full live match state as JSON
# inside a Next.js React Server Component payload
# (`self.__next_f.push([...])` script chunks). Verified against a
# real saved page: every JSON key/value is preceded by a single
# optional backslash (`\"key\":\"value\"`) - both the OPENING and
# CLOSING quote of every string. A common bug (which I hit while
# building this) is escaping only the opening quote and hardcoding
# the rest, which silently breaks every match. `kv()` below is the
# single place that pattern is defined, so every field goes through
# the same, verified-correct escaping - don't hand-roll key/value
# patterns outside of it.
#
# There are also THREE separate, only loosely-synced JSON structures
# describing the same match on this page (this page embeds "related
# matches" cards from a shared feed, not just this match's own data):
#   1. "matchInfo"  - lightweight card feed. Cleanest source for
#                      state/status (e.g. state="Lunch", status="Day 1:
#                      Lunch Break") and team names. Scope by matchId.
#   2. "matchHeader" - fuller info: toss, format, series. Its own
#                      "status" field lags behind matchInfo's (was
#                      still "Day 1: 1st Session" while matchInfo
#                      already said "Lunch") - use matchInfo for
#                      current session state, matchHeader for toss/format.
#   3. "miniscore"   - live score: current innings, both batters, both
#                      bowlers, run rate, partnership, last wicket.
#      Field names confirmed: bowler figures use "economy"/"wickets",
#      not "econ"/"wkts". strikeRate is a JSON string, not a number.

BS = r'\\?'  # optional single backslash before a quote - confirmed via
             # char-by-char inspection of a real saved page


def kv(key, value_pattern):
    """
    Build a `"key":value_pattern` regex fragment where BOTH the key's
    own closing quote and (if value_pattern is a quoted string) the
    value's quotes need the optional backslash - always route field
    matching through this rather than hardcoding quotes manually.
    """
    return rf'{BS}"{key}{BS}":{value_pattern}'


STR = lambda key: kv(key, rf'{BS}"([^"\\]*){BS}"')
NUM = lambda key: kv(key, r'([\d.]+)')
NUM_OR_NULL = lambda key: kv(key, r'([\d.]+|null)')

PLAYER_BLOCK_RE = (
    r'\{' + kv("id", r'\d+,')
    + STR("name") + ','
    + kv("runs", r'(\d+),')
    + kv("balls", r'(\d+),')
    + kv("fours", r'(\d+),')
    + kv("sixes", r'(\d+),')
    + STR("strikeRate")
)
BOWLER_BLOCK_RE = (
    r'\{' + kv("id", r'\d+,')
    + STR("name") + ','
    + kv("overs", r'([\d.]+),')
    + kv("maidens", r'(\d+),')
    + kv("economy", r'([\d.]+),')
    + kv("runs", r'(\d+),')
    + kv("wickets", r'(\d+)')
)


def _search(pattern, html):
    m = re.search(pattern, html) if isinstance(pattern, str) else pattern.search(html)
    return m.group(1) if m else None


def _search_last(pattern, text):
    """
    Like _search, but returns the LAST match in the text rather than
    the first. The page embeds this match's data more than once (an
    older SSR snapshot + a fresher hydration update) - confirmed by
    testing: the first occurrence can be stale (wrong innings' batting/
    bowling team, wrong striker/bowler), while the last occurrence
    reflects the actual current live state. Use this for anything
    derived from the miniscore/matchHeader blocks.
    """
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    matches = list(compiled.finditer(text))
    return matches[-1].group(1) if matches else None


MINISCORE_WINDOW = 4000  # chars to scope batter/bowler/score extraction to,
                          # starting from the LAST "miniscore" key in the page


def _last_miniscore_block(html):
    """
    Return the substring starting at the LAST occurrence of the
    "miniscore" JSON key, so batter/bowler/score extraction is scoped
    to the freshest live-state block instead of accidentally matching
    an earlier (stale) one elsewhere in the page.
    """
    positions = [m.start() for m in re.finditer(kv("miniscore", ""), html)]
    if not positions:
        return html  # fall back to whole page if the key isn't found this way
    start = positions[-1]
    return html[start:start + MINISCORE_WINDOW]


def extract_match_info_card(html, match_id):
    """
    The lightweight "matchInfo" card (part of a related-matches feed
    embedded on every match page) - cleanest source for current
    state/status and team names, scoped to this specific match_id.
    """
    pattern = re.compile(
        kv("matchInfo", r'\{' + kv("matchId", re.escape(str(match_id)) + ',') + r'.*?'
           + STR("state") + ',' + STR("status") + '.*?'
           + kv("team1", r'\{.*?' + STR("teamName") + ',' + STR("teamSName")) + '.*?'
           + kv("team2", r'\{.*?' + STR("teamName") + ',' + STR("teamSName"))
           ),
        re.DOTALL,
    )
    m = pattern.search(html)
    if not m:
        return None
    state, status, t1_name, t1_short, t2_name, t2_short = m.groups()
    return {
        "state": state, "status": status,
        "team1": {"name": t1_name, "short": t1_short},
        "team2": {"name": t2_name, "short": t2_short},
    }


def extract_day_number(html, match_id):
    """
    Extract the Test match day number (Day 1/2/3/4/5) from its own
    dedicated JSON field, rather than parsing it out of the "status"
    text string. Scoped to this specific match_id (this structure -
    "matchInfo":{"matchId":...,"dayNumber":N,...} - is a per-match
    alert-config block that could in principle repeat for other
    matches on the page too), and takes the LAST occurrence, same
    freshness reasoning as the rest of the live fields.

    Returns None for non-Test matches (they won't have this field) or
    if it can't be found.
    """
    pattern = re.compile(
        kv("matchInfo", r'\{' + kv("matchId", re.escape(str(match_id)) + ',') + r'.*?'
           + kv("dayNumber", r'(\d+)')),
        re.DOTALL,
    )
    return _search_last(pattern, html)


def extract_recent_overs(html):
    """
    Extract recent COMPLETED overs with their ball-by-ball sequence,
    e.g. over 37: ['0','0','0','6','1','0']. Confirmed against real
    data ('W' appears for a wicket ball), but no example with a wide/
    no-ball/bye was available while building this - if Cricbuzz embeds
    those as text tokens in the same space-separated string (e.g. a
    literal "wd"/"nb"/"b" token), they'll come through automatically
    in `balls` since we just split on whitespace; if they use a
    different notation (e.g. numeric codes), this will need revisiting
    against a real over that actually has one - save the page HTML
    from a match when you see a wide/no-ball happen and I can check.

    IMPORTANT LIMITATION: this only contains overs that have already
    finished (this array updates on an "over-break" event) - there is
    no current-over-in-progress ball-by-ball data in this page. The
    match's live `overs` value (e.g. 39.2) can be ahead of the last
    entry here (e.g. over 39) while the next over is still being
    bowled. If you need genuinely live ball-by-ball for the in-progress
    over, that's most likely served via a separate, incrementally-
    polled commentary endpoint rather than baked into this page's
    initial payload - would need a fresh investigation to find it.

    Returns a list of dicts, ordered most-recent-completed-over first:
        {
          "over_number": 39,
          "balls": ["0","0","0","0","0","0"],
          "runs": 0,
          "batting_team": "ENGW", "team_score": "131-5",
          "striker": {"name": ..., "score": "38(73)"},
          "non_striker": {"name": ..., "score": "0(2)"},
          "bowler": {"name": ..., "figures": "2-2-0-1"},  # overs-maidens-runs-wkts
        }
    """
    pattern = re.compile(
        kv("overNumber", r'(\d+),')
        + kv("overSummary", rf'{BS}"([^"\\]*){BS}"') + ','
        + kv("overRuns", r'(-?\d+),')
        + kv("batTeamObj", r'\{' + kv("teamName", rf'{BS}"([^"\\]*){BS}"') + ','
             + kv("teamScore", rf'{BS}"([^"\\]*){BS}"') + r'\}') + ','
        + kv("batStrikerObj", r'\{' + kv("playerId", r'\d+,')
             + kv("playerName", rf'{BS}"([^"\\]*){BS}"') + ','
             + kv("playerScore", rf'{BS}"([^"\\]*){BS}"') + r'\}') + ','
        + kv("batNonStrikerObj", r'\{' + kv("playerId", r'\d+,')
             + kv("playerName", rf'{BS}"([^"\\]*){BS}"') + ','
             + kv("playerScore", rf'{BS}"([^"\\]*){BS}"') + r'\}') + ','
        + kv("bowlerObj", r'\{' + kv("playerId", r'\d+,')
             + kv("playerName", rf'{BS}"([^"\\]*){BS}"') + ','
             + kv("playerScore", rf'{BS}"([^"\\]*){BS}"') + r'\}')
    )

    overs = []
    for m in pattern.finditer(html):
        (over_number, summary, runs, team_name, team_score,
         striker_name, striker_score, non_striker_name, non_striker_score,
         bowler_name, bowler_figures) = m.groups()

        overs.append({
            "over_number": int(over_number),
            "balls": summary.split(),
            "runs": int(runs),
            "batting_team": team_name,
            "team_score": team_score,
            "striker": {"name": striker_name, "score": striker_score},
            "non_striker": {"name": non_striker_name, "score": non_striker_score},
            "bowler": {"name": bowler_name, "figures": bowler_figures},
        })

    # de-dupe (same SSR+hydration duplication pattern as everywhere
    # else on this page) - keep first occurrence of each over_number,
    # which in this array appears to be listed newest-first already
    seen = set()
    deduped = []
    for o in overs:
        if o["over_number"] not in seen:
            seen.add(o["over_number"])
            deduped.append(o)

    return deduped


def get_last_over(html):
    """Convenience: just the most recently completed over, or None."""
    overs = extract_recent_overs(html)
    return overs[0] if overs else None


def parse_match_detail(html, match_id=None):
    """
    Parse an individual Cricbuzz match commentary page for rich live
    state: teams, toss, format, day/session status, current innings,
    both batters' figures, both bowlers' figures, last wicket,
    partnership, run rate, and target (if chasing).

    Pass match_id to get the most reliable current state/status/team
    names, via the matchInfo card (see extract_match_info_card).
    """
    info_card = extract_match_info_card(html, match_id) if match_id else None

    match_format = _search_last(kv("matchFormat", rf'{BS}"([^"\\]*){BS}"'), html)
    match_description = _search_last(kv("matchDescription", rf'{BS}"([^"\\]*){BS}"'), html)
    series_desc = _search_last(kv("seriesDesc", rf'{BS}"([^"\\]*){BS}"'), html)
    toss_winner = _search_last(kv("tossWinnerName", rf'{BS}"([^"\\]*){BS}"'), html)
    toss_decision = _search_last(kv("decision", rf'{BS}"([^"\\]*){BS}"'), html)

    # everything below is scoped to the LAST "miniscore" block only -
    # batting/bowling team, innings id, both batters, both bowlers,
    # score, run rates, partnership, last wicket. Unscoped searches on
    # these fields were returning stale data from an earlier snapshot
    # embedded elsewhere on the page (confirmed: batting_team_short
    # and bowling_team_short came back swapped, innings_id was stuck
    # on the first innings, once a match moved into its 2nd innings).
    block = _last_miniscore_block(html)

    batting_team_short = _search(kv("battingTeamShortName", rf'{BS}"([^"\\]*){BS}"'), block)
    bowling_team_short = _search(kv("bowlingTeamShortName", rf'{BS}"([^"\\]*){BS}"'), block)

    innings_id = _search(NUM("inningsId"), block)
    # top-level match overs (not a bowler's individual overs count, which
    # is a nested "overs" field inside bowlerStriker/bowlerNonStriker
    # appearing earlier in the block) - anchored via the field order
    # confirmed against real data: "...,"overs":25,"target":null,...".
    overs = _search(kv("overs", r'([\d.]+),') + BS + '"target' + BS + '"', block)
    target = _search(NUM_OR_NULL("target"), block)
    current_run_rate = _search(NUM("currentRunRate"), block)
    required_run_rate = _search(NUM("requiredRunRate"), block)
    last_wicket = _search(kv("lastWicket", rf'{BS}"([^"\\]*){BS}"'), block)

    partnership_m = re.search(
        kv("partnerShip", r'\{' + kv("balls", r'(\d+),') + kv("runs", r'(\d+)')), block
    )
    partnership = (
        {"balls": int(partnership_m.group(1)), "runs": int(partnership_m.group(2))}
        if partnership_m else None
    )

    bat_score_m = re.search(
        kv("batTeam", r'\{' + kv("teamId", r'\d+,') + kv("teamScore", r'(\d+),') + kv("teamWkts", r'(\d+)')), block
    )
    score = f"{bat_score_m.group(1)}/{bat_score_m.group(2)}" if bat_score_m else None

    def player(role, block_re):
        return re.search(kv(role, block_re), block)

    striker_m = player("batsmanStriker", PLAYER_BLOCK_RE)
    non_striker_m = player("batsmanNonStriker", PLAYER_BLOCK_RE)
    bowler_m = player("bowlerStriker", BOWLER_BLOCK_RE)
    second_bowler_m = player("bowlerNonStriker", BOWLER_BLOCK_RE)

    def batter_dict(m):
        if not m:
            return None
        name, runs, balls, fours, sixes, sr = m.groups()
        return {"name": name, "runs": int(runs), "balls": int(balls),
                "fours": int(fours), "sixes": int(sixes), "strike_rate": float(sr)}

    def bowler_dict(m):
        if not m:
            return None
        name, overs_, maidens, econ, runs, wkts = m.groups()
        return {"name": name, "overs": float(overs_), "maidens": int(maidens),
                "economy": float(econ), "runs": int(runs), "wickets": int(wkts)}

    day_number = extract_day_number(html, match_id) if match_id else None
    recent_overs = extract_recent_overs(html)

    return {
        "team1": info_card["team1"] if info_card else None,
        "team2": info_card["team2"] if info_card else None,
        "batting_team_short": batting_team_short,
        "bowling_team_short": bowling_team_short,
        "match_format": match_format,
        "match_description": match_description,
        "series_desc": series_desc,
        "state": info_card["state"] if info_card else None,     # e.g. "Lunch", "In Progress", "Complete"
        "status": info_card["status"] if info_card else None,   # e.g. "Day 1: Lunch Break"
        "day_number": int(day_number) if day_number else None,  # e.g. 1, 2, 3... (Test matches only)
        "toss_winner": toss_winner,
        "toss_decision": toss_decision,
        "innings_id": int(innings_id) if innings_id else None,
        "score": score,
        "overs": overs,
        "current_run_rate": float(current_run_rate) if current_run_rate else None,
        "required_run_rate": float(required_run_rate) if required_run_rate else None,
        "target": int(target) if target and target != "null" else None,
        "partnership": partnership,
        "last_wicket": last_wicket,
        "striker": batter_dict(striker_m),
        "non_striker": batter_dict(non_striker_m),
        "bowler": bowler_dict(bowler_m),
        "second_bowler": bowler_dict(second_bowler_m),
        "recent_overs": recent_overs,                            # last few COMPLETED overs, newest first
        "last_over": recent_overs[0] if recent_overs else None,  # convenience: just the most recent one
    }


def fetch_match_score(match_id):
    """
    Stage 2: fetch a single match page and parse its og:title meta tag
    for team/score/overs/batsmen/bowler, plus a best-effort scan of the
    page text for target/lead/trail phrasing (Test-match specific -
    unverified against live markup, treat as a starting point).
    """
    url = MATCH_URL.format(match_id=match_id) + f"?_={time.time_ns()}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    #print(soup)

    title = clean(soup.title.get_text(strip=True) if soup.title else "")
    title = re.sub(r"^Cricket commentary\s*\|\s*", "", title, flags=re.IGNORECASE)

    og_tag = soup.find("meta", property="og:title")
    og_title = og_tag.get("content", "") if og_tag else ""

    team, score, overs = None, None, None
    m = SCORE_RE.search(og_title)
    if m:
        team, runs, wickets, overs = m.groups()
        score = f"{runs}/{wickets}"

    batsmen = []
    block = BATSMEN_BLOCK_RE.search(og_title)
    if block:
        batsmen = [
            {"name": clean(name), "score": clean(bscore)}
            for name, bscore in BATSMAN_RE.findall(block.group(1))[:2]
        ]

    page_text = clean(soup.get_text(" ", strip=True))
    bowler_match = BOWLER_RE.search(page_text)
    bowler = clean(bowler_match.group(1)) if bowler_match else None

    target_match = TARGET_RE.search(page_text)
    trail_match = TRAIL_RE.search(page_text)
    lead_match = LEAD_RE.search(page_text)

    m = re.match(r"^\s*(.*?)\s+vs\s+(.*?),", title)

    if m:
        team1 = m.group(1)
        team2 = m.group(2)
        print(team1)  # WAF
        print(team2)  # LAKR
    else:
        raise Exception("Team not found")

    # state/status (e.g. "Lunch", "Day 1: Lunch Break") and the rest of
    # the rich live-match fields (batters, bowlers, partnership, last
    # wicket, run rates) all come from the page's embedded JSON, not
    # og:title/page text - see parse_match_detail() above for how.
    detail = parse_match_detail(resp.text, match_id)

    return {
        "match_id": match_id,
        "url": url,
        "title": title,
        "team1": team1,
        "team2": team2,
        "series_desc": detail["series_desc"],
        "match_format": detail["match_format"],
        "match_description": detail["match_description"],
        "state": detail["state"],        # e.g. "Lunch", "In Progress", "Complete"
        "status": detail["status"],      # e.g. "Day 1: Lunch Break"
        "day_number": detail["day_number"],  # e.g. 1, 2, 3... (Test matches only, None otherwise)
        "toss_winner": detail["toss_winner"],
        "toss_decision": detail["toss_decision"],
        "batting_team_short": detail["batting_team_short"],
        "bowling_team_short": detail["bowling_team_short"],
        "innings_id": detail["innings_id"],
        "score": detail["score"] or score,      # prefer JSON-derived score, fall back to og:title's
        "overs": detail["overs"] or overs,
        "current_run_rate": detail["current_run_rate"],
        "required_run_rate": detail["required_run_rate"],
        "partnership": detail["partnership"],
        "last_wicket": detail["last_wicket"],
        "striker": detail["striker"],
        "non_striker": detail["non_striker"],
        "bowler": detail["bowler"],
        "second_bowler": detail["second_bowler"],
        "recent_overs": detail["recent_overs"],
        "last_over": detail["last_over"],
        "target": detail["target"] if detail["target"] is not None else (int(target_match.group(1)) if target_match else 0),
        "trail": int(trail_match.group(1)) if trail_match else 0,
        "lead": int(lead_match.group(1)) if lead_match else 0,
    }


def parse_teams_from_title(title):
    """
    Cricbuzz match titles are usually "Team A vs Team B, Nth <fmt>,
    <series name>". Pull the two team names out of that.
    """
    m = re.match(r"([A-Za-z .]+?)\s+vs\s+([A-Za-z .]+?),", title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""


def guess_match_type(title):
    """Rough classifier: Test -> 'T', everything else (ODI/T20) -> 'L'."""
    return "T" if re.search(r"\btest\b", title, re.IGNORECASE) else "L"


def to_scorecard_kwargs(match):
    """Map a fetch_match_score() result into create_scorecard_image() kwargs."""
    team1, team2 = parse_teams_from_title(match["title"])
    match_type = guess_match_type(match["title"])

    return {
        "team1": (team1[:5] or match["batting_team"] or "").upper(),
        "team2": team2[:5].upper(),
        "score": match["score"] or "",
        "overs": match["overs"] or "",
        "match_type": match_type,
        "inns": 1,          # og:title doesn't expose innings number directly -
                             # extend this once you can confirm the field on a
                             # live page (Test matches show it in commentary)
        "target": match["target"],
        "lead": match["lead"],
        "trail": match["trail"],
    }


def get_all_live_scorecards():
    """Convenience: fetch every live match and return scorecard-ready kwargs."""
    results = []
    for match_id in get_live_match_ids():
        try:
            match = fetch_match_score(match_id)
            results.append(to_scorecard_kwargs(match))
        except requests.RequestException as e:
            print(f"Skipping match {match_id}: {e}")
    return results


def get_match_details_for_team(team):
    ids = get_live_match_ids()
    print(f"Found {len(ids)} live match IDs: {ids}")

    for match_id in ids:
        data = fetch_match_score(match_id)
        if data['team1']==team or data['team2']==team:
            return match_id

def get_scorecard_by_id(match_id):
    data = fetch_match_score(match_id)
    return data


# matchid=get_match_details_for_team("INDW")
# get_scorecard_by_id(matchid)

matchid=get_match_details_for_team("INDW")
print(get_scorecard_by_id(matchid))