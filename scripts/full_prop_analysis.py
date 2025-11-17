#!/usr/bin/env python3
"""
Full prop analysis skeleton for an event (Cowboys @ Raiders).
- Loads registry and market_to_canonical mapping
- For each market in the OddsAPI market list, canonicalizes outcomes found in cached DK snapshots
- Runs model handlers where available (specialized), otherwise uses generic handler
- Produces outputs/cowboys_raiders_full_models.json and _edges.md (DraftKings only)

Notes:
- Deep modeling is applied to core markets (passing_yards, receptions, rushing_yards, TDs). Others use generic.
- This script assumes models/registry.yaml, models/market_to_canonical.yaml exist and handlers are importable.
"""
import json, glob, importlib, re
from pathlib import Path
from scripts.check_models_for_props import normalize_outcome, load_registry

CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
OUT_DIR = Path('outputs')
OUT_DIR.mkdir(exist_ok=True)
EVENT_ID = '80d04ba917883a6438580ebae9fb0f22'

# load registry
reg, patterns = load_registry()

# helper: find DK snapshot for event
files = glob.glob(str(CACHE_DIR / 'web_*.json')) + glob.glob('outputs/**/*.json', recursive=True)

snapshots=[]
for f in files:
    try:
        j=json.load(open(f))
    except Exception:
        continue
    if isinstance(j, dict) and j.get('id')==EVENT_ID:
        snapshots.append((f,j))
    elif isinstance(j,list):
        for ev in j:
            if isinstance(ev,dict) and ev.get('id')==EVENT_ID:
                snapshots.append((f,ev))
                break

# gather DK markets across snapshots
dk_markets={}
for f,ev in snapshots:
    for bk in ev.get('bookmakers',[]):
        if bk.get('key','').lower()!='draftkings':
            continue
        for m in bk.get('markets',[]):
            dk_markets.setdefault(m.get('key'), []).append((f,m))

# flatten outcomes
canonical_props = {}
for mkey, entries in dk_markets.items():
    for f,m in entries:
        for outcome in m.get('outcomes',[]):
            participant = outcome.get('description') or outcome.get('participant') or outcome.get('name')
            label = outcome.get('name') or outcome.get('label') or ''
            key = normalize_outcome(mkey, label, participant)
            canonical_props.setdefault(key, []).append({'market':mkey, 'participant':participant, 'label':label, 'price': outcome.get('price'), 'file':f})

# function to load handler
from importlib import import_module

def get_handler_for_canonical(key):
    # iterate registry patterns compiled
    for pat, name, is_generic in patterns:
        # pat is regex object in patterns in check script; but here patterns from loader are tuples (regex, key, is_generic)
        try:
            cre=pat
            if cre.match(key):
                # registry key name -> get handler
                entry = reg.get(name)
                if entry:
                    return entry.get('handler'), entry.get('is_generic', False)
        except Exception:
            continue
    return None, False

results=[]
for key, examples in canonical_props.items():
    handler_path, is_generic = get_handler_for_canonical(key)
    if handler_path:
        mod_name, fn_name = handler_path.split(':')
        try:
            mod = import_module(mod_name)
            fn = getattr(mod, fn_name)
            # call fn with minimal args (use first example)
            ex = examples[0]
            res = fn(key, event_id=EVENT_ID, participant=ex.get('participant'))
            results.append({'key':key, 'handler':handler_path, 'result':res, 'examples':examples[:2]})
        except Exception as e:
            results.append({'key':key, 'handler':handler_path, 'error':str(e), 'examples':examples[:2]})
    else:
        # use generic handler
        try:
            mod = import_module('models.generic')
            res = mod.model_generic(key, event_id=EVENT_ID, participant=examples[0].get('participant'))
            results.append({'key':key, 'handler':'models.generic:model_generic','result':res,'examples':examples[:2]})
        except Exception as e:
            results.append({'key':key,'handler':None,'error':str(e),'examples':examples[:2]})

outf = OUT_DIR / 'cowboys_raiders_full_models.json'
with outf.open('w') as fh:
    json.dump({'event':EVENT_ID,'results':results}, fh, indent=2)

# produce a short edges md from results for core markets
md=['# Cowboys @ Raiders - Full prop quick results\n','\n']
for r in results:
    k=r['key']
    if any(s in k for s in ('anytime_td','_td','passing_yards','receptions','rushing_yards')):
        if 'result' in r and r['result']:
            res=r['result']
            md.append(f"- {k}: handler={r['handler']} result_summary={str(res)[:120]}\n")
        else:
            md.append(f"- {k}: handler={r.get('handler')} ERROR {r.get('error')}\n")
mdp = OUT_DIR/'cowboys_raiders_full_quick.md'
mdp.write_text('\n'.join(md))
print('Wrote', outf, mdp)
