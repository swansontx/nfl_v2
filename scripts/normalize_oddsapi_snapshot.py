#!/usr/bin/env python3
"""
Normalize cached OddsAPI snapshots into row-level JSON files.
Input: looks for web_*.json in the cache dir
Output: outputs/oddsapi_normalized/<eventid>_<book>_<ts>.json
"""
import json, glob, os, datetime
from pathlib import Path

CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
OUT_DIR = Path('outputs') / 'oddsapi_normalized'
OUT_DIR.mkdir(parents=True, exist_ok=True)

files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/*.json')
count=0
for f in files:
    try:
        j=json.load(open(f))
    except Exception:
        continue
    # the historical API returns {timestamp, data: {...}}; other snapshots may be event dict or list
    timestamp = None
    events = []
    if isinstance(j, dict) and 'data' in j and isinstance(j['data'], dict):
        timestamp = j.get('timestamp')
        ev = j['data']
        events=[ev]
    elif isinstance(j, dict) and j.get('id'):
        events=[j]
    elif isinstance(j, list):
        events=[ev for ev in j if isinstance(ev, dict) and ev.get('id')]
    else:
        continue

    for ev in events:
        event_id = ev.get('id')
        sport = ev.get('sport_key')
        home = ev.get('home_team')
        away = ev.get('away_team')
        for bk in ev.get('bookmakers',[]):
            book = bk.get('key')
            mk_time = bk.get('last_update')
            rows=[]
            for m in bk.get('markets',[]):
                mkey = m.get('key')
                m_last = m.get('last_update')
                for out in m.get('outcomes',[]):
                    row = {
                        'snapshot_file': os.path.basename(f),
                        'snapshot_ts': timestamp or mk_time or m_last,
                        'event_id': event_id,
                        'sport': sport,
                        'commence_time': ev.get('commence_time'),
                        'home': home,
                        'away': away,
                        'book': book,
                        'market': mkey,
                        'market_last_update': m_last,
                        'outcome_name': out.get('name'),
                        'description': out.get('description') or out.get('participant') or out.get('name'),
                        'point': out.get('point') or out.get('line') or out.get('price'),
                        'price': out.get('price'),
                        'outcome_id': out.get('id') or out.get('participant_id') or None
                    }
                    rows.append(row)
            if rows:
                # write rows to file
                tspart = (timestamp or mk_time or datetime.datetime.utcnow().isoformat()).replace(':','').replace('-','')
                outp = OUT_DIR / f"{event_id}_{book}_{os.path.basename(f)}.json"
                with outp.open('w') as fh:
                    json.dump(rows, fh, indent=2)
                count += 1
print('Wrote normalized files for', count, 'book/event snapshots')
