GOOSE NFL-PROPS AGENT — README & OPERATIONAL GUIDE

Generated: 2025-10-25

Purpose
-------
This documentation explains the "goose" NFL props agent (this repository) so other goose instances or engineers can understand, restart, extend, or recover the system. It covers architecture, data sources, key scripts, how to run the pipelines, how to capture sportsbook player-prop outcomes, how the simple API works, and troubleshooting/recovery steps if this agent crashes.

Repository layout (important paths)
----------------------------------
- backend/
  - nfl_sources.py        — adapter to load NFL data (prefers nflreadpy, falls back to nfl_data_py)
  - api.py                — FastAPI backend exposing schedule/odds/projections/props/parlay endpoints
- scripts/
  - download_nfl_2025.py  — full data ingestion (now uses backend.nfl_sources adapter)
  - generate_projections.py — generic projection generator
  - run_week_props.py     — week-specific props candidate generator + matching
  - generate_vikings_chargers_props.py — example focused script
  - scrape_dk_event_props.py — headless capture (Playwright) to fetch DK network responses
  - scrape_dk_event_props_target.py — targeted DK capture (search + capture)
  - scrape_dk_all_events.py — attempts to capture many events (used carefully)
  - scrape_dk_event_props_target.py — small helper to interact and capture per-event responses
  - produce_game_recs.py  — produces Markdown model recommendations
  - scripts/*             — other helper scripts
- nfl_data_2025_csv/      — NFL datasets (pbp, rosters, snap counts, NGS, injuries, etc.)
- data/odds_live/         — saved odds and event market JSON from TheOddsAPI and DK captures
- outputs/                — derived outputs: projections, props, reports, logs
- docs/                   — documentation (this file)

High-level architecture
-----------------------
1. Data ingestion: backend.nfl_sources loads NFL data. Prefer nflreadpy (nflverse) as canonical source. Adapter falls back to nfl_data_py.
2. Odds ingestion: TheOddsAPI used to fetch spreads/totals and event market listings. For player-outcome prices (player props) we use either TheOddsAPI (when available) or direct bookmaker captures (DraftKings) via a headless browser.
3. Feature engineering: scripts use PBP + NGS + snap counts to compute player/team features (QB dropbacks, INT rates, special teams, kicker distance buckets, turnover rates).
4. Modeling: simple projection scripts generate expected values/poisson/normal approximations per prop type.
5. Market matching & EV: match model projections to market prices (where available) to compute EV per $1 bet.
6. API & UI: backend/api.py exposes endpoints so frontends or other goose instances can load schedule, odds, projections and request parlay suggestions.

Data sources & credentials
-------------------------
- Preferred NFL data: nflreadpy (https://nflreadpy.nflverse.com). Install inside the project venv: pip install nflreadpy. If not available, adapter falls back to nfl_data_py.
- Odds data: TheOddsAPI (configured via ODDS_API_KEY). The repo expects a key in either:
  - environment variable ODDS_API_KEY, or
  - backend/.odds_api_key (local file, convenient for dev)
- Bookmaker scraping: DraftKings (public site). We use Playwright to capture network JSON. Install/playwright browsers via:
  - pip install playwright
  - playwright install chromium

Key files for credentials
- backend/.odds_api_key (optional local file containing the TheOddsAPI key)

How to run (developer quick-start)
----------------------------------
1. Create & activate venv (macOS example):
   python3 -m venv .venv && source .venv/bin/activate
2. Install Python dependencies:
   pip install -r requirements.txt
   (If requirements.txt not present, install at least: pandas, requests, fastapi, uvicorn, playwright)
3. If you will capture DraftKings pages, install playwright browsers:
   playwright install chromium
4. Configure odds API key: export ODDS_API_KEY="<your_key>" or create backend/.odds_api_key
5. Run data download (nfl_data_2025_csv/download_nfl_2025.py):
   python3 nfl_data_2025_csv/download_nfl_2025.py
   - This pulls pbp, rosters, snap counts, injuries, NGS (if available), and saves CSVs in nfl_data_2025_csv/
6. Fetch live odds (spreads & totals) via TheOddsAPI (script or programmatic):
   python3 - <<PY
   from backend import odds_api
   data = odds_api.fetch_odds(markets='spreads,totals', use_cache=False)
   PY
7. Generate projections & props candidates:
   python3 scripts/generate_projections.py
   python3 scripts/run_week_props.py
8. Start API server (optional):
   uvicorn backend.api:app --reload --port 8000
   - endpoints: /api/schedule, /api/selected_events, /api/odds/latest, /api/event/{id}/markets, /api/projections, /api/props_candidates, /api/injuries, /api/parlay/suggest

How the DraftKings capture workflow works (recommended approach)
--------------------------------------------------------------
Goal: obtain outcome-level market JSON (player props with prices). High-level steps:
1. Use Playwright headless to open sportsbook.draftkings.com.
2. Search or navigate to the specific event card, click to open the event page.
3. Click the "Player Props" tab or expand the player props subcategory. This triggers the client to request a market JSON that includes markets + selections/outcomes with prices.
4. Capture network responses (responses with content-type application/json). Save them to outputs/dk_target/.
5. Parse captured JSONs for elements containing "markets" or "selections" and extract market_key, outcome name, point, and price.
6. Save parsed outcomes to outputs/dk_event_markets_parsed/<event>_props.csv
7. Replay the same API request programmatically (requests.get with identical headers) to fetch outcomes for other events if the endpoint is consistent.

Implementation notes on capture/replay
- Some API endpoints are geo- or site-specific (US-OR-SB vs US-CA-SB). Use the same base host observed in the captured responses.
- The captured manifest/template JSON often includes parameters (eventsQuery, marketsQuery) that you can reuse to perform a programmatic fetch.
- If capture returns only template data (no outcomes), you likely did not open the specific subcategory; interactively opening the Player Props tab usually triggers the outcomes fetch.

Modeling approach used (current)
--------------------------------
- QB INT: estimate INT lambda = pass_att_per_game * int_rate (season). Use Poisson tail for lines (0.5/1.5).
- QB pass yards: estimate mean = pass_yards_per_game; assume normal-ish dispersion sd ~ 35% of mean; compute tail probabilities for common lines (200.5/225.5/250.5).
- Receiver yards + rush yards: mean = yds_per_game; sd ~ 60% of mean for individual players; approximate tail probabilities.
- Kicker FG attempts: aggregate FG attempts / season -> fg_att_per_game -> Poisson for 0.5/1.5 lines.
- Turnovers/special teams: computed from PBP (turnovers per game, punt/kick return yards, kicker distance splits).

How matching & EV is computed
----------------------------
- Market implied probability (from American odds):
  - if a > 0: implied = 100/(a+100)
  - if a < 0: implied = -a/(-a+100)
- Decimal odds conversion: if a > 0 decimal = 1 + a/100 else decimal = 1 + 100/(-a)
- EV per $1 = model_prob * decimal - 1
- For parlays: joint probability assumed independent (product of model probs), payout product of decimal odds; EV computed similarly.

API reference (quick)
---------------------
- GET /api/health — health
- GET /api/schedule — returns schedule CSV as JSON
- GET /api/selected_events — returns the last saved selected events (odds filter)
- GET /api/odds/latest — returns the latest spreads/totals file fetched from TheOddsAPI (cached)
- GET /api/event/{event_id}/markets — returns cached event markets (from data/odds_live/*)
- GET /api/projections — returns latest projections CSV
- GET /api/props_candidates — returns latest props candidate CSV
- GET /api/injuries — returns parsed ESPN injuries CSV
- POST /api/parlay/suggest — body: { selections: [{player,market_price,model_prob,...}], max_legs }; returns suggested parlays and EVs

Troubleshooting & recovery (if this goose instance dies)
-------------------------------------------------------
1. Recreate venv & install deps. Key deps: pandas, requests, fastapi, uvicorn, playwright (if capturing DK), nflreadpy (optional).
2. Restore keys: ODDS_API_KEY in env or backend/.odds_api_key.
3. Re-run data download (nfl_data_2025_csv/download_nfl_2025.py). If nflreadpy is desired, pip install nflreadpy in the venv before running.
4. Re-fetch odds: use backend.odds_api.fetch_odds (script or run commands in README).
5. Re-run model scripts (scripts/generate_projections.py, scripts/run_week_props.py, scripts/produce_game_recs.py) to regenerate outputs.
6. If market prices missing, re-run targeted DK capture scripts (scripts/scrape_dk_event_props_target.py) for events you need and parse their outputs.
7. Run the FastAPI server: uvicorn backend.api:app --reload and use endpoints to inspect data.
8. If you see rate limits or 422s from TheOddsAPI, check plan/quota. For DK activity, run captures slowly (1 event at a time, small delays).

Developer notes & TODOs
-----------------------
- TODO: Convert modeling to use NGS pressure/sack/AY/A features (ngs_passing_2025.csv loaded in nfl_data_2025_csv/). This will materially improve QB INT and pass-yard estimates.
- TODO: Improve player name matching when joining model candidates to market outcomes (use fuzzy matching and rosters mapping via nflreadpy seasonal rosters).
- TODO: Harden and standardize the DK replay endpoint builder (taking the template parameters and building canonical requests).
- TODO: Add unit tests for adapter and small data validation checks (e.g., ensure PBP has recent date).

Contact / ownership
-------------------
- Owner: goose agent (this repo). Human contact: repo owner (check git history for last committer).


If anything is unclear or you want this expanded into a runbook with exact shell commands and checklists, tell me which sections to expand and I’ll produce a longer runbook file.
