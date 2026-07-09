"""Diagnostic Ten'Up phase 7 (09/07/2026) - TEMPORAIRE. Capture de l'API de resultats.
1. Naviguer directement vers /recherche/tournois/resultats -> capturer les XHR
2. Sonder en direct les endpoints /back/public/v1/tournois/*
"""
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE = "https://tenup.fft.fr"
RESULTS    = f"{TENUP_BASE}/recherche/tournois/resultats"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

captured = []
AD = ("doubleclick", "googlesyndication", "adtrafficquality", "googletag", "google-analytics", "gstatic", "sodar", "iconify", "simplesvg", "unisvg")

def on_response(resp):
    req = resp.request
    if req.resource_type not in ("xhr", "fetch"):
        return
    if any(h in req.url for h in AD):
        return
    e = {"method": req.method, "url": req.url, "status": resp.status, "post": (req.post_data or "")[:600]}
    try:
        if "json" in resp.headers.get("content-type", ""):
            e["body"] = resp.text()[:1200]
    except Exception:
        pass
    captured.append(e)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR", viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("response", on_response)
    # Passer par la home de recherche pour recuperer les cookies queue-it
    page.goto(f"{TENUP_BASE}/recherche/tournois", wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name=re.compile("tout refuser", re.I)).first.click(timeout=4000)
        time.sleep(1)
    except Exception:
        pass

    print("=== NAVIGATION DIRECTE VERS LA PAGE RESULTATS ===")
    page.goto(RESULTS, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    time.sleep(8)
    print("URL :", page.url)
    body = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ')")
    print("Body[:400] :", body[:400])
    print("codes niveaux visibles :", sorted(set(re.findall(r'P\d{2,4}\b', body)))[:15])
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()

print(f"\n=== XHR/FETCH CAPTURES ({len(captured)}) ===")
for e in captured:
    print(f"\n{e['method']} {e['url'][:220]}  -> {e['status']}")
    if e.get("post"):
        print("  POST :", e["post"])
    if e.get("body"):
        print("  JSON :", e["body"].replace(chr(10), " ")[:1000])

print("\n=== SONDAGE DIRECT DES ENDPOINTS CANDIDATS ===")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Referer": RESULTS})
for k, v in cookies.items():
    s.cookies.set(k, v)
candidates = [
    ("GET", "/back/public/v1/tournois/formulaire?environment=web_prod"),
    ("GET", "/back/public/v1/tournois/resultats?environment=web_prod"),
    ("GET", "/back/public/v1/recherche/tournois/resultats?environment=web_prod"),
    ("GET", "/back/public/recherche/tournois/resultats?environment=web_prod"),
    ("POST", "/back/public/v1/tournois/resultats?environment=web_prod"),
    ("POST", "/back/public/v1/recherche/tournois/resultats?environment=web_prod"),
]
for method, path in candidates:
    url = TENUP_BASE + path
    try:
        if method == "GET":
            r = s.get(url, timeout=25, allow_redirects=False)
        else:
            r = s.post(url, json={"pratique": "PADEL", "page": 0}, timeout=25, allow_redirects=False)
        ct = r.headers.get("content-type", "")[:40]
        print(f"\n{method} {path}\n  -> {r.status_code} | {ct}")
        if "json" in ct:
            print("  JSON :", r.text[:500].replace(chr(10), " "))
        elif r.status_code in (301, 302):
            print("  location :", r.headers.get("location", "-")[:120])
        else:
            print("  body[:120] :", r.text[:120].replace(chr(10), " "))
    except Exception as e:
        print(f"\n{method} {path} -> EXCEPTION {str(e)[:100]}")

print("\nDIAGNOSTIC PHASE 7 TERMINE")
