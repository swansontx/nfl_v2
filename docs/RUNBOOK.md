# Runbook — Recovering and Running the Pipeline for an Event

This runbook explains the steps to prepare data and run the modeling pipeline for a single event (e.g., Cowboys vs Raiders). Use this when recovering from an outage or preparing for game day.

Prerequisites

- Local repo: ~/nfl-props-app
- Python 3.10+ (system Python OK). Prefer conda/miniforge for heavy deps.
- Environment variables:
  - ODDS_API_KEY (TheOddsAPI key)
  - OPENAI_API_KEY (if assistant/LLM automation used)
- Ensure certifi is installed for SSL (see TROUBLESHOOTING.md)

Quick one-shot sequence (recommended)

1. Inspect cache for existing snapshots
   - ls ~/.cache/goose/computer_controller/web_*.json
   - If you have the event id, grep the cache to find recent snapshots:
     ```bash
     rg -i "<EVENT_ID>|cowboys|raiders" ~/.cache/goose/computer_controller || true
     ```

2. Fetch a fresh per-event snapshot (DraftKings + all markets)
   - If you have ODDS_API_KEY in env, run:
     ```bash
     python3 scripts/extract_map_event_markets.py --event <EVENT_ID>
     ```
   - This saves a cache snapshot (if not present) and writes outputs/event_<EVENT>_markets.tsv

3. Auto-augment registry and create mapping
   - Create provisional registry entries from the snapshot and produce mapping JSON
     ```bash
     python3 scripts/augment_registry_from_market.py --event <EVENT_ID>
     ```

4. Enrich registry using nflverse data
   - Download latest player lookup from nflverse releases (scripts exist to fetch stats_player_reg_<YEAR>.csv). We prefer using the expanded alias generation to improve full-name matches.
   - Build inputs/player_lookup_<YEAR>.json or use the generated inputs/player_lookup_nflverse_expanded.json produced by scripts/parse_nflverse_releases.py
   - Enrich augmented registry automatically (recommended flags):
     ```bash
     python3 scripts/enrich_registry_with_nflverse.py --event <EVENT_ID> --threshold 80
     # for better full-name coverage use the expanded lookup pipeline
     python3 scripts/parse_nflverse_releases.py && python3 scripts/enrich_registry_with_nflverse.py --event <EVENT_ID> --threshold 80 --lookup inputs/player_lookup_nflverse_expanded.json
     ```
   - Verify outputs/event_<EVENT>_nflverse_verification_<high|med|low|unmatched>.csv and inspect low-score rows.

5. Re-run models for the event
   - Run models using the (enriched) registry:
     ```bash
     python3 scripts/run_v5_models.py
     ```
   - Outputs:
     - outputs/cowboys_raiders_td_models_v5.json
     - outputs/cowboys_raiders_td_edges_v5.md

6. Quick injury/news check
   - Run the PFR/news scraping scripts (scripts/fetch_players.py or the news scraper) for the top modeled players and produce outputs/validation_news_report.txt

7. Produce final human report
   - Inspect outputs/*.md and outputs/*.csv
   - Copy selected artifacts to a share or produce a short summary for betting decisions.

Backing up & rollbacks

- The enrichment scripts create backups (player_registry.json.bak). If a run went wrong you can restore the backup.

Automated scheduling (optional)

- Use system cron or a platform scheduler to run light polling until game start:
  - Poll TheOddsAPI every 5–10 minutes, save snapshots, and re-run mapping+models only on new snapshots.
  - Be mindful of rate limits: add exponential backoff and stop polling once market coverage is complete.

Notes

- Keep API keys out of the repo. Use environment variables or a secrets manager.
- Persist snapshots (timestamped) for reproducibility and incident diagnosis.

