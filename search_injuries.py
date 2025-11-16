import sys
import csv
from collections import defaultdict

CSV = 'nfl_data_2025_csv/injuries_espn_raw.csv'

def load():
    rows = []
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def search(rows, q):
    q = q.lower()
    out = []
    for r in rows:
        # search across name, cols, context, type
        fields = ' '.join([r.get('type','') or '', r.get('name','') or '', r.get('cols','') or '', r.get('context','') or '']).lower()
        if q in fields:
            out.append(r)
    return out


def summarize(rows, limit=10):
    # show first matches
    for i,r in enumerate(rows[:limit]):
        print(f"--- Match {i+1} ---")
        print('type:', r.get('type'))
        if r.get('name'):
            print('name:', r.get('name'))
        if r.get('href'):
            print('href:', r.get('href'))
        if r.get('cols'):
            print('cols snippet:\n', r.get('cols')[:1000])
        if r.get('context'):
            print('context snippet:\n', r.get('context')[:500])
        if r.get('data_keys'):
            print('data_keys:', r.get('data_keys'))
        print()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python search_injuries.py <query>')
        sys.exit(1)
    q = ' '.join(sys.argv[1:])
    rows = load()
    results = search(rows, q)
    print(f'Found {len(results)} matching records for "{q}"')
    summarize(results, limit=10)
