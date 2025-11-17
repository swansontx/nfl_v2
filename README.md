# NFL Props App

This repo contains a backend API and a simple frontend to view NFL projections and props. The architecture has:

- FastAPI backend (backend/api.py)
- Background recompute worker (scripts/generate_projections.py invoked by app/services/worker.py)
- Scheduler using APScheduler (app/services/scheduler.py)
- Minimal React + Vite frontend (frontend/)
- Docker + docker-compose for local development

Run locally (quick):

1. Install dependencies: pip install -r requirements.txt (prefer conda/miniforge for arm64 heavy deps)
2. Ensure certifi is installed and SSL_CERT_FILE is set if you encounter SSL errors:

   ```bash
   pip install --user certifi
   export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")
   ```

3. Start API: uvicorn backend.api:app --reload
4. Start frontend dev server: cd frontend && npm install && npm run dev

Fetching odds and running models (event workflow):

- Use the scripts in scripts/ to fetch event snapshots, extract markets, augment and enrich the player registry, and run models.

Example one-off:

```bash
# fetch + extract markets
python3 scripts/extract_map_event_markets.py --event <EVENT_ID>
# auto-augment registry from the snapshot
python3 scripts/augment_registry_from_market.py --event <EVENT_ID>
# enrich using nflverse release data (downloaded csv -> inputs/player_lookup_<YEAR>.json)
python3 scripts/enrich_registry_with_nflverse.py --event <EVENT_ID> --threshold 80
# run the models
python3 scripts/run_v5_models.py
```

Read the docs/ directory for detailed runbook, architecture, and troubleshooting:

- docs/PROJECT_OVERVIEW.md
- docs/RUNBOOK.md
- docs/ARCHITECTURE.md
- docs/TROUBLESHOOTING.md

Or run with docker-compose:

  docker-compose up --build

