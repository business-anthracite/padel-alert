"""Diagnostic Ten'Up phase 4 (09/07/2026) - TEMPORAIRE.
1. Scan des 60 chunks JS Nuxt -> carte des endpoints back/public
2. Recherche Padel simulee APRES fermeture du popup cookies -> capture des appels
"""
import re
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
ENTRY_JS     = f"{TENUP_BASE}/_nuxt/D1gS3xjv.js"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

print("=== 1. SCAN DES BUNDLES JS ===")
s = requests.Session()
s.headers.update({"User-Agent": UA})
try:
    entry = s.get(ENTRY_JS, timeout=30)
    print("entry status:", entry.status_code, "taille:", len(entry.text))
    chunks = sorted(set(re.findall(r'[A-Za-z0-9_\-]{6,14}\.js', entry.text)))
    print("chunks detectes:", len(chunks))
    endpoints = set()
    api_hints = set()
    scanned = 0
    for c in chunks:
        try:
            r = s.get(f"{TENUP_BASE}/_nuxt/{c}", timeout=20)
            if r.status_code != 200:
                continue
            scanned += 1
            js = r.text
            for m in re.findall(r'back/public/[A-Za-z0-9_/${}.\-]{2,90}', js):
                endpoints.add(m)
            for m in re.findall(r'["`](/[a-z][a-z0-9_/\-]{3,60}/(?:recherche|search|tournoi|tournois|competition)[a-z0-9_/\-]*)["`]', js):
                api_hints.add(m if isinstance(m, str) else m[0])
        except Exception:
            pass
    print(f"chunks scannes: {scanned}")
    print(f"\nENDPOINTS back/public ({len(endpoints)}) :")
    for e in sorted(endpoints):
        print("   ", e)
    print(f"\nAUTRES ROUTES api candidates ({len(api_hints)}) :")
    for e in sorted(api_hints):
        print("   ", e)
except Exception as e:
    print("scan ECHEC:", str(e)[:200])

print("\n=== 2. RECHERCHE SIMULEE (popup ferme d abord) ===")
captured = []

def on_response(resp):
    req = resp.request
    if req.resource_type not in ("xhr", "fetch"):
        return
    if "tenup" not in req.url and "fft" not in req.url:
        return
    entry = {"method": req.method, "url": req.url[:250], "status": resp.status,
             "post": (req.post_data or "")[:500]}
    try:
        if "json" in resp.headers.get("content-type", ""):
            entry["body"] = resp.text()[:700]
    except Exception:
        pass
    captured.append(entry)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR",
                              viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("response", on_response)
    page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass

    # 2a. Fermer le popup cookies (bloquait tous les clics en phase 3)
    closed = False
    for pattern in [r"tout refuser", r"tout accepter"]:
        try:
            page.get_by_role("button", name=re.compile(pattern, re.I)).first.click(timeout=4000)
            print(f"[popup ferme via '{pattern}']")
            closed = True
            break
        except Exception:
            pass
    if not closed:
        print("[popup non trouve - peut-etre absent]")
    time.sleep(1)

    # 2b. Cliquer le bouton Padel (role button)
    try:
        page.get_by_role("button", name=re.compile(r"^padel$", re.I)).first.click(timeout=5000)
        print("[clic bouton Padel OK]")
    except Exception as e:
        print("[clic Padel ECHEC]", str(e)[:100])
    time.sleep(1)

    # 2c. Cliquer le RECHERCHER du formulaire (le dernier)
    try:
        page.get_by_role("button", name=re.compile(r"rechercher", re.I)).last.click(timeout=5000)
        print("[clic RECHERCHER (form) OK]")
    except Exception as e:
        print("[clic RECHERCHER ECHEC]", str(e)[:100])

    time.sleep(10)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    print("URL apres recherche :", page.url)
    snippet = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ').substring(0, 600)")
    print("Body apres recherche :", snippet)
    browser.close()

print(f"\n=== APPELS TENUP/FFT CAPTURES ({len(captured)}) ===")
for e in captured:
    print(f"\n{e['method']} {e['url']}  -> {e['status']}")
    if e.get("post"):
        print("  POST :", e["post"])
    if e.get("body"):
        print("  JSON :", e["body"].replace(chr(10), " ")[:700])

print("\nDIAGNOSTIC PHASE 4 TERMINE")
