import pytest
import json
from unittest.mock import patch

import backend.odds_api as odds_api


def test_fetch_event_odds_uses_correct_url(monkeypatch):
    class DummyResp:
        def __init__(self, status_code=200, text='{}'):
            self.status_code = status_code
            self._text = text
            self.url = 'http://example'
        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception('http')
        def json(self):
            return json.loads(self._text)
        @property
        def text(self):
            return self._text

    def fake_session_get(url, params=None, timeout=None):
        # assert expected path
        assert '/sports/americanfootball_nfl/events/' in url
        return DummyResp(200, text='[]')

    monkeypatch.setattr(odds_api, '_requests_session_with_retries', lambda: type('S', (), {'get': staticmethod(fake_session_get)})())
    res = odds_api.fetch_event_odds('test_event_1', use_cache=False)
    assert res == []


def test_fetch_event_player_props_builds_markets(monkeypatch):
    called = {}
    def fake_fetch_event_odds(event_id, sport=None, regions=None, markets=None, bookmakers=None, use_cache=True, cache_name_suffix=None, timeout=20):
        called['markets'] = markets
        return {}
    monkeypatch.setattr(odds_api, 'fetch_event_odds', fake_fetch_event_odds)
    odds_api.fetch_event_player_props('eve1')
    assert 'player_pass_yds' in called['markets']
