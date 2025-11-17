#!/usr/bin/env python3
"""
Dry-run models for DraftKings props for the Eagles vs Lions event.
Loads the DK props from cache files for that event, calls the registry handlers (importlib)
and writes outputs/models_dryrun.json
"""
from pathlib import Path
import json, glob, importlib
from scripts.check_models_for_props import load_registry, normalize_outcome, find_props_in_snapshot, load_snapshots

ROOT = Path('.').resolve()
CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
SNAPSHOT_GLOBS = [str(CACHE_DIR / 'web_*.json'), str(ROOT / 'outputs' / '**' / '*.json')]
OUT_DIR = ROOT / 'outputs'
OUT_DIR.mkdir(parents=True, exist_ok=True)

reg, patterns = load_registry()

# build compiled pattern -> handler list from registry
import re
compiled_patterns = []
for name, entry in reg.items():
    pat = entry.get('pattern', name)
    pat_re = re.escape(pat).replace(r"\\*", r"(.+)")
    try:
        cre = re.compile(f"^{pat_re}$")
        compiled_patterns.append((cre, entry.get('handler'), bool(entry.get('is_generic'))))
    except re.error:
        continue


def find_handler_for_key(key):
    for cre, handler, is_generic in compiled_patterns:
        if cre.match(key):
            return handler
    return None

results = []
for fname, snap in load_snapshots(SNAPSHOT_GLOBS):
    # filter to drafts for the Eagles vs Lions event by team names
    txt = json.dumps(snap).lower()
    if 'philadelphia' not in txt and 'detroit' not in txt:
        continue
    # iterate bookmakers
    if isinstance(snap, dict) and 'bookmakers' in snap:
        for book in snap.get('bookmakers', []):
            if book.get('key','').lower() != 'draftkings':
                continue
            for market in book.get('markets', []) or []:
                mk = market.get('key')
                for outcome in market.get('outcomes', []) or []:
                    participant = outcome.get('description') or outcome.get('participant') or outcome.get('player') or outcome.get('name')
                    label = outcome.get('name') or outcome.get('label') or ''
                    price = outcome.get('price') or outcome.get('point') or outcome.get('odds') or None
                    if (not participant or participant in ('Yes','No','Over','Under')) and mk and mk.startswith('player_'):
                        for fk in ('description','player','participant','label','name'):
                            v = outcome.get(fk)
                            if isinstance(v, str) and v not in ('Yes','No','Over','Under') and len(v) > 0 and not v.isdigit():
                                participant = v
                                break
                    key = normalize_outcome(mk or '', label or '', participant)
                    handler_path = find_handler_for_key(key)
                    if not handler_path:
                        results.append({'key': key, 'handler': None, 'participant': participant, 'market': mk, 'price': price, 'book_file': fname})
                        continue
                    module_name, func_name = handler_path.split(':')
                    try:
                        mod = importlib.import_module(module_name)
                        fn = getattr(mod, func_name)
                        out = fn(key, event_id=None, participant=participant)
                        results.append({'key': key, 'handler': handler_path, 'participant': participant, 'market': mk, 'price': price, 'result': out})
                    except Exception as e:
                        results.append({'key': key, 'handler': handler_path, 'participant': participant, 'market': mk, 'price': price, 'error': str(e)})

outf = OUT_DIR / 'models_dryrun.json'
with outf.open('w') as fh:
    json.dump(results, fh, indent=2)
print('Wrote', outf)
