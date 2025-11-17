#!/usr/bin/env python3
"""
Improved TD modeling (v4) for Cowboys @ Raiders using cached snapshots and player summary.
- Aggregate DraftKings totals/spreads across all snapshots and pick latest non-null
- Use summary.csv for player->team and position mapping
- Compute anytime, 2+, first TD probabilities with better team baselines
- Output models and edges v4
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


def slugify(name):
    if not name: return 'unknown'
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+","_", s).strip('_')
    return s


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


def load_summary_csv():
    summary = {}
    scsv = PLAYER_DATA_DIR / 'summary.csv'
    if scsv.exists():
        with scsv.open() as fh:
            rdr = csv.DictReader(fh)
            for r in rdr:
                name = r.get('name')
                if not name: continue
                summary[name.lower()] = {'team': r.get('team') or r.get('team_name'), 'pos': (r.get('position') or 'UNK')}
    return summary


def find_all_snapshots_for_event(event_id):
    files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/**/*.json', recursive=True)
    matches=[]
    for f in files:
        try:
            j=json.load(open(f))
        except Exception:
            continue
        if isinstance(j, dict) and j.get('id')==event_id:
            matches.append((Path(f).stat().st_mtime, f, j))
        elif isinstance(j, list):
            for ev in j:
                if isinstance(ev, dict) and ev.get('id')==event_id:
                    matches.append((Path(f).stat().st_mtime, f, ev))
                    break
    matches.sort(reverse=True)
    return matches


def aggregate_dk_markets(matches):
    all_markets=[]
    # track totals/spreads with timestamps to pick latest
    totals_list=[]
    spreads_list=[]
    for mtime,f, ev in matches:
        # for each snapshot, extract dk markets
        bks = ev.get('bookmakers', [])
        for bk in bks:
            if bk.get('key','').lower()!='draftkings':
                continue
            for m in bk.get('markets',[]):
                k = m.get('key')
                all_markets.append((mtime, k, m))
                if k=='totals':
                    outs=m.get('outcomes',[])
                    if outs and outs[0].get('point') is not None:
                        totals_list.append((mtime, outs[0].get('point')))
                if k=='spreads':
                    for o in m.get('outcomes',[]):
                        pt=o.get('point')
                        if isinstance(pt,(int,float)):
                            if pt<0:
                                fav=o.get('name')
                                spreads_list.append((mtime, abs(pt), fav))
                                break
    # pick latest totals/spread
    total=None; spread=None; fav=None
    if totals_list:
        totals_list.sort(reverse=True)
        total=totals_list[0][1]
    if spreads_list:
        spreads_list.sort(reverse=True)
        spread=f[1] if (f:=spreads_list[0]) else None
        fav=spreads_list[0][2]
    return all_markets, total, spread, fav


def build_player_lists(all_markets):
    anytime_map={}  # slug -> {participant, price}
    first_map={}
    for mtime,k,m in all_markets:
        if k=='player_anytime_td':
            for o in m.get('outcomes',[]):
                participant = (o.get('description') or o.get('name') or '').strip()
                price = o.get('price')
                slug = slugify(participant)
                anytime_map[slug] = {'participant': participant, 'price': price, 'mtime':mtime}
        if k=='player_1st_td':
            for o in m.get('outcomes',[]):
                participant = (o.get('description') or o.get('name') or '').strip()
                price = o.get('price')
                slug = slugify(participant)
                first_map[slug] = {'participant': participant, 'price': price, 'mtime':mtime}
    return anytime_map, first_map


def map_players_to_team_and_pos(anytime_map, summary, home, away):
    by_team=defaultdict(list)
    for slug,p in anytime_map.items():
        name = p['participant']
        info = summary.get(name.lower(), {})
        team = info.get('team') or None
        pos = (info.get('pos') or 'UNK').upper()
        if team is None:
            # check home/away match in name or fallback unknown
            if home and home.split()[0].lower() in name.lower():
                team=home
            elif away and away.split()[0].lower() in name.lower():
                team=away
            else:
                team='unknown'
        p.update({'team':team,'pos':pos,'slug':slug})
        by_team[team].append(p)
    return by_team


def compute_modeled_any_first(by_team, total, spread, home, away, fav):
    if total is None:
        total=48.0
    if spread is None:
        spread=0.0
    fav_pts = total/2 + spread/2
    dog_pts = total/2 - spread/2
    if fav and fav.lower()==home.lower():
        team_pts = {home: fav_pts, away: dog_pts}
    elif fav and fav.lower()==away.lower():
        team_pts = {away: fav_pts, home: dog_pts}
    else:
        team_pts = {home: total/2, away: total/2}
    team_tds = {t: team_pts[t]/7.0 for t in team_pts}

    modeled_any=[]
    for team,pls in by_team.items():
        team_td_rate = team_tds.get(team, sum(team_tds.values())/2.0)
        # weights from pos priors
        weights=[POSITION_PRIORS.get(p.get('pos','UNK'), 0.03) for p in pls]
        ssum=sum(weights) if sum(weights)>0 else len(pls)
        for p,w in zip(pls,weights):
            raw = (w/ssum) if ssum>0 else 1.0/len(pls)
            # blend with tiny influence from implied if present in p
            imp = american_to_imp_prob(p.get('price')) if p.get('price') is not None else None
            if imp:
                # use implied as signal scaled small
                raw = 0.8*raw + 0.2*(imp/(imp+0.001))
            # final share normalization later
            p['raw_share']=raw
        total_share=sum([p['raw_share'] for p in pls])
        for p in pls:
            final_share = p['raw_share']/total_share if total_share>0 else 1.0/len(pls)
            lam = team_td_rate * final_share
            p_any = 1-math.exp(-lam)
            p_2plus = 1-math.exp(-lam)*(1+lam)
            modeled_any.append({'key':f"player_{p['slug']}_anytime_td", 'participant':p['participant'], 'team':team, 'pos':p.get('pos'), 'price':p.get('price'), 'imp_prob': american_to_imp_prob(p.get('price')) if p.get('price') is not None else None, 'final_share':final_share, 'lambda':lam, 'p_any':p_any, 'p_2plus':p_2plus})

    # first TD
    home_pts = team_pts.get(home,0.0)
    away_pts = team_pts.get(away,0.0)
    p_home_first = home_pts/(home_pts+away_pts) if (home_pts+away_pts)>0 else 0.5
    p_away_first = 1-p_home_first
    modeled_first=[]
    for team,pls in by_team.items():
        total = sum([p.get('final_share', p.get('raw_share',1.0)) for p in pls])
        for p in pls:
            normalized = (p.get('final_share') or p.get('raw_share'))/total if total>0 else 1.0/len(pls)
            team_first_prob = p_home_first if team==home else p_away_first
            p_first = team_first_prob * normalized
            modeled_first.append({'key':f"player_{p['slug']}_1st_td", 'participant':p['participant'], 'team':team, 'pos':p.get('pos'), 'price':p.get('price'), 'imp_prob': american_to_imp_prob(p.get('price')) if p.get('price') is not None else None, 'p_first':p_first})

    return team_pts, team_tds, modeled_any, modeled_first


def main():
    snaps = find_all_snapshots_for_event(EVENT_ID)
    if not snaps:
        print('no snapshots for event'); return
    print('found', len(snaps), 'snapshots')
    all_markets, total, spread, fav = aggregate_dk_markets(snaps)
    print('aggregated total, spread, fav:', total, spread, fav)
    anytime_map, first_map = build_player_lists(all_markets)
    print('players found anytime:', len(anytime_map), 'first:', len(first_map))
    summary = load_summary_csv()
    # determine home/away from first snapshot
    home=snaps[0][2].get('home_team') or snaps[0][2].get('home')
    away=snaps[0][2].get('away_team') or snaps[0][2].get('away')
    by_team = map_players_to_team_and_pos(anytime_map, summary, home, away)
    team_pts, team_tds, modeled_any, modeled_first = compute_modeled_any_first(by_team, total, spread, home, away, fav)
    out={'event_id':EVENT_ID,'home':home,'away':away,'team_points':team_pts,'team_tds':team_tds,'anytime':modeled_any,'first':modeled_first}
    outp=OUT_DIR/'cowboys_raiders_td_models_v4.json'
    outp.write_text(json.dumps(out,indent=2))

    md=[f"# Cowboys @ Raiders TD edges (v4)\n","\n"]
    md.append('## Anytime TD\n')
    rows=[]
    for r in modeled_any:
        imp=r.get('imp_prob') or 0.0
        edge=r['p_any']-imp
        rows.append((edge,r))
    rows.sort(key=lambda x:-x[0])
    for edge,r in rows:
        md.append(f"- {r['participant']} ({r['team']}) pos={r.get('pos')} price={r.get('price')} implied={r.get('imp_prob'):.3f} modeled={r['p_any']:.3f} edge={edge:.3f}\n")
    md.append('\n## First TD\n')
    rowsf=[]
    for r in modeled_first:
        imp=r.get('imp_prob') or 0.0
        edge=r['p_first']-imp
        rowsf.append((edge,r))
    rowsf.sort(key=lambda x:-x[0])
    for edge,r in rowsf:
        md.append(f"- {r['participant']} ({r['team']}) pos={r.get('pos')} price={r.get('price')} implied={r.get('imp_prob'):.3f} modeled_first={r['p_first']:.4f} edge={edge:.4f}\n")

    mdp=OUT_DIR/'cowboys_raiders_td_edges_v4.md'
    mdp.write_text('\n'.join(md))
    print('Wrote', outp, mdp)

if __name__=='__main__':
    main()
