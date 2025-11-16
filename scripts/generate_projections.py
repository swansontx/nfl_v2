#!/usr/bin/env python3
import pandas as pd
import numpy as np
import json
import csv
from math import exp, factorial
from datetime import datetime
import os

os.makedirs('outputs', exist_ok=True)

# Load data
qb_path = 'outputs/qb_stats.csv'
kicker_path = 'outputs/kicker_stats.csv'
pbp_path = 'nfl_data_2025_csv/pbp_2025.csv'
selected_path = 'data/odds_live/selected_events_20251022_1941.json'

qb = pd.read_csv(qb_path) if os.path.exists(qb_path) else pd.DataFrame()
kicker = pd.read_csv(kicker_path) if os.path.exists(kicker_path) else pd.DataFrame()
selected = json.load(open(selected_path)) if os.path.exists(selected_path) else []

# compute games played from pbp
if os.path.exists(pbp_path):
    pbp_small = pd.read_csv(pbp_path, usecols=['game_id','home_team','away_team','field_goal_attempt','kicker_player_name'])
    home_games = pbp_small[['game_id','home_team']].drop_duplicates().groupby('home_team').size()
    away_games = pbp_small[['game_id','away_team']].drop_duplicates().groupby('away_team').size()
    games_played = (home_games.add(away_games, fill_value=0)).reset_index()
    games_played.columns = ['team','games_played']
else:
    games_played = pd.DataFrame()

# prepare QB stats
if not qb.empty:
    if 'pass_attempts' in qb.columns:
        qb['pass_att_per_game'] = qb['pass_attempts'] / 17.0
    else:
        qb['pass_att_per_game'] = 0.0
    if 'interceptions' in qb.columns and 'pass_attempts' in qb.columns:
        qb['int_rate'] = qb['interceptions'] / qb['pass_attempts'].replace(0, np.nan)
        qb['int_rate'] = qb['int_rate'].fillna(0)
    else:
        qb['int_rate'] = 0.0
    qb['expected_ints_per_game'] = qb['pass_att_per_game'] * qb['int_rate']

# kicker stats per game
if not kicker.empty:
    if 'fg_attempts' in kicker.columns:
        kicker['fg_att_per_game'] = kicker['fg_attempts'] / 17.0
    else:
        kicker['fg_att_per_game'] = 0.0
    if 'fg_makes' in kicker.columns and 'fg_attempts' in kicker.columns:
        kicker['fg_pct'] = kicker['fg_makes'] / kicker['fg_attempts'].replace(0, np.nan)
        kicker['fg_pct'] = kicker['fg_pct'].fillna(0.9)
    else:
        kicker['fg_pct'] = 0.9

candidates = []
now = datetime.now().strftime('%Y%m%d_%H%M')

# Helper: Poisson tail probability P(X >= k)
def poisson_prob_ge(lam, k):
    if lam < 1e-9:
        return 0.0 if k > 0 else 1.0
    csum = 0.0
    for i in range(0, k):
        csum += (lam ** i) * exp(-lam) / factorial(i)
    return max(0.0, 1.0 - csum)

# Build QB interception candidates for selected events
# Precompute passers by posteam from PBP (used as a reliable team-specific fallback)
passers_by_team = {}
if os.path.exists(pbp_path):
    try:
        pbp_tmp = pd.read_csv(pbp_path, usecols=['posteam','passer_player_name','pass_attempt'], low_memory=False)
        passers = pbp_tmp[pbp_tmp['pass_attempt']==1].groupby(['posteam','passer_player_name']).size().reset_index(name='count')
        for team_name in passers['posteam'].unique():
            top = passers[passers['posteam']==team_name].sort_values('count', ascending=False).iloc[0]
            passers_by_team[team_name] = top['passer_player_name']
    except Exception:
        pass

try:
    pfr = pd.read_csv('nfl_data_2025_csv/seasonal_pfr_pass_2025.csv')
except Exception:
    pfr = pd.DataFrame()

