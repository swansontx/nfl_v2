#!/usr/bin/env python3
"""
Run v5 modeling: enrich player registry with model_output_pfr and nfl_data_py features (if available),
then compute TD models (anytime, 2+, first) for Cowboys @ Raiders event.

Improved mapping: parse DraftKings snapshot 'description' fields for player names,
map to player_registry entries using normalized exact match and fuzzy matching.
Also normalize team names between snapshots and registry.
"""
import json, math, os, re, unicodedata
from pathlib import Path
from collections import defaultdict
import difflib

ROOT = Path('.').resolve()
PLAYER_REG = ROOT / 'models' / 'player_registry.json'
MO_PFR = Path.home() / '.cache' / 'goose' / 'computer_controller' / 'model_output_pfr.json'
OUT_REG = ROOT / 'models' / 'player_registry_enriched.json'
OUT_V5 = ROOT / 'outputs' / 'cowboys_raiders_td_models_v5.json'
OUT_EDGES = ROOT / 'outputs' / 'cowboys_raiders_td_edges_v5.md'
UNMATCHED_CSV = ROOT / 'outputs' / 'unmatched_dk_players_80d04ba9.csv'
EVENT_ID = '80d04ba917883a6438580ebae9fb0f22'
SNAPSHOT = Path.home() / '.cache' / 'goose' / 'computer_controller' / f'web_event_{EVENT_ID}_fetch.json'

# position priors
POSITION_PRIORS = {'RB':0.22, 'WR':0.18, 'TE':0.12, 'QB':0.03, 'DST':0.02, 'K':0.01, 'UNK':0.03}

# helpers
def norm(s):
    if not s:
        return ''
    s = str(s)
    s = s.strip().lower()
    # remove punctuation
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9\s]", '', s)
    s = re.sub(r"\s+", ' ', s)
    return s

# load registry
if not PLAYER_REG.exists():
    print('player registry missing:', PLAYER_REG)
    registry = {}
else:
    registry = json.loads(PLAYER_REG.read_text())

# build name -> slug lookup from registry
name_to_slug = {}
slug_to_names = defaultdict(list)
for slug, rec in registry.items():
    names = []
    if rec.get('name'):
        names.append(rec['name'])
    # also include slug split as possible variant
    names.append(slug.replace('_',' '))
    # include last name and first last
    if rec.get('name'):
        parts = rec['name'].split()
        if len(parts) >= 2:
            names.append(parts[-1])
            names.append(' '.join(parts[:2]))
    for n in names:
        nn = norm(n)
        if nn:
            name_to_slug[nn] = slug
            slug_to_names[slug].append(nn)

# attach pfr features if available
if MO_PFR.exists():
    mo = json.loads(MO_PFR.read_text())
    # find summary mapping heuristically
    pfr_summary = None
    for k in ('summary','players','player_summary'):
        if k in mo and isinstance(mo[k], dict):
            pfr_summary = mo[k]
            break
    if not pfr_summary:
        pfr_summary = {}
    # attach if pfr_id matches
    for slug, rec in registry.items():
        pid = rec.get('pfr_id')
        if pid and pid in pfr_summary:
            rec['pfr_features'] = pfr_summary[pid]
else:
    print('model_output_pfr.json not found; skipping PFR feature attach')

# try to import nfl_data_py for play-by-play features and rosters
pbp = None
rosters = None
try:
    import nfl_data_py as nd
    print('nfl_data_py available — importing pbp for 2023-2025 (this may take time)')
    try:
        pbp = nd.import_pbp_data([2023,2024,2025])
    except Exception:
        try:
            pbp = nd.import_pbp([2025])
        except Exception as e:
            print('nfl_data_py import error (pbp):', e)
            pbp = None
    try:
        rosters = nd.import_rosters([2025])
    except Exception as e:
        print('nfl_data_py import error (rosters):', e)
        rosters = None
except Exception as e:
    print('nfl_data_py not available:', e)
    pbp = None
    rosters = None

# compute team points per game if pbp available
team_points = {}
if pbp is not None:
    try:
        import pandas as pd
        df = pbp
        # fallback: don't attempt heavy computation here; prefer using market totals if present later
        team_points = {}
    except Exception as e:
        print('Error processing pbp with pandas', e)
        team_points = {}

# load snapshot if present
snapshot = None
if SNAPSHOT.exists():
    try:
        snapshot = json.loads(SNAPSHOT.read_text())
    except Exception as e:
        print('Failed to read snapshot', SNAPSHOT, e)
else:
    print('Snapshot not found at', SNAPSHOT)

