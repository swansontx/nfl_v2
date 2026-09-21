#!/usr/bin/env python3
"""Scenario-conditioned prop sets for NYG @ LA, MNF Week 2 2026.

    python3 scripts/scenario_props.py                # all three scenarios
    python3 scripts/scenario_props.py --nacua out    # force Nacua inactive
    python3 scripts/scenario_props.py --scenario rams

Builds three internally-consistent prop sets:

  base    the market's view -- Rams by ~7, total 48
  giants  the Giants play well: cover or win outright
  rams    the Rams control it: comfortable double-digit win

The point of splitting them is that props are not independent of the game
script. "Skattebo over rushing yards" and "Dart over passing yards" are both
reasonable bets, but they want opposite games, so backing both is closer to a
hedge than a position. Each set below hangs together: every leg wants the
same game.

Projections blend each player's 2025 per-game rate (from nflverse) with his
2026 Week 1 line, weighting the recent game as worth three of last season's
so a role change moves the number without a single game dominating. Scenario
multipliers are then applied to volume.

Prop LINES are hand-entered from public reporting on the afternoon of
2026-09-21 and flagged reported/ESTIMATED -- nflverse carries no prop markets
and every book is blocked by this environment's egress policy. Re-check
before betting; the game line had already moved from 6.5/47.5 to 7/48 while
this was being written.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.projection import prob_over, prob_at_least_one_td, blend, implied_line  # noqa: E402
from app.core.parlay import (  # noqa: E402
    american_to_decimal, correlation_matrix, parlay_ev, devig_two_way,
)
from backend import nflverse as nv  # noqa: E402

SEASON, WEEK = 2026, 2

# player -> (market key, line, american price, reported?)
# `reported` False means the line is an estimate and the probability below
# inherits that uncertainty.
PROPS = {
    'Jaxson Dart':      ('pass_yds', 213.5, -114, True),
    'Matthew Stafford': ('pass_yds', 238.5, -113, True),
    'Malik Nabers':     ('rec_yds',   63.5, -114, True),
    'Isaiah Likely':    ('rec_yds',   44.5, -115, False),
    'Davante Adams':    ('rec_yds',   54.5, -110, False),
    'Cam Skattebo':     ('rush_yds',  51.5, -114, True),
    'Kyren Williams':   ('rush_yds',  58.5, -115, False),
    'Blake Corum':      ('rush_yds',  33.5, -115, False),
}
# Kyren's receiving prop is quoted separately from his rushing prop.
KYREN_REC = ('rec_yds', 14.5, -111, True)
NABERS_ATD = (200, True)

# Scenario -> player -> multiplier on projected volume.
# Read each column as one coherent game, not as independent knobs.
SCENARIOS = {
    'base': {},
    'giants': {
        # Giants stay on schedule: Dart efficient, run game alive all night.
        'Jaxson Dart': 1.12,
        'Malik Nabers': 1.15,
        'Isaiah Likely': 1.10,
        'Cam Skattebo': 1.25,     # leading/close keeps the run game alive
        # Rams chase: more dropbacks, fewer clock-grinding carries.
        'Matthew Stafford': 1.10,
        'Davante Adams': 1.12,
        'Kyren Williams': 0.78,   # rushing volume evaporates when behind
        'Blake Corum': 0.62,      # the back who gets cut first when trailing
        'Kyren Williams REC': 1.30,
    },
    'rams': {
        # Rams grind: backfield eats, Stafford efficient but volume capped.
        'Kyren Williams': 1.22,
        'Blake Corum': 1.30,
        'Matthew Stafford': 0.94,
        'Davante Adams': 1.05,
        # Giants abandon the run and throw into a lead -- volume up,
        # efficiency down. Net passing yards rise; rushing collapses.
        'Jaxson Dart': 1.08,
        'Malik Nabers': 1.10,
        'Isaiah Likely': 1.05,
        'Cam Skattebo': 0.68,
        'Kyren Williams REC': 0.85,
    },
}

# If Nacua is out, his ~10 targets/game have to go somewhere.
NACUA_OUT_BOOST = {
    'Davante Adams': 1.30,
    'Kyren Williams REC': 1.15,
    'Matthew Stafford': 0.96,   # a real downgrade at the position
}

SCENARIO_BLURB = {
    'base': 'Market view: Rams -7, total 48. Nothing unusual happens.',
    'giants': 'Giants cover or win: Dart on schedule, Skattebo volume, game competitive into Q4.',
    'rams': 'Rams control: double-digit win, backfield grinds clock, Giants throw from behind.',
}


def baselines():
    """2025 per-game rates and 2026 Week 1 lines, straight from nflverse.

    Only games the player actually featured in are averaged;
    see nflverse.played_in_game().
    """
    prior_rows = nv.load('player_week', 2025)
    wk1 = nv.load('player_week', 2026, where={'week': 1})

    names = set(PROPS) | {'Kyren Williams'}
    out = {}
    for name in names:
        prior = [r for r in prior_rows
                 if r['player_display_name'] == name
                 and r.get('season_type', 'REG') == 'REG'
                 and nv.played_in_game(r)]
        recent = [r for r in wk1 if r['player_display_name'] == name]
        g = len(prior)

        def avg(rows, key):
            return sum(nv.num(r.get(key)) for r in rows) / len(rows) if rows else 0.0

        out[name] = {
            'games_2025': g,
            'pass_yds': blend(avg(prior, 'passing_yards'), avg(recent, 'passing_yards'), g),
            'rush_yds': blend(avg(prior, 'rushing_yards'), avg(recent, 'rushing_yards'), g),
            'rec_yds': blend(avg(prior, 'receiving_yards'), avg(recent, 'receiving_yards'), g),
            'targets': blend(avg(prior, 'targets'), avg(recent, 'targets'), g),
            'rec_tds': blend(avg(prior, 'receiving_tds'), avg(recent, 'receiving_tds'), g),
            'wk1_rec_yds': avg(recent, 'receiving_yards'),
            'wk1_rush_yds': avg(recent, 'rushing_yards'),
            'wk1_pass_yds': avg(recent, 'passing_yards'),
        }
    return out


def project(base, scenario, nacua_out):
    """Apply scenario and Nacua multipliers to the blended baselines."""
    mult = dict(SCENARIOS[scenario])
    if nacua_out:
        for k, v in NACUA_OUT_BOOST.items():
            mult[k] = mult.get(k, 1.0) * v

    proj = {}
    for name, (market, line, price, reported) in PROPS.items():
        m = mult.get(name, 1.0)
        proj[name] = {
            'market': market, 'line': line, 'price': price, 'reported': reported,
            'projection': base[name][market] * m,
            'mult': m,
        }
    # Kyren receiving is tracked under its own multiplier key.
    m = mult.get('Kyren Williams REC', 1.0)
    market, line, price, reported = KYREN_REC
    proj['Kyren Williams (rec)'] = {
        'market': market, 'line': line, 'price': price, 'reported': reported,
        'projection': base['Kyren Williams']['rec_yds'] * m, 'mult': m,
    }
    return proj


def nabers_atd_prob(base, scenario, nacua_out):
    mult = SCENARIOS[scenario].get('Malik Nabers', 1.0)
    return prob_at_least_one_td(max(0.05, base['Malik Nabers']['rec_tds'] * mult))


# Correlations within a set. Same-game legs share a script; these are the
# pairings that matter for the parlays below.
CORR = {
    ('Jaxson Dart', 'Malik Nabers'): 0.50,
    ('Jaxson Dart', 'Isaiah Likely'): 0.45,
    ('Jaxson Dart', 'Cam Skattebo'): -0.22,
    ('Malik Nabers', 'Isaiah Likely'): -0.18,
    ('Matthew Stafford', 'Davante Adams'): 0.55,
    ('Matthew Stafford', 'Kyren Williams'): -0.20,
    ('Kyren Williams', 'Blake Corum'): 0.30,
    ('Kyren Williams', 'Kyren Williams (rec)'): -0.15,
    ('Davante Adams', 'Kyren Williams'): -0.12,
    # Both are Rams passing-game legs with Nacua out: shared pass volume
    # pushes them together, target competition pulls them apart. Net mild.
    ('Davante Adams', 'Kyren Williams (rec)'): 0.15,
}

# The parlay each scenario actually argues for.
SETS = {
    'base':   ['Kyren Williams (rec)', 'Davante Adams'],
    'giants': ['Jaxson Dart', 'Malik Nabers', 'Cam Skattebo'],
    'rams':   ['Kyren Williams', 'Blake Corum', 'Davante Adams'],
}


def score_parlay(keys, proj, probs):
    pair = {}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            r = CORR.get((keys[i], keys[j])) or CORR.get((keys[j], keys[i]))
            if r:
                pair[(i, j)] = r
    return parlay_ev(
        [probs[k] for k in keys],
        [american_to_decimal(proj[k]['price']) for k in keys],
        corr=correlation_matrix(len(keys), pair) if pair else None,
    )


def run(scenario, base, nacua_out):
    proj = project(base, scenario, nacua_out)
    probs = {k: prob_over(v['projection'], v['line'], market=v['market'])
             for k, v in proj.items()}

    print(f'=== {scenario.upper()}  --  {SCENARIO_BLURB[scenario]}')
    print(f'    Nacua assumed {"OUT" if nacua_out else "ACTIVE"}\n')
    print(f"    {'player':<24}{'line':>8}{'proj':>8}{'median':>8}{'P(over)':>9}  src")
    order = sorted(proj, key=lambda k: -probs[k])
    for k in order:
        v = proj[k]
        src = 'reported' if v['reported'] else 'ESTIMATED'
        med = implied_line(v['projection'], market=v['market'])
        print(f"    {k:<24}{v['line']:>8.1f}{v['projection']:>8.1f}{med:>8.1f}"
              f"{probs[k]:>8.0%}   {src}")
    atd = nabers_atd_prob(base, scenario, nacua_out)
    print(f"    {'Malik Nabers anytime TD':<24}{'-':>8}{'-':>8}{'-':>8}{atd:>8.0%}   reported (+200)")

    keys = SETS[scenario]
    res = score_parlay(keys, proj, probs)
    print(f"\n    parlay: {' + '.join(keys)}")
    print(f"      independent product : {res['independent_prob']:.1%}")
    print(f"      correlation-aware   : {res['joint_prob']:.1%} "
          f"(lift {res['correlation_lift']:+.1%})")
    print(f"      payout if priced as separate legs: {res['payout']:.2f}x  "
          f"(a real SGP pays less)")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', choices=list(SCENARIOS) + ['all'], default='all')
    ap.add_argument('--nacua', choices=['in', 'out'], default='out',
                    help='Nacua was DNP all week and trending out; default out')
    args = ap.parse_args()

    game = nv.find_game(SEASON, WEEK, 'NYG')
    m = nv.game_market(game)
    dv = devig_two_way(m['away_moneyline'], m['home_moneyline'])
    print(f"{m['away_team']} @ {m['home_team']}  {m['gameday']} {m['gametime']} ET, {m['stadium']}")
    print(f"nflverse line: {m['home_team']} -{m['spread_line']}, total {m['total_line']} "
          f"(market has since moved to -7 / 48)")
    if dv:
        print(f"de-vigged: {m['away_team']} {dv[0]:.1%} / {m['home_team']} {dv[1]:.1%}")
    print()

    base = baselines()
    nacua_out = args.nacua == 'out'
    todo = list(SCENARIOS) if args.scenario == 'all' else [args.scenario]
    for s in todo:
        run(s, base, nacua_out)

    print('Lines marked ESTIMATED are my guesses at where the book is; the')
    print('probability next to them is only as good as that guess.')
    print('Legs within a set are meant to be played together -- they want the')
    print('same game. Mixing sets hedges you against yourself.')


if __name__ == '__main__':
    main()
