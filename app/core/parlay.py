"""Parlay pricing and construction.

The important thing this module gets right is that parlay legs are usually
*not* independent. For a same-game parlay (SGP) -- several legs from one
game -- multiplying leg probabilities together is simply wrong: "Dart over
passing yards" and "Nabers over receiving yards" rise and fall together, so
the true joint probability is meaningfully higher than the product. Legs on
opposite sides of a game script (favourite moneyline + underdog receiver
over) move against each other, and the product overstates them.

We model the dependence with a Gaussian copula: each leg i is a threshold on
a latent standard normal Z_i, chosen so P(Z_i < t_i) equals the leg's
marginal probability. The Z's carry a correlation matrix, and the joint
probability is the orthant probability P(all Z_i < t_i), estimated by Monte
Carlo. With a zero correlation matrix this collapses exactly to the
independent product, so the old behaviour is still available.

The second thing to be careful about is the payout. A book prices an SGP
*with* the correlation already baked in, so you do not get the product of the
individual decimal odds. Pass the real quoted parlay price as `price` when
you have it; without it we fall back to the product and mark the result
`priced_independently=True`, which is optimistic and should not be read as a
tradeable edge.

Everything here is pure standard library so the module stays importable
without numpy/scipy.
"""

from typing import List, Dict, Any, Optional, Sequence, Tuple
from itertools import combinations
import math
import random

__all__ = [
    'american_to_decimal', 'decimal_to_american', 'implied_prob',
    'devig_two_way', 'correlation_matrix', 'joint_probability',
    'parlay_ev', 'suggest_parlays',
]

# Default number of Monte Carlo draws for the copula. Antithetic sampling
# means the effective sample size is 2x this.
DEFAULT_SIMS = 20000
DEFAULT_SEED = 20260921


# --------------------------------------------------------------------------
# odds conversion
# --------------------------------------------------------------------------

def american_to_decimal(a):
    """Convert American odds to decimal. Returns None if unparseable."""
    try:
        a = int(a)
    except Exception:
        return None
    if a == 0:
        return None
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / (-a)


def decimal_to_american(d):
    """Convert decimal odds back to American. Returns None if unparseable."""
    try:
        d = float(d)
    except Exception:
        return None
    if d <= 1.0:
        return None
    if d >= 2.0:
        return int(round((d - 1.0) * 100.0))
    return int(round(-100.0 / (d - 1.0)))


def implied_prob(american):
    """Vig-inclusive implied probability of an American price."""
    dec = american_to_decimal(american)
    if dec is None:
        return None
    return 1.0 / dec


def devig_two_way(side_a, side_b) -> Optional[Tuple[float, float]]:
    """Strip vig from a two-way market, returning (prob_a, prob_b).

    Uses the multiplicative (proportional) method: normalise the two
    vig-inclusive implied probabilities so they sum to 1. This is the right
    baseline to compare a model probability against -- comparing against the
    raw implied probability credits you with the hold as if it were edge.
    """
    pa = implied_prob(side_a)
    pb = implied_prob(side_b)
    if pa is None or pb is None:
        return None
    total = pa + pb
    if total <= 0:
        return None
    return pa / total, pb / total


# --------------------------------------------------------------------------
# Gaussian copula machinery
# --------------------------------------------------------------------------