for ev in selected:
    eid = ev.get('id')
    home = ev.get('home_team')
    away = ev.get('away_team')
    date = ev.get('commence_time', '').split('T')[0]

    for team in [home, away]:
        passer_name = None
        # Prefer PFR seasonal passer if available
        if not pfr.empty and 'team' in pfr.columns and team is not None:
            tdf = pfr[pfr['team'] == team]
            if not tdf.empty:
                passer_name = tdf.sort_values('pass_attempts', ascending=False).iloc[0].get('passer_player_name', None) if 'passer_player_name' in tdf.columns else tdf.iloc[0].get('player', None)

        # Next, use PBP-derived top passer for the team
        if passer_name is None and team is not None:
            passer_name = passers_by_team.get(team)

        # If still not found, skip this team -- avoid assigning a global top passer to every team
        if passer_name is None:
            continue

        # Try to find matching stats in qb table
        qbstats = pd.DataFrame()
        if not qb.empty:
            # Check multiple possible column names for the passer in qb table
            candidate_cols = [c for c in qb.columns if 'passer' in c.lower() or 'player' in c.lower() or 'name' in c.lower()]
            # Exact match first
            for col in candidate_cols:
                if col in qb.columns and qb[col].eq(passer_name).any():
                    qbstats = qb[qb[col] == passer_name]
                    break
            # Last-name fuzzy match
            if qbstats.empty:
                lname = str(passer_name).split()[-1]
                for col in candidate_cols:
                    try:
                        if qb[col].astype(str).str.contains(lname, na=False).any():
                            qbstats = qb[qb[col].astype(str).str.contains(lname, na=False)]
                            break
                    except Exception:
                        continue

        # Determine lambda for interceptions
        lam = 0.0
        if not qbstats.empty and 'expected_ints_per_game' in qbstats.columns:
            lam = float(qbstats.iloc[0]['expected_ints_per_game'])
        elif not qbstats.empty and 'int_rate' in qbstats.columns and 'pass_att_per_game' in qbstats.columns:
            lam = float(qbstats.iloc[0].get('int_rate', 0.0) * qbstats.iloc[0].get('pass_att_per_game', 0.0))
        else:
            # fallback small prior
            lam = 0.05

        for line in [0.5, 1.5]:
            k = int(np.ceil(line))
            prob = poisson_prob_ge(lam, k)
            candidates.append({
                'event_id': eid,
                'date': date,
                'team': team,
                'player': passer_name,
                'prop_type': 'QB_INTERCEPTIONS',
                'line': line,
                'proj_prob_ge_line': prob,
                'proj_ev_lambda': lam,
                'source': 'model'
            })

# Build kicker FG attempt candidates using kicker table; use top kickers
if not kicker.empty:
    top_k = kicker.sort_values('fg_attempts', ascending=False).head(40)
    for _, row in top_k.iterrows():
        kname = row.get('kicker_player_name') if 'kicker_player_name' in row else row.get('index', None)
        lam = float(row.get('fg_att_per_game', 0.0))
        for line in [0.5, 1.5]:
            k = int(np.ceil(line))
            prob = poisson_prob_ge(lam, k)
            candidates.append({
                'event_id': None,
                'date': None,
                'team': None,
                'player': kname,
                'prop_type': 'KICKER_FG_ATT',
                'line': line,
                'proj_prob_ge_line': prob,
                'proj_ev_lambda': lam,
                'source': 'model'
            })

# Save outputs
keys = ['event_id','date','team','player','prop_type','line','proj_prob_ge_line','proj_ev_lambda','source']
csv_out = f'outputs/projections_{now}.csv'
with open(csv_out, 'w', newline='') as f:
    w = csv.DictWriter(f, keys)
    w.writeheader()
    for c in candidates:
        w.writerow({k: c.get(k, None) for k in keys})
json_out = f'outputs/projections_{now}.json'
with open(json_out, 'w') as f:
    json.dump(candidates, f, indent=2)

print('Wrote', csv_out, json_out)
