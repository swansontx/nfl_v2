#!/usr/bin/env python3
"""
Extract all markets from a per-event TheOddsAPI snapshot and map player descriptions to canonical players
(using nfl_data_py import_players when available). Produces TSV/CSV outputs:
 - outputs/event_<EVENT>_markets.tsv       (one row per outcome)
 - outputs/event_<EVENT>_matched.csv       (rows with player_slug matched)
 - outputs/event_<EVENT>_unmatched.csv     (rows without a confident match)
 - outputs/event_<EVENT>_mapping.json      (raw mapping from description -> slug/score)

Usage: python3 scripts/extract_map_event_markets.py --event <EVENT_ID>

This script prefers to use a local cached snapshot at ~/.cache/goose/computer_controller/web_event_<EVENT>_fetch.json
If not present, it will try to fetch from TheOddsAPI if ODDS_API_KEY env var is set (but won't print it).
"""
import os, json, time, argparse, csv, math
from pathlib import Path
import difflib
from rapidfuzz import process, fuzz
import unicodedata, re

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / 'outputs'
OUTDIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'

parser = argparse.ArgumentParser()
parser.add_argument('--event', required=True, help='event id')
parser.add_argument('--snapshot', default=None, help='optional path to snapshot json')
args = parser.parse_args()
EVENT = args.event
SNAPSHOT_PATH = Path(args.snapshot) if args.snapshot else CACHE_DIR / f'web_event_{EVENT}_fetch.json'

# normalization
def norm(s):
    if not s:
        return ''
    s = str(s)
    s = s.strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9\s]", '', s)
    s = re.sub(r"\s+", ' ', s)
    return s

# load snapshot
snapshot = None
if SNAPSHOT_PATH.exists():
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
else:
    print('Snapshot not found at', SNAPSHOT_PATH)
    # try fetching if API key provided
    api_key = os.environ.get('ODDS_API_KEY') or os.environ.get('ODDSAPI_KEY')
    if api_key:
        import requests
        url = f'https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{EVENT}/odds'
        params = {'apiKey': api_key, 'regions': 'us'}
        print('Fetching full event snapshot from TheOddsAPI...')
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        snapshot = r.json()
        ts = time.strftime('%Y%m%dT%H%M%SZ')
        outp = CACHE_DIR / f'web_event_{EVENT}_full_{ts}.json'
        outp.write_text(json.dumps(snapshot))
        print('Saved snapshot to', outp)
    else:
        raise SystemExit('No snapshot and no ODDS_API_KEY provided; aborting')

# flatten outcomes
rows = []
for ev in (snapshot if isinstance(snapshot, list) else [snapshot]):
    if ev.get('id') != EVENT:
        continue
    for bk in ev.get('bookmakers', []):
        bk_key = bk.get('key')
        for m in bk.get('markets', []):
            mk = m.get('key')
            last_update = m.get('last_update')
            for o in m.get('outcomes', []):
                player = o.get('description') or o.get('participant') or o.get('label') or o.get('name')
                rows.append({
                    'event_id': ev.get('id'),
                    'bookmaker': bk_key,
                    'market_key': mk,
                    'outcome_name': o.get('name'),
                    'player_desc': player,
                    'normalized_player': norm(player),
                    'point': o.get('point'),
                    'price': o.get('price'),
                    'raw': o,
                    'last_update': last_update,
                })

markets_tsv = OUTDIR / f'event_{EVENT}_markets.tsv'
with open(markets_tsv, 'w', newline='') as fh:
    writer = csv.writer(fh, delimiter='\t')
    writer.writerow(['event_id','bookmaker','market_key','outcome_name','player_desc','normalized_player','point','price','last_update'])
    for r in rows:
        writer.writerow([r['event_id'], r['bookmaker'], r['market_key'], r['outcome_name'], r['player_desc'] or '', r['normalized_player'], r['point'] if r['point'] is not None else '', r['price'] if r['price'] is not None else '', r['last_update'] or ''])
print('Wrote markets TSV to', markets_tsv)

