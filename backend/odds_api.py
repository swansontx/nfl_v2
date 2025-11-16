"""
Simple wrapper for The-Odds-API (v4) targeted for NFL use in this project.

Features:
- Reads API key from environment variable ODDS_API_KEY (preferred). If not present, will try
  to read from file backend/.odds_api_key (convenience for local dev).
- Basic file caching to avoid repeated API calls in a short time window.
- Minimal helpers:
  - fetch_odds : fetch /v4/sports/{sport}/odds (supports markets/regions)
  - get_event_markets : fetch /v4/sports/{sport}/events/{eventId}/markets
  - fetch_event_odds : fetch /v4/sports/{sport}/events/{eventId}/odds
  - fetch_event_player_props : convenience wrapper to request common player markets

This module is designed to be conservative with API usage; responses are cached to
backtest/cache/ so repeated runs will reuse local cache.

Usage:
    from backend import odds_api
    data = odds_api.fetch_odds(markets='totals', regions='us')

"""
from __future__ import annotations
import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except Exception:
    Retry = None

BASE = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path('backtest/cache')
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> Optional[str]:
    # prefer env var
    key = os.environ.get('ODDS_API_KEY')
    if key:
        return key
    # fallback file
    kfile = Path('backend/.odds_api_key')
    if kfile.exists():
        return kfile.read_text().strip()
    return None


def _cache_path(name: str) -> Path:
    ts = int(time.time())
    return CACHE_DIR / f"{name}_{ts}.json"


def _save_cache(name: str, data: Any) -> Path:
    p = _cache_path(name)
    p.write_text(json.dumps(data, default=str))
    return p


def _load_cache(name: str) -> Optional[Any]:
    # find latest cache file for this name
    files = sorted(CACHE_DIR.glob(f"{name}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text())
    except Exception:
        return None


def _requests_session_with_retries(total_retries: int = 3, backoff_factor: float = 0.5, status_forcelist=(500, 502, 503, 504)):
    """Create a requests.Session with a Retry adapter for transient errors."""
    if Retry is None:
        # fallback to plain requests
        return requests
    s = requests.Session()
    retries = Retry(total=total_retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist, allowed_methods=frozenset(['GET', 'POST']))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


def fetch_odds(sport: str = 'americanfootball_nfl', regions: str = 'us', markets: str = 'totals',
               oddsFormat: str = 'american', dateFormat: str = 'iso', use_cache: bool = True,
               cache_name_suffix: Optional[str] = None, timeout: int = 20) -> Dict[str, Any]:
    """
    Fetch odds for a sport. Caches the JSON response to backtest/cache.
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError('ODDS_API_KEY not set in environment and no backend/.odds_api_key file found')
    name = f"odds_{sport}_{regions}_{markets}"
    if cache_name_suffix:
        name = name + "_" + cache_name_suffix
    if use_cache:
        cached = _load_cache(name)
        if cached:
            return cached
    url = f"{BASE}/sports/{sport}/odds"
    params = {
        'regions': regions,
        'markets': markets,
        'oddsFormat': oddsFormat,
        'dateFormat': dateFormat,
        'apiKey': key
    }
    s = _requests_session_with_retries()
    r = s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    # save cache
    _save_cache(name, data)
    return data


def get_event_markets(event_id: str, sport: str = 'americanfootball_nfl', regions: str = 'us',
                      bookmakers: Optional[str] = None, use_cache: bool = True, timeout: int = 15) -> Dict[str, Any]:
    """
    Get the available market keys for an event (per bookmaker). Uses endpoint:
    /v4/sports/{sport}/events/{eventId}/markets
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError('ODDS_API_KEY not set in environment and no backend/.odds_api_key file found')
    name = f"event_markets_{event_id}"
    if use_cache:
        cached = _load_cache(name)
        if cached:
            return cached
    url = f"{BASE}/sports/{sport}/events/{event_id}/markets"
    params = {
        'apiKey': key,
        'regions': regions,
        'dateFormat': 'iso'
    }
    if bookmakers:
        params['bookmakers'] = bookmakers
    s = _requests_session_with_retries()
    r = s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    _save_cache(name, data)
    return data


def fetch_event_odds(event_id: str, sport: str = 'americanfootball_nfl', regions: str = 'us',
                     markets: Optional[str] = None, bookmakers: Optional[str] = None,
                     use_cache: bool = True, cache_name_suffix: Optional[str] = None, timeout: int = 20) -> Dict[str, Any]:
    """
    Fetch odds for a specific event. Uses endpoint: /v4/sports/{sport}/events/{eventId}/odds
    Pass explicit player prop market keys in `markets` (comma-separated), and optionally `bookmakers`.
    Caches the response similar to fetch_odds.
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError('ODDS_API_KEY not set in environment and no backend/.odds_api_key file found')
    name = f"event_odds_{event_id}"
    if cache_name_suffix:
        name = name + "_" + cache_name_suffix
    if use_cache:
        cached = _load_cache(name)
        if cached:
            return cached
    url = f"{BASE}/sports/{sport}/events/{event_id}/odds"
    params = {
        'apiKey': key,
        'regions': regions,
        'dateFormat': 'iso'
    }
    if markets:
        params['markets'] = markets
    if bookmakers:
        params['bookmakers'] = bookmakers

    s = _requests_session_with_retries()
    r = s.get(url, params=params, timeout=timeout)
    try:
        r.raise_for_status()
    except Exception as e:
        # include response body for observability
        body = None
        try:
            body = r.text[:2000]
        except Exception:
            body = '<unavailable>'
        raise RuntimeError(f"Odds API error: status={r.status_code}, url={r.url}, body={body}") from e
    data = r.json()
    _save_cache(name, data)
    return data


def fetch_event_player_props(event_id: str, sport: str = 'americanfootball_nfl', regions: str = 'us',
                             bookmakers: Optional[str] = 'draftkings,fanduel,betmgm', use_cache: bool = True,
                             cache_name_suffix: Optional[str] = None, timeout: int = 20) -> Dict[str, Any]:
    """Convenience wrapper to fetch common player prop markets for an event.
    Ensures we call the per-event odds endpoint with explicit player markets.
    """
    # common player markets to request (extend as needed)
    player_markets = [
        'player_pass_yds', 'player_receptions', 'player_anytime_td', 'player_rush_yds', 'player_rec_yds',
        'player_rec_yds', 'player_receiving_yds', 'player_rush_yds', 'player_pass_tds'
    ]
    markets = ','.join(sorted(set(player_markets)))
    return fetch_event_odds(event_id=event_id, sport=sport, regions=regions, markets=markets,
                            bookmakers=bookmakers, use_cache=use_cache, cache_name_suffix=cache_name_suffix,
                            timeout=timeout)


if __name__ == '__main__':
    # quick local demo
    import pprint
    print('Using ODDS_API_KEY from env:', bool(_get_api_key()))
    try:
        d = fetch_odds()
        pprint.pprint(d[:1])
    except Exception as e:
        print('demo failed:', e)
