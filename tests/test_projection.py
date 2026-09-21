import math

import pytest

from app.core.projection import (
    CV, norm_cdf, prob_over, prob_under, prob_at_least_one_td,
    implied_line, blend,
)


def test_norm_cdf_known_values():
    assert norm_cdf(0.0) == pytest.approx(0.5)
    assert norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert norm_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_prob_over_at_the_median_is_half():
    # By construction, P(X > median) == 0.5 for any lognormal.
    proj, cv = 70.0, 0.6
    median = implied_line(proj, cv=cv)
    assert prob_over(proj, median, cv=cv) == pytest.approx(0.5, abs=1e-6)


def test_lognormal_median_is_below_the_mean():
    # Right skew: the median must sit below the arithmetic mean, which is why
    # a projection equal to the line is NOT a coin flip.
    assert implied_line(100.0, cv=0.6) < 100.0


def test_projection_equal_to_line_is_worse_than_a_coin_flip():
    # Right skew bites hard at receiving-yards variance: a projection sitting
    # exactly ON the line only cashes ~39% of the time, not 50%. To back an
    # over you need the projection meaningfully above the posted number.
    p = prob_over(63.5, 63.5, market='rec_yds')
    assert p == pytest.approx(0.391, abs=0.005)


def test_prob_over_monotonic_in_line():
    probs = [prob_over(80.0, line, market='rec_yds') for line in (40, 60, 80, 100, 120)]
    assert probs == sorted(probs, reverse=True)


def test_prob_over_monotonic_in_projection():
    probs = [prob_over(proj, 60.0, market='rec_yds') for proj in (30, 50, 70, 90)]
    assert probs == sorted(probs)


def test_higher_cv_pulls_a_favoured_over_toward_a_coin_flip():
    # More variance makes a projection comfortably above the line less certain.
    low = prob_over(90.0, 60.0, cv=0.3)
    high = prob_over(90.0, 60.0, cv=0.9)
    assert low > high


def test_higher_cv_helps_an_unfavoured_over():
    # ...and makes a projection below the line more likely to get there.
    low = prob_over(40.0, 60.0, cv=0.3)
    high = prob_over(40.0, 60.0, cv=0.9)
    assert high > low


def test_prob_over_and_under_sum_to_one():
    assert prob_over(70, 63.5, market='rec_yds') + \
           prob_under(70, 63.5, market='rec_yds') == pytest.approx(1.0)


def test_degenerate_inputs():
    assert prob_over(0.0, 50.0) == 0.0
    assert prob_over(-5.0, 50.0) == 0.0
    assert prob_over(50.0, 0.0) == 1.0
    assert prob_over(50.0, 40.0, cv=0.0) == 1.0
    assert prob_over(30.0, 40.0, cv=0.0) == 0.0


def test_market_defaults_are_used():
    explicit = prob_over(70.0, 63.5, cv=CV['rec_yds'])
    by_name = prob_over(70.0, 63.5, market='rec_yds')
    assert explicit == pytest.approx(by_name)
    # unknown market falls back to the default CV
    assert prob_over(70.0, 63.5, market='nonsense') == \
           pytest.approx(prob_over(70.0, 63.5, cv=CV['default']))


def test_receiving_is_noisier_than_passing():
    assert CV['rec_yds'] > CV['rush_yds'] > CV['pass_yds']


def test_pooled_backfield_is_less_variable_than_one_back():
    assert CV['backfield_rush_yds'] < CV['rush_yds']


def test_prob_at_least_one_td():
    assert prob_at_least_one_td(0.0) == 0.0
    assert prob_at_least_one_td(0.5) == pytest.approx(1 - math.exp(-0.5))
    assert prob_at_least_one_td(10.0) > 0.999
    assert prob_at_least_one_td(-1.0) == 0.0


def test_blend_weights_recent_sample():
    # 1 recent game worth 3 prior games, against a 12-game prior:
    # weight on recent = 3 / (3 + 12) = 0.2
    assert blend(100.0, 200.0, prior_games=12) == pytest.approx(120.0)


def test_blend_with_no_prior_returns_recent():
    assert blend(100.0, 200.0, prior_games=0) == 200.0


def test_blend_with_huge_prior_barely_moves():
    assert blend(100.0, 200.0, prior_games=1000) == pytest.approx(100.0, abs=1.0)


def test_blend_recent_weight_is_tunable():
    strong = blend(100.0, 200.0, prior_games=12, recent_weight_games=12.0)
    weak = blend(100.0, 200.0, prior_games=12, recent_weight_games=1.0)
    assert strong > weak
    assert strong == pytest.approx(150.0)
