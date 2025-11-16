#!/usr/bin/env python3
import pandas as pd
import numpy as np
import json, os
from math import ceil
from datetime import datetime
os.makedirs('outputs', exist_ok=True)

# Target teams
home='Los Angeles Chargers'
away='Minnesota Vikings'

# load pbp
pbp = pd.read_csv('nfl_data_2025_csv/pbp_2025.csv', usecols=['game_id','home_team','away_team','passer_player_name','passing_yards','pass_attempt','interception','receiver_player_name','receiving_yards','complete_pass','rusher_player_name','rushing_yards','rush_attempt','field_goal_attempt','field_goal_result','kicker_player_name','return_yards','punt_returner_player_name','kickoff_returner_player_name'])

# helper to compute per-game stats for passers
def player_pass_stats(pbp):
    df = pbp.groupby('passer_player_name').agg(pass_yards=('passing_yards','sum'), pass_att=('pass_attempt','sum'), interceptions=('interception','sum'), games=('game_id','nunique')).reset_index()
    df['pass_yards_per_game'] = df['pass_yards'] / df['games'].replace(0,np.nan)
    df['pass_att_per_game'] = df['pass_att'] / df['games'].replace(0,np.nan)
    df['int_rate'] = df['interceptions'] / df['pass_att'].replace(0,np.nan)
    df = df.dropna(subset=['pass_yards_per_game'])
    return df

def receiver_stats(pbp):
    df = pbp.groupby('receiver_player_name').agg(rec_yards=('receiving_yards','sum'), catches=('complete_pass','sum'), games=('game_id','nunique'))
    df = df.reset_index()
    df['rec_yards_per_game'] = df['rec_yards'] / df['games'].replace(0,np.nan)
    df['catches_per_game'] = df['catches'] / df['games'].replace(0,np.nan)
    df = df.dropna(subset=['rec_yards_per_game'])
    return df

def rusher_stats(pbp):
    df = pbp.groupby('rusher_player_name').agg(rush_yards=('rushing_yards','sum'), rush_att=('rush_attempt','sum'), games=('game_id','nunique'))
    df = df.reset_index()
    df['rush_yards_per_game'] = df['rush_yards'] / df['games'].replace(0,np.nan)
    df['rush_att_per_game'] = df['rush_att'] / df['games'].replace(0,np.nan)
    df = df.dropna(subset=['rush_yards_per_game'])
    return df

pass_stats = player_pass_stats(pbp)
rec_stats = receiver_stats(pbp)
rush_stats = rusher_stats(pbp)

# find top QBs for each team using pbp: look at home_team/away_team association
# find most common passer in games where team is home/away

def top_players_for_team(team, role='passer', topn=6):
    if role=='passer':
        # find passers who threw for this team (posteam?) pbp doesn't have posteam here; approximate by matching game rows where passer present and team is either home or away
        # We'll inspect pbp rows where passer_player_name not null and team is either home or away and attribute by which side matches passer's team? Hard to map; instead use seasonal_pfr as fallback
        df = pass_stats.copy()
        # find passers that appear in games where team is present
        games = pbp[(pbp['home_team']==team) | (pbp['away_team']==team)]['game_id'].unique()
        df = pbp[pbp['game_id'].isin(games)].groupby('passer_player_name').agg(pass_yards=('passing_yards','sum'), pass_att=('pass_attempt','sum'), games=('game_id','nunique')).reset_index()
        df['pass_yards_per_game'] = df['pass_yards']/df['games'].replace(0,np.nan)
        df = df.sort_values('pass_yards_per_game', ascending=False)
        return df['passer_player_name'].dropna().unique()[:topn]
    elif role=='receiver':
        games = pbp[(pbp['home_team']==team) | (pbp['away_team']==team)]['game_id'].unique()
        df = pbp[pbp['game_id'].isin(games)].groupby('receiver_player_name').agg(rec_yards=('receiving_yards','sum'), catches=('complete_pass','sum'), games=('game_id','nunique')).reset_index()
        df['rec_yards_per_game'] = df['rec_yards']/df['games'].replace(0,np.nan)
        df = df.sort_values('rec_yards_per_game', ascending=False)
        return df['receiver_player_name'].dropna().unique()[:topn]
    else:
        games = pbp[(pbp['home_team']==team) | (pbp['away_team']==team)]['game_id'].unique()
        df = pbp[pbp['game_id'].isin(games)].groupby('rusher_player_name').agg(rush_yards=('rushing_yards','sum'), rush_att=('rush_attempt','sum'), games=('game_id','nunique')).reset_index()
        df['rush_att_per_game'] = df['rush_att']/df['games'].replace(0,np.nan)
        df = df.sort_values('rush_att_per_game', ascending=False)
        return df['rusher_player_name'].dropna().unique()[:topn]

v_qbs = top_players_for_team('Minnesota Vikings', 'passer', topn=2)
c_qbs = top_players_for_team('Los Angeles Chargers', 'passer', topn=2)
print('Vikings top QBs (by recent games):', v_qbs)
print('Chargers top QBs:', c_qbs)

