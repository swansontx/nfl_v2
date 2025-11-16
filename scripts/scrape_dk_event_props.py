#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import json, time, os, re, sys

os.makedirs('outputs', exist_ok=True)

SEARCH_TERMS = ['Vikings Chargers', 'Minnesota Vikings Los Angeles Chargers', 'Vikings at Chargers']

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        requests = []

        def on_request(req):
            url = req.url
            if 'odds' in url or 'events' in url or 'markets' in url or 'sportsbook' in url or 'props' in url:
                requests.append({'url': url, 'method': req.method, 'post': req.post_data})

        page.on('request', on_request)

        print('Navigating to DraftKings sportsbook')
        page.goto('https://sportsbook.draftkings.com', timeout=60000)
        time.sleep(2)

        # try the site search input if present
        try:
            # click search icon
            page.click('button[aria-label="Search"]', timeout=3000)
        except Exception:
            pass
        time.sleep(1)
        # type search
        searched=False
        for term in SEARCH_TERMS:
            try:
                page.fill('input[type="search"]', term, timeout=3000)
                page.keyboard.press('Enter')
                time.sleep(3)
                searched=True
                break
            except Exception:
                continue
        # fallback: navigate to nfl page
        if not searched:
            try:
                page.goto('https://sportsbook.draftkings.com/sports/football', timeout=60000)
                time.sleep(2)
            except Exception:
                pass

        # wait and capture network
        time.sleep(5)

        # save captured request URLs
        ts = time.strftime('%Y%m%d_%H%M%S')
        out = f'outputs/dk_requests_{ts}.json'
        with open(out, 'w') as f:
            json.dump(requests, f, indent=2)
        print('Saved requests to', out)

        # try to dump any response bodies for requests that look JSON
        saved=0
        for i,req in enumerate(requests):
            url=req['url']
            try:
                if url.startswith('http'):
                    resp = context.request.get(url)
                    ctype = resp.headers.get('content-type','')
                    if 'application/json' in ctype or url.endswith('.json') or 'events' in url or 'markets' in url:
                        data = resp.text()
                        fname = f'outputs/dk_resp_{i}_{ts}.json'
                        with open(fname,'w') as f:
                            f.write(data)
                        saved+=1
            except Exception:
                continue
        print('Saved', saved, 'response bodies')
        browser.close()

if __name__=='__main__':
    run()
