"""Diagnostic Ten'Up phase 14 (09/07) - SOURCE COORDS suite.
1. GET /back/public/v1/clubs (+ variantes query)
2. Capture reseau de la page /recherche/clubs -> endpoint + shape (CP/coords ?)
"""
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE = "https://tenup.fft.fr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Content-Type": "application/json", "Origin": TENUP_BASE,
                  "Referer": f"{TENUP_BASE}/recherche/clubs/resultats"})

print("=== 1. GET /back/public/v1/clubs (variantes) ===")
for path in [
    "/back/public/v1/clubs",
    "/back/public/v1/clubs?pratique=PADEL&from=0&size=3",
    "/back/public/v1/clubs?nom=padel&from=0&size=3",
    "/back/public/v1/clubs/formulaire",
]:
    try:
        r = s.get(TENUP_BASE + path, timeout=25, allow_redirects=False)
        ct = r.headers.get("content-type","")[:30]
        print(f"\nGET {path} -> {r.status_code} | {ct}")
        if "json" in ct:
            body = r.text
            print("  a codePostal:", "codepostal" in body.lower(), "| a lat:", '"lat"' in body, "| a adresse:", "adresse" in body.lower())
            print("  [:400]:", body[:400].replace(chr(10)," "))
    except Exception as e:
        print(f"GET {path} -> EXC {str(e)[:80]}")

print("\n=== 2. Capture reseau page /recherche/clubs ===")
captured = []
AD = ("doubleclick","googlesyndication","adtrafficquality","googletag","google-analytics","gstatic","sodar","iconify","simplesvg","unisvg","queue-it")
def on_resp(resp):
    req = resp.request
    if req.resource_type not in ("xhr","fetch"): return
    if any(h in req.url for h in AD): return
    if "back/public" not in req.url and "/api/" not in req.url: return
    e = {"method":req.method,"url":req.url[:230],"status":resp.status,"post":(req.post_data or "")[:400]}
    try:
        if "json" in resp.headers.get("content-type",""):
            e["body"] = resp.text()[:900]
    except Exception: pass
    captured.append(e)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR", viewport={"width":1440,"height":900})
    page = ctx.new_page()
    page.on("response", on_resp)
    page.goto(f"{TENUP_BASE}/recherche/clubs", wait_until="domcontentloaded", timeout=60000)
    try: page.wait_for_load_state("networkidle", timeout=30000)
    except Exception: pass
    try:
        page.get_by_role("button", name=re.compile("tout refuser", re.I)).first.click(timeout=4000)
        time.sleep(1)
    except Exception: pass
    # Selectionner Padel puis rechercher
    page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Padel'); if(b)b.click(); }""")
    time.sleep(1)
    page.evaluate("""() => { const bs=[...document.querySelectorAll('button')].filter(x=>/rechercher/i.test(x.innerText.trim())); if(bs.length)bs[bs.length-1].click(); }""")
    time.sleep(10)
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except Exception: pass
    print("URL:", page.url)
    browser.close()

print(f"\nappels API captures ({len(captured)}):")
for e in captured:
    print(f"\n{e['method']} {e['url']} -> {e['status']}")
    if e.get("post"): print("  POST:", e["post"])
    if e.get("body"):
        b = e["body"]
        print("  a codePostal:", "codepostal" in b.lower(), "| a lat:", '"lat"' in b)
        print("  JSON:", b[:600].replace(chr(10)," "))

print("\nDIAGNOSTIC PHASE 14 TERMINE")