v_receivers = top_players_for_team('Minnesota Vikings','receiver', topn=8)
c_receivers = top_players_for_team('Los Angeles Chargers','receiver', topn=8)
print('Vikings receivers sample:', v_receivers[:5])
print('Chargers receivers sample:', c_receivers[:5])

v_rushers = top_players_for_team('Minnesota Vikings','rusher', topn=6)
c_rushers = top_players_for_team('Los Angeles Chargers','rusher', topn=6)

# Build prop candidates
candidates = []
# QB passing yards lines
for qb in list(v_qbs[:1]) + list(c_qbs[:1]):
    if pd.isna(qb):
        continue
    row = pass_stats[pass_stats['passer_player_name']==qb]
    if row.empty:
        continue
    mean = float(row['pass_yards_per_game'].iloc[0])
    sd = max(1.0, 0.35*mean)
    for line in [200.5, 225.5, 250.5]:
        # prob of >= line assuming normal
        prob = 1 - (0.5*(1+np.math.erf((line-mean)/(sd*np.sqrt(2)))))
        candidates.append({'player':qb,'team':('Vikings' if qb in v_qbs else 'Chargers'),'prop':'QB_PASS_YDS','line':line,'proj_mean':mean,'proj_prob_ge':prob})
# QB INTs
# use qb int rate from pass_stats
for qb in list(v_qbs[:1]) + list(c_qbs[:1]):
    row = pass_stats[pass_stats['passer_player_name']==qb]
    if row.empty: continue
    lam = float(row['pass_att_per_game'].iloc[0] * (row['interceptions'].iloc[0]/max(1,row['pass_att'].iloc[0]))) if row['pass_att'].iloc[0]>0 else 0.05
    for line in [0.5,1.5]:
        k = int(np.ceil(line))
        # Poisson tail
        prob = 1 - sum([np.exp(-lam)*lam**i/np.math.factorial(i) for i in range(0,k)])
        candidates.append({'player':qb,'team':('Vikings' if qb in v_qbs else 'Chargers'),'prop':'QB_INTERCEPTIONS','line':line,'proj_lambda':lam,'proj_prob_ge':prob})

# Receivers yards
for r in list(v_receivers[:6]) + list(c_receivers[:6]):
    if pd.isna(r): continue
    row = rec_stats[rec_stats['receiver_player_name']==r]
    if row.empty: continue
    mean = float(row['rec_yards_per_game'].iloc[0])
    sd = max(1.0, 0.6*mean)
    for line in [40.5, 60.5, 80.5]:
        prob = 1 - (0.5*(1+np.math.erf((line-mean)/(sd*np.sqrt(2)))))
        candidates.append({'player':r,'team':('Vikings' if r in v_receivers else 'Chargers'),'prop':'REC_YDS','line':line,'proj_mean':mean,'proj_prob_ge':prob})

# Rushers yards
for r in list(v_rushers[:4]) + list(c_rushers[:4]):
    if pd.isna(r): continue
    row = rush_stats[rush_stats['rusher_player_name']==r]
    if row.empty: continue
    mean = float(row['rush_yards_per_game'].iloc[0])
    sd = max(1.0, 0.6*mean)
    for line in [30.5, 50.5, 70.5]:
        prob = 1 - (0.5*(1+np.math.erf((line-mean)/(sd*np.sqrt(2)))))
        candidates.append({'player':r,'team':('Vikings' if r in v_rushers else 'Chargers'),'prop':'RUSH_YDS','line':line,'proj_mean':mean,'proj_prob_ge':prob})

# Anytime TDs: approximate from TD occurrences in pbp; use 'td_player_name' not included so approximate using passing/rushing/receiving TDs not available; use heuristic lambda = (mean yards>50?) fallback small
# We'll skip detailed TD lambda and leave as placeholder

# Kicker FG attempts from pbp
kickers = pbp[pbp['kicker_player_name'].notna()].groupby('kicker_player_name').agg(fg_attempts=('field_goal_attempt','sum')).reset_index()
if not kickers.empty:
    kickers['fg_att_per_game'] = kickers['fg_attempts']/17.0
    topk = kickers.sort_values('fg_att_per_game', ascending=False).head(10)
    for _,row in topk.iterrows():
        kname=row['kicker_player_name'] if 'kicker_player_name' in row else row['kicker_player_name']
        lam = float(row['fg_att_per_game'])
        for line in [0.5,1.5]:
            k=int(np.ceil(line))
            prob = 1 - sum([np.exp(-lam)*lam**i/np.math.factorial(i) for i in range(0,k)])
            candidates.append({'player':kname,'team':None,'prop':'KICKER_FG_ATT','line':line,'proj_lambda':lam,'proj_prob_ge':prob})

# Save CSV
outf=f'outputs/vikings_chargers_props_model_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
df=pd.DataFrame(candidates)
df.to_csv(outf, index=False)
print('Wrote', outf)
PY
