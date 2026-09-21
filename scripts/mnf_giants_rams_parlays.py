#!/usr/bin/env python3
"""Same-game parlay board for NYG @ LAR, MNF Week 2 (2026-09-21, 8:15pm ET).

Why this script exists
----------------------
The live pipeline could not be used for this game: there is no ODDS_API_KEY
in the environment and the session's egress policy blocks the sports data
hosts, so nothing could be pulled from The Odds API or ESPN. The market
numbers below were read off public reporting this afternoon and are hand
entered. They will have moved -- re-check before betting.

More importantly: the leg probabilities here are ASSUMPTIONS, not model
output. No projection model was run. What this script is actually for is the
part that does not depend on a model -- the correlation structure between
legs, and what that structure does to a parlay's true hit rate. Swap in your
own `p` values (or wire it to the projections pipeline) and the ranking
becomes meaningful.

Run:  python3 scripts/mnf_giants_rams_parlays.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.parlay import (  # noqa: E402
    american_to_decimal,
    devig_two_way,
    correlation_matrix,
    parlay_ev,
)

GAME = 'NYG @ LAR -- MNF Week 2, 2026-09-21 20:15 ET, SoFi Stadium'

# --------------------------------------------------------------------------
# Market (hand-entered this afternoon; verify before use)
# --------------------------------------------------------------------------
SPREAD = 'LAR -6.5 / -7'
TOTAL = 47.5
ML_RAMS, ML_GIANTS = -340, 275

# Each leg: label, American price, and an assumed win probability.
# `p` is a judgement call, NOT a model number -- see the docstring.
LEGS = {
    'dart_pass_o213_5':   ('Jaxson Dart o213.5 pass yds', -114, 0.55),
    'nabers_rec_o63_5':   ('Malik Nabers o63.5 rec yds',  -114, 0.57),
    'nabers_atd':         ('Malik Nabers anytime TD',      200, 0.35),
    'kyren_rec_o14_5':    ('Kyren Williams o14.5 rec yds', -111, 0.56),
    'rams_ml':            ('Rams moneyline',              -340, 0.77),
    'backfield_100_rush': ('Williams+Corum 100+ rush yds', -218, 0.68),
}

# --------------------------------------------------------------------------
# Correlation structure -- the actual content of this file
# --------------------------------------------------------------------------
# Latent (Gaussian copula) correlations. Signs matter more than exact values.
CORR = {
    # Nabers is the clear alpha in New York's passing game; Dart's yardage
    # runs through him. Strongest positive pair on the board.
    ('dart_pass_o213_5', 'nabers_rec_o63_5'): 0.55,
    ('dart_pass_o213_5', 'nabers_atd'): 0.40,
    ('nabers_rec_o63_5', 'nabers_atd'): 0.45,

    # Giants are +6.5 road dogs. Trailing means more pass volume, so the
    # Giants passing legs are HELPED by the Rams winning -- but a Rams
    # blowout eventually kills volume too. Mildly positive, not strongly.
    ('rams_ml', 'dart_pass_o213_5'): 0.10,

    # Rams leading = run the clock = more backfield rushing. Clean positive.
    ('rams_ml', 'backfield_100_rush'): 0.35,

    # Kyren's receiving work comes on passing downs, which show up when the
    # Rams are NOT comfortably ahead grinding clock. Slightly negative
    # against the rushing prop and against the Rams ML.
    ('kyren_rec_o14_5', 'backfield_100_rush'): -0.15,
    ('kyren_rec_o14_5', 'rams_ml'): -0.10,
}

# Book SGP prices, where known. None means we fall back to multiplying the
# legs, which OVERSTATES the payout a book would actually offer.
SGP_PRICES: dict[tuple[str, ...], float] = {}

CANDIDATES = [
    ('Giants passing stack', ['dart_pass_o213_5', 'nabers_rec_o63_5']),
    ('Giants passing stack + TD', ['dart_pass_o213_5', 'nabers_rec_o63_5', 'nabers_atd']),
    ('Rams game script', ['rams_ml', 'backfield_100_rush']),
    ('Rams win / Giants garbage-time volume', ['rams_ml', 'dart_pass_o213_5']),
    ('Nacua-out pivot', ['kyren_rec_o14_5', 'nabers_rec_o63_5']),
    ('Cross-game-script (deliberately bad)', ['rams_ml', 'kyren_rec_o14_5']),
]


def _corr_for(keys: list[str]):
    pair = {}
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            r = CORR.get((keys[a], keys[b])) or CORR.get((keys[b], keys[a]))
            if r:
                pair[(a, b)] = r
    return correlation_matrix(len(keys), pair) if pair else None


def main() -> None:
    print(GAME)
    print(f'Spread {SPREAD} | Total {TOTAL} | ML {ML_RAMS}/{ML_GIANTS}')
    fav, dog = devig_two_way(ML_RAMS, ML_GIANTS)
    print(f'De-vigged moneyline: Rams {fav:.1%} / Giants {dog:.1%}')
    print()
    print('NOTE: leg probabilities are assumptions, not model output.')
    print('      Nacua (groin/hip) is a game-time call -- inactives ~6:45pm ET.')
    print()

    rows = []
    for name, keys in CANDIDATES:
        probs = [LEGS[k][2] for k in keys]
        decs = [american_to_decimal(LEGS[k][1]) for k in keys]
        price = SGP_PRICES.get(tuple(sorted(keys)))
        res = parlay_ev(probs, decs, corr=_corr_for(keys), price=price)
        rows.append((name, keys, res))

    rows.sort(key=lambda r: -r[2]['correlation_lift'])

    for name, keys, res in rows:
        print(f'--- {name}')
        for k in keys:
            label, price, p = LEGS[k]
            print(f'      {label:<34} {price:>5}   assumed p={p:.0%}')
        lift = res['correlation_lift']
        print(f'    independent (what the old code assumed) : {res["independent_prob"]:.1%}')
        print(f'    correlation-aware joint probability     : {res["joint_prob"]:.1%}')
        print(f'    correlation lift                        : {lift:+.1%}')
        if res['priced_independently']:
            print(f'    payout {res["payout"]:.2f}x  <- INVENTED (product of legs).')
            print('       A book prices correlation in and will pay less than this,')
            print('       so treat the EV below as an upper bound, not an edge.')
        else:
            print(f'    payout {res["payout"]:.2f}x  (real SGP price)')
        print(f'    EV per 1u                               : {res["ev_per_1"]:+.3f}')
        print()

    print('Read the "correlation lift" column, not the EV column.')
    print('Positive lift = the naive product understates how often this lands.')
    print('Negative lift = legs fight each other; the naive product flatters it.')


if __name__ == '__main__':
    main()
