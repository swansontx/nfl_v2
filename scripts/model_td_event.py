#!/usr/bin/env python3
"""
Model anytime TD, first TD, and 2+ TDs for a given event id using DraftKings snapshots.
Writes outputs/<event_slug>_td_models.json and _td_edges.md
"""
import json, math
from pathlib import Path
import glob, os, re

CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
OUT_DIR = Path('outputs')
OUT_DIR.mkdir(exist_ok=True)

EVENT_ID = '80d04ba917883a6438580ebae9fb0f22'  # Cowboys @ Raiders (from cache)

# position priors for TD share (rough)
POSITION_PRIORS = {'RB':0.22, 'WR':0.18, 'TE':0.12, 'QB':0.03, 'DST':0.02, 'K':0.01, 'UNK':0.03}


def american_to_decimal(a):
    a = int(a)
    if a > 0:
        return 1 + a/100.0
    else:
        return 1 + 100.0/abs(a)


def american_to_imp_prob(a):
    dec = american_to_decimal(a)
    return 1.0/dec


def find_event_files(event_id):
    files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/**/*.json', recursive=True)
    matches = []
    for f in files:
        try:
            j=json.load(open(f))
        except Exception:
            continue
        # j could be dict with id or list of events
        if isinstance(j, dict) and j.get('id')==event_id:
            matches.append((f,j))
        elif isinstance(j, list):
            for ev in j:
                if isinstance(ev, dict) and ev.get('id')==event_id:
                    matches.append((f,ev))
    return matches


def extract_dk_markets(event):
    # event is dict from snapshot for a single event or bookmaker snapshot
    # If full per-book snapshot: contains 'bookmakers' list
    markets = []
    if 'bookmakers' in event:
        # book data may be nested in lists of events; handle either dict or list container
    if 'bookmakers' in event:
        for book in event['bookmakers']:
            if book.get('key','').lower()!='draftkings':
                continue
            for m in book.get('markets',[]):
                markets.append((m.get('key'), m))
    elif isinstance(event, list):
        for ev in event:
            if not isinstance(ev, dict):
                continue
            for book in ev.get('bookmakers',[]):
                if book.get('key','').lower()!='draftkings':
                    continue
                for m in book.get('markets',[]):
                    markets.append((m.get('key'), m))
    return markets


def get_team_expected_tds(markets, home, away):
    # find totals and spreads
    total = None
    spread = None
    fav_team = None
    for key,m in markets:
        if key=='totals':
            # outcomes Over/Under have 'point'
            outs = m.get('outcomes',[])
            if outs:
                total = outs[0].get('point') or outs[0].get('line')
        if key=='spreads':
            # find which outcome has negative point (fav)
            for o in m.get('outcomes',[]):
                pt = o.get('point')
                if pt is not None and isinstance(pt,(int,float)) and pt<0:
                    fav_team = o.get('name')
                    spread = abs(pt)
                    break
    if total is None:
        total = 46.0  # fallback
    if spread is None:
        spread = 0.0
    # compute expected points per team
    fav_pts = total/2.0 + spread/2.0
    dog_pts = total/2.0 - spread/2.0
    # map which is which
    if fav_team and fav_team.lower()==home.lower():
        return {home: fav_pts, away: dog_pts}
    elif fav_team and fav_team.lower()==away.lower():
        return {away: fav_pts, home: dog_pts}
    else:
        # unknown, assume equal
        return {home: total/2.0, away: total/2.0}


def slugify(name):
    if not name: return 'unknown'
    s = re.sub(r'[^a-z0-9 ]','', name.lower())
    s = re.sub(r'\s+','_', s)
    return s


def infer_position(player_name):
    # naive: RB if common RB names? We'll fallback to unknown. Ideally use player_data cache.
    return 'UNK'


