#!/usr/bin/env python3
import pandas as pd
import numpy as np
import json, glob, os, re
from math import exp, factorial
from datetime import datetime
os.makedirs('outputs', exist_ok=True)

# load selected events for 10/26-10/27
sel_files = glob.glob('data/odds_live/selected_events_*.json')
if not sel_files:
    raise SystemExit('No selected events file found')
sel = json.load(open(sel_files[-1]))
# load pbp
pbp = pd.read_csv('nfl_data_2025_csv/pbp_2025.csv', low_memory=False)

# helper stats
def pass_stats(pbp):
    df = pbp[pbp['pass_attempt']==1].groupby('passer_player_name').agg(pass_yards=('passing_yards','sum'), pass_att=('pass_attempt','sum'), interceptions=('interception','sum'), games=('game_id','nunique')).reset_index()
    df['pass_yards_per_game']=df['pass_yards']/df['games'].replace(0,np.nan)
    df['pass_att_per_game']=df['pass_att']/df['games'].replace(0,np.nan)
    df['int_rate']=df['interceptions']/df['pass_att'].replace(0,np.nan)
    return df

def rec_stats(pbp):
    df = pbp[pbp['complete_pass']==1].groupby('receiver_player_name').agg(rec_yards=('receiving_yards','sum'), catches=('complete_pass','sum'), games=('game_id','nunique')).reset_index()
    df['rec_yards_per_game']=df['rec_yards']/df['games'].replace(0,np.nan)
    df['catches_per_game']=df['catches']/df['games'].replace(0,np.nan)
    return df

def rush_stats(pbp):
    df = pbp[pbp['rush_attempt']==1].groupby('rusher_player_name').agg(rush_yards=('rushing_yards','sum'), rush_att=('rush_attempt','sum'), games=('game_id','nunique')).reset_index()
    df['rush_yards_per_game']=df['rush_yards']/df['games'].replace(0,np.nan)
    df['rush_att_per_game']=df['rush_att']/df['games'].replace(0,np.nan)
    return df

pass_df = pass_stats(pbp)
rec_df = rec_stats(pbp)
rush_df = rush_stats(pbp)

# load event markets
market_files = {os.path.basename(f).split('_markets.json')[0]:f for f in glob.glob('data/odds_live/event_markets_latest/*_markets.json')}

matches=[]
candidates=[]

# name normalize
def norm(s):
    if pd.isna(s): return ''
    return re.sub('[^A-Za-z0-9 ]','',str(s)).lower()

