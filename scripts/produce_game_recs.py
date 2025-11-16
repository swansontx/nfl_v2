#!/usr/bin/env python3
import pandas as pd, numpy as np, json, os, re
from datetime import datetime
os.makedirs('outputs', exist_ok=True)

sel = json.load(open('data/odds_live/selected_events_20251025_0742.json'))
pbp = pd.read_csv('nfl_data_2025_csv/pbp_2025.csv', low_memory=False)

# helper stats
pass_df = pbp[pbp['pass_attempt']==1].groupby('passer_player_name').agg(pass_yards=('passing_yards','sum'), pass_att=('pass_attempt','sum'), interceptions=('interception','sum'), games=('game_id','nunique')).reset_index()
pass_df['pass_yards_per_game']=pass_df['pass_yards']/pass_df['games'].replace(0,np.nan)
pass_df['pass_att_per_game']=pass_df['pass_att']/pass_df['games'].replace(0,np.nan)
pass_df['int_rate']=pass_df['interceptions']/pass_df['pass_att'].replace(0,np.nan)

rec_df = pbp[pbp['complete_pass']==1].groupby('receiver_player_name').agg(rec_yards=('receiving_yards','sum'), catches=('complete_pass','sum'), games=('game_id','nunique')).reset_index()
rec_df['rec_yards_per_game']=rec_df['rec_yards']/rec_df['games'].replace(0,np.nan)
rec_df['catches_per_game']=rec_df['catches']/rec_df['games'].replace(0,np.nan)

rush_df = pbp[pbp['rush_attempt']==1].groupby('rusher_player_name').agg(rush_yards=('rushing_yards','sum'), rush_att=('rush_attempt','sum'), games=('game_id','nunique')).reset_index()
rush_df['rush_yards_per_game']=rush_df['rush_yards']/rush_df['games'].replace(0,np.nan)
rush_df['rush_att_per_game']=rush_df['rush_att']/rush_df['games'].replace(0,np.nan)

reports=[]

for ev in sel:
    home = ev.get('home') or ev.get('home_team')
    away = ev.get('away') or ev.get('away_team')
    eid = ev.get('id')
    date = ev.get('commence_time','').split('T')[0]
    game = f"{away} @ {home}"
    # find games for this matchup in pbp
    games_ids = pbp[(pbp['home_team']==home) & (pbp['away_team']==away)]['game_id'].unique()
    # fallback: all games where either team present
    if len(games_ids)==0:
        games_ids = pbp[(pbp['home_team']==home)|(pbp['away_team']==home)|(pbp['home_team']==away)|(pbp['away_team']==away)]['game_id'].unique()
    # top players by season but restricted to those appearing in these games
    passers = pbp[pbp['game_id'].isin(games_ids) & (pbp['pass_attempt']==1)].groupby('passer_player_name').agg(pa=('pass_attempt','sum'), y=('passing_yards','sum')).reset_index().sort_values('pa',ascending=False)
    receivers = pbp[pbp['game_id'].isin(games_ids) & (pbp['complete_pass']==1)].groupby('receiver_player_name').agg(yds=('receiving_yards','sum'), catches=('complete_pass','sum')).reset_index().sort_values('yds',ascending=False)
    rushers = pbp[pbp['game_id'].isin(games_ids) & (pbp['rush_attempt']==1)].groupby('rusher_player_name').agg(att=('rush_attempt','sum'), yds=('rushing_yards','sum')).reset_index().sort_values('att',ascending=False)
    # pick top names
    top_qb = passers['passer_player_name'].dropna().unique()[:2].tolist()
    top_rec = receivers['receiver_player_name'].dropna().unique()[:6].tolist()
    top_rush = rushers['rusher_player_name'].dropna().unique()[:4].tolist()
    picks=[]
    # QB pass yards lines
    for qb in top_qb:
        if not qb: continue
        row = pass_df[pass_df['passer_player_name']==qb]
        if row.empty: continue
        mean = float(row['pass_yards_per_game'].iloc[0])
        sd = max(10.0, 0.35*mean)
        for line in [200.5,225.5,250.5]:
            z=(line-mean)/(sd*(2**0.5))
            prob = 1 - 0.5*(1+np.math.erf(z))
            picks.append({'game':game,'player':qb,'prop':'QB_PASS_YDS','line':line,'proj_mean':mean,'proj_prob':prob,'reason':'season rate adjusted'})
    # QB INTs
    for qb in top_qb:
        row = pass_df[pass_df['passer_player_name']==qb]
        if row.empty: continue
        lam = float((row['pass_att_per_game'].iloc[0] if row['pass_att_per_game'].iloc[0]>0 else 1.0) * (row['int_rate'].iloc[0] if not np.isnan(row['int_rate'].iloc[0]) else 0.01))
        for line in [0.5,1.5]:
            k=int(np.ceil(line))
            prob = 1 - sum([(lam**i)*np.exp(-lam)/np.math.factorial(i) for i in range(0,k)])
            picks.append({'game':game,'player':qb,'prop':'QB_INT','line':line,'proj_lambda':lam,'proj_prob':prob,'reason':'poisson int based on int_rate'})
    # receivers
    for r in top_rec[:6]:
        if not r: continue
        row = rec_df[rec_df['receiver_player_name']==r]
        if row.empty: continue
        mean=float(row['rec_yards_per_game'].iloc[0])
        sd=max(5.0,0.6*mean)
        for line in [40.5,60.5,80.5]:
            z=(line-mean)/(sd*(2**0.5))
            prob=1-0.5*(1+np.math.erf(z))
            picks.append({'game':game,'player':r,'prop':'REC_YDS','line':line,'proj_mean':mean,'proj_prob':prob,'reason':'season rec yds per game'})
    # rushers
    for r in top_rush[:4]:
        if not r: continue
        row = rush_df[rush_df['rusher_player_name']==r]
        if row.empty: continue
        mean=float(row['rush_yards_per_game'].iloc[0])
        sd=max(5.0,0.6*mean)
        for line in [30.5,50.5,70.5]:
            z=(line-mean)/(sd*(2**0.5))
            prob=1-0.5*(1+np.math.erf(z))
            picks.append({'game':game,'player':r,'prop':'RUSH_YDS','line':line,'proj_mean':mean,'proj_prob':prob,'reason':'season rush yds per game'})
    # compile top picks by proj_prob
    dfp=pd.DataFrame(picks)
    if dfp.empty:
        continue
    dfp_sorted=dfp.sort_values('proj_prob',ascending=False).head(8)
    reports.append({'event':game,'picks':dfp_sorted.to_dict('records')})

# write markdown summary
md=[]
md.append('# Model prop recommendations for 10/26-10/27')
md.append('Generated: '+datetime.now().isoformat())
for r in reports:
    md.append('\n## '+r['event'])
    for p in r['picks']:
        md.append(f"- {p['player']} — {p['prop']} {p['line']} | P(>=line)={p['proj_prob']:.2%} | {p['reason']}")

out='outputs/model_prop_recommendations_20251026_27.md'
open(out,'w').write('\n'.join(md))
print('Wrote', out)
PY