def main():
    files = find_event_files(EVENT_ID)
    if not files:
        print('No cached snapshots for event', EVENT_ID)
        return
    # prefer latest file
    files.sort(key=lambda x: Path(x[0]).stat().st_mtime, reverse=True)
    fpath, ev = files[0]
    print('Using snapshot', fpath)
    # find home/away
    home = ev.get('home_team') or ev.get('home')
    away = ev.get('away_team') or ev.get('away')
    markets = extract_dk_markets(ev)
    team_pts = get_team_expected_tds(markets, home, away)
    team_tds = {t: team_pts[t]/7.0 for t in team_pts}

    # collect anytime_td, 1st_td markets
    anytime_players = []
    first_players = []
    # find market objects
    market_map = {k:m for k,m in markets}
    if 'player_anytime_td' in market_map:
        outs = market_map['player_anytime_td'].get('outcomes',[])
        for o in outs:
            participant = o.get('description') or o.get('name')
            price = o.get('price')
            anytime_players.append({'participant': participant, 'price': price})
    if 'player_1st_td' in market_map:
        outs = market_map['player_1st_td'].get('outcomes',[])
        for o in outs:
            participant = o.get('description') or o.get('name')
            price = o.get('price')
            first_players.append({'participant': participant, 'price': price})

    # group players by team by simple heuristic: if name contains team name? else check in player list
    # we'll parse participant strings like 'Jalen Hurts' or 'Philadelphia Eagles D/ST'
    def team_of(participant):
        p=participant.lower()
        if 'cowboy' in p:
            return 'Dallas Cowboys'
        if 'raider' in p or 'las vegas' in p:
            return 'Las Vegas Raiders'
        # else guess by last name mapping from anytime list
        return None

    # compute implied probs and weight per team
    from collections import defaultdict
    team_players = defaultdict(list)
    for pl in anytime_players:
        team = team_of(pl['participant'])
        pl['slug'] = slugify(pl['participant'])
        if team is None:
            # attempt to infer by presence in first_players mapping
            team = None
        if team is None:
            # default: assign by checking common local names: if player in home/away rosters? we skip
            team = 'unknown'
        pl['team'] = team
        pl['imp_prob'] = american_to_imp_prob(pl['price']) if pl['price'] is not None else None
        team_players[team].append(pl)

    # compute player shares per team by normalizing implied probs
    modeled = []
    for team, pls in team_players.items():
        ssum = sum([p['imp_prob'] or 0.001 for p in pls])
        for p in pls:
            imp = p['imp_prob'] or 0.001
            raw_share = imp/ssum if ssum>0 else 1.0/len(pls)
            # shrink toward position prior (unknown -> leave)
            pos = infer_position(p['participant'])
            pos_prior = POSITION_PRIORS.get(pos, 0.03)
            final_share = 0.7*raw_share + 0.3*pos_prior
            # normalize later across team
            p['raw_share'] = final_share
        # normalize final_share to sum to 1
        total_share = sum([x['raw_share'] for x in pls])
        for p in pls:
            p['final_share'] = p['raw_share']/total_share if total_share>0 else 1.0/len(pls)
            # compute lambda and probs
            team_td_rate = team_tds.get(team, sum(team_tds.values())/2.0)
            lam = team_td_rate * p['final_share']
            p_any = 1 - math.exp(-lam)
            p_2plus = 1 - math.exp(-lam)*(1+lam)
            modeled.append({'key': f"player_{p['slug']}_anytime_td", 'participant': p['participant'], 'team': team, 'price': p['price'], 'imp_prob': p['imp_prob'], 'final_share': p['final_share'], 'lambda': lam, 'p_any': p_any, 'p_2plus': p_2plus})

    # first TD: compute P(team scores first) from team pts
    home_pts = team_pts.get(home, 0.0)
    away_pts = team_pts.get(away, 0.0)
    p_home_first = home_pts/(home_pts+away_pts) if (home_pts+away_pts)>0 else 0.5
    p_away_first = 1-p_home_first

    # for simplicity, approximate first-TD share proportional to final_share among that team's anytime players
    first_modeled = []
    # build mapping of final_share per team from modeled
    per_team_shares = {}
    for team, pls in team_players.items():
        per_team_shares[team] = {p['participant']: p['final_share'] for p in pls}
    for team, pls in team_players.items():
        total = sum([p['final_share'] for p in pls])
        for p in pls:
            normalized = p['final_share']/total if total>0 else 1.0/len(pls)
            p_team_first = p_home_first if team==home else p_away_first
            p_first = p_team_first * normalized
            first_modeled.append({'key':f"player_{p['slug']}_1st_td", 'participant':p['participant'], 'team':team, 'price':p['price'], 'imp_prob': p.get('imp_prob'), 'p_first': p_first})

    out = {'event_id': EVENT_ID, 'home': home, 'away': away, 'team_points': team_pts, 'team_tds': team_tds, 'anytime': modeled, 'first': first_modeled}
    outp = OUT_DIR / f"cowboys_raiders_td_models.json"
    with outp.open('w') as fh:
        json.dump(out, fh, indent=2)
    # produce edges md for anytime and first and 2+
    md = [f"# Cowboys @ Raiders TD model edges\n", f"Event: {EVENT_ID}\n", f"Home: {home}  Away: {away}\n\n"]
    # anytime
    md.append('## Anytime TD\n')
    rows = []
    for r in modeled:
        if r['imp_prob'] is None:
            imp = 0.0
        else:
            imp = r['imp_prob']
        edge = r['p_any'] - imp
        rows.append((edge, r))
    rows.sort(key=lambda x: -x[0])
    for edge,r in rows[:40]:
        md.append(f"- {r['participant']} | price={r['price']} | implied={r['imp_prob']:.3f} | modeled={r['p_any']:.3f} | edge={edge:.3f} | lambda={r['lambda']:.4f}\n")
    md.append('\n## 2+ TDs\n')
    rows2 = []
    for r in modeled:
        imp = r['imp_prob'] or 0.0
        edge2 = r['p_2plus'] - 0.0  # DK doesn't have direct implied for 2+ since price was for Yes only; we skip implied for 2+
        rows2.append((edge2,r))
    rows2.sort(key=lambda x: -x[0])
    for edge,r in rows2[:40]:
        md.append(f"- {r['participant']} | modeled P(2+)= {r['p_2plus']:.3f} | lambda={r['lambda']:.4f}\n")
    md.append('\n## First TD\n')
    rowsf = []
    for it in first_modeled:
        imp = it.get('imp_prob') or 0.0
        edgef = it['p_first'] - imp
        rowsf.append((edgef, it))
    rowsf.sort(key=lambda x: -x[0])
    for edge,it in rowsf[:40]:
        md.append(f"- {it['participant']} | price={it['price']} | implied={it.get('imp_prob'):.3f} | modeled_first={it['p_first']:.4f} | edge={edge:.4f}\n")

    mdp = OUT_DIR / 'cowboys_raiders_td_edges.md'
    mdp.write_text('\n'.join(md))
    print('Wrote', outp, mdp)

if __name__ == '__main__':
    main()
