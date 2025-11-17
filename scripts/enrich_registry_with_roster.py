#!/usr/bin/env python3
"""
Enrich player_registry_augmented.json using nfl_data_py player tables.
- Loads models/player_registry_augmented.json (fallback to player_registry.json if not present)
- Uses nfl_data_py.import_players() or import_ids() to retrieve roster names
- Matches augmented entries to roster via rapidfuzz token_sort_ratio
- Attaches player_id, team, and canonical player_name when confident (score>=85)
- Writes:
  - models/player_registry_enriched.json (enriched full registry)
  - outputs/event_<EVENT>_verification.csv (rows with matching info)

Usage: python3 scripts/enrich_registry_with_roster.py --event <EVENT_ID> --threshold 85
"""
import argparse, json, os
from pathlib import Path
from rapidfuzz import process, fuzz
import unicodedata, re, csv

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / 'models'
OUTDIR = ROOT / 'outputs'
MODELS_DIR.mkdir(parents=True, exist_ok=True)
OUTDIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--event', required=True)
parser.add_argument('--threshold', type=int, default=85)
args = parser.parse_args()
EVENT = args.event
THRESH = args.threshold

# load augmented registry
aug_file = MODELS_DIR / 'player_registry_augmented.json'
base_registry = MODELS_DIR / 'player_registry.json'
if aug_file.exists():
    registry = json.loads(aug_file.read_text())
elif base_registry.exists():
    registry = json.loads(base_registry.read_text())
else:
    registry = {}

# normalization helper
def norm(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9\s]", '', s)
    s = re.sub(r"\s+", ' ', s)
    return s

# build list of registry entries to enrich (those with auto_added or without player_id)
candidates = [slug for slug,rec in registry.items() if rec.get('auto_added') or not rec.get('pfr_id')]
print('Candidates to enrich:', len(candidates))

# load nfl_data_py players
roster_map = {}  # norm_name -> {'player_name','player_id','team'}
try:
    import nfl_data_py as nd
    ply = None
    if hasattr(nd, 'import_players'):
        try:
            ply = nd.import_players()
        except Exception:
            ply = None
    if not ply and hasattr(nd, 'import_ids'):
        try:
            ply = nd.import_ids()
        except Exception:
            ply = None
    if ply is not None:
        try:
            import pandas as pd
            df = ply
            for _, r in df.iterrows():
                name = r.get('player_name') or r.get('full_name') or r.get('name')
                if not name:
                    continue
                pid = r.get('gsis_id') or r.get('nfl_id') or r.get('player_id') or r.get('player')
                team = r.get('team') or r.get('team_abbr') or r.get('team_name')
                roster_map[norm(name)] = {'player_name': name, 'player_id': pid, 'team': team}
        except Exception:
            try:
                for r in ply:
                    name = r.get('player_name') or r.get('full_name') or r.get('name')
                    pid = r.get('gsis_id') or r.get('player_id')
                    team = r.get('team')
                    roster_map[norm(name)] = {'player_name': name, 'player_id': pid, 'team': team}
            except Exception:
                pass
except Exception as e:
    print('nfl_data_py not available or failed:', e)

print('Roster size from nfl_data_py:', len(roster_map))
roster_keys = list(roster_map.keys())

# perform matching
verification_rows = []
enriched = 0
for slug in candidates:
    rec = registry[slug]
    name = rec.get('name') or slug.replace('_',' ')
    nname = norm(name)
    best = None
    source = None
    score = 0
    if nname in roster_map:
        best = roster_map[nname]
        score = 100
        source = 'exact'
    else:
        if roster_keys:
            res = process.extractOne(nname, roster_keys, scorer=fuzz.token_sort_ratio)
            if res:
                cand_name, score, idx = res
                score = int(score)
                if score >= THRESH:
                    best = roster_map.get(cand_name)
                    source = 'fuzzy'
    if best:
        # attach
        rec['player_id'] = best.get('player_id')
        rec['canonical_name'] = best.get('player_name')
        rec['team'] = best.get('team') or rec.get('team')
        rec['matched_score'] = score
        rec['matched_source'] = source
        enriched += 1
    else:
        rec['matched_score'] = 0
        rec['matched_source'] = 'none'
    verification_rows.append({'dk_desc': name, 'slug': slug, 'matched_name': rec.get('canonical_name') or '', 'player_id': rec.get('player_id') or '', 'team': rec.get('team') or '', 'score': rec.get('matched_score'), 'source': rec.get('matched_source')})

# write enriched registry
enriched_file = MODELS_DIR / 'player_registry_enriched.json'
with open(enriched_file,'w',encoding='utf-8') as fh:
    json.dump(registry, fh, indent=2)
print('Wrote enriched registry to', enriched_file, 'enriched count:', enriched)

# write verification CSV
ver_file = OUTDIR / f'event_{EVENT}_verification.csv'
with open(ver_file,'w',newline='',encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['dk_desc','slug','matched_name','player_id','team','score','source'])
    for r in verification_rows:
        w.writerow([r['dk_desc'], r['slug'], r['matched_name'], r['player_id'], r['team'], r['score'], r['source']])
print('Wrote verification CSV to', ver_file)

# Optionally, overwrite primary registry (backup first)
primary = MODELS_DIR / 'player_registry.json'
if primary.exists():
    backup = MODELS_DIR / f'player_registry.json.bak'
    backup.write_text(primary.read_text())
    print('Backed up primary registry to', backup)
primary.write_text(json.dumps(registry, indent=2))
print('Overwrote player_registry.json with enriched registry')
