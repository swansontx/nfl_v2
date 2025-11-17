#!/usr/bin/env python3
"""
Targeted TD models for Cowboys @ Raiders (event from cache).
- Aggregates DraftKings markets across all cached snapshots for the event
- Extracts player_anytime_td and player_1st_td
- Maps player -> team using player_data summary.csv and HTML as fallback
- Computes anytime, 2+ and first-TD probabilities using simple priors
- Writes outputs/cowboys_raiders_td_models_v3.json and _edges_v3.md
"""
import json, glob, re, math, csv
from pathlib import Path
from collections import defaultdict

CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
PLAYER_DATA_DIR = CACHE_DIR / 'player_data'
OUT_DIR = Path('outputs')
OUT_DIR.mkdir(exist_ok=True)
EVENT_ID = '80d04ba917883a6438580ebae9fb0f22'

POSITION_PRIORS = {'RB':0.22, 'WR':0.18, 'TE':0.12, 'QB':0.03, 'DST':0.02, 'K':0.01, 'UNK':0.03}


def american_to_imp_prob(a):
    try:
        a=int(a)
    except Exception:
        return None
    if a>0:
        dec = 1 + a/100.0
    else:
        dec = 1 + 100.0/abs(a)
    return 1.0/dec


def slugify(name):
    if not name: return 'unknown'
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+","_", s).strip('_')
    return s


def find_event_snapshots(event_id):
    files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/**/*.json', recursive=True)
    matches=[]
    for f in files:
        try:
            j=json.load(open(f))
        except Exception:
            continue
        if isinstance(j, dict) and j.get('id')==event_id:
            matches.append((f,j))
        elif isinstance(j, list):
            for ev in j:
                if isinstance(ev, dict) and ev.get('id')==event_id:
                    matches.append((f,j))
                    break
    return matches


def extract_dk_markets_from_snapshot(ev):
    markets=[]
    if isinstance(ev, dict) and 'bookmakers' in ev:
        for book in ev['bookmakers']:
            if book.get('key','').lower()!='draftkings':
                continue
            for m in book.get('markets',[]):
                markets.append(m)
    elif isinstance(ev, list):
        for e in ev:
            if not isinstance(e, dict):
                continue
            for book in e.get('bookmakers',[]):
                if book.get('key','').lower()!='draftkings':
                    continue
                for m in book.get('markets',[]):
                    markets.append(m)
    return markets


def load_player_summary():
    summary = {}
    scsv = PLAYER_DATA_DIR / 'summary.csv'
    if scsv.exists():
        try:
            with scsv.open() as fh:
                rdr = csv.DictReader(fh)
                for r in rdr:
                    # expected columns: name, team, position, slug
                    name = r.get('name') or r.get('player')
                    if not name: continue
                    summary[name.lower()] = {'team': r.get('team') or r.get('team_name'), 'pos': r.get('position')}
        except Exception:
            pass
    return summary


def map_player_to_team(name, home, away, summary):
    if not name: return None
    key = name.lower()
    if key in summary and summary[key].get('team'):
        return summary[key]['team']
    # try match by substring
    if home and home.lower() in key:
        return home
    if away and away.lower() in key:
        return away
    # fallback: search player_data HTML for team mentions
    slug = slugify(name)
    files = glob.glob(str(PLAYER_DATA_DIR / f"**/*{slug}*.html"), recursive=True)
    for f in files:
        try:
            t=open(f,'r',encoding='utf-8',errors='ignore').read().lower()
        except Exception:
            continue
        if home and home.lower().split()[0] in t:
            return home
        if away and away.lower().split()[0] in t:
            return away
    return None


def compute_team_expected_tds(all_markets, home, away):
    # aggregate totals/spreads across markets (prefer latest non-null)
    total=None
    spread=None
    fav=None
    for m in all_markets:
        key=m.get('key')
        if key=='totals':
            outs=m.get('outcomes',[])
            if outs and outs[0].get('point') is not None:
                total=outs[0].get('point')
        if key=='spreads':
            for o in m.get('outcomes',[]):
                pt=o.get('point')
                if isinstance(pt,(int,float)):
                    if pt<0:
                        fav=o.get('name')
                        spread=abs(pt)
                        break
    if total is None:
        total=46.0
    if spread is None:
        spread=0.0
    fav_pts=total/2+spread/2
    dog_pts=total/2-spread/2
    if fav and fav.lower()==home.lower():
        return {home: fav_pts, away: dog_pts}
    if fav and fav.lower()==away.lower():
        return {away: fav_pts, home: dog_pts}
    return {home: total/2, away: total/2}


