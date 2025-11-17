# Architecture — Data Flow and Components

This doc outlines the pipeline components, data flow, and key design choices.

Overview

1. Ingest: TheOddsAPI per-event odds snapshots (prefer DraftKings). Snapshots saved to ~/.cache/goose/computer_controller and optionally copied to outputs/ for persistence.
2. Extract: scripts/extract_map_event_markets.py reads snapshots and flattens bookmaker->market->outcome rows (outputs/event_<EVENT>_markets.tsv).
3. Canonicalization: scripts/augment_registry_from_market.py creates or augments models/player_registry.json with provisional slugs for every DK player description.
4. Enrichment: scripts/enrich_registry_with_nflverse.py enriches provisional entries with nflverse player ids and teams (uses downloaded nflverse CSVs in inputs/).
5. Modeling: scripts/run_v5_models.py reads the registry, PFR-derived model_output_pfr.json, and nfl_data_py pbp (when available) to produce per-prop model outputs and edge lists.
6. Validation: news/injury scrapers and quick checks (scripts/fetch_players.py) add flags for manual review.
7. Output: outputs/ contains all result artifacts (CSVs, JSON, MD). Models write a per-event JSON and an edges MD for review.

Key design choices

- Use TheOddsAPI as the single source for bookmaker odds snapshots. Fetch DraftKings explicitly when possible.
- Prefer nflverse release CSVs (nflverse-data releases) as the canonical roster/player source for mapping because they are versioned and available via releases (more stable than web scraping).
- Keep a local player registry (models/player_registry.json) that maps canonical slugs to pfr_id/team/pos and allows augmentation for missing names.
- Avoid storing secrets in the repo — require ODDS_API_KEY and other secrets via env vars.

Resilience & reproducibility

- Snapshots are persisted with timestamps to enable replay and to debug mapping mismatches.
- Augmentation creates provisional entries (auto_added flag) and verification CSVs to prompt manual review.
- Backups: enrichment scripts back up the original player_registry.json before overwriting.

Extensions & future improvements

- Add a more robust fuzzy matching pipeline (rapidfuzz + name variant generation, nicknames table).
- Add a small web UI for manual resolution of unmatched players (select from top candidates) and commit to registry.
- Add alerting when DraftKings props are missing for a published game (to trigger polling or manual check).

