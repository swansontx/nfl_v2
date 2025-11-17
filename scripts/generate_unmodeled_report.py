#!/usr/bin/env python3
"""
Generate JSON and MD reports of unmodeled props (explicitly missing from registry)
and props matched only by generic handlers for triage.
"""
import json
from pathlib import Path
from scripts.check_models_for_props import load_registry, load_snapshots, find_props_in_snapshot, normalize_outcome, matches_registry

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    reg, patterns = load_registry()
    canonical_set = {}
    # reuse SNAPSHOT_GLOBS from check_models_for_props by scanning same locations
    # but load_snapshots isn't exported; we'll import module functions directly
    from scripts.check_models_for_props import load_snapshots as _load_snapshots
    for fname, snap in _load_snapshots([str((Path.home() / ".cache" / "goose" / "computer_controller" / "web_*.json")), str(ROOT / "outputs" / "**" / "*.json")]):
        for mk, lab, part in find_props_in_snapshot(snap):
            key = normalize_outcome(mk or "", lab or "", part)
            canonical_set.setdefault(key, []).append({"file": fname, "market": mk, "label": lab, "participant": part})

    missing_explicit = []
    matched_only_by_generic = []
    for key, samples in canonical_set.items():
        matched, matched_generic = matches_registry(patterns, key)
        if not matched:
            missing_explicit.append({"key": key, "examples": samples[:3]})
        elif matched and matched_generic:
            matched_only_by_generic.append({"key": key, "examples": samples[:3]})

    report = {
        "total_unique_props": len(canonical_set),
        "missing_explicit_count": len(missing_explicit),
        "matched_only_by_generic_count": len(matched_only_by_generic),
        "missing_explicit": missing_explicit,
        "matched_only_by_generic": matched_only_by_generic,
    }

    out_json = OUT_DIR / "unmodeled_props_report.json"
    with out_json.open("w") as fh:
        json.dump(report, fh, indent=2)

    # Markdown summary
    md = []
    md.append(f"# Unmodeled Props Report\n")
    md.append(f"Total unique canonical props seen: {report['total_unique_props']}\n")
    md.append(f"Missing explicit models: {report['missing_explicit_count']}\n")
    md.append(f"Matched only by generic handlers: {report['matched_only_by_generic_count']}\n")

    if missing_explicit:
        md.append("## Unmatched (no registry entry)\n")
        for it in missing_explicit[:100]:
            md.append(f"- {it['key']} — examples: {', '.join([e['file'].split('/')[-1] for e in it['examples']])}\n")
    if matched_only_by_generic:
        md.append("## Matched only by generic handlers (triage)\n")
        for it in matched_only_by_generic[:100]:
            md.append(f"- {it['key']} — examples: {', '.join([e['file'].split('/')[-1] for e in it['examples']])}\n")

    out_md = OUT_DIR / "unmodeled_props_report.md"
    with out_md.open("w") as fh:
        fh.write("\n".join(md))

    print("Wrote:", out_json, out_md)


if __name__ == '__main__':
    main()