def main():
    snaps = find_event_snapshots(EVENT_ID)
    if not snaps:
        print('no snapshots for event', EVENT_ID); return
    print('found', len(snaps), 'matching snapshots; aggregating markets')
    all_markets = []
    home=None
    away=None
    for f, ev in snaps:
        # find home/away if present
        if isinstance(ev, dict):
            home = home or ev.get('home_team') or ev.get('home')
            away = away or ev.get('away_team') or ev.get('away')
        elif isinstance(ev, list):
            for e in ev:
                if isinstance(e, dict) and e.get('id')==EVENT_ID:
                    home = home or e.get('home_team') or e.get('home')
                    away = away or e.get('away_team') or e.get('away')
        mk = extract_dk_markets_from_snapshot(ev)
        all_markets.extend(mk)
    if not home or not away:
        print('could not determine home/away from snapshots')
    team_points = compute_team_expected_tds(all_markets, home, away)
    team_tds = {t: team_points[t]/7.0 for t in team_points}

    # load player summary
    summary = load_player_summary()

    # collect players from all markets (dedupe by participant)
    anytime_map = {}
    first_map = {}
    for m in all_markets:
        key = m.get('key')
        if key=='player_anytime_td':
            for o in m.get('outcomes',[]):
                participant = (o.get('description') or o.get('name') or '').strip()
                price = o.get('price')
                slug = slugify(participant)
                anytime_map[slug] = {'participant': participant, 'price': price}
        if key=='player_1st_td':
            for o in m.get('outcomes',[]):
                participant = (o.get('description') or o.get('name') or '').strip()
                price = o.get('price')
                slug = slugify(participant)
                first_map[slug] = {'participant': participant, 'price': price}

    # assign teams and implied probs
    by_team = defaultdict(list)
    for slug,p in anytime_map.items():
        team = map_player_to_team(p['participant'], home, away, summary) or 'unknown'
        imp = american_to_imp_prob(p['price']) if p.get('price') is not None else None
        p.update({'slug':slug,'team':team,'imp_prob':imp})
        by_team[team].append(p)

    modeled_any=[]
    for team, pls in by_team.items():
        team_td_rate = team_tds.get(team, sum(team_tds.values())/2.0)
        vals=[(p['imp_prob'] or 0.001) for p in pls]
        ssum=sum(vals)
        for p,v in zip(pls,vals):
            raw = v/ssum if ssum>0 else 1.0/len(pls)
            pos='UNK'
            pos_prior=POSITION_PRIORS.get(pos,0.03)
            final_share=0.7*raw+0.3*pos_prior
            p['final_share']=final_share
        total_share=sum([p['final_share'] for p in pls])
        for p in pls:
            p['final_share']=p['final_share']/total_share if total_share>0 else 1.0/len(pls)
            lam = team_td_rate * p['final_share']
            p_any = 1-math.exp(-lam)
            p_2plus = 1-math.exp(-lam)*(1+lam)
            modeled_any.append({'key':f"player_{p['slug']}_anytime_td", 'participant':p['participant'], 'team':p['team'], 'price':p['price'], 'imp_prob':p['imp_prob'], 'final_share':p['final_share'], 'lambda':lam, 'p_any':p_any, 'p_2plus':p_2plus})

    # first TD modeling
    home_pts = team_points.get(home,0.0)
    away_pts = team_points.get(away,0.0)
    p_home_first = home_pts/(home_pts+away_pts) if (home_pts+away_pts)>0 else 0.5
    p_away_first = 1-p_home_first
    modeled_first=[]
    for slug,p in anytime_map.items():
        team = map_player_to_team(p['participant'], home, away, summary) or 'unknown'
        # find final_share for this player among its team
        team_list = by_team.get(team, [])
        if not team_list:
            normalized = 0.0
        else:
            # find player in team_list by slug
            found = None
            for q in team_list:
                if q['slug']==slug:
                    found=q; break
            normalized = found['final_share'] if found else 0.0
        team_first_prob = p_home_first if team==home else p_away_first
        p_first = team_first_prob * normalized
        imp = p.get('price') and american_to_imp_prob(p['price']) or None
        modeled_first.append({'key':f"player_{slug}_1st_td", 'participant':p['participant'], 'team':team, 'price':p['price'], 'imp_prob':imp, 'p_first':p_first})

    out={'event_id':EVENT_ID,'home':home,'away':away,'team_points':team_points,'team_tds':team_tds,'anytime':modeled_any,'first':modeled_first}
    outp=OUT_DIR/'cowboys_raiders_td_models_v3.json'
    outp.write_text(json.dumps(out,indent=2))

    # write edges md
    md=[f"# Cowboys @ Raiders TD edges (v3)\n","\n"]
    md.append('## Anytime TD\n')
    rows=[]
    for r in modeled_any:
        imp=r['imp_prob'] or 0.0
        edge=r['p_any']-imp
        rows.append((edge,r))
    rows.sort(key=lambda x:-x[0])
    for edge,r in rows:
        md.append(f"- {r['participant']} ({r['team']}) price={r['price']} implied={r['imp_prob']:.3f} modeled={r['p_any']:.3f} edge={edge:.3f}\n")
    md.append('\n## First TD\n')
    rowsf=[]
    for r in modeled_first:
        imp=r.get('imp_prob') or 0.0
        edge=r['p_first']-imp
        rowsf.append((edge,r))
    rowsf.sort(key=lambda x:-x[0])
    for edge,r in rowsf:
        md.append(f"- {r['participant']} ({r['team']}) price={r['price']} implied={r.get('imp_prob'):.3f} modeled_first={r['p_first']:.4f} edge={edge:.4f}\n")

    mdp=OUT_DIR/'cowboys_raiders_td_edges_v3.md'
    mdp.write_text('\n'.join(md))
    print('Wrote', outp, mdp)

if __name__=='__main__':
    main()
