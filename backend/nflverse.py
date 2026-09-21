"""Client for nflverse-data -- free NFL data, no API key required.

Why this source
---------------
nflverse publishes the nflfastR data stack as plain CSV on GitHub releases:
schedules (including closing spreads, totals and moneylines), play-by-play,
weekly player and team stats, official injury reports, snap counts, depth
charts, rosters and PFR advanced stats. It updates during the season, it is
free, and it needs no key.

It is also, from this environment, the only thing reachable. A reachability
sweep on 2026-09-21 found the session's egress policy blocks ESPN, Sleeper,
DraftKings, Kalshi, Pro-Football-Reference and The Odds API, while
github.com and raw.githubusercontent.com return 200. `api.github.com` is
403 (unauthenticated rate limit), so this module builds release download
URLs directly rather than going through the releases API.

What it does not have
---------------------
Player prop lines. nflverse carries game-level markets only -- spread, total
and moneyline, in the schedule file. Props need a book or an aggregator, and
every one of those is blocked here. If you want props you need an
ODDS_API_KEY plus api.the-odds-api.com allowed through the egress policy;
see backend/odds_api.py.

Usage
-----
    from backend import nflverse

    games = nflverse.load('schedules')
    inj   = nflverse.injuries(2026, week=2, teams=('NYG', 'LA'))
    snaps = nflverse.snap_shares(2026, week=1, team='LA')
"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

BASE = 'https://github.com/nflverse/nflverse-data/releases/download'
CACHE_DIR = Path('data/nflverse')
DEFAULT_MAX_AGE_HOURS = 6.0

# Dataset name -> (release tag, filename template).
# {season} is substituted when a season is supplied. Availability was probed
# against the 2026 season on 2026-09-21; see AVAILABILITY_NOTES below.
DATASETS: Dict[str, tuple] = {
    'schedules':      ('schedules', 'games.csv'),
    'players':        ('players', 'players.csv'),
    'rosters':        ('rosters', 'roster_{season}.csv'),
    'injuries':       ('injuries', 'injuries_{season}.csv'),
    'snap_counts':    ('snap_counts', 'snap_counts_{season}.csv'),
    'depth_charts':   ('depth_charts', 'depth_charts_{season}.csv'),
    'pbp':            ('pbp', 'play_by_play_{season}.csv'),
    'player_week':    ('stats_player', 'stats_player_week_{season}.csv'),
    'player_season':  ('stats_player', 'stats_player_reg_{season}.csv'),
    'team_week':      ('stats_team', 'stats_team_week_{season}.csv'),
    'adv_pass':       ('pfr_advstats', 'advstats_week_pass_{season}.csv'),
    'adv_rush':       ('pfr_advstats', 'advstats_week_rush_{season}.csv'),
    'adv_rec':        ('pfr_advstats', 'advstats_week_rec_{season}.csv'),
    'adv_def':        ('pfr_advstats', 'advstats_week_def_{season}.csv'),
    'ftn_charting':   ('ftn_charting', 'ftn_charting_{season}.csv'),
}

# Datasets that used to exist under these names but 404 for 2026. Kept so the
# error message can say "renamed/retired" rather than just "not found".
RETIRED = {
    'participation': 'not published for 2026; use ftn_charting or pbp',
    'espn_data': 'not published for 2026',
    'nextgen_stats': 'ngs_{season}_*.csv naming; not published for 2026 yet',
    'rosters_weekly': 'not published for 2026 yet; use rosters',
}

# Datasets are large; pbp and depth_charts especially. Warn rather than
# silently pulling 50MB on a cold cache.
LARGE_MB = {'pbp': 11, 'depth_charts': 52, 'players': 7}


class DatasetUnavailable(RuntimeError):
    """Raised when a dataset/season combination is not published."""


def dataset_url(name: str, season: Optional[int] = None) -> str:
    """Build the release download URL for a dataset."""
    if name not in DATASETS:
        hint = RETIRED.get(name)
        if hint:
            raise DatasetUnavailable(f"dataset '{name}' is unavailable: {hint}")
        raise KeyError(f"unknown dataset '{name}'; known: {sorted(DATASETS)}")
    tag, template = DATASETS[name]
    if '{season}' in template:
        if season is None:
            raise ValueError(f"dataset '{name}' requires a season")
        filename = template.format(season=season)
    else:
        filename = template
    return f'{BASE}/{tag}/{filename}'


def cache_path(name: str, season: Optional[int] = None) -> Path:
    tag, template = DATASETS[name]
    filename = template.format(season=season) if '{season}' in template else template
    return CACHE_DIR / filename


def _is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    if max_age_hours is None:
        return True
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def fetch(name: str, season: Optional[int] = None, use_cache: bool = True,
          max_age_hours: float = DEFAULT_MAX_AGE_HOURS, timeout: int = 120) -> Path:
    """Download a dataset to the local cache and return its path.

    Re-downloads when the cached copy is older than `max_age_hours`. Pass
    `max_age_hours=None` to accept any cached copy regardless of age.
    """
    path = cache_path(name, season)
    if use_cache and _is_fresh(path, max_age_hours):
        return path

    url = dataset_url(name, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=timeout, allow_redirects=True)
    if resp.status_code == 404:
        raise DatasetUnavailable(
            f"nflverse has no '{name}' for season {season} ({url}). "
            f"The season may not have started, or the release was renamed."
        )
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return path


def load(name: str, season: Optional[int] = None, use_cache: bool = True,
         max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
         where: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Load a dataset as a list of dicts, optionally filtered.

    `where` matches on exact string equality; a sequence value matches any of
    its members. Values are left as strings -- use `num()` to coerce.
    """
    path = fetch(name, season, use_cache=use_cache, max_age_hours=max_age_hours)
    with path.open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    return filter_rows(rows, where) if where else rows


