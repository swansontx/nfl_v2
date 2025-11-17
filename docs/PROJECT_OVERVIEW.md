# NFL Props App — Project Overview

Purpose

This repository builds a recommendation pipeline for NFL player and game props with a primary focus on DraftKings pricing. The goal is to ingest bookmaker odds, enrich with canonical player and play-by-play data (nflverse / nfl_data_py), run predictive models, and output prioritized edges and recommendations for manual review and execution.

Primary objectives

- Capture DraftKings player prop markets (via TheOddsAPI) reliably and persist snapshots for reproducibility.
- Canonicalize bookmaker outcomes to nflverse/nfl_data_py player identifiers so model features align with real-world player data.
- Generate model probabilities, compute edges vs implied book probabilities, and produce human-consumable outputs (ranked lists, markdown reports, CSVs).
- Provide quick triage (injury/news) and produce recommendations for betting or deeper analysis.

Who this doc is for

- New collaborators trying to get the system running for a game.
- Engineers/analysts recovering after an outage to re-run the pipeline for a specific event.
- Maintainers wanting a high-level map of components, scripts, and decision rationale.

Where to start (quick)

1. Inspect cached snapshots and outputs:
   - Cache: ~/.cache/goose/computer_controller/
   - Project outputs: nfl-props-app/outputs/
   - Important logs: /Users/travisswanson/Documents/log.txt and LOG_SUMMARY.md
2. Fetch a single event snapshot (if needed):
   - Use scripts/fetch_event_props.py or the curl example in PROGRESS.md
3. Run extraction + mapping + models (one-liners):
   - python3 scripts/extract_map_event_markets.py --event <EVENT_ID>
   - python3 scripts/augment_registry_from_market.py --event <EVENT_ID>
   - python3 scripts/enrich_registry_with_nflverse.py --event <EVENT_ID>
   - python3 scripts/run_v5_models.py

Where files land

- models/: canonical player registry files (player_registry.json, player_registry_augmented.json, player_registry_enriched.json)
- outputs/: generated reports, CSVs, and model outputs (e.g. cowboys_raiders_td_models_v5.json)
- scripts/: small orchestration and extraction scripts (fetch_event_props.py, run_v5_models.py, extract_map_event_markets.py, augment_registry_from_market.py, enrich_registry_with_nflverse.py)
- inputs/: externally downloaded reference files (nflverse CSVs) used to enrich mapping

Contact / ownership

- Primary maintainer: travisswanson (local). Keep secrets (API keys) out of the repo; use environment variables.


README pointers

- See PROGRESS.md for the current project status and recent findings.
- See docs/RUNBOOK.md for step-by-step recovery instructions.
- See docs/ARCHITECTURE.md for component diagrams and data flow.