# Build roster/player lookup using nfl_data_py if available
roster_names = {}  # normalized -> {'player_name':..., 'player_id':..., 'team':...}
try:
    import nfl_data_py as nd
    print('nfl_data_py available — importing player data for lookup')
    try:
        # import_players or import_ids may exist; try import_players for 2025
        ply = None
        if hasattr(nd, 'import_players'):
            ply = nd.import_players()
        elif hasattr(nd, 'import_ids'):
            ply = nd.import_ids()
        else:
            ply = None
        if ply is not None:
            # ply may be DataFrame-like
            try:
                import pandas as pd
                df = ply
                for _, r in df.iterrows():
                    name = r.get('player_name') or r.get('full_name') or r.get('name')
                    team = r.get('team') or r.get('team_abbr') or r.get('team_abbreviation')
                    pid = r.get('gsis_id') or r.get('nfl_id') or r.get('player_id') or r.get('player')
                    if not name:
                        continue
                    nn = norm(name)
                    if nn:
                        roster_names[nn] = {'player_name': name, 'player_id': pid, 'team': team}
                        # also add last name variant
                        parts = nn.split()
                        if len(parts)>1:
                            roster_names[parts[-1]] = roster_names.get(parts[-1], {'player_name': name, 'player_id': pid, 'team': team})
            except Exception:
                # ply might be list of dicts
                try:
                    for r in ply:
                        name = r.get('player_name') or r.get('full_name') or r.get('name')
                        team = r.get('team')
                        pid = r.get('gsis_id') or r.get('player_id')
                        if not name:
                            continue
                        nn = norm(name)
                        roster_names[nn] = {'player_name': name, 'player_id': pid, 'team': team}
                except Exception:
                    pass
    except Exception as e:
        print('Error importing players from nfl_data_py:', e)
except Exception:
    print('nfl_data_py not available; proceeding without roster lookup')

print('Roster lookup size:', len(roster_names))

# Unique normalized player descriptions from snapshot
unique_desc = sorted({r['normalized_player'] for r in rows if r['normalized_player']})

mapping = {}  # normalized_desc -> {'match': slug/info or None, 'candidates':[...]}
matched_rows = []
unmatched_rows = []

roster_keys = list(roster_names.keys())
for ndsc in unique_desc:
    entry = {'match': None, 'candidates': []}
    if ndsc in roster_names:
        entry['match'] = roster_names[ndsc]
    else:
        # fuzzy match using difflib
        cand = difflib.get_close_matches(ndsc, roster_keys, n=3, cutoff=0.8)
        for c in cand:
            entry['candidates'].append({'roster_norm': c, 'info': roster_names.get(c)})
        if not cand:
            # try looser cutoff
            cand2 = difflib.get_close_matches(ndsc, roster_keys, n=3, cutoff=0.6)
            for c in cand2:
                entry['candidates'].append({'roster_norm': c, 'info': roster_names.get(c)})
    mapping[ndsc] = entry

# attach mapping to rows
for r in rows:
    ndsc = r['normalized_player']
    m = mapping.get(ndsc)
    if m and m.get('match'):
        r2 = r.copy()
        r2['matched_player_name'] = m['match']['player_name']
        r2['matched_player_id'] = m['match']['player_id']
        r2['matched_team'] = m['match'].get('team')
        matched_rows.append(r2)
    else:
        r2 = r.copy()
        r2['candidate_matches'] = m['candidates'] if m else []
        unmatched_rows.append(r2)

# write matched and unmatched CSVs
matched_csv = OUTDIR / f'event_{EVENT}_matched.csv'
unmatched_csv = OUTDIR / f'event_{EVENT}_unmatched.csv'
with open(matched_csv, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['event_id','bookmaker','market_key','outcome_name','player_desc','normalized_player','point','price','matched_player_name','matched_player_id','matched_team','last_update'])
    for r in matched_rows:
        w.writerow([r['event_id'], r['bookmaker'], r['market_key'], r['outcome_name'], r['player_desc'] or '', r['normalized_player'], r['point'] or '', r['price'] or '', r.get('matched_player_name') or '', r.get('matched_player_id') or '', r.get('matched_team') or '', r.get('last_update') or ''])

with open(unmatched_csv, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['event_id','bookmaker','market_key','outcome_name','player_desc','normalized_player','point','price','candidate_matches','last_update'])
    for r in unmatched_rows:
        cand = json.dumps([c for c in r.get('candidate_matches',[])], ensure_ascii=False)
        w.writerow([r['event_id'], r['bookmaker'], r['market_key'], r['outcome_name'], r['player_DESC'] if 'player_DESC' in r else (r['player_desc'] or ''), r['normalized_player'], r['point'] or '', r['price'] or '', cand, r.get('last_update') or ''])

# mapping json
map_file = OUTDIR / f'event_{EVENT}_mapping.json'
with open(map_file, 'w', encoding='utf-8') as fh:
    json.dump(mapping, fh, indent=2, ensure_ascii=False)

print('Wrote matched CSV:', matched_csv)
print('Wrote unmatched CSV:', unmatched_csv)
print('Wrote mapping JSON:', map_file)
print('Done')
