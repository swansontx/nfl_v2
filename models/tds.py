def model_anytime_td(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    # Simple Poisson/Bernoulli style placeholder: estimate low probability
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.tds:model_anytime_td',
        'distribution': 'poisson',
        'params': {'lambda': 0.25},
        'modeled_prob': None,
        'note': 'placeholder: anytime TD prior'
    }

def model_first_td(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.tds:model_first_td',
        'distribution': 'bernoulli',
        'params': {'p': 0.02},
        'modeled_prob': None,
        'note': 'placeholder'
    }

def model_last_td(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.tds:model_last_td',
        'distribution': 'bernoulli',
        'params': {'p': 0.02},
        'modeled_prob': None,
        'note': 'placeholder'
    }
