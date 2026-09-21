#!/usr/bin/env python3
"""Pre-game report for any NFL game, built from nflverse (free, no API key).

    python3 scripts/game_report.py --season 2026 --week 2 --team NYG
    python3 scripts/game_report.py            # defaults to tonight's MNF

Pulls the real schedule/market row, the official injury report, and prior-week
snap share and production for both teams, then prints the matchup picture.

What this can and cannot price
------------------------------
nflverse carries GAME-level markets only: spread, total, moneyline. Those are
real and are used directly. It does NOT carry player prop lines -- no free
source reachable from this environment does. So the prop section only runs if
you hand it lines via --props, and the leg probabilities you supply are yours,
not the model's.

The part that needs no prop feed is the correlation structure, which is what
app/core/parlay.py exists to handle: same-game legs share a game script, and
multiplying their probabilities together understates correlated parlays.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.parlay import (  # noqa: E402
    american_to_decimal, devig_two_way, correlation_matrix, parlay_ev,
)
from backend import nflverse as nv  # noqa: E402


def print_market(game: dict) -> None:
    m = nv.game_market(game)
    home, away = m['home_team'], m['away_team']
    spread = m['spread_line']
    fav, dog = (home, away) if spread > 0 else (away, home)
    print(f"{away} @ {home}  --  {m['gameday']} {m['gametime']} ET, "
          f"{m['stadium']} ({m['roof']})")
    print(f"  spread : {fav} -{abs(spread)}")
    print(f"  total  : {m['total_line']}")
    print(f"  ML     : {away} {m['away_moneyline']:+.0f} / {home} {m['home_moneyline']:+.0f}")
    dv = devig_two_way(m['away_moneyline'], m['home_moneyline'])
    if dv:
        print(f"  de-vigged win prob: {away} {dv[0]:.1%} / {home} {dv[1]:.1%}")
    print()


def print_injuries(season: int, week: int, teams) -> None:
    rows = nv.injuries(season, week=week, teams=teams)
    if not rows:
        print('No injury report published yet for this week.\n')
        return
    rank = {'Out': 0, 'Doubtful': 1, 'Questionable': 2}
    for team in teams:
        team_rows = [r for r in rows if r['team'] == team]
        designated = [r for r in team_rows if r.get('report_status')]
        dnp = [r for r in team_rows
               if not r.get('report_status')
               and 'Did Not Participate' in (r.get('practice_status') or '')]
        print(f'--- {team} injury report')
        if not designated and not dnp:
            print('    clean')
        for r in sorted(designated, key=lambda x: rank.get(x['report_status'], 9)):
            inj = r.get('report_primary_injury') or r.get('practice_primary_injury') or '-'
            prac = (r.get('practice_status') or '').replace(' Participation in Practice', '')
            prac = prac.replace(' In Practice', '')
            print(f"    {r['report_status']:<12} {r['position']:<3} {r['full_name']:<24} "
                  f"{inj:<14} practice={prac or '-'}")
        for r in dnp:
            inj = r.get('practice_primary_injury') or '-'
            print(f"    {'(DNP, no tag)':<12} {r['position']:<3} {r['full_name']:<24} {inj}")
        print()


def print_usage(season: int, week: int, team: str, top: int = 8) -> None:
    if week < 1:
        return
    try:
        rows = nv.player_usage(season, week, team)
    except nv.DatasetUnavailable as exc:
        print(f'--- {team} usage unavailable: {exc}\n')
        return
    rows = [r for r in rows if r['targets'] or r['carries'] or r['passing_attempts']]
    print(f'--- {team} week {week} usage')
    print(f"    {'pos':<4}{'player':<24}{'snap':>6}{'tgt':>5}{'rec':>5}{'recyd':>7}"
          f"{'car':>5}{'rushyd':>8}{'passyd':>8}")
    for r in rows[:top]:
        print(f"    {(r['position'] or '?'):<4}{(r['player'] or '?'):<24}"
              f"{r['offense_share']:>5.0%}{r['targets']:>5.0f}{r['receptions']:>5.0f}"
              f"{r['receiving_yards']:>7.0f}{r['carries']:>5.0f}"
              f"{r['rushing_yards']:>8.0f}{r['passing_yards']:>8.0f}")
    print()


def print_parlays(props_path: str) -> None:
    """Score parlays from a JSON file of props + correlations.

    Expected shape:
        {"legs":   {"key": {"label":..., "price": -114, "p": 0.55}, ...},
         "corr":   [["keyA","keyB",0.55], ...],
         "parlays":[{"name":..., "legs":["keyA","keyB"], "price": 2.75}, ...]}
    """
    spec = json.loads(Path(props_path).read_text())
    legs, parlays = spec['legs'], spec.get('parlays', [])
    corr_map = {(a, b): r for a, b, r in spec.get('corr', [])}

    print('=== parlays ===')
    print('Leg probabilities are the ones you supplied, not model output.\n')
    scored = []
    for p in parlays:
        keys = p['legs']
        probs = [legs[k]['p'] for k in keys]
        decs = [american_to_decimal(legs[k]['price']) for k in keys]
        pair = {}
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                r = corr_map.get((keys[i], keys[j])) or corr_map.get((keys[j], keys[i]))
                if r:
                    pair[(i, j)] = r
        res = parlay_ev(probs, decs,
                        corr=correlation_matrix(len(keys), pair) if pair else None,
                        price=p.get('price'))
        scored.append((p['name'], keys, res))

    for name, keys, res in sorted(scored, key=lambda x: -x[2]['correlation_lift']):
        print(f'--- {name}')
        for k in keys:
            print(f"      {legs[k]['label']:<34}{legs[k]['price']:>6}   p={legs[k]['p']:.0%}")
        print(f"    independent product : {res['independent_prob']:.1%}")
        print(f"    correlation-aware   : {res['joint_prob']:.1%}  "
              f"(lift {res['correlation_lift']:+.1%})")
        if res['priced_independently']:
            print(f"    payout {res['payout']:.2f}x  <- INVENTED (product of legs);")
            print('       a book prices correlation in and pays less, so the EV')
            print('       below is an upper bound, not an edge.')
        else:
            print(f"    payout {res['payout']:.2f}x  (real SGP price)")
        print(f"    EV per 1u           : {res['ev_per_1']:+.3f}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--week', type=int, default=2)
    ap.add_argument('--team', default='NYG', help='either team in the game')
    ap.add_argument('--props', help='JSON file of prop legs and correlations')
    ap.add_argument('--refresh', action='store_true', help='ignore cached data')
    args = ap.parse_args()

    kw = {'max_age_hours': 0 if args.refresh else nv.DEFAULT_MAX_AGE_HOURS}

    game = nv.find_game(args.season, args.week, args.team, **kw)
    if not game:
        sys.exit(f'No game found for {args.team} in {args.season} week {args.week}')

    teams = (game['away_team'], game['home_team'])
    print_market(game)
    print_injuries(args.season, args.week, teams)
    for t in teams:
        print_usage(args.season, args.week - 1, t)

    if args.props:
        print_parlays(args.props)
    else:
        print('No --props file given; skipping parlay scoring.')
        print('nflverse has no prop lines -- see the module docstring.')


if __name__ == '__main__':
    main()
