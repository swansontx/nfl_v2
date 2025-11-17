def model_receptions(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    return {
        'prop_key': prop_key,
        'participant': participant,
        'handler': 'models.receptions:model_receptions',
        'distribution': 'normal',
        'params': {'mean': 4.5, 'sd': 2.5},
        'modeled_prob': None,
        'note': 'placeholder'
    }
