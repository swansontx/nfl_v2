#!/usr/bin/env python3
"""
Add core prop patterns to models/registry.yaml (if missing) with sensible handler placeholders.
Set priority=critical for core player prop types and include preferred_books=['draftkings','fanduel','betmgm'] metadata.
"""
from pathlib import Path
import yaml

ROOT = Path('.').resolve()
REG_PATH = ROOT / 'models' / 'registry.yaml'

core_patterns = {
    'player_passing_yards': {
        'pattern': 'player_*_passing_yards',
        'handler': 'models.passing:model_passing_yards',
        'distribution': 'lognormal',
        'required_data': ['nflfastR_pbp', 'player_gamelogs'],
        'priority': 'critical'
    },
    'player_passing_tds': {
        'pattern': 'player_*_passing_tds',
        'handler': 'models.tds:model_passing_tds',
        'distribution': 'poisson',
        'required_data': ['pfr_gamelogs'],
        'priority': 'critical'
    },
    'player_receptions': {
        'pattern': 'player_*_receptions',
        'handler': 'models.receptions:model_receptions',
        'distribution': 'normal',
        'required_data': ['pfr_gamelogs'],
        'priority': 'critical'
    },
    'player_receiving_yards': {
        'pattern': 'player_*_receiving_yards',
        'handler': 'models.receiving:model_receiving_yards',
        'distribution': 'lognormal',
        'required_data': ['pfr_gamelogs','nflfastR_pbp'],
        'priority': 'critical'
    },
    'player_receiving_tds': {
        'pattern': 'player_*_receiving_tds',
        'handler': 'models.tds:model_receiving_tds',
        'distribution': 'poisson',
        'required_data': ['pfr_gamelogs','redzone_shares'],
        'priority': 'critical'
    },
    'player_rushing_yards': {
        'pattern': 'player_*_rushing_yards',
        'handler': 'models.rushing:model_rushing_yards',
        'distribution': 'lognormal',
        'required_data': ['pfr_gamelogs','nflfastR_pbp'],
        'priority': 'critical'
    },
    'player_rushing_tds': {
        'pattern': 'player_*_rushing_tds',
        'handler': 'models.tds:model_rushing_tds',
        'distribution': 'poisson',
        'required_data': ['pfr_gamelogs','redzone_shares'],
        'priority': 'critical'
    },
    'player_rush_attempts': {
        'pattern': 'player_*_rush_attempts',
        'handler': 'models.rushing:model_rush_attempts',
        'distribution': 'poisson',
        'required_data': ['pfr_gamelogs'],
        'priority': 'optional'
    },
    'player_anytime_td': {
        'pattern': 'player_*_anytime_td',
        'handler': 'models.tds:model_anytime_td',
        'distribution': 'poisson',
        'required_data': ['pfr_gamelogs','redzone_shares'],
        'priority': 'critical'
    },
    'player_1st_td': {
        'pattern': 'player_*_1st_td',
        'handler': 'models.tds:model_first_td',
        'distribution': 'bernoulli',
        'required_data': ['pfr_gamelogs','redzone_shares'],
        'priority': 'optional'
    },
    'player_last_td': {
        'pattern': 'player_*_last_td',
        'handler': 'models.tds:model_last_td',
        'distribution': 'bernoulli',
        'required_data': ['pfr_gamelogs'],
        'priority': 'optional'
    },
    'team_points': {
        'pattern': 'team_*_points',
        'handler': 'models.team:model_team_points',
        'distribution': 'normal',
        'required_data': ['team_stats'],
        'priority': 'optional'
    },
    'h2h': {
        'pattern': 'h2h_*',
        'handler': 'models.market:model_h2h',
        'distribution': 'implied',
        'required_data': [],
        'priority': 'optional'
    },
    'spreads': {
        'pattern': 'spreads_*',
        'handler': 'models.market:model_spread',
        'distribution': 'implied',
        'required_data': [],
        'priority': 'optional'
    },
    'totals': {
        'pattern': 'totals_*',
        'handler': 'models.market:model_totals',
        'distribution': 'implied',
        'required_data': [],
        'priority': 'optional'
    }
}


def main():
    reg = {}
    if REG_PATH.exists():
        reg = yaml.safe_load(REG_PATH.read_text()) or {}
    changed = False
    for k, entry in core_patterns.items():
        if k not in reg:
            reg[k] = entry
            # include preferred_books metadata
            reg[k]['preferred_books'] = ['draftkings','fanduel','betmgm']
            changed = True
    if changed:
        REG_PATH.write_text(yaml.safe_dump(reg, sort_keys=False))
        print('Updated registry.yaml with core patterns')
    else:
        print('Registry already contains core patterns')

if __name__ == '__main__':
    main()
