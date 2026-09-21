import time

import pytest

from backend import nflverse


# --------------------------------------------------------------- url building

def test_dataset_url_with_season():
    url = nflverse.dataset_url('injuries', 2026)
    assert url.endswith('/injuries/injuries_2026.csv')
    assert url.startswith('https://github.com/nflverse/nflverse-data/releases/download')


def test_dataset_url_without_season():
    assert nflverse.dataset_url('schedules').endswith('/schedules/games.csv')


def test_dataset_url_requires_season_when_templated():
    with pytest.raises(ValueError):
        nflverse.dataset_url('injuries')


def test_unknown_dataset_raises_keyerror():
    with pytest.raises(KeyError):
        nflverse.dataset_url('not_a_dataset')


def test_retired_dataset_explains_itself():
    with pytest.raises(nflverse.DatasetUnavailable) as exc:
        nflverse.dataset_url('participation', 2026)
    assert 'unavailable' in str(exc.value)


# ------------------------------------------------------------------- fetching

class _Resp:
    def __init__(self, status_code=200, content=b''):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f'http {self.status_code}')


def test_fetch_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(nflverse, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(nflverse.requests, 'get',
                        lambda url, **kw: _Resp(200, b'a,b\n1,2\n'))
    path = nflverse.fetch('injuries', 2026)
    assert path.read_text() == 'a,b\n1,2\n'
    assert path.name == 'injuries_2026.csv'


def test_fetch_404_raises_dataset_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(nflverse, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(nflverse.requests, 'get', lambda url, **kw: _Resp(404, b''))
    with pytest.raises(nflverse.DatasetUnavailable) as exc:
        nflverse.fetch('injuries', 1999)
    assert '1999' in str(exc.value)


def test_fetch_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(nflverse, 'CACHE_DIR', tmp_path)
    target = tmp_path / 'injuries_2026.csv'
    target.write_text('cached\n')

    def boom(*a, **kw):
        raise AssertionError('should not hit the network')

    monkeypatch.setattr(nflverse.requests, 'get', boom)
    assert nflverse.fetch('injuries', 2026).read_text() == 'cached\n'


def test_fetch_refetches_when_cache_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(nflverse, 'CACHE_DIR', tmp_path)
    target = tmp_path / 'injuries_2026.csv'
    target.write_text('old\n')
    old = time.time() - 48 * 3600
    import os
    os.utime(target, (old, old))
    monkeypatch.setattr(nflverse.requests, 'get', lambda url, **kw: _Resp(200, b'new\n'))
    assert nflverse.fetch('injuries', 2026, max_age_hours=6).read_text() == 'new\n'


def test_empty_cache_file_is_not_considered_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(nflverse, 'CACHE_DIR', tmp_path)
    (tmp_path / 'injuries_2026.csv').write_text('')
    monkeypatch.setattr(nflverse.requests, 'get', lambda url, **kw: _Resp(200, b'ok\n'))
    assert nflverse.fetch('injuries', 2026).read_text() == 'ok\n'


# ------------------------------------------------------------------ filtering

ROWS = [
    {'team': 'LA', 'week': '1', 'player': 'Nacua'},
    {'team': 'LA', 'week': '2', 'player': 'Adams'},
    {'team': 'NYG', 'week': '2', 'player': 'Nabers'},
]


def test_filter_rows_exact_match():
    got = nflverse.filter_rows(ROWS, {'team': 'LA'})
    assert [r['player'] for r in got] == ['Nacua', 'Adams']


def test_filter_rows_coerces_numbers_to_strings():
    got = nflverse.filter_rows(ROWS, {'week': 2})
    assert [r['player'] for r in got] == ['Adams', 'Nabers']


def test_filter_rows_sequence_matches_any():
    got = nflverse.filter_rows(ROWS, {'team': ('LA', 'NYG'), 'week': 2})
    assert [r['player'] for r in got] == ['Adams', 'Nabers']


def test_filter_rows_multiple_keys_are_and():
    assert nflverse.filter_rows(ROWS, {'team': 'LA', 'week': 9}) == []


# ------------------------------------------------------------------- coercion

def test_num_handles_missing_and_junk():
    assert nflverse.num('12.5') == 12.5
    assert nflverse.num('') == 0.0
    assert nflverse.num('NA') == 0.0
    assert nflverse.num(None) == 0.0
    assert nflverse.num('abc', default=-1.0) == -1.0
    assert nflverse.num('7') == 7.0


# --------------------------------------------------------------------- market

def test_game_market_extracts_lines():
    row = {
        'game_id': '2026_02_NYG_LA', 'away_team': 'NYG', 'home_team': 'LA',
        'gameday': '2026-09-21', 'gametime': '20:15', 'stadium': 'SoFi Stadium',
        'roof': 'dome', 'spread_line': '6.5', 'total_line': '47.5',
        'away_moneyline': '240', 'home_moneyline': '-298',
    }
    m = nflverse.game_market(row)
    assert m['spread_line'] == 6.5
    assert m['total_line'] == 47.5
    assert m['home_moneyline'] == -298
    assert m['away_team'] == 'NYG'


def test_find_game_matches_home_or_away(monkeypatch):
    rows = [
        {'season': '2026', 'week': '2', 'home_team': 'LA', 'away_team': 'NYG'},
        {'season': '2026', 'week': '2', 'home_team': 'KC', 'away_team': 'PHI'},
    ]
    monkeypatch.setattr(nflverse, 'load', lambda *a, **kw: nflverse.filter_rows(rows, kw.get('where') or {}))
    assert nflverse.find_game(2026, 2, 'NYG')['home_team'] == 'LA'
    assert nflverse.find_game(2026, 2, 'LA')['away_team'] == 'NYG'
    assert nflverse.find_game(2026, 2, 'SEA') is None


# ------------------------------------------------------------ played_in_game

def test_qb_judged_on_attempts_not_touches():
    # The Dart case: a QB with a single kneel-down carry and no attempts did
    # not play, even though targets+carries is nonzero.
    benched = {'position': 'QB', 'attempts': '0', 'carries': '1', 'targets': '0'}
    assert nflverse.played_in_game(benched) is False

    started = {'position': 'QB', 'attempts': '29', 'carries': '11', 'targets': '0'}
    assert nflverse.played_in_game(started) is True


def test_qb_attempt_threshold_is_tunable():
    row = {'position': 'QB', 'attempts': '13', 'carries': '2'}
    assert nflverse.played_in_game(row) is True
    assert nflverse.played_in_game(row, min_qb_attempts=15) is False


def test_skill_player_needs_one_touch():
    assert nflverse.played_in_game(
        {'position': 'WR', 'targets': '1', 'carries': '0'}) is True
    assert nflverse.played_in_game(
        {'position': 'RB', 'targets': '0', 'carries': '3'}) is True
    assert nflverse.played_in_game(
        {'position': 'WR', 'targets': '0', 'carries': '0'}) is False


def test_missing_position_falls_back_to_touches():
    assert nflverse.played_in_game({'targets': '2'}) is True
    assert nflverse.played_in_game({}) is False


def test_handles_na_cells():
    assert nflverse.played_in_game(
        {'position': 'WR', 'targets': 'NA', 'carries': ''}) is False
