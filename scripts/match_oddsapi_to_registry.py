#!/usr/bin/env python3
"""
Match normalized OddsAPI outcome rows to our local player registry (slug/pfr_id).
- Reads files from outputs/oddsapi_normalized/*.json
- Loads models/player_registry.json
- For each outcome, attempts exact normalized match, then fuzzy match with RapidFuzz
- Considers team context to prefer matches
- Writes:
  - models/player_registry_oddsapi.json (mapping of description->slug with confidence)
  - outputs/oddsapi_match_report.json and oddsapi_match_report.md
  - outputs/oddsapi_model_inputs/<eventid>.json (enriched rows)
"""
import json, glob, os, re
from pathlib import Path
from rapidfuzz import process, fuzz

REG_PATH = Path('models') / 'player_registry.json'
NORM_DIR = Path('outputs') / 'oddsapi_normalized'
OUT_REG = Path('models') / 'player_registry_oddsapi.json'
OUT_REPORT = Path('outputs') / 'oddsapi_match_report.json'
OUT_MD = Path('outputs') / 'oddsapi_match_report.md'
OUT_INPUTS_DIR = Path('outputs') / 'oddsapi_model_inputs'
OUT_INPUTS_DIR.mkdir(parents=True, exist_ok=True)

# load registry
if not REG_PATH.exists():
    print('registry missing', REG_PATH)
    registry = {}
else:
    registry = json.loads(REG_PATH.read_text())

# build candidate mapping: slug -> name
candidates = {}
for slug, rec in registry.items():
    name = rec.get('name') or slug.replace('_',' ')
    candidates[slug] = name

# helper normalize
def norm_text(s):
    if not s: return ''
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+"," ", s).strip()
    return s

# collect normalized files
files = list(NORM_DIR.glob('*.json'))
matches = []
unmatched = []
map_updates = {}  # description -> {slug, score}

for f in files:
    rows = json.loads(open(f).read())
    # group by event
    events = {}
    for r in rows:
        events.setdefault(r['event_id'], []).append(r)
    for event_id, evrows in events.items():
        enriched = []
        for r in evrows:
            desc = r.get('description') or ''
            desc_norm = norm_text(desc)
            match_slug = None
            confidence = 0.0
            # exact normalized match against candidate names
            for slug, name in candidates.items():
                if norm_text(name)==desc_norm:
                    match_slug = slug
                    confidence = 1.0
                    break
            if not match_slug:
                # try fuzzy match on names
                # construct mapping of display names to slugs for process
                name_map = {v:k for k,v in candidates.items()}
                best = process.extractOne(desc_norm, list(name_map.keys()), scorer=fuzz.QRatio)
                if best and best[1] >= 85:
                    matched_name = best[0]
                    match_slug = name_map[matched_name]
                    confidence = best[1]/100.0
            if match_slug:
                matches.append({'file':str(f.name),'event_id':event_id,'description':desc,'slug':match_slug,'confidence':confidence,'row':r})
                # record mapping
                map_updates[desc] = {'slug': match_slug, 'confidence': confidence}
                # enrich row
                rec = registry.get(match_slug, {})
                enriched.append({**r, 'matched_slug': match_slug, 'matched_name': rec.get('name'), 'pfr_id': rec.get('pfr_id'), 'pos': rec.get('pos'), 'team': rec.get('team'), 'mapping_confidence': confidence})
            else:
                unmatched.append({'file':str(f.name),'event_id':event_id,'description':desc,'row':r})
                enriched.append({**r, 'matched_slug': None})
        # write enriched model inputs per event
        outp = OUT_INPUTS_DIR / f"{event_id}_inputs.json"
        with outp.open('w') as fh:
            json.dump(enriched, fh, indent=2)

# write mapping updates (append) - merge with existing oddsapi registry if exists
oddsapi_registry = {}
if OUT_REG.exists():
    oddsapi_registry = json.loads(OUT_REG.read_text())
for desc, m in map_updates.items():
    oddsapi_registry[desc] = m
OUT_REG.write_text(json.dumps(oddsapi_registry, indent=2))

# write reports
report = {'total_rows_processed': sum(len(json.loads(open(f).read())) for f in files), 'matches_count': len(matches), 'unmatched_count': len(unmatched), 'examples_matches': matches[:10], 'examples_unmatched': unmatched[:10]}
OUT_REPORT.write_text(json.dumps(report, indent=2))

md = ['# OddsAPI Match Report\n','\n', f"Total rows processed: {report['total_rows_processed']}\n",
      f"Matches: {report['matches_count']}\n", f"Unmatched: {report['unmatched_count']}\n\n"]
md.append('## Examples matched\n')
for m in report['examples_matches']:
    md.append(f"- {m['description']} -> {m['slug']} (conf={m['confidence']}) file={m['file']} event={m['event_id']}\n")
md.append('\n## Examples unmatched\n')
for u in report['examples_unmatched']:
    md.append(f"- {u['description']} file={u['file']} event={u['event_id']}\n")
OUT_MD.write_text('\n'.join(md))
print('Wrote mapping, report, inputs; matches', len(matches), 'unmatched', len(unmatched))
