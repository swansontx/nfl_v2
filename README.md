# NFL Props App

This repo contains a backend API and a simple frontend to view NFL projections and props. The architecture has:

- FastAPI backend (backend/api.py)
- Background recompute worker (scripts/generate_projections.py invoked by app/services/worker.py)
- Scheduler using APScheduler (app/services/scheduler.py)
- Minimal React + Vite frontend (frontend/)
- Docker + docker-compose for local development

Run locally (quick):

1. Install dependencies: pip install -r requirements.txt
2. Start API: uvicorn backend.api:app --reload
3. Start frontend dev server: cd frontend && npm install && npm run dev

Or run with docker-compose:

  docker-compose up --build


## Data sources

`backend/nflverse.py` is the primary data layer: [nflverse-data](https://github.com/nflverse/nflverse-data)
published as CSV on GitHub releases. Free, no API key, updated in-season.
Covers schedules (with spread/total/moneyline), play-by-play, weekly player
and team stats, official injury reports, snap counts, rosters and PFR
advanced stats.

```python
from backend import nflverse as nv

game  = nv.find_game(2026, week=2, team='NYG')
inj   = nv.injuries(2026, week=2, teams=('NYG', 'LA'))
usage = nv.player_usage(2026, week=1, team='LA')
```

Cached under `data/nflverse/` (gitignored) with a 6-hour TTL.
`nv.available(season)` probes which datasets exist for a season.

Pre-game report for any game:

```
python3 scripts/game_report.py --season 2026 --week 2 --team NYG
python3 scripts/game_report.py --props scripts/props_2026_02_NYG_LA.json
```

### Player props

nflverse has **game-level markets only**. Player prop lines need a book or an
aggregator (`backend/odds_api.py` wraps The-Odds-API), which requires an
`ODDS_API_KEY`. A reachability sweep on 2026-09-21 found this environment's
egress policy blocks ESPN, Sleeper, DraftKings, Kalshi, Pro-Football-Reference
and api.the-odds-api.com; only github.com and raw.githubusercontent.com are
reachable. Until that changes, prop lines have to be supplied by hand -- see
`scripts/props_2026_02_NYG_LA.json` for the format.

## Parlay pricing

`app/core/parlay.py` prices parlays with a Gaussian copula rather than
multiplying leg probabilities. Same-game legs share a game script, so the
independent product materially understates correlated parlays (and flatters
anti-correlated ones). Supply the book's real SGP price via `price=`; without
it the payout falls back to the product of the legs and is flagged
`priced_independently=True`, which is an upper bound, not an edge.
