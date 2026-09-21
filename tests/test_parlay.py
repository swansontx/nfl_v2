import math

import pytest

from app.core.parlay import (
    american_to_decimal,
    decimal_to_american,
    implied_prob,
    devig_two_way,
    correlation_matrix,
    joint_probability,
    parlay_ev,
    suggest_parlays,
)


# ---------------------------------------------------------------- odds maths

def test_american_to_decimal_both_signs():
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-110) == pytest.approx(1.909090, abs=1e-5)
    assert american_to_decimal(250) == pytest.approx(3.5)


def test_american_to_decimal_rejects_junk():
    assert american_to_decimal(None) is None
    assert american_to_decimal('abc') is None
    assert american_to_decimal(0) is None


def test_decimal_american_round_trip():
    for am in (-400, -220, -110, 100, 150, 275, 900):
        assert decimal_to_american(american_to_decimal(am)) == am


def test_implied_prob_matches_decimal():
    assert implied_prob(-110) == pytest.approx(1 / 1.9090909, abs=1e-6)
    assert implied_prob(100) == pytest.approx(0.5)


def test_devig_two_way_sums_to_one():
    a, b = devig_two_way(-110, -110)
    assert a == pytest.approx(0.5)
    assert b == pytest.approx(0.5)
    assert a + b == pytest.approx(1.0)


def test_devig_removes_hold_from_favourite():
    # -340 / +275 is roughly the Rams/Giants moneyline. Raw implied
    # probabilities sum to more than 1; de-vigged they must sum to exactly 1
    # and the favourite must come down off its raw number.
    raw_fav = implied_prob(-340)
    fav, dog = devig_two_way(-340, 275)
    assert fav + dog == pytest.approx(1.0)
    assert fav < raw_fav


# ------------------------------------------------------------------- copula

def test_zero_correlation_is_exact_product():
    probs = [0.6, 0.55, 0.7]
    assert joint_probability(probs) == pytest.approx(0.6 * 0.55 * 0.7)
    identity = correlation_matrix(3)
    assert joint_probability(probs, corr=identity) == pytest.approx(0.6 * 0.55 * 0.7)


def test_bivariate_copula_matches_closed_form():
    """For two coin-flip legs the orthant probability has a closed form:

        P(both) = 1/4 + arcsin(r) / (2*pi)

    which is a clean check that the copula is actually correct and not just
    directionally right.
    """
    for r in (-0.5, -0.2, 0.0, 0.3, 0.6, 0.8):
        expected = 0.25 + math.asin(r) / (2 * math.pi)
        got = joint_probability([0.5, 0.5], corr=correlation_matrix(2, {(0, 1): r}),
                                n_sims=60000)
        assert got == pytest.approx(expected, abs=0.006), f'r={r}'


def test_positive_correlation_raises_joint_probability():
    probs = [0.55, 0.6]
    indep = 0.55 * 0.6
    corr = correlation_matrix(2, {(0, 1): 0.5})
    assert joint_probability(probs, corr=corr) > indep


def test_negative_correlation_lowers_joint_probability():
    probs = [0.55, 0.6]
    indep = 0.55 * 0.6
    corr = correlation_matrix(2, {(0, 1): -0.5})
    assert joint_probability(probs, corr=corr) < indep


def test_near_perfect_correlation_approaches_min_leg():
    probs = [0.5, 0.7]
    corr = correlation_matrix(2, {(0, 1): 0.99})
    got = joint_probability(probs, corr=corr, n_sims=60000)
    assert got == pytest.approx(min(probs), abs=0.03)


def test_degenerate_probabilities():
    assert joint_probability([]) == 1.0
    assert joint_probability([0.0, 0.9]) == 0.0
    assert joint_probability([1.0, 1.0]) == 1.0
    assert joint_probability([0.42]) == pytest.approx(0.42)


def test_joint_probability_is_deterministic():
    probs = [0.6, 0.5, 0.55]
    corr = correlation_matrix(3, {(0, 1): 0.4, (1, 2): 0.3})
    a = joint_probability(probs, corr=corr)
    b = joint_probability(probs, corr=corr)
    assert a == b


def test_inconsistent_correlations_are_repaired_not_fatal():
    # a~b and b~c strongly positive but a~c strongly negative is not a valid
    # correlation matrix; we shrink rather than blow up.
    corr = correlation_matrix(3, {(0, 1): 0.9, (1, 2): 0.9, (0, 2): -0.9})
    p = joint_probability([0.5, 0.5, 0.5], corr=corr)
    assert 0.0 <= p <= 1.0