# Acklam's inverse normal CDF approximation (relative error < 1.15e-9).
_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00]


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF."""
    if p <= 0.0:
        return -float('inf')
    if p >= 1.0:
        return float('inf')
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
           (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)


def _cholesky(m: List[List[float]]) -> Optional[List[List[float]]]:
    """Cholesky decomposition. Returns None if the matrix is not PSD."""
    n = len(m)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                d = m[i][i] - s
                if d <= 1e-12:
                    return None
                L[i][j] = math.sqrt(d)
            else:
                L[i][j] = (m[i][j] - s) / L[j][j]
    return L


def _psd_cholesky(m: List[List[float]]) -> List[List[float]]:
    """Cholesky with shrinkage repair for correlation matrices that aren't PSD.

    Hand-specified pairwise correlations are easy to make inconsistent (e.g.
    a=b and b=c strongly positive but a=c negative). Rather than fail, shrink
    the off-diagonals toward the identity until the matrix is PSD.
    """
    n = len(m)
    if n == 0:
        return []
    for w in (1.0, 0.95, 0.9, 0.8, 0.7, 0.5, 0.3, 0.0):
        trial = [[m[i][j] if i == j else m[i][j] * w for j in range(n)]
                 for i in range(n)]
        L = _cholesky(trial)
        if L is not None:
            return L
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def correlation_matrix(n: int, pair_corr: Optional[Dict[Tuple[int, int], float]] = None) -> List[List[float]]:
    """Build an n x n correlation matrix from sparse pairwise entries.

    `pair_corr` maps (i, j) index pairs to a correlation in [-1, 1]; order of
    the pair does not matter and unlisted pairs default to 0.
    """
    m = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for (i, j), r in (pair_corr or {}).items():
        if i == j:
            continue
        if not (0 <= i < n and 0 <= j < n):
            raise IndexError(f'correlation index out of range: ({i}, {j})')
        r = max(-0.999, min(0.999, float(r)))
        m[i][j] = r
        m[j][i] = r
    return m


def joint_probability(probs: Sequence[float],
                      corr: Optional[List[List[float]]] = None,
                      n_sims: int = DEFAULT_SIMS,
                      seed: int = DEFAULT_SEED) -> float:
    """P(all legs win) under a Gaussian copula.

    `probs` are the marginal win probabilities. `corr` is the latent
    correlation matrix; None or all-zero off-diagonals gives the independent
    product. Uses antithetic variates to reduce Monte Carlo error.
    """
    probs = [float(p) for p in probs]
    if not probs:
        return 1.0
    if any(p <= 0.0 for p in probs):
        return 0.0
    if all(p >= 1.0 for p in probs):
        return 1.0

    n = len(probs)
    if n == 1:
        return min(1.0, probs[0])

    # No correlation supplied -> exact independent product, no simulation.
    if corr is None or all(corr[i][j] == 0.0 for i in range(n) for j in range(n) if i != j):
        out = 1.0
        for p in probs:
            out *= min(1.0, p)
        return out

    thresholds = [_norm_ppf(min(1.0, p)) for p in probs]
    L = _psd_cholesky(corr)
    rng = random.Random(seed)

    hits = 0
    draws = 0
    for _ in range(n_sims):
        z = [rng.gauss(0.0, 1.0) for _ in range(n)]
        # antithetic pair: z and -z
        for sign in (1.0, -1.0):
            ok = True
            for i in range(n):
                xi = sign * sum(L[i][k] * z[k] for k in range(i + 1))
                if xi >= thresholds[i]:
                    ok = False
                    break
            if ok:
                hits += 1
            draws += 1
    return hits / draws if draws else 0.0


# --------------------------------------------------------------------------
# parlay pricing
# --------------------------------------------------------------------------

def parlay_ev(probs: Sequence[float],
              decimals: Sequence[float],
              corr: Optional[List[List[float]]] = None,
              price: Optional[float] = None,
              n_sims: int = DEFAULT_SIMS,
              seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """Price a parlay.

    `probs`    -- model win probability per leg
    `decimals` -- decimal odds per leg (used only for the fallback payout)
    `corr`     -- latent correlation matrix, or None for independence
    `price`    -- the book's actual decimal payout for the parlay. Supply this
                  whenever you have it; a real SGP is priced with correlation
                  already applied and will not pay the product of the legs.

    Returns the joint probability, the payout used, EV per 1 unit staked, and
    `priced_independently` -- True when we had to invent the payout by
    multiplying the legs, which flatters the bet.
    """
    joint = joint_probability(probs, corr=corr, n_sims=n_sims, seed=seed)

    if price is not None:
        payout = float(price)
        priced_independently = False
    else:
        payout = 1.0
        for d in decimals:
            payout *= d if d else 1.0
        priced_independently = True

    independent = 1.0
    for p in probs:
        independent *= p

    return {
        'joint_prob': joint,
        'independent_prob': independent,
        'correlation_lift': joint - independent,
        'payout': payout,
        'ev_per_1': joint * payout - 1.0,
        'priced_independently': priced_independently,
    }


def suggest_parlays(selections: List[Dict[str, Any]],
                    max_legs: int = 6,
                    top_k: int = 20,
                    min_legs: int = 2,
                    pair_corr: Optional[Dict[Tuple[int, int], float]] = None,
                    parlay_prices: Optional[Dict[Tuple[int, ...], float]] = None,
                    n_sims: int = DEFAULT_SIMS,
                    seed: int = DEFAULT_SEED):
    """Rank parlay combinations built from `selections`.

    Each selection is a dict with at least `model_prob` and `market_price`
    (American odds); `player` and `market` are used for labelling.

    `pair_corr` maps index pairs in `selections` to latent correlations --
    supply these for same-game legs. `parlay_prices` maps a sorted tuple of
    leg indices to the book's real decimal payout for that exact combination.

    Combinations containing a leg with no model probability are skipped
    rather than silently scored as zero.
    """
    if not selections:
        return {'selected': [], 'parlay_suggestions': []}

    enriched = []
    for idx, s in enumerate(selections):
        model_prob = s.get('model_prob')
        mprice = s.get('market_price')
        dec = american_to_decimal(mprice) if mprice is not None else None
        ev = None
        if dec is not None and model_prob is not None:
            ev = model_prob * dec - 1.0
        enriched.append({**s, 'index': idx, 'decimal': dec, 'ev_per_1': ev})

    # Sort for presentation, but keep the original index so correlation and
    # price lookups stay aligned with what the caller passed in.
    selected = sorted(enriched, key=lambda x: (x['ev_per_1'] is None, -(x['ev_per_1'] or 0)))

    priceable = [e for e in enriched if e['model_prob'] is not None and e['decimal'] is not None]
    min_legs = max(1, min_legs)
    max_legs = min(max_legs, len(priceable))

    combos = []
    for r in range(min_legs, max_legs + 1):
        for combo in combinations(priceable, r):
            idxs = tuple(sorted(c['index'] for c in combo))
            probs = [c['model_prob'] for c in combo]
            decs = [c['decimal'] for c in combo]

            sub_corr = None
            if pair_corr:
                local = {}
                for a in range(len(combo)):
                    for b in range(a + 1, len(combo)):
                        ia, ib = combo[a]['index'], combo[b]['index']
                        r_ab = pair_corr.get((ia, ib), pair_corr.get((ib, ia)))
                        if r_ab:
                            local[(a, b)] = r_ab
                if local:
                    sub_corr = correlation_matrix(len(combo), local)

            price = (parlay_prices or {}).get(idxs)
            res = parlay_ev(probs, decs, corr=sub_corr, price=price,
                            n_sims=n_sims, seed=seed)
            combos.append({
                'legs': [c.get('player') for c in combo],
                'leg_indices': list(idxs),
                'markets': [c.get('market') for c in combo],
                'implied_payout': res['payout'],
                'joint_prob': res['joint_prob'],
                'independent_prob': res['independent_prob'],
                'correlation_lift': res['correlation_lift'],
                'ev_per_1': res['ev_per_1'],
                'priced_independently': res['priced_independently'],
            })

    combos_sorted = sorted(combos, key=lambda x: -x['ev_per_1'])
    return {'selected': selected, 'parlay_suggestions': combos_sorted[:top_k]}