for ev in sel:
    eid = ev.get('id')
    home = ev.get('home') or ev.get('home_team') or ev.get('homeTeam')
    away = ev.get('away') or ev.get('away_team') or ev.get('awayTeam')
    date = ev.get('commence_time','').split('T')[0]
    game_label = f"{away or 'TBD'} @ {home or 'TBD'}"
    # choose top players for teams from stats
    # QBs: top passers by pass_att_per_game within games involving team
    games_for_team = pbp[(pbp['home_team']==home)|(pbp['away_team']==home)|(pbp['home_team']==away)|(pbp['away_team']==away)]['game_id'].unique()
    # players appearing in these games
    p_pass = pbp[pbp['game_id'].isin(games_for_team) & (pbp['pass_attempt']==1)].groupby('passer_player_name').agg(pass_att=('pass_attempt','sum'), pass_yards=('passing_yards','sum')).reset_index().sort_values('pass_att',ascending=False)
    p_rec = pbp[pbp['game_id'].isin(games_for_team) & (pbp['complete_pass']==1)].groupby('receiver_player_name').agg(rec_yards=('receiving_yards','sum'), catches=('complete_pass','sum')).reset_index().sort_values('rec_yards',ascending=False)
    p_rush = pbp[pbp['game_id'].isin(games_for_team) & (pbp['rush_attempt']==1)].groupby('rusher_player_name').agg(rush_att=('rush_attempt','sum'), rush_yards=('rushing_yards','sum')).reset_index().sort_values('rush_att',ascending=False)
    # take top N
    top_qbs = p_pass['passer_player_name'].dropna().unique()[:2]
    top_recs = p_rec['receiver_player_name'].dropna().unique()[:6]
    top_rush = p_rush['rusher_player_name'].dropna().unique()[:4]

    # helper to guess which team a player belongs to for this event
    def guess_team_for_player(player_name, home_team, away_team):
        # look in pbp for occurrences of player as passer/rusher/receiver and see which team is posteam most often
        sub = pbp[(pbp['passer_player_name']==player_name) | (pbp['rusher_player_name']==player_name) | (pbp['receiver_player_name']==player_name)]
        if sub.empty:
            return home_team if home_team else (away_team if away_team else '')
        # count posteam occurrences
        counts = sub['posteam'].value_counts()
        if not counts.empty:
            top = counts.index[0]
            if top == home_team:
                return home_team
            if top == away_team:
                return away_team
            # if top is neither, but one of home/away is in counts, prefer that
            if home_team in counts.index:
                return home_team
            if away_team in counts.index:
                return away_team
            return top
        return home_team if home_team else (away_team if away_team else '')

    # make QB pass yards props
    for qb in top_qbs:
        if qb=='': continue
        row = pass_df[pass_df['passer_player_name']==qb]
        if row.empty: continue
        mean = float(row['pass_yards_per_game'].iloc[0])
        sd = max(10.0, 0.35*mean)
        team_guess = guess_team_for_player(qb, home, away)
        for line in [200.5,225.5,250.5]:
            z = (line-mean)/(sd*np.sqrt(2))
            prob = 1 - 0.5*(1+np.math.erf(z))
            candidates.append({'event_id':eid,'date':date,'game':game_label,'player':qb,'team':team_guess,'prop':'QB_PASS_YDS','line':line,'model_prob':prob,'model_mean':mean})
    # QB INTs
    for qb in top_qbs:
        row = pass_df[pass_df['passer_player_name']==qb]
        if row.empty: continue
        lam = float(row['pass_att_per_game'].iloc[0] * (row['int_rate'].iloc[0] if not np.isnan(row['int_rate'].iloc[0]) else 0.01))
        team_guess = guess_team_for_player(qb, home, away)
        for line in [0.5,1.5]:
            k=int(np.ceil(line))
            prob = 1 - sum([(lam**i)*exp(-lam)/factorial(i) for i in range(0,k)])
            candidates.append({'event_id':eid,'date':date,'game':game_label,'player':qb,'team':team_guess,'prop':'QB_INT','line':line,'model_prob':prob,'model_lambda':lam})
    # receivers yards
    for r in top_recs:
        if r=='': continue
        row = rec_df[rec_df['receiver_player_name']==r]
        if row.empty: continue
        mean = float(row['rec_yards_per_game'].iloc[0])
        sd = max(5.0, 0.6*mean)
        team_guess = guess_team_for_player(r, home, away)
        for line in [40.5,60.5,80.5]:
            z=(line-mean)/(sd*np.sqrt(2))
            prob=1-0.5*(1+np.math.erf(z))
            candidates.append({'event_id':eid,'date':date,'game':game_label,'player':r,'team':team_guess,'prop':'REC_YDS','line':line,'model_prob':prob,'model_mean':mean})
    # rushers
    for r in top_rush:
        if r=='': continue
        row = rush_df[rush_df['rusher_player_name']==r]
        if row.empty: continue
        mean = float(row['rush_yards_per_game'].iloc[0])
        sd = max(5.0, 0.6*mean)
        team_guess = guess_team_for_player(r, home, away)
        for line in [30.5,50.5,70.5]:
            z=(line-mean)/(sd*np.sqrt(2))
            prob=1-0.5*(1+np.math.erf(z))
            candidates.append({'event_id':eid,'date':date,'game':game_label,'player':r,'team':team_guess,'prop':'RUSH_YDS','line':line,'model_prob':prob,'model_mean':mean})

    # attempt to find market prices in event markets file
    markets_file = market_files.get(eid)
    market_map = {}
    if markets_file:
        j = json.load(open(markets_file))
        for b in j.get('bookmakers',[]):
            bk = b.get('key')
            for m in b.get('markets',[]):
                mkey = m.get('key')
                outcomes = m.get('outcomes') or []
                # store if outcomes have prices
                if outcomes:
                    market_map.setdefault(mkey,[])
                    for o in outcomes:
                        market_map[mkey].append({'bookmaker':bk,'name':o.get('name'),'price':o.get('price'),'point':o.get('point')})
    # match candidates to market_map where possible
    for c in candidates:
        if c['event_id']!=eid: continue
        player_last = norm(c['player']).split()[-1] if c['player'] else ''
        matched=None
        for mkey, outs in market_map.items():
            if not mkey.startswith('player'): continue
            for o in outs:
                name = norm(o['name'])
                if player_last and player_last in name:
                    # try number match
                    if c['prop']=='QB_INT' and 'interception' in mkey:
                        matched = (mkey,o)
                    elif c['prop']=='KICKER_FG_ATT' and 'field_goal' in mkey:
                        matched = (mkey,o)
                    elif c['prop']=='REC_YDS' and ('reception' in mkey or 'reception_yds' in mkey or 'reception_yds' in mkey):
                        matched = (mkey,o)
                    elif c['prop']=='RUSH_YDS' and 'rush' in mkey:
                        matched = (mkey,o)
                    elif c['prop']=='QB_PASS_YDS' and 'pass_yds' in mkey:
                        matched = (mkey,o)
                    if matched:
                        break
            if matched: break
        if matched:
            mkey,o = matched
            market_prob = None
            if o.get('price') is not None:
                a=o.get('price')
                try:
                    a=int(a)
                    if a>0:
                        implied = 100.0/(a+100.0)
                    else:
                        implied = -a/(-a+100.0)
                    market_prob = implied
                except Exception:
                    market_prob=None
            c.update({'market_key':mkey,'bookmaker':o.get('bookmaker'),'market_name':o.get('name'),'market_price':o.get('price'),'market_implied_prob':market_prob})

# write candidates CSV
outf = f'outputs/props_candidates_20251026_20251027_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
import csv
keys=['event_id','date','game','player','team','prop','line','model_prob','model_mean','market_key','bookmaker','market_name','market_price','market_implied_prob']
with open(outf,'w',newline='') as f:
    w=csv.DictWriter(f,keys)
    w.writeheader()
    for c in candidates:
        w.writerow({k:c.get(k,None) for k in keys})
print('Wrote',outf)

