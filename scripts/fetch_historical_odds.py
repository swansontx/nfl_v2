"""
Fetch historical odds for NFL events happening on a target date (e.g. 2025-11-16).
Saves JSON to backtest/cache as historical_{event_id}_{date}.json

This script will:
 - find NFL events for the target date using backend.odds_api.fetch_odds
 - for each event, request the odds-history endpoint for the previous N days
 - save results to backtest/cache

Run: python3 scripts/fetch_historical_odds.py
"""
from __future__ import annotations
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

# ensure project root is on sys.path so `from backend import odds_api` works when running this script directly
import sys
from pathlib import Path as _Path
proj_root = _Path(__file__).resolve().parents[1]
if str(proj_root) not in sys.path:
    sys.path.insert(0, str(proj_root))

# reuse backend odds module helpers if available
try:
    from backend import odds_api
except Exception:
    odds_api = None

BASE = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path('backtest/cache')
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> Optional[str]:
    if odds_api:
        return odds_api._get_api_key()
    # fallback: read local file
    kfile = Path('backend/.odds_api_key')
    if kfile.exists():
        return kfile.read_text().strip()
    return os.environ.get('ODDS_API_KEY')


def _save_cache(name: str, data: Any) -> Path:
    p = CACHE_DIR / f"{name}.json"
    p.write_text(json.dumps(data))
    return p


def iso_date(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def find_events_on_date(target_date: datetime) -> List[Dict[str, Any]]:
    """
    Use backend.odds_api.fetch_odds to list events and filter those on target_date.
    """
    print('Fetching current odds/events to find events on', target_date.date())
    try:
        data = (odds_api.fetch_odds(sport='americanfootball_nfl', regions='us', markets='spreads,totals,h2h', use_cache=False)
                if odds_api else None)
    except Exception as e:
        print('fetch_odds failed:', e)
        data = None
    if not data:
        return []
    events = []
    for e in data:
        # commence_time example: '2025-11-16T13:00:00Z'
        ct = e.get('commence_time')
        if not ct:
            continue
        try:
            dt = datetime.strptime(ct, '%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            continue
        if dt.date() == target_date.date():
            events.append(e)
    return events


def fetch_history_for_event(event_id: str, sport: str, from_dt: datetime, to_dt: datetime, markets: str = 'spreads,totals,head-to-head') -> Optional[Dict[str, Any]]:
    key = _get_api_key()
    if not key:
        print('No API key found')
        return None
    url = f"{BASE}/sports/{sport}/odds-history"
    params = {
        'apiKey': key,
        'regions': 'us',
        'markets': markets,
        'dateFormat': 'iso',
        'eventIds': event_id,
        'from': iso_date(from_dt),
        'to': iso_date(to_dt),
    }
    print('Requesting history for', event_id, 'from', params['from'], 'to', params['to'])
    r = requests.get(url, params=params, timeout=30)
    try:
        r.raise_for_status()
    except Exception as e:
        print('HTTP error for event', event_id, r.status_code, r.text[:500])
        return None
    return r.json()


def main():
    # target date: Sunday 2025-11-16
    target_date = datetime(2025, 11, 16)
    days_back = 10
    sport = 'americanfootball_nfl'

    events = find_events_on_date(target_date)
    print('Found', len(events), 'events on', target_date.date())
    if not events:
        print('No events found for target date. Exiting.')
        return

    results = {}
    for e in events:
        event_id = e.get('id') or e.get('id')
        if not event_id:
            continue
        results[event_id] = {}
        # we'll pull history in daily windows (24h) for the previous N days up to the day before target
        for d in range(days_back, 0, -1):
            from_dt = target_date - timedelta(days=d)
            to_dt = from_dt + timedelta(days=1)
            hist = fetch_history_for_event(event_id, sport, from_dt, to_dt)
            name = f"historical_{event_id}_{from_dt.strftime('%Y%m%d')}"
            if hist is not None:
                _save_cache(name, hist)
                results[event_id][from_dt.strftime('%Y-%m-%d')] = {'saved': True, 'path': str(CACHE_DIR / f"{name}.json")}
            else:
                results[event_id][from_dt.strftime('%Y-%m-%d')] = {'saved': False}
            # be polite
            time.sleep(1)

    summary_path = CACHE_DIR / f"historical_summary_{target_date.strftime('%Y%m%d')}.json"
    summary_path.write_text(json.dumps(results))
    print('Done. Summary saved to', summary_path)


if __name__ == '__main__':
    main()
