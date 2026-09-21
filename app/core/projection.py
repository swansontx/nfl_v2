"""Turn a projected mean into a prop probability.

A projection like "Nabers 68 receiving yards" is not directly bettable: what
you need is P(yards > 63.5). That requires a distribution, not a point
estimate, and the distribution matters more than the mean for props priced
near the middle.

Yardage props are modelled lognormally. Yards are non-negative and
right-skewed -- a receiver's ceiling game is much further from the median
than his floor game is -- and the lognormal captures that where a normal
does not, while staying cheap to evaluate. Counting props (touchdowns) use
Poisson.

Coefficients of variation are the tunable part. The defaults in CV are
typical for each market, but they are the single biggest lever on a
near-the-line prop, so override them when you have better information (a
back-up quarterback, a blowout-prone game, a player on a snap count).

Pure standard library.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

__all__ = ['CV', 'norm_cdf', 'prob_over', 'prob_under', 'prob_at_least_one_td',
           'implied_line', 'blend']

# Typical coefficient of variation (sd / mean) by market. Receiving is the
# noisiest -- a single deep ball moves a receiver's day -- and quarterback
# passing yards the most stable, because attempts accumulate.
CV: Dict[str, float] = {
    'pass_yds': 0.30,
    'rush_yds': 0.50,
    'rec_yds': 0.60,
    'receptions': 0.40,
    'backfield_rush_yds': 0.35,   # two backs pooled -> less variance than one
    'default': 0.50,
}


def norm_cdf(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _lognormal_params(mean: float, cv: float) -> tuple:
    """Lognormal (mu, sigma) matching a given arithmetic mean and CV."""
    sigma = math.sqrt(math.log(1.0 + cv * cv))
    mu = math.log(mean) - 0.5 * sigma * sigma
    return mu, sigma


def prob_over(projection: float, line: float, market: str = 'default',
              cv: Optional[float] = None) -> float:
    """P(outcome > line) for a lognormal with the given mean.

    Returns 0.0 for a non-positive projection and 1.0 for a non-positive
    line, both of which are degenerate rather than erroneous.
    """
    if projection <= 0:
        return 0.0
    if line <= 0:
        return 1.0
    c = cv if cv is not None else CV.get(market, CV['default'])
    if c <= 0:
        return 1.0 if projection > line else 0.0
    mu, sigma = _lognormal_params(projection, c)
    return 1.0 - norm_cdf((math.log(line) - mu) / sigma)


def prob_under(projection: float, line: float, market: str = 'default',
               cv: Optional[float] = None) -> float:
    return 1.0 - prob_over(projection, line, market, cv)


def prob_at_least_one_td(expected_tds: float) -> float:
    """P(at least one TD) from an expected-touchdown rate, via Poisson."""
    if expected_tds <= 0:
        return 0.0
    return 1.0 - math.exp(-expected_tds)


def implied_line(projection: float, market: str = 'default',
                 cv: Optional[float] = None) -> float:
    """The line at which this projection is a true coin flip (the median).

    Useful for spotting where the book's line sits relative to your number:
    a median well above the posted line means the over is live.
    """
    if projection <= 0:
        return 0.0
    c = cv if cv is not None else CV.get(market, CV['default'])
    mu, _ = _lognormal_params(projection, c)
    return math.exp(mu)


def blend(prior: float, recent: float, prior_games: float,
          recent_weight_games: float = 3.0) -> float:
    """Weighted blend of a multi-game prior and a small recent sample.

    `recent_weight_games` is how many games of the prior the recent sample is
    worth. The default of 3 means one recent game counts for three of last
    season's -- enough to move the number on a role change without letting a
    single game dominate a full prior season.
    """
    if prior_games <= 0:
        return recent
    w_recent = recent_weight_games / (recent_weight_games + prior_games)
    return recent * w_recent + prior * (1.0 - w_recent)
