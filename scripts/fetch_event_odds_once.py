#!/usr/bin/env python3
"""
Fetch per-event odds from TheOddsAPI for a single event and save the JSON to cache.
Checks for DraftKings player prop markets (anytime/1st) and exits with status.
"""
import urllib.parse, urllib.request, json, sys
from pathlib import Path

EVENT_ID = '80d04ba917883a6438580ebae9fb0f22'
API_KEY = '5750b06f728d04facf314761cc58f99d'  # from project memory
OUT_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / f'web_event_{EVENT_ID}.json'

url = f'https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{EVENT_ID}/odds'
params = {'apiKey': API_KEY, 'regions': 'us', 'markets': ''}
q = urllib.parse.urlencode(params)
full = url + '?' + q

print('Fetching', full)
req = urllib.request.Request(full, headers={'User-Agent':'goose/1.0'})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode('utf-8')
        try:
            j = json.loads(data)
        except Exception as e:
            print('Failed to parse JSON:', e)
            j = None
        with OUT_PATH.open('w') as fh:
            fh.write(data)
        print('Saved to', OUT_PATH)
except Exception as e:
    print('Fetch error:', e)
    sys.exit(2)

# Inspect for DraftKings player props
found = False
if isinstance(j, list):
    for ev in j:
        if not isinstance(ev, dict):
            continue
        for bk in ev.get('bookmakers', []):
            if bk.get('key','').lower()=='draftkings':
                for m in bk.get('markets', []):
                    k = m.get('key','')
                    if 'td' in k or 'anytime' in k:
                        print('Found DK market:', k)
                        found = True
else:
    print('Unexpected response shape')

if found:
    print('DraftKings player markets present')
    sys.exit(0)
else:
    print('No DraftKings player markets present (yet)')
    sys.exit(1)
