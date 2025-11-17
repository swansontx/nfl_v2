#!/usr/bin/env python3
"""
Build a player registry focused on: PFR ids, canonical slug, player_file, team, position,
and link features from model_output_pfr.json (if available).

Outputs: models/player_registry.json and outputs/player_registry_preview.md
"""
import csv, json, glob, re
from pathlib import Path

PLAYER_DATA_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller' / 'player_data'
MODEL_OUTPUT_PFR = Path.home() / '.cache' / 'goose' / 'computer_controller' / 'model_output_pfr.json'
OUT_REG = Path('models') / 'player_registry.json'
OUT_MD = Path('outputs') / 'player_registry_preview.md'
OUT_REG.parent.mkdir(parents=True, exist_ok=True)
Path('outputs').mkdir(parents=True, exist_ok=True)

def slugify(name):
    if not name: return None
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+","_", s).strip('_')
    return s

# load summary.csv if present
summary = {}
summary_file = PLAYER_DATA_DIR / 'summary.csv'
if summary_file.exists():
    with summary_file.open() as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            name = r.get('name')
            if not name: continue
            entry = {'name': name, 'player_file': r.get('player_file'), 'player_url': r.get('player_url'), 'search_file': r.get('search_file')}
            summary[name.lower()] = entry

# load model_output_pfr json
pfr_features = {}
if MODEL_OUTPUT_PFR.exists():
    mo = json.load(open(MODEL_OUTPUT_PFR))
    # try to pull summary per-player if present under 'summary' or similar
    if isinstance(mo, dict):
        for k in ('summary','players','player_summary'):
            if k in mo and isinstance(mo[k], dict):
                pfr_features = mo[k]
                break
        # fallback: if top-level has per-player keys
        if not pfr_features:
            for kk, vv in mo.items():
                if isinstance(vv, dict) and 'player' in vv or 'td' in vv:
                    # heuristic, include
                    pfr_features = mo.get('summary', {} )
                    break

registry = {}
# from summary.csv
for name, entry in summary.items():
    slug = slugify(name)
    pfr_id = None
    url = entry.get('player_url') or ''
    m = re.search(r'/players/[A-Z]/([A-Za-z0-9]+)\.htm', url)
    if m:
        pfr_id = m.group(1)
    registry[slug] = {'name': entry.get('name'), 'slug': slug, 'pfr_id': pfr_id, 'player_file': entry.get('player_file'), 'team': None, 'pos': None}

# Supplement with HTML scan for team/position
for slug, rec in registry.items():
    pf = rec.get('player_file')
    if pf:
        try:
            txt = Path(pf).read_text(encoding='utf-8', errors='ignore').lower()
        except Exception:
            txt=''
        # try to find team
        for team_pattern in ['dallas cowboys','las vegas raiders','cowboys','raiders','philadelphia eagles','detroit lions']:
            if team_pattern in txt:
                rec['team'] = team_pattern.title()
                break
        # try position
        m = re.search(r'position[:\s><\\]*([a-z]{2,3})', txt)
        if m:
            rec['pos'] = m.group(1).upper()

# attach pfr features if pfr_id present
for slug, rec in registry.items():
    pid = rec.get('pfr_id')
    if pid and pid in pfr_features:
        rec['pfr'] = pfr_features[pid]

# write registry
OUT_REG.write_text(json.dumps(registry, indent=2))

# write preview
md=['# Player Registry Preview\n']
for slug, rec in list(registry.items())[:60]:
    md.append(f"- {rec.get('name')} (slug={slug}) pfr_id={rec.get('pfr_id')} team={rec.get('team')} pos={rec.get('pos')}\n")
OUT_MD.write_text('\n'.join(md))
print('Wrote', OUT_REG, OUT_MD)