def filter_rows(rows: Iterable[Dict[str, str]],
                where: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for row in rows:
        keep = True
        for key, want in where.items():
            got = row.get(key)
            if isinstance(want, (list, tuple, set, frozenset)):
                if got not in {str(w) for w in want}:
                    keep = False
                    break
            elif got != str(want):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def num(value: Any, default: float = 0.0) -> float:
    """Coerce a CSV cell to float, treating '' and 'NA' as missing."""
    if value is None:
        return default
    s = str(value).strip()
    if s == '' or s.upper() in ('NA', 'NAN', 'NULL', 'NONE'):
        return default
    try:
        return float(s)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# convenience queries
# --------------------------------------------------------------------------

def schedule(season: Optional[int] = None, week: Optional[int] = None,
             **kw) -> List[Dict[str, str]]:
    """Game schedule, including spread_line, total_line and moneylines."""
    where: Dict[str, Any] = {}
    if season is not None:
        where['season'] = season
    if week is not None:
        where['week'] = week
    return load('schedules', where=where or None, **kw)


def find_game(season: int, week: int, team: str, **kw) -> Optional[Dict[str, str]]:
    """The game `team` plays in a given week, home or away."""
    for row in schedule(season, week, **kw):
        if team in (row.get('home_team'), row.get('away_team')):
            return row
    return None


def injuries(season: int, week: Optional[int] = None,
             teams: Optional[Sequence[str]] = None, **kw) -> List[Dict[str, str]]:
    """Official injury report rows."""
    where: Dict[str, Any] = {}
    if week is not None:
        where['week'] = week
    if teams:
        where['team'] = list(teams)
    return load('injuries', season, where=where or None, **kw)


def snap_shares(season: int, week: int, team: str,
                positions: Sequence[str] = ('QB', 'RB', 'WR', 'TE'),
                **kw) -> List[Dict[str, Any]]:
    """Offensive snap share for a team's skill players, highest first.

    nflverse stores `offense_pct` as a 0-1 fraction despite the name, which
    is easy to render as "0.6%" by mistake. We expose it as
    `offense_share` (0-1) so the units are unambiguous.
    """
    rows = load('snap_counts', season, where={'week': week, 'team': team}, **kw)
    out = [
        {
            'player': r.get('player'),
            'position': r.get('position'),
            'offense_snaps': num(r.get('offense_snaps')),
            'offense_share': num(r.get('offense_pct')),
        }
        for r in rows if r.get('position') in positions
    ]
    out.sort(key=lambda r: -r['offense_share'])
    return out


def weekly_stats(season: int, week: int, team: Optional[str] = None,
                 **kw) -> List[Dict[str, str]]:
    """Weekly player box-score stats."""
    where: Dict[str, Any] = {'week': week}
    if team:
        where['team'] = team
    return load('player_week', season, where=where, **kw)


def player_usage(season: int, week: int, team: str, **kw) -> List[Dict[str, Any]]:
    """Snap share joined to box-score production for one team-week."""
    snaps = {s['player']: s for s in snap_shares(season, week, team, **kw)}
    stats = weekly_stats(season, week, team, **kw)
    out = []
    for s in stats:
        name = s.get('player_display_name')
        snap = snaps.get(name, {})
        out.append({
            'player': name,
            'position': s.get('position') or snap.get('position'),
            'offense_share': snap.get('offense_share', 0.0),
            'targets': num(s.get('targets')),
            'receptions': num(s.get('receptions')),
            'receiving_yards': num(s.get('receiving_yards')),
            'carries': num(s.get('carries')),
            'rushing_yards': num(s.get('rushing_yards')),
            'passing_yards': num(s.get('passing_yards')),
            'passing_attempts': num(s.get('attempts')),
        })
    out.sort(key=lambda r: -(r['targets'] + r['carries']))
    return out


def game_market(row: Dict[str, str]) -> Dict[str, Any]:
    """Extract the game-level betting market from a schedule row.

    `spread_line` is quoted from the home team's perspective: positive means
    the home team is favoured by that many points.
    """
    return {
        'game_id': row.get('game_id'),
        'away_team': row.get('away_team'),
        'home_team': row.get('home_team'),
        'gameday': row.get('gameday'),
        'gametime': row.get('gametime'),
        'stadium': row.get('stadium'),
        'roof': row.get('roof'),
        'spread_line': num(row.get('spread_line'), default=float('nan')),
        'total_line': num(row.get('total_line'), default=float('nan')),
        'away_moneyline': num(row.get('away_moneyline'), default=float('nan')),
        'home_moneyline': num(row.get('home_moneyline'), default=float('nan')),
    }


def available(season: int, timeout: int = 20) -> Dict[str, bool]:
    """Probe which datasets actually exist for a season (HEAD requests)."""
    out = {}
    for name in DATASETS:
        try:
            url = dataset_url(name, season)
        except ValueError:
            continue
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            out[name] = r.status_code == 200
        except requests.RequestException:
            out[name] = False
    return out