# attempt to derive totals/spread from cached per-event snapshots (as before)
cache_dir = Path.home() / '.cache' / 'goose' / 'computer_controller'
files = list(cache_dir.glob('web_*.json')) + list(Path('outputs').glob('*.json'))
latest_totals = None
latest_spread = None
latest_fav = None
for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
    try:
        j = json.loads(open(f).read())
    except Exception:
        continue
    evs = [j] if isinstance(j, dict) else (j if isinstance(j, list) else [])
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        if ev.get('id')!=EVENT_ID:
            continue
        for bk in ev.get('bookmakers',[]):
            if bk.get('key','').lower()!='draftkings':
                continue
            for m in bk.get('markets',[]):
                if m.get('key')=='totals' and not latest_totals:
                    outs = m.get('outcomes',[])
                    if outs and outs[0].get('point') is not None:
                        latest_totals = outs[0].get('point')
                if m.get('key')=='spreads' and not latest_spread:
                    for o in m.get('outcomes',[]):
                        pt=o.get('point')
                        if isinstance(pt,(int,float)) and pt<0:
                            latest_spread = abs(pt)
                            latest_fav = o.get('name')
                            break

# find home/away from snapshot or cached files
home=None; away=None
for f in files:
    try:
        j = json.loads(open(f).read())
    except Exception:
        continue
    evs = [j] if isinstance(j, dict) else (j if isinstance(j, list) else [])
    for ev in evs:
        if isinstance(ev, dict) and ev.get('id')==EVENT_ID:
            home = ev.get('home_team') or ev.get('home')
            away = ev.get('away_team') or ev.get('away')
            break
    if home:
        break

# set team_points using totals/spread if present
if latest_totals is not None:
    if latest_spread is None:
        latest_spread = 0.0
    fav_pts = latest_totals/2.0 + latest_spread/2.0
    dog_pts = latest_totals/2.0 - latest_spread/2.0
    if latest_fav and home and latest_fav.lower()==home.lower():
        team_points = {home: fav_pts, away: dog_pts}
    elif latest_fav and away and latest_fav.lower()==away.lower():
        team_points = {away: fav_pts, home: dog_pts}
    else:
        team_points = {home: latest_totals/2.0, away: latest_totals/2.0}
else:
    if home and away:
        team_points = {home:24.0, away:24.0}

team_tds = {t: team_points[t]/7.0 for t in team_points}

# helper to normalize team matching between registry and snapshot team names
def match_team(reg_team, snapshot_team_keys):
    """Return snapshot key that matches reg_team if any, else None"""
    if not reg_team or not snapshot_team_keys:
        return None
    r = norm(reg_team)
    for k in snapshot_team_keys:
        if not k:
            continue
        kk = norm(k)
        # direct inclusion
        if r in kk or kk in r:
            return k
        # token overlap
        rset=set(r.split())
        kset=set(kk.split())
        if len(rset & kset)>=1:
            return k
    return None

# parse DraftKings snapshot to extract player descriptions per market
dk_players = set()
dk_markets = {}  # market_key -> list of outcome dicts
if snapshot:
    evs = snapshot if isinstance(snapshot, list) else [snapshot]
    for ev in evs:
        if ev.get('id')!=EVENT_ID:
            continue
        for bk in ev.get('bookmakers',[]):
            if bk.get('key','').lower()!='draftkings':
                continue
            for m in bk.get('markets',[]):
                mk=m.get('key')
                if not mk:
                    continue
                outs = m.get('outcomes',[])
                # normalize outcome objects to include 'player' when possible
                parsed = []
                for o in outs:
                    # candidate fields for player name: description, participant, label
                    player = o.get('description') or o.get('participant') or o.get('label') or o.get('name')
                    parsed.append({'raw':o, 'player':player, 'name':o.get('name'), 'point':o.get('point'), 'price':o.get('price')})
                    if player:
                        dk_players.add(player)
                dk_markets[mk]=parsed

print('Found', len(dk_players), 'unique player description strings in DK snapshot')

# attempt to map dk player description -> registry slug
mapped = {}
unmatched = []
for p in sorted(dk_players):
    pn = norm(p)
    if pn in name_to_slug:
        mapped[p]=name_to_slug[pn]
        continue
    # try fuzzy match against registry names keys
    # search among name_to_slug keys
    candidates = difflib.get_close_matches(pn, list(name_to_slug.keys()), n=3, cutoff=0.8)
    if candidates:
        mapped[p]=name_to_slug[candidates[0]]
        continue
    # try fuzzy match against registry 'name' fields directly
    registry_names = [norm(rec.get('name')) for rec in registry.values() if rec.get('name')]
    candidates2 = difflib.get_close_matches(pn, registry_names, n=3, cutoff=0.7)
    if candidates2:
        # find slug for this name
        candname = candidates2[0]
        slug = None
        for s, rec in registry.items():
            if norm(rec.get('name'))==candname:
                slug=s
                break
        if slug:
            mapped[p]=slug
            continue
    # try roster lookup (nfl_data_py rosters) if available
    if rosters is not None:
        try:
            # rosters is a dataframe-like; search by display name
            import pandas as pd
            if isinstance(rosters, pd.DataFrame):
                # create a mapping of normalized roster names
                roster_names = {norm(r['player_name']): r for _,r in rosters.iterrows()}
                if pn in roster_names:
                    # best-effort: attach by player_name
                    r = roster_names[pn]
                    # assemble a slug-like key
                    slug_guess = norm(r['player_name']).replace(' ','_')
                    mapped[p]=slug_guess
                    continue
        except Exception:
            pass
    unmatched.append(p)

