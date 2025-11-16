#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, json, os, sys

if len(sys.argv) < 2:
    print('Usage: scrape_dk_event_props_target.py "SEARCH TERM"')
    sys.exit(1)
term = sys.argv[1]
print('Search term:', term)

os.makedirs('outputs/dk_target', exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    captured = []

    def on_response(resp):
        url = resp.url
        ctype = resp.headers.get('content-type','')
        if 'application/json' in ctype or 'events' in url or 'markets' in url or '/api/' in url:
            try:
                text = resp.text()
                captured.append({'url': url, 'status': resp.status, 'text': text[:200000]})
            except Exception:
                pass

    page.on('response', on_response)
    page.goto('https://sportsbook.draftkings.com', timeout=60000)
    time.sleep(2)
    # open search
    try:
        page.click('button[aria-label="Search"]', timeout=3000)
        time.sleep(1)
    except Exception:
        pass
    # type and search
    try:
        page.fill('input[type="search"]', term)
        time.sleep(0.5)
        page.keyboard.press('Enter')
        time.sleep(3)
    except Exception:
        # fallback: go to nfl page
        page.goto('https://sportsbook.draftkings.com/sports/football', timeout=60000)
        time.sleep(2)
    # wait for possible network calls
    time.sleep(6)

    ts = time.strftime('%Y%m%d_%H%M%S')
    out = f'outputs/dk_target/{term[:40].replace(" ","_")}_{ts}.json'
    with open(out, 'w') as f:
        json.dump(captured, f)
    print('Saved captured responses to', out)
    browser.close()
