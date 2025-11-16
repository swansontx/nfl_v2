from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import json, os, glob, csv
from typing import List, Optional, Dict, Any
from pathlib import Path

from app.core import cache as app_cache
from app.core.parlay import suggest_parlays
from app.services.worker import recompute_projections
from app.services import scheduler

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title='Goose NFL Props API')
# CORS - allow frontend dev by default, override with VITE_API_URL
_frontend_origin = os.environ.get('VITE_API_URL', 'http://localhost:5173')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_frontend_origin],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

DATA_DIR = Path('data')
ODDS_DIR = DATA_DIR / 'odds_live'
OUTPUTS = Path('outputs')
NFLDATA = Path('nfl_data_2025_csv')

# Scheduler will be started/stopped via FastAPI lifecycle events

@app.on_event('startup')
async def _startup():
    scheduler.start()

@app.on_event('shutdown')
async def _shutdown():
    scheduler.shutdown()

# Simple helpers

def load_json(path):
    if not Path(path).exists():
        return None
    with open(path) as f:
        return json.load(f)

@app.get('/api/health')
def health():
    return {'status':'ok'}

@app.get('/api/schedule')
def schedule():
    p = NFLDATA / 'schedules_2025.csv'
    if not p.exists():
        raise HTTPException(status_code=404, detail='schedules file not found')
    import pandas as pd
    df = pd.read_csv(p)
    return df.to_dict(orient='records')

@app.get('/api/selected_events')
def selected_events():
    files = sorted(ODDS_DIR.glob('selected_events_*.json'))
    if not files:
        raise HTTPException(status_code=404, detail='no selected events')
    return load_json(files[-1])

@app.get('/api/odds/latest')
def odds_latest():
    files = sorted(ODDS_DIR.glob('odds_*spreads_totals*.json'))
    if not files:
        raise HTTPException(status_code=404, detail='no odds files')
    return load_json(files[-1])

@app.get('/api/event/{event_id}/markets')
def event_markets(event_id: str):
    # try batch files, then per-event
    p1 = ODDS_DIR / 'event_markets_latest' / f'{event_id}_markets.json'
    p2 = ODDS_DIR / 'event_markets_batch' / f'{event_id}_markets.json'
    p3 = ODDS_DIR / 'event_markets_dk' / f'{event_id}_dk_markets.json'
    for p in [p1,p2,p3]:
        if p.exists():
            return load_json(p)
    raise HTTPException(status_code=404, detail='event markets not cached')

@app.get('/api/projections')
def projections():
    files = sorted(OUTPUTS.glob('projections_*.csv'))
    if not files:
        raise HTTPException(status_code=404, detail='no projections')
    import pandas as pd
    df = pd.read_csv(files[-1])
    return df.to_dict(orient='records')

@app.get('/api/props_candidates')
def props_candidates():
    # return the latest props candidates file if present
    files = sorted(OUTPUTS.glob('props_candidates_*.csv'))
    if not files:
        # fallback to general projections
        return projections()
    import pandas as pd
    df = pd.read_csv(files[-1])
    return df.to_dict(orient='records')

@app.get('/api/injuries')
def injuries():
    p = NFLDATA / 'espn_injuries_sheet_parsed.csv'
    if p.exists():
        import pandas as pd
        df = pd.read_csv(p)
        return df.to_dict(orient='records')
    # fallback
    files = sorted(OUTPUTS.glob('injuries_summary_*.md'))
    if files:
        return {'summary_file': str(files[-1])}
    raise HTTPException(status_code=404, detail='no injuries data')

class ParlayRequest(BaseModel):
    selections: List[Dict[str, Any]]
    max_legs: Optional[int] = 6

@app.post('/api/parlay/suggest')
def parlay_suggest(req: ParlayRequest):
    # delegate to core/parlay implementation
    res = suggest_parlays(req.selections, max_legs=req.max_legs, top_k=20)
    return res


@app.post('/api/refresh_projections')
def refresh_projections(background_tasks: BackgroundTasks):
    """Trigger a background recompute of projections. Returns accepted status or error if the generator is missing."""
    # Prefer to provide immediate feedback if the generator script is missing
    try:
        from app.services import worker as worker_service
        script = worker_service._find_script()
    except Exception:
        script = None
    if not script:
        return {'status': 'rejected', 'reason': 'generate_projections script not found on disk'}
    background_tasks.add_task(worker_service.recompute_projections)
    return {'status': 'accepted', 'script': str(script)}

# run with: uvicorn backend.api:app --reload
