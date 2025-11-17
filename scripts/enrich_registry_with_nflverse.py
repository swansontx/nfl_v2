#!/usr/bin/env python3
"""
Enrich registry entries using nflverse player lookup JSON created from nflverse-data release CSVs.
- Input: inputs/player_lookup_2023.json (normalized name -> {player_name, player_id, team})
- Enriches models/player_registry_enriched.json (or player_registry.json) by matching normalized DK descriptions
- Matching: exact normalized match then rapidfuzz fuzzy match (threshold default 85)
- Writes updated models/player_registry_enriched.json and a verification CSV

Usage: python3 scripts/enrich_registry_with_nflverse.py --event <EVENT>
"""
import argparse, json, os
from pathlib import Path
from rapidfuzz import process, fuzz
import unicodedata, re, csv

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / 'models'
OUTDIR = ROOT / 'outputs'
INPUTS = ROOT / 'inputs'
MODELS_DIR.mkdir(parents=True, exist_ok=True)
OUTDIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--event', required=True)
parser.add_argument('--threshold', type=int, default=85)
args = parser.parse_args()
EVENT = args.event
THRESH = args.threshold

# normalization helper
def norm(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9\s]", '', s)
    s = re.sub(r"\s+", ' ', s)
    return s

# load player lookup
lookup_file = INPUTS / 'player_lookup_2023.json'
if not lookup_file.exists():
    raise SystemExit('Player lookup not found: '+str(lookup_file))
lookup = json.loads(lookup_file.read_text())
lookup_keys = list(lookup.keys())

# load registry
reg_file = MODELS_DIR / 'player_registry_enriched.json'
if not reg_file.exists():
    reg_file = MODELS_DIR / 'player_registry.json'
if not reg_file.exists():
    raise SystemExit('No registry file found in models/')
registry = json.loads(reg_file.read_text())

candidates = [slug for slug,rec in registry.items() if rec.get('auto_added') or not rec.get('player_id')]
print('Candidates to enrich:', len(candidates))

verification = []
enriched=0
for slug in candidates:
    rec = registry[slug]
    name = rec.get('name') or slug.replace('_',' ')
    nname = norm(name)
    best=None
    score=0
    source=None
    # try exact in lookup
    if nname in lookup:
        best = lookup[nname]
        score=100
        source='exact'
    else:
        # fuzzy match
        res = process.extractOne(nname, lookup_keys, scorer=fuzz.token_sort_ratio)
        if res:
            cand_name, score, idx = res
            score=int(score)
            if score>=THRESH:
                best = lookup[cand_name]
                source='fuzzy'
    if best:
        rec['player_id']=best.get('player_id') or best.get('player_id')
        rec['canonical_name']=best.get('player_name')
        rec['team']=best.get('team') if best.get('team') else rec.get('team')
        rec['matched_score']=score
        rec['matched_source']=source
        enriched+=1
    else:
        rec['matched_score']=0
        rec['matched_source']='none'
    verification.append({'dk_desc': name, 'slug': slug, 'matched_name': rec.get('canonical_name') or '', 'player_id': rec.get('player_id') or '', 'team': rec.get('team') or '', 'score': rec.get('matched_score'), 'source': rec.get('matched_source')})

# write back registry
out_file = MODELS_DIR / 'player_registry_enriched.json'
out_file.write_text(json.dumps(registry, indent=2))
print('Wrote enriched registry to', out_file, 'enriched count:', enriched)

# write verification CSV
ver_file = OUTDIR / f'event_{EVENT}_nflverse_verification.csv'
with open(ver_file,'w',newline='',encoding='utf-8') as fh:
    w=csv.writer(fh)
    w.writerow(['dk_desc','slug','matched_name','player_id','team','score','source'])
    for r in verification:
        w.writerow([r['dk_desc'], r['slug'], r['matched_name'], r['player_id'], r['team'], r['score'], r['source']])
print('Wrote verification CSV to', ver_file)

# backup and overwrite primary registry
primary = MODELS_DIR / 'player_registry.json'
if primary.exists():
    primary_backup = MODELS_DIR / 'player_registry.json.gz.bak'
    primary_backup.write_text(primary.read_text())
primary.write_text(json.dumps(registry, indent=2))
print('Overwrote primary registry.json with enriched registry (backup created if existed)')
