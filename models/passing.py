def model_passing_yards(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    # Very simple placeholder model: return a generic prior estimate.
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.passing:model_passing_yards',
        'distribution': 'normal',
        'params': {'mean': 220.0, 'sd': 60.0},
        'modeled_prob': None,
        'note': 'placeholder: replace with nflfastR-based model'
    }


def model_passing_tds(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    # Poisson prior placeholder
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.passing:model_passing_tds',
        'distribution': 'poisson',
        'params': {'lambda': 1.2},
        'modeled_prob': None,
        'note': 'placeholder: replace with PFR-based TD model'
    }