def test_correlation_matrix_is_symmetric_and_validated():
    m = correlation_matrix(3, {(0, 2): 0.4})
    assert m[0][2] == m[2][0] == pytest.approx(0.4)
    assert all(m[i][i] == 1.0 for i in range(3))
    with pytest.raises(IndexError):
        correlation_matrix(2, {(0, 5): 0.3})


# ------------------------------------------------------------------ pricing

def test_parlay_ev_flags_invented_payout():
    res = parlay_ev([0.6, 0.6], [1.9, 1.9])
    assert res['priced_independently'] is True
    assert res['payout'] == pytest.approx(1.9 * 1.9)


def test_parlay_ev_uses_supplied_price():
    res = parlay_ev([0.6, 0.6], [1.9, 1.9], price=3.0)
    assert res['priced_independently'] is False
    assert res['payout'] == pytest.approx(3.0)
    assert res['ev_per_1'] == pytest.approx(0.36 * 3.0 - 1.0)


def test_parlay_ev_reports_correlation_lift():
    corr = correlation_matrix(2, {(0, 1): 0.5})
    res = parlay_ev([0.55, 0.6], [1.9, 1.9], corr=corr)
    assert res['independent_prob'] == pytest.approx(0.33)
    assert res['correlation_lift'] > 0
    assert res['joint_prob'] > res['independent_prob']


def test_correlated_sgp_at_book_price_can_beat_naive_view():
    """The practical point of the module: a positively correlated SGP is more
    likely to land than the product suggests, so pricing it independently
    understates the hit rate even though the book pays less than the product.
    """
    probs = [0.55, 0.58]
    corr = correlation_matrix(2, {(0, 1): 0.45})
    naive = parlay_ev(probs, [1.91, 1.91])
    real = parlay_ev(probs, [1.91, 1.91], corr=corr, price=3.1)
    assert real['joint_prob'] > naive['joint_prob']
    assert real['payout'] < naive['payout']


# --------------------------------------------------------------- suggestion

def _sel(player, prob, price, market='rec_yds'):
    return {'player': player, 'model_prob': prob, 'market_price': price, 'market': market}


def test_suggest_parlays_empty():
    assert suggest_parlays([]) == {'selected': [], 'parlay_suggestions': []}


def test_suggest_parlays_defaults_to_multi_leg():
    sels = [_sel('A', 0.6, -110), _sel('B', 0.55, -120), _sel('C', 0.52, 100)]
    out = suggest_parlays(sels, max_legs=3)
    assert out['parlay_suggestions']
    # min_legs defaults to 2, so no single-leg "parlays"
    assert all(len(p['legs']) >= 2 for p in out['parlay_suggestions'])


def test_suggest_parlays_skips_legs_without_model_prob():
    sels = [_sel('A', 0.6, -110), _sel('B', None, -120), _sel('C', 0.52, 100)]
    out = suggest_parlays(sels, max_legs=3)
    for p in out['parlay_suggestions']:
        assert 'B' not in p['legs']
    # but the leg is still reported in `selected`
    assert any(s['player'] == 'B' for s in out['selected'])


def test_suggest_parlays_applies_correlation_by_original_index():
    sels = [_sel('A', 0.55, -110), _sel('B', 0.6, -110)]
    plain = suggest_parlays(sels, max_legs=2)['parlay_suggestions'][0]
    corr = suggest_parlays(sels, max_legs=2, pair_corr={(0, 1): 0.6})['parlay_suggestions'][0]
    assert corr['joint_prob'] > plain['joint_prob']
    assert corr['correlation_lift'] > 0
    assert plain['correlation_lift'] == pytest.approx(0.0)


def test_suggest_parlays_honours_real_parlay_price():
    sels = [_sel('A', 0.55, -110), _sel('B', 0.6, -110)]
    out = suggest_parlays(sels, max_legs=2, parlay_prices={(0, 1): 2.8})
    top = out['parlay_suggestions'][0]
    assert top['payout' if 'payout' in top else 'implied_payout'] == pytest.approx(2.8)
    assert top['priced_independently'] is False


def test_suggest_parlays_sorted_by_ev():
    sels = [_sel('A', 0.7, 150), _sel('B', 0.3, -200), _sel('C', 0.6, 100)]
    out = suggest_parlays(sels, max_legs=3)
    evs = [p['ev_per_1'] for p in out['parlay_suggestions']]
    assert evs == sorted(evs, reverse=True)
