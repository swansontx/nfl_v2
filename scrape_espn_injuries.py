import requests
from bs4 import BeautifulSoup
import csv
import re
import json

URL = 'https://www.espn.com/nfl/injuries'
headers = {
    'User-Agent': 'Mozilla/5.0 (compatible; InjuryScraper/1.0; +https://example.com)'
}
resp = requests.get(URL, headers=headers, timeout=15)
resp.raise_for_status()
html = resp.text
soup = BeautifulSoup(html, 'lxml')

records = []

# Strategy 1: look for tables
for table in soup.find_all('table'):
    # columns headers
    headers = [th.get_text(strip=True) for th in table.find_all('th')]
    if not headers:
        continue
    rows = table.find_all('tr')
    for tr in rows[1:]:
        cols = [td.get_text(' ', strip=True) for td in tr.find_all(['td','th'])]
        if not cols:
            continue
        # store as raw list
        rec = {'source':'table', 'cols': cols}
        records.append(rec)

# Strategy 2: look for lists/cards with player names and statuses
# ESPN uses anchor tags to player pages; find sections containing 'injury'
for tag in soup.find_all(['section','div']):
    text = tag.get_text(' ', strip=True).lower()
    if 'injury' in text or 'status' in text:
        # look for player links inside
        for a in tag.find_all('a', href=True):
            href = a['href']
            if re.search(r'/player/|/name/', href) or re.search(r'/players?/', href):
                name = a.get_text(' ', strip=True)
                if name and len(name.split())<=4:
                    records.append({'source':'card', 'name':name, 'href':href, 'context': tag.get_text(' ', strip=True)[:200]})

# Strategy 3: try to extract JSON blobs inside scripts
for script in soup.find_all('script'):
    if not script.string:
        continue
    txt = script.string
    # find json-like structures
    if 'injury' in txt.lower() or 'injuries' in txt.lower():
        # try to find {...}
        try:
            # crude: find first { and last }
            start = txt.find('{')
            end = txt.rfind('}')
            if start!=-1 and end!=-1 and end>start:
                blob = txt[start:end+1]
                # attempt to fix trailing commas
                blob = re.sub(r',\s*}', '}', blob)
                blob = re.sub(r',\s*]', ']', blob)
                data = json.loads(blob)
                records.append({'source':'json_script', 'data_keys': list(data.keys())[:10]})
        except Exception:
            pass

# Write out a simple CSV capturing useful fields depending on record type
out_file = 'nfl_data_2025_csv/injuries_espn_raw.csv'
with open(out_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['type','name','href','cols','context','data_keys'])
    for r in records:
        writer.writerow([r.get('source'), r.get('name',''), r.get('href',''), '\n'.join(r.get('cols',[])) if isinstance(r.get('cols',[]), list) else r.get('cols',''), r.get('context',''), ','.join(r.get('data_keys',[])) if isinstance(r.get('data_keys',[]), list) else r.get('data_keys','')])

print('Wrote', out_file, 'records:', len(records))
