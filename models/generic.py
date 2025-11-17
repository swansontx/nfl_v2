def model_generic(prop_key, event_id=None, participant=None, historical_data=None, config=None):
    """Return a conservative wide-prior model output for unmodeled props.

    This simple handler is used as a fallback. It should return a dict with
    standardized keys so callers can ingest results uniformly.
    """
    return {
        "prop_key": prop_key,
        "event_id": event_id,
        "participant": participant,
        "handler": "models.generic:model_generic",
        "distribution": "wide_prior",
        "params": {"mean": None, "var": None},
        "modeled_prob": None,
        "notes": "Generic wide-prior model — add explicit model for better estimates",
    }
