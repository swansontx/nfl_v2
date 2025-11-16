#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, json, os

os.makedirs('outputs/dk_event_capture', exist_ok=True)

# load selected events
sel = json.load(open('data/odds_live/selected_events_20251025_0742.json'))

def normalize_title(ev):
    away = ev.get('away') or ev.get('away_team')
    home = ev.get('home') or ev.get('home_team')
    return f"{away} at {home}" if away and home else (ev.get('away')+' '+ev.get('home'))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64)')

    for ev in sel:
        eid = ev.get('id')
        title = normalize_title(ev)
        print('Processing event:', title)
        page = context.new_page()
        captured = []
        def on_response(resp):
            try:
                url = resp.url
                ctype = resp.headers.get('content-type','')
                if 'application/json' in ctype or 'markets' in url or 'selections' in url or '/api/' in url:
                    text = resp.text()
                    captured.append({'url': url, 'status': resp.status, 'text': text[:300000]})
            except Exception:
                pass
        page.on('response', on_response)

        try:
            page.goto('https://sportsbook.draftkings.com', timeout=60000)
            time.sleep(2)
            # open search
            try:
                page.click('button[aria-label="Search"]', timeout=3000)
            except Exception:
                pass
            time.sleep(1)
            # try several query forms
            queries = [f"{ev.get('away')} at {ev.get('home')}", f"{ev.get('away')} vs {ev.get('home')}", f"{ev.get('away')} {ev.get('home')}"]
            searched=False
            for q in queries:
                try:
                    page.fill('input[type="search"]', q)
                    time.sleep(0.5)
                    page.keyboard.press('Enter')
                    time.sleep(3)
                    searched=True
                    break
                except Exception:
                    continue
            if not searched:
                # try direct nfl landing
                page.goto('https://sportsbook.draftkings.com/sports/football', timeout=60000)
                time.sleep(2)
            # look for event link text and click
            # find element containing away team name and click
            try:
                # search results may include anchor with event title
                link = page.query_selector(f"text=\"{ev.get('away')}\" >> text=\"{ev.get('home')}\"")
                if link:
                    link.click()
                    time.sleep(2)
                else:
                    # fallback: click first event card
                    elems = page.query_selector_all('a[data-testid="event-link"]')
                    if elems:
                        elems[0].click(); time.sleep(2)
            except Exception:
                pass
            # open Player Props tab if present
            try:
                # many sites have a button/link 'Player Props' or 'Player Prop'
                btn = page.query_selector('text=Player Props') or page.query_selector('text=Player Prop')
                if btn:
                    btn.click()
                    time.sleep(2)
            except Exception:
                pass
            # wait a bit to capture network
            time.sleep(4)
            ts = time.strftime('%Y%m%d_%H%M%S')
            out = f'outputs/dk_event_capture/{eid}_{ts}.json'
            with open(out,'w') as f:
                json.dump(captured, f)
            print('Saved capture to', out, 'responses:', len(captured))
        except Exception as e:
            print('Failed event', title, e)
        finally:
            try:
                page.close()
            except Exception:
                pass
        # sleep between events to be gentle
        time.sleep(6)

    browser.close()
print('All done')
