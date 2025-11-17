#!/usr/bin/env python3
"""
Produce provisional TD models (anytime, first, 2+) for Cowboys vs Raiders using local cached data.
- No polling; manual refresh only.
- Build player list by scanning player_data HTMLs for 'Cowboys' or 'Raiders'.
- Infer position (RB/WR/TE/QB) heuristically from HTML; fallback to UNK.
- Use team totals from cached DK snapshots to compute team TD rates.
- Distribute team TDs to players by position-prior-weighted shares.
- Output outputs/cowboys_raiders_td_provisional.json and _provisional.md
"""
import glob, json, re, math
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


def find_event_snapshot(event_id):
    files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/**/*.json', recursive=True)
    # prefer files where the event dict contains home_team/away_team
    candidates=[]
    for f in files:
        try:
            j = json.load(open(f))
        except Exception:
            continue
        if isinstance(j, dict) and j.get('id')==event_id:
            candidates.append((f,j))
        elif isinstance(j, list):
            for ev in j:
                if isinstance(ev, dict) and ev.get('id')==event_id:
                    candidates.append((f,ev))
    # pick candidate that contains home/away
    for f,ev in candidates:
        if isinstance(ev, dict) and ev.get('home_team') and ev.get('away_team'):
            return f, ev
    # fallback to latest candidate
    if candidates:
        candidates.sort(key=lambda x: Path(x[0]).stat().st_mtime, reverse=True)
        return candidates[0]
    return None, None


def extract_team_points(event):
    # pull DK totals/spreads from event markets across bookmakers if present
    totals=None
    spreads=None
    if not event:
        return None
    bks = event.get('bookmakers', [])
    for bk in bks:
        if bk.get('key','').lower()!='draftkings':
            continue
        for m in bk.get('markets',[]):
            if m.get('key')=='totals':
                outs=m.get('outcomes',[])
                if outs and outs[0].get('point') is not None:
                    totals = outs[0].get('point')
            if m.get('key')=='spreads':
                for o in m.get('outcomes',[]):
                    pt=o.get('point')
                    if isinstance(pt,(int,float)):
                        if pt<0:
                            fav=o.get('name')
                            spreads=abs(pt)
    return totals, spreads


def scan_player_data_for_teams(home, away):
    players = []
    # read summary csv to get list of player HTMLs
    summary = PLAYER_DATA_DIR / 'summary.csv'
    candidates = []
    if summary.exists():
        import csv
        with summary.open() as fh:
            rdr = csv.DictReader(fh)
            for r in rdr:
                name = r.get('name')
                file = r.get('player_file') or r.get('player_file')
                if name and file:
                    candidates.append((name, Path(file)))
    else:
        # fallback: iterate html files
        htmls = glob.glob(str(PLAYER_DATA_DIR / '*.html'))
        for h in htmls:
            name = Path(h).stem
            candidates.append((name, Path(h)))

    for name, pfile in candidates:
        if not pfile.exists():
            continue
        try:
            txt = pfile.read_text(encoding='utf-8', errors='ignore').lower()
        except Exception:
            continue
        if home and home.split()[0].lower() in txt or away and away.split()[0].lower() in txt:
            # infer position
            pos = 'UNK'
            m = re.search(r'position</span>\s*<span[^>]*>([^<]+)<', txt)
            if not m:
                m = re.search(r'position[:\s]+([a-z]{2,3})', txt)
            if m:
                posv = m.group(1).strip().upper()
                if posv.startswith('RB'):
                    pos='RB'
                elif posv.startswith('WR'):
                    pos='WR'
                elif posv.startswith('TE'):
                    pos='TE'
                elif posv.startswith('QB'):
                    pos='QB'
            players.append({'name': name, 'file': str(pfile), 'pos': pos, 'slug': slugify(name), 'html_sample': txt[:400]})
    return players


def compute_provisional(players, home, away, total, spread):
    # compute team_pt expectations
    if total is None:
        total=48.0
    if spread is None:
        spread=0.0
    fav_pts = total/2 + spread/2
    dog_pts = total/2 - spread/2
    # cannot know fav team reliably here; assume equal
    team_pts = {home: total/2, away: total/2}
    team_tds = {t: team_pts[t]/7.0 for t in team_pts}

    # group players by team using simple HTML scanning presence
    team_players=defaultdict(list)
    for p in players:
        txt = p.get('html_sample','').lower()
        team = None
        if home and home.split()[0].lower() in txt:
            team=home
        elif away and away.split()[0].lower() in txt:
            team=away
        else:
            team='unknown'
        p['team']=team
        team_players[team].append(p)

    modeled_any=[]
    modeled_first=[]
    # for each team, allocate shares by position prior weighted
    for team, pls in team_players.items():
        # compute weight per player based on position prior
        weights=[POSITION_PRIORS.get(p['pos'],'UNK') if p['pos'] in POSITION_PRIORS else POSITION_PRIORS['UNK'] for p in pls]
        ssum=sum(weights) if sum(weights)>0 else len(pls)
        for p,w in zip(pls,weights):
            share = (w/ssum) if ssum>0 else 1.0/len(pls)
            team_td_rate = team_tds.get(team, total/14.0)
            lam = team_td_rate * share
            p_any = 1-math.exp(-lam)
            p_2plus = 1-math.exp(-lam)*(1+lam)
            modeled_any.append({'participant':p['name'],'team':team,'pos':p['pos'],'share':share,'lambda':lam,'p_any':p_any,'p_2plus':p_2plus})
            # first TD: assume P(team_first)=0.5 for now, distribute by same share
            p_first = 0.5 * share
            modeled_first.append({'participant':p['name'],'team':team,'pos':p['pos'],'p_first':p_first})
    return team_pts, team_tds, modeled_any, modeled_first


def main():
    f, ev = find_event_snapshot(EVENT_ID)
    if not f:
        print('no snapshot for event in cache')
        return
    print('using snapshot', f)
    home = ev.get('home_team') or ev.get('home')
    away = ev.get('away_team') or ev.get('away')
    total, spread = extract_team_points(ev)
    print('total, spread:', total, spread)
    players = scan_player_data_for_teams(home, away)
    print('found', len(players), 'players in player_data matching teams')
    team_pts, team_tds, modeled_any, modeled_first = compute_provisional(players, home, away, total, spread)
    out = {'event_id':EVENT_ID,'home':home,'away':away,'team_points':team_pts,'team_tds':team_tds,'anytime':modeled_any,'first':modeled_first}
    outp=OUT_DIR/'cowboys_raiders_td_provisional.json'
    outp.write_text(json.dumps(out,indent=2))
    md=['# Cowboys vs Raiders provisional TD models\n','\n']
    md.append('## Anytime TD (provisional)\n')
    for r in sorted(modeled_any, key=lambda x:-x['p_any'])[:40]:
        md.append(f"- {r['participant']} ({r['team']}) pos={r['pos']} modeled_any={r['p_any']:.3f} modeled_2plus={r['p_2plus']:.3f} share={r['share']:.3f}\n")
    md.append('\n## First TD (provisional)\n')
    for r in sorted(modeled_first, key=lambda x:-x['p_first'])[:40]:
        md.append(f"- {r['participant']} ({r['team']}) pos={r['pos']} modeled_first={r['p_first']:.3f}\n")
    mdp=OUT_DIR/'cowboys_raiders_td_provisional.md'
    mdp.write_text('\n'.join(md))
    print('Wrote', outp, mdp)

if __name__=='__main__':
    main()
