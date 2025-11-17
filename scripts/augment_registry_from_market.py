#!/usr/bin/env python3
"""
Augment player_registry.json using extracted event markets and nfl_data_py players.
- Input: outputs/event_<EVENT>_markets.tsv
- Uses rapidfuzz to fuzzy-match normalized_player to roster names and existing registry names.
- Auto-matches high-confidence (score >= 90) to existing players and attaches player_id if available.
- For unmatched but plausible entries, creates provisional registry entries with auto_added=true.
- Outputs:
  - models/player_registry_augmented.json
  - outputs/event_<EVENT>_final_mapping.json
  - outputs/event_<EVENT>_augmented_unmatched.csv (remaining ambiguous)

Usage: python3 scripts/augment_registry_from_market.py --event <EVENT>
"""
import argparse, json, os
from pathlib import Path
from rapidfuzz import process, fuzz
import unicodedata, re, csv

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / 'outputs'
MODELS_DIR = ROOT / 'models'
MODELS_DIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--event', required=True)
parser.add_argument('--threshold', type=int, default=90, help='rapidfuzz threshold for auto-match')
args = parser.parse_args()
EVENT = args.event
THRESH = args.threshold

markets_tsv = OUTDIR / f'event_{EVENT}_markets.tsv'
if not markets_tsv.exists():
    raise SystemExit('Markets TSV not found: '+str(markets_tsv))

# load existing registry
registry_file = MODELS_DIR / 'player_registry.json'
if registry_file.exists():
    registry = json.loads(registry_file.read_text())
else:
    registry = {}

# build registry name index
def norm(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r"[^a-z0-9\s]","", s)
    s = re.sub(r"\s+"," ", s)
    return s

registry_name_map = {}  # norm_name -> slug
for slug, rec in registry.items():
    n = rec.get('name')
    if n:
        registry_name_map[norm(n)] = slug
    # also include slug as name
    registry_name_map[norm(slug.replace('_',' '))] = slug

# load roster via nfl_data_py if available
roster_map = {}  # norm_name -> {player_name, player_id, team}
try:
    import nfl_data_py as nd
    # try import_players or import_ids
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
except Exception:
    pass

roster_keys = list(roster_map.keys())
registry_keys = list(registry_name_map.keys())

# read unique normalized players from markets file
unique = []
with open(markets_tsv,'r',encoding='utf-8') as fh:
    rdr = csv.DictReader(fh, delimiter='\t')
    seen=set()
    for r in rdr:
        ndp = r.get('normalized_player','').strip()
        if ndp and ndp not in seen:
            seen.add(ndp)
            unique.append(ndp)

final_mapping = {}
auto_added = {}
ambiguous = []

for name in unique:
    mapped = {'name': name, 'match': None, 'score': 0, 'source': None, 'candidates': []}
    # try exact registry match
    if name in registry_name_map:
        mapped['match'] = registry_name_map[name]
        mapped['score'] = 100
        mapped['source'] = 'registry_exact'
        final_mapping[name]=mapped
        continue
    # try exact roster match
    if name in roster_map:
        mapped['match'] = None
        mapped['score'] = 100
        mapped['source'] = 'roster_exact'
        mapped['candidates'].append({'type':'roster', 'info': roster_map[name]})
        final_mapping[name]=mapped
        continue
    # fuzzy match against registry names
    if registry_keys:
        res = process.extract(name, registry_keys, scorer=fuzz.token_sort_ratio, limit=5)
        for cand,score,idx in res:
            mapped['candidates'].append({'type':'registry', 'norm': cand, 'slug': registry_name_map.get(cand), 'score': int(score)})
        if mapped['candidates'] and mapped['candidates'][0]['score']>=THRESH:
            mapped['match'] = mapped['candidates'][0]['slug']
            mapped['score'] = mapped['candidates'][0]['score']
            mapped['source'] = 'registry_fuzzy'
            final_mapping[name]=mapped
            continue
    # fuzzy match against roster
    if roster_keys:
        res = process.extract(name, roster_keys, scorer=fuzz.token_sort_ratio, limit=5)
        for cand,score,idx in res:
            mapped['candidates'].append({'type':'roster', 'norm': cand, 'info': roster_map.get(cand), 'score': int(score)})
        if mapped['candidates'] and mapped['candidates'][0]['score']>=THRESH:
            # find a slug in registry by normalized roster name if exists
            rinfo = mapped['candidates'][0]['info']
            # try to find registry slug by matching canonical name
            candidate_slug = None
            for k,v in registry.items():
                if norm(v.get('name','')) == mapped['candidates'][0]['norm']:
                    candidate_slug = k
                    break
            mapped['match'] = candidate_slug or None
            mapped['score'] = mapped['candidates'][0]['score']
            mapped['source'] = 'roster_fuzzy'
            final_mapping[name]=mapped
            continue
    # no confident match: create provisional registry entry
    slug = name.replace(' ','_')
    slug = re.sub(r'[^a-z0-9_]','', slug)
    # title case the display name
    display = ' '.join([p.capitalize() for p in name.split()])
    # infer team from name if contains team tokens
    team = None
    for t in ['dallas cowboys','las vegas raiders','cowboys','raiders']:
        if t in name:
            team = t.title()
            break
    # add provisional
    provisional = {'name': display, 'slug': slug, 'pfr_id': None, 'player_file': '', 'team': team or None, 'pos': None, 'auto_added': True}
    registry[slug] = provisional
    auto_added[slug] = provisional
    mapped['match'] = slug
    mapped['score'] = 0
    mapped['source'] = 'auto_added'
    final_mapping[name]=mapped

# write augmented registry
aug_file = MODELS_DIR / 'player_registry_augmented.json'
with open(aug_file,'w',encoding='utf-8') as fh:
    json.dump(registry, fh, indent=2)

# write final mapping
map_file = OUTDIR / f'event_{EVENT}_final_mapping.json'
with open(map_file,'w',encoding='utf-8') as fh:
    json.dump(final_mapping, fh, indent=2)

# write augmented unmatched (remaining ambiguous ones with candidates)
amb_file = OUTDIR / f'event_{EVENT}_augmented_unmatched.csv'
with open(amb_file,'w',newline='',encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(['normalized_player','match_slug','score','source','candidates'])
    for name,m in final_mapping.items():
        if m['source'] in ('registry_fuzzy','roster_fuzzy') and m['score'] < THRESH:
            w.writerow([name, m.get('match') or '', m.get('score'), m.get('source'), json.dumps(m.get('candidates') or [])])

print('Wrote augmented registry to', aug_file)
print('Wrote final mapping to', map_file)
print('Wrote augmented_unmatched to', amb_file)
print('Auto-added entries count:', len(auto_added))
