#!/usr/bin/env python3
"""
Generate a DraftKings-only missing-props report.
Scans cached snapshots and outputs for bookmakers with key 'draftkings', canonicalizes props,
compares to registry, and produces a prioritized report (JSON + MD) in outputs/.
"""
from pathlib import Path
import json, glob, re

ROOT = Path('.').resolve()
CACHE_DIR = Path.home() / '.cache' / 'goose' / 'computer_controller'
SNAPSHOT_GLOBS = [str(CACHE_DIR / 'web_*.json'), str(ROOT / 'outputs' / '**' / '*.json')]
OUT_DIR = ROOT / 'outputs'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# heuristics for critical props
CRITICAL_KEYWORDS = ['pass', 'passing', 'rush', 'rushing', 'receiv', 'recept', 'td', 'touchdown']

# import helpers from existing script
from scripts.check_models_for_props import load_registry, normalize_outcome


def iter_dk_props(globs):
    files = []
    for g in globs:
        files.extend(glob.glob(g, recursive=True))
    for f in files:
        try:
            with open(f) as fh:
                snap = json.load(fh)
        except Exception:
            continue
        # snapshot may or may not be OddsAPI structure
        if isinstance(snap, dict) and 'bookmakers' in snap:
            for book in snap.get('bookmakers', []):
                bkey = book.get('key','').lower()
                if bkey != 'draftkings':
                    continue
                for market in book.get('markets', []) or []:
                    mk = market.get('key')
                    for outcome in market.get('outcomes', []) or []:
                        # same participant heuristics as in check script
                        participant = outcome.get('description') or outcome.get('participant') or outcome.get('player') or outcome.get('name')
                        label = outcome.get('name') or outcome.get('label') or ''
                        if (not participant or participant in ('Yes','No','Over','Under')) and mk and mk.startswith('player_'):
                            for fk in ('description','player','participant','label','name'):
                                v = outcome.get(fk)
                                if isinstance(v, str) and v not in ('Yes','No','Over','Under') and len(v) > 0 and not v.isdigit():
                                    participant = v
                                    break
                        yield f, mk, label, participant, book.get('last_update')
        # otherwise skip non-oddsapi structured files


def infer_priority(key):
    low = key.lower()
    for kw in CRITICAL_KEYWORDS:
        if kw in low:
            return 'critical'
    return 'optional'


def main():
    reg, patterns = load_registry()
    seen = {}
    for fname, mk, lab, part, ts in iter_dk_props(SNAPSHOT_GLOBS):
        key = normalize_outcome(mk or '', lab or '', part)
        entry = seen.setdefault(key, {'count':0, 'examples':[], 'market_keys':set()})
        entry['count'] += 1
        entry['examples'].append({'file': Path(fname).name, 'market': mk, 'label': lab, 'participant': part, 'ts': ts})
        if mk:
            entry['market_keys'].add(mk)
    # classify by registry match
    missing = []
    for key, data in seen.items():
        # use load_registry's patterns to determine if it matches non-generic
        matched = False
        matched_generic = False
        for p, k, is_generic in patterns:
            if p.match(key):
                matched = True
                if is_generic:
                    matched_generic = True
                else:
                    matched_generic = False
                    break
        if not matched:
            status = 'unmatched'
        elif matched and matched_generic:
            status = 'matched_only_generic'
        else:
            status = 'matched'
        if status != 'matched':
            missing.append({'key': key, 'count': data['count'], 'examples': data['examples'][:3], 'market_keys': list(data['market_keys']), 'inferred_priority': infer_priority(key), 'status': status})
    # sort: critical first, then by count
    missing.sort(key=lambda x: (0 if x['inferred_priority']=='critical' else 1, -x['count']))

    out = {
        'total_dk_props_seen': sum(v['count'] for v in seen.values()),
        'unique_dk_canonical_props': len(seen),
        'missing_count': len(missing),
        'missing': missing,
    }

    out_json = OUT_DIR / 'dk_unmodeled_props.json'
    out_md = OUT_DIR / 'dk_unmodeled_props.md'
    with out_json.open('w') as fh:
        json.dump(out, fh, indent=2)
    md = [f"# DraftKings Unmodeled Props Report\n", f"Total DK props seen (rows): {out['total_dk_props_seen']}\n", f"Unique DK canonical props: {out['unique_dk_canonical_props']}\n", f"Missing explicit models: {out['missing_count']}\n\n"]
    for it in missing[:200]:
        md.append(f"- {it['key']} (count={it['count']}, priority={it['inferred_priority']}, status={it['status']}) — markets={','.join(it['market_keys'])}\n")
        for ex in it['examples']:
            md.append(f"  - example: {ex['file']} market={ex['market']} label={ex['label']} participant={ex['participant']} ts={ex.get('ts')}\n")
    out_md.write_text('\n'.join(md))
    print('Wrote', out_json, out_md)

if __name__ == '__main__':
    main()
