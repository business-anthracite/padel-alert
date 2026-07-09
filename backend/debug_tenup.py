"""Diagnostic Ten'Up phase 5 (09/07/2026) - TEMPORAIRE.
1. Recherche Padel simulee : popup ferme + clics JS directs (bypass role)
2. Scan des chunks JS REELLEMENT charges (avec cookies Queue-it) -> endpoints
"""
import re
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

captured = []

def on_response(resp):
    req = resp.request
    if req.resource_type not in ("xhr", "fetch", "document"):
        return
    if "tenup" not in req.url and "fft" not in req.url:
        return
    entry = {"method": req.method, "url": req.url[:250], "status": resp.status,
             "type": req.resource_type, "post": (req.post_data or "")[:500]}
    try:
        if "json" in resp.headers.get("content-type", ""):
            entry["body"] = resp.text()[:800]
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

    # Popup cookies
    try:
        page.get_by_role("button", name=re.compile("tout refuser", re.I)).first.click(timeout=4000)
        print("[popup ferme]")
        time.sleep(2)
    except Exception:
        print("[popup absent]")

    # Clic JS direct sur le bouton Padel
    ok = page.evaluate("""() => {
        const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === 'Padel');
        if (b) { b.click(); return true; } return false;
    }""")
    print("[clic JS Padel]", ok)
    time.sleep(1)

    # Clic JS direct sur le DERNIER bouton RECHERCHER (celui du formulaire)
    ok = page.evaluate("""() => {
        const bs = [...document.querySelectorAll('button')].filter(x => /rechercher/i.test(x.innerText.trim()));
        if (bs.length) { bs[bs.length - 1].click(); return bs.length; } return 0;
    }""")
    print("[clic JS RECHERCHER] boutons matches:", ok)

    time.sleep(10)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    print("URL apres recherche :", page.url)
    snippet = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ').substring(0, 800)")
    print("Body apres recherche :", snippet)

    # Chunks JS reellement charges par le navigateur
    loaded_js = page.evaluate("() => performance.getEntriesByType('resource').map(r => r.name).filter(n => n.includes('_nuxt') && n.endsWith('.js'))")
    print(f"\nChunks JS charges par le navigateur : {len(loaded_js)}")
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()

print(f"\n=== APPELS TENUP/FFT CAPTURES ({len(captured)}) ===")
for e in captured:
    print(f"\n{e['method']} [{e['type']}] {e['url']}  -> {e['status']}")
    if e.get("post"):
        print("  POST :", e["post"])
    if e.get("body"):
        print("  JSON :", e["body"].replace(chr(10), " ")[:800])

print("\n=== SCAN DES CHUNKS (avec cookies Queue-it) ===")
s = requests.Session()
s.headers.update({"User-Agent": UA})
for k, v in cookies.items():
    s.cookies.set(k, v)
endpoints = set()
scanned = 0
for u in loaded_js[:80]:
    try:
        r = s.get(u, timeout=20)
        if r.status_code != 200:
            continue
        scanned += 1
        for m in re.findall(r'back/public/[A-Za-z0-9_/${}.\-]{2,90}', r.text):
            endpoints.add(m)
    except Exception:
        pass
print(f"chunks scannes: {scanned}")
print(f"ENDPOINTS back/public ({len(endpoints)}) :")
for e in sorted(endpoints):
    print("   ", e)

print("\nDIAGNOSTIC PHASE 5 TERMINE")
