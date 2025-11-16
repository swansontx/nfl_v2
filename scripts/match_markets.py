#!/usr/bin/env python3
import json, glob, os, re
import pandas as pd
from math import ceil

def american_to_decimal(a):
    if a is None:
        return None
    a = int(a)
    if a > 0:
        return 1.0 + a/100.0
    else:
        return 1.0 + 100.0/(-a)

def american_to_prob(a):
    a = int(a)
    if a > 0:
        return 100.0/(a+100.0)
    else:
        return -a/(-a+100.0)

# load latest projections file
proj_files = sorted(glob.glob('outputs/projections_*.csv'))
if not proj_files:
    print('No projections file found')
    raise SystemExit(1)
proj_file = proj_files[-1]
print('Using projections file', proj_file)
projs = pd.read_csv(proj_file)

# load market files
market_files = glob.glob('data/odds_live/event_props/*_dk_markets.json') + glob.glob('backtest/cache/event_markets_*.json') + glob.glob('data/odds_live/event_markets_*.json') + glob.glob('data/dk_events/full/*_dk_all_markets.json')
print('Found market files:', len(market_files))
markets = []
for f in market_files:
    try:
        j = json.load(open(f))
    except Exception:
        continue
    # structure may vary: some files are {'markets':[...]}, some are full event dict
    if isinstance(j, dict) and 'markets' in j:
        ev_id = j.get('id') or j.get('event_id') or os.path.basename(f).split('_')[0]
        markets.append((ev_id, j))
    elif isinstance(j, dict) and 'bookmakers' in j:
        ev_id = j.get('id') or j.get('event_id') or os.path.basename(f).split('_')[0]
        markets.append((ev_id, j))
    else:
        # could be a mapping summary
        markets.append((os.path.basename(f), j))

# If we couldn't find markets for an event during matching, we can try the Odds API per-event
from backend import odds_api


def ensure_event_markets(event_id):
    # look for an existing market in loaded markets
    for mid, mo in markets:
        if str(event_id) in str(mid) or str(mid) in str(event_id):
            return mo
    # if not found, try to fetch from Odds API (will use cache if available)
    try:
        print('Fetching event markets from Odds API for', event_id)
        ev = odds_api.fetch_event_player_props(event_id, use_cache=True)
        return ev
    except Exception as e:
        print('Failed to fetch event markets for', event_id, e)
        return None

# Helper to search outcomes for a player and line
number_re = re.compile(r"([0-9]+\.?[0-9]*)")

def find_matching_outcome(player, line, market_obj):
    # search across bookmakers -> markets -> outcomes
    player_norm = ''.join(e for e in (player or '').lower() if e.isalnum() or e.isspace())
    line_str = str(line)
    candidates = []
    if not isinstance(market_obj, dict):
        return []
    bks = market_obj.get('bookmakers') or []
    for bk in bks:
        bk_key = bk.get('key')
        for m in bk.get('markets', []):
            mkey = m.get('key')
            outcomes = m.get('outcomes') or []
            for o in outcomes:
                name = o.get('name') or ''
                # check if player appears in name
                name_norm = ''.join(e for e in name.lower() if e.isalnum() or e.isspace())
                if player_norm.strip() == 'nan' or player_norm=='':
                    # if no player, skip
                    continue
                if player_norm.split()[-1] in name_norm:
                    # check if numeric line in name
                    nums = number_re.findall(name)
                    if nums:
                        # take first numeric
                        if abs(float(nums[0]) - float(line)) < 0.01:
                            candidates.append((bk_key, mkey, o))
                    else:
                        # maybe outcomes are 'Over'/'Under' with point in market
                        # if market has 'point' attribute in m or o
                        if 'point' in o and float(o['point'])==float(line):
                            candidates.append((bk_key, mkey, o))
                        elif 'point' in m and float(m['point'])==float(line):
                            candidates.append((bk_key, mkey, o))
                else:
                    # check if name contains Over/Under and number
                    if player_norm.split()[-1] in name_norm and number_re.search(name):
                        nums = number_re.findall(name)
                        if nums and abs(float(nums[0]) - float(line)) < 0.01:
                            candidates.append((bk_key, mkey, o))
    return candidates

matches = []
for idx,row in projs.iterrows():
    player = row.get('player')
    line = row.get('line')
    event_id = row.get('event_id')
    # try to find market file for event
    matched = []
    # if event_id given, search markets matching that id
    for mid, mo in markets:
        if event_id and (str(event_id) not in str(mid) and str(mid) not in str(event_id)):
            continue
        # search
        found = find_matching_outcome(player, line, mo)
        if found:
            for bk_key, mkey, outcome in found:
                price = outcome.get('price')
                if price is None:
                    continue
                decimal = american_to_decimal(price)
                implied_prob = american_to_prob(price)
                ev = row['proj_prob_ge_line'] * decimal - 1.0
                matches.append({
                    'player': player,
                    'event_id': event_id,
                    'market_key': mkey,
                    'bookmaker': bk_key,
                    'outcome_name': outcome.get('name'),
                    'american': price,
                    'decimal': decimal,
                    'market_implied_prob': implied_prob,
                    'model_proj_prob': row['proj_prob_ge_line'],
                    'EV_per_1': ev,
                    'line': line
                })
    # if no matches, try fuzzy search across all markets
    if not matches:
        # attempt to fetch per-event markets for this event_id if available
        if event_id:
            ev_markets = ensure_event_markets(event_id)
            if ev_markets:
                found = find_matching_outcome(player, line, ev_markets)
                if found:
                    for bk_key, mkey, outcome in found:
                        price = outcome.get('price')
                        if price is None:
                            continue
                        decimal = american_to_decimal(price)
                        implied_prob = american_to_prob(price)
                        ev = row['proj_prob_ge_line'] * decimal - 1.0
                        matches.append({
                            'player': player,
                            'event_id': event_id,
                            'market_key': mkey,
                            'bookmaker': bk_key,
                            'outcome_name': outcome.get('name'),
                            'american': price,
                            'decimal': decimal,
                            'market_implied_prob': implied_prob,
                            'model_proj_prob': row['proj_prob_ge_line'],
                            'EV_per_1': ev,
                            'line': line
                        })
        # fallback: search across all known markets
        if not matches:
            for mid, mo in markets:
                found = find_matching_outcome(player, line, mo)
                if found:
                    for bk_key, mkey, outcome in found:
                        price = outcome.get('price')
                        if price is None:
                            continue
                        decimal = american_to_decimal(price)
                        implied_prob = american_to_prob(price)
                        ev = row['proj_prob_ge_line'] * decimal - 1.0
                        matches.append({
                            'player': player,
                            'event_id': mid,
                            'market_key': mkey,
                            'bookmaker': bk_key,
                            'outcome_name': outcome.get('name'),
                            'american': price,
                            'decimal': decimal,
                            'market_implied_prob': implied_prob,
                            'model_proj_prob': row['proj_prob_ge_line'],
                            'EV_per_1': ev,
                            'line': line
                        })

# write matches to CSV
if matches:
    df = pd.DataFrame(matches)
    df_sorted = df.sort_values('EV_per_1', ascending=False)
    df_sorted.to_csv('outputs/prop_market_matches.csv', index=False)
    print('Wrote outputs/prop_market_matches.csv with', len(df_sorted), 'matches')
    print(df_sorted.head(20).to_string(index=False))
else:
    print('No market matches found')