print('Mapped', len(mapped), 'players; Unmatched:', len(unmatched))
# write unmatched report
if unmatched:
    try:
        with open(UNMATCHED_CSV,'w') as fh:
            fh.write('raw_description\n')
            for p in unmatched:
                fh.write(p.replace('\n',' ')+"\n")
        print('Wrote unmatched report to', UNMATCHED_CSV)
    except Exception as e:
        print('Failed to write unmatched report', e)

# attach mapping info into registry entries where possible
for desc, slug in mapped.items():
    if slug in registry:
        rec = registry[slug]
        rec.setdefault('dk_markets', {})
        # populate markets where this player appears
        for mk, outs in dk_markets.items():
            # find outcomes referencing this desc
            founds = [o for o in outs if o.get('player')==desc]
            if founds:
                rec['dk_markets'].setdefault(mk, []).extend(founds)
    else:
        # create a minimal registry entry for unmatched slug guesses
        registry.setdefault(slug, {'name': desc, 'slug': slug, 'team': None, 'pos': None, 'dk_markets': {}})

# set team_points into registry entries (team matching may need normalization)
snapshot_team_keys = list(team_points.keys())
for slug, rec in registry.items():
    rec['team_points'] = None
    rec['team_tds'] = None
    reg_team = rec.get('team')
    matched_key = match_team(reg_team, snapshot_team_keys)
    if matched_key:
        rec['team_points'] = team_points.get(matched_key)
        rec['team_tds'] = (team_points.get(matched_key)/7.0) if team_points.get(matched_key) else None

# write enriched registry
try:
    OUT_REG.write_text(json.dumps(registry, indent=2))
    print('Wrote enriched registry to', OUT_REG)
except Exception as e:
    print('Failed to write enriched registry', e)

# compute TD models for players in registry that are in the event teams and/or have dk_markets
modeled = []
for slug, rec in registry.items():
    # only model players that have dk_markets entries (i.e., present in DK snapshot) and have team_points
    if not rec.get('dk_markets'):
        continue
    team = rec.get('team')
    # try to get team_points via direct match or fallback to team_tds in rec
    team_td_rate = None
    if rec.get('team_tds'):
        team_td_rate = rec.get('team_tds')
    else:
        # attempt to infer from team_points map
        if team in team_tds:
            team_td_rate = team_tds.get(team)
        else:
            # try to find matching team key
            mk = match_team(team, list(team_tds.keys()))
            if mk:
                team_td_rate = team_tds.get(mk)
    if not team_td_rate:
        # fallback to average
        if team_tds:
            team_td_rate = sum(team_tds.values())/len(team_tds)
        else:
            team_td_rate = 3.5
    # derive historical_td_share from pfr features if available
    hist_share = None
    if rec.get('pfr_features'):
        pf = rec['pfr_features']
        if isinstance(pf, dict):
            if 'td_share' in pf:
                hist_share = pf['td_share']
            elif 'tds' in pf and 'games' in pf and pf.get('games'):
                hist_share = (pf.get('tds')/pf.get('games'))/team_td_rate if team_td_rate>0 else None
    if hist_share is None:
        pos = (rec.get('pos') or 'UNK')
        hist_share = POSITION_PRIORS.get(pos, 0.03)
    redzone_share = None
    if rec.get('pfr_features') and isinstance(rec['pfr_features'], dict):
        if 'redzone_share' in rec['pfr_features']:
            redzone_share = rec['pfr_features']['redzone_share']
    if redzone_share is None:
        redzone_share = hist_share
    player_share = 0.6*hist_share + 0.4*redzone_share
    lam = team_td_rate * player_share
    p_any = 1 - math.exp(-lam)
    p_2plus = 1 - math.exp(-lam)*(1+lam)
    modeled.append({'slug':slug,'name':rec.get('name'),'team':rec.get('team'),'pos':rec.get('pos'),'hist_share':hist_share,'redzone_share':redzone_share,'player_share':player_share,'lambda':lam,'p_any':p_any,'p_2plus':p_2plus})

# write outputs
try:
    OUT_V5.write_text(json.dumps({'event':EVENT_ID,'modeled':modeled,'team_points':team_points,'team_tds':team_tds}, indent=2))
    print('Wrote v5 models to', OUT_V5)
except Exception as e:
    print('Failed to write v5 models', e)

md=['# Cowboys @ Raiders TD models v5 (provisional)\n','\n']
for r in sorted(modeled, key=lambda x:-x['p_any'])[:200]:
    md.append(f"- {r['name']} ({r.get('team')}) pos={r.get('pos')} modeled_any={r['p_any']:.3f} modeled_2+={r['p_2plus']:.3f} lambda={r['lambda']:.4f}\n")
try:
    OUT_EDGES.write_text('\n'.join(md))
    print('Wrote edges md to', OUT_EDGES)
except Exception as e:
    print('Failed to write edges md', e)

print('Modeling complete. Modeled players count:', len(modeled))
if unmatched:
    print('Unmatched DK player descriptions written to', UNMATCHED_CSV)
