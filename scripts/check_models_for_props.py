#!/usr/bin/env python3
"""
Scan cached OddsAPI snapshots and project outputs for props, canonicalize them,
and compare against models/registry.yaml to find unmodeled props.

This version treats registry entries marked with `is_generic: true` as generic
handlers. If a canonical prop only matches generic patterns, it will be listed
as "matched_only_by_generic" so you can triage and add explicit models.
"""
import json
import re
import glob
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path.home() / ".cache" / "goose" / "computer_controller"
SNAPSHOT_GLOBS = [str(CACHE_DIR / "web_*.json"), str(ROOT / "outputs" / "**" / "*.json")]
# If you want to point at another folder for API snapshots, add it here.


def load_registry(reg_path=None):
    p = Path(reg_path or ROOT / "models" / "registry.yaml")
    with p.open() as fh:
        reg = yaml.safe_load(fh)
    # compile patterns into regex (escape and replace * with .+)
    patterns = []
    for key, entry in reg.items():
        pat = entry.get("pattern", key)
        # make a regex that matches full string
        pat_re = re.escape(pat).replace(r"\\*", r"(.+)")
        is_generic = bool(entry.get("is_generic"))
        patterns.append((re.compile(f"^{pat_re}$"), key, is_generic))
    return reg, patterns


def normalize_outcome(market_key, outcome_label, participant=None):
    # First prefer an explicit mapping from market_key -> canonical template
    from pathlib import Path
    import yaml
    ROOT = Path(__file__).resolve().parents[1]
    mtc_path = ROOT / 'models' / 'market_to_canonical.yaml'
    if mtc_path.exists() and market_key:
        mtc = yaml.safe_load(mtc_path.open())
        tmpl = mtc.get(market_key)
        if tmpl:
            return tmpl.format(participant=slugify(participant))

    s = f"{market_key} {outcome_label} {participant or ''}".lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # common rules
    if "passing yards" in s or "pass yards" in s:
        return f"player_{slugify(participant)}_passing_yards"
    if "receiving yards" in s or "rec yards" in s:
        return f"player_{slugify(participant)}_receiving_yards"
    if "receptions" in s or r"\brec\b" in s:
        return f"player_{slugify(participant)}_receptions"
    if "anytime td" in s or ("anytime" in s and "td" in s) or ("any td" in s):
        return f"player_{slugify(participant)}_anytime_td"
    if "combined td" in s or "combined tds" in s or "total tds" in s:
        return f"player_{slugify(participant)}_combined_tds"
    if "rushing yards" in s or "rush yards" in s:
        return f"player_{slugify(participant)}_rushing_yards"
    if "rush attempts" in s or "rushes" in s:
        return f"player_{slugify(participant)}_rush_attempts"
    if "fumbles" in s:
        return f"player_{slugify(participant)}_fumbles"
    if "interceptions" in s:
        return f"player_{slugify(participant)}_interceptions"
    # team points
    if ("team points" in s) or ("points" in s and participant and participant.lower() in s):
        return f"team_{slugify(participant)}_points"

    # fallback: normalize to underscored phrase
    return re.sub(r"\s+", "_", s)


def slugify(name):
    if not name:
        return "unknown"
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]+", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name


def load_snapshots(globs):
    files = []
    for g in globs:
        files.extend(glob.glob(g, recursive=True))
    for f in files:
        try:
            with open(f) as fh:
                yield f, json.load(fh)
        except Exception:
            continue


def find_props_in_snapshot(snapshot):
    props = []
    # support OddsAPI v4 format and generic outputs
    if isinstance(snapshot, dict) and "bookmakers" in snapshot:
        for book in snapshot.get("bookmakers", []):
            for market in book.get("markets", []) or []:
                market_key = market.get("key")
                for outcome in market.get("outcomes", []) or []:
                    # outcome structure may vary; prefer 'description' (OddsAPI often puts player name here)
                    participant = outcome.get("description") or outcome.get("participant") or outcome.get("player") or outcome.get("name")
                    # label should capture Over/Under/Yes/No or specific outcome label
                    label = outcome.get("name") or outcome.get("label") or ""
                    # Some markets (like player_anytime_td) publish many 'Yes' outcomes with description=player name.
                    # For other markets the player name may appear in the market object; try to detect that too.
                    if (not participant or participant in ("Yes","No","Over","Under")) and market.get("key") and market.get("key").startswith("player_"):
                        # try market-level fields or outcome text that include a player
                        # scan other fields in outcome for embedded names
                        for fk in ("description","player","participant","label","name","translations"):
                            v = outcome.get(fk)
                            if isinstance(v, str) and v not in ("Yes","No","Over","Under") and len(v) > 0 and not v.isdigit():
                                participant = v
                                break
                    props.append((market_key, label, participant))
    # also detect structures like outputs/top_nontrivial.json (custom)
    if isinstance(snapshot, list):
        for item in snapshot:
            if isinstance(item, dict):
                mk = item.get("market") or item.get("market_key")
                lab = item.get("outcome") or item.get("label") or item.get("name")
                part = item.get("participant") or item.get("player")
                if mk or lab:
                    props.append((mk, lab, part))
    return props


def matches_registry(patterns, key):
    """Return (matched_bool, matched_generic_bool)."""
    matched = False
    matched_generic = False
    for p, k, is_generic in patterns:
        if p.match(key):
            matched = True
            if is_generic:
                matched_generic = True
            else:
                # matched an explicit non-generic pattern; return early
                return True, False
    return matched, matched_generic


def main():
    reg, patterns = load_registry()
    canonical_set = {}
    for fname, snap in load_snapshots(SNAPSHOT_GLOBS):
        for mk, lab, part in find_props_in_snapshot(snap):
            key = normalize_outcome(mk or "", lab or "", part)
            canonical_set.setdefault(key, []).append({"file": fname, "market": mk, "label": lab, "participant": part})

    missing_explicit = []
    matched_only_by_generic = []
    for key, samples in canonical_set.items():
        matched, matched_generic = matches_registry(patterns, key)
        if not matched:
            missing_explicit.append((key, samples[:2]))
        elif matched and matched_generic:
            # if matched_generic True but no explicit non-generic match, record it
            # Note: matches_registry returns early if non-generic match found, so here matched_generic implies only generic matched
            matched_only_by_generic.append((key, samples[:2]))

    print(f"Total unique canonical props seen: {len(canonical_set)}")
    if missing_explicit:
        print("\nUNMATCHED (no registry entry):")
        for k, s in missing_explicit:
            print(k)
            for ex in s:
                print("  -", ex)
    else:
        print("\nNo completely unmatched props.")

    if matched_only_by_generic:
        print("\nMATCHED ONLY BY GENERIC PATTERNS (please triage):")
        for k, s in matched_only_by_generic:
            print(k)
            for ex in s:
                print("  -", ex)
    else:
        print("\nNo props matched exclusively by generic handlers.")


if __name__ == "__main__":
    main()
