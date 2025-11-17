def model_rushing_yards(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.rushing:model_rushing_yards',
        'distribution': 'lognormal',
        'params': {'mean': 45.0, 'sd': 35.0},
        'modeled_prob': None,
        'note': 'placeholder'
    }

def model_rushing_tds(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.rushing:model_rushing_tds',
        'distribution': 'poisson',
        'params': {'lambda': 0.5},
        'modeled_prob': None,
        'note': 'placeholder'
    }
