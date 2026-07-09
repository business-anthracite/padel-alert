"""Diagnostic Ten'Up phase 3 (09/07/2026) - TEMPORAIRE.
Objectif : cartographier la nouvelle API (/back/public/...) en analysant
les bundles JS de l'app Nuxt + tenter la recherche avec le bon bouton.
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
    if req.resource_type not in ("xhr", "fetch"):
        return
    entry = {"method": req.method, "url": req.url[:250], "status": resp.status,
             "post": (req.post_data or "")[:400]}
    try:
        if "json" in resp.headers.get("content-type", ""):
            entry["body"] = resp.text()[:500]
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

    print("=== BOUTONS VISIBLES ===")
    btns = page.evaluate("() => [...document.querySelectorAll('button, [role=button], input[type=submit]')].map(b => (b.innerText||b.value||'').trim().replace(/\\s+/g,' ').substring(0,60)).filter(t => t)")
    for b in btns:
        print("   [", b, "]")

    print("\n=== RUNTIME CONFIG NUXT ===")
    try:
        cfg = page.evaluate("() => JSON.stringify(window.__NUXT__ && (window.__NUXT__.config || window.__NUXT__.state || {})).substring(0, 1500)")
        print(cfg)
    except Exception as e:
        print("(indisponible)", str(e)[:100])

    print("\n=== SCRIPTS NUXT ===")
    scripts = page.evaluate("() => [...document.querySelectorAll('script[src]')].map(s => s.src)")
    nuxt_js = [u for u in scripts if "_nuxt" in u]
    for u in nuxt_js:
        print("   ", u)

    cookies = {c["name"]: c["value"] for c in ctx.cookies()}

    # Tentative recherche avec le bouton de la zone de formulaire (dernier RECHERCHER)
    print("\n=== TENTATIVE RECHERCHE (dernier bouton RECHERCHER) ===")
    try:
        page.get_by_text("Padel", exact=True).last.click(timeout=4000)
        print("[clic Padel OK]")
    except Exception as e:
        print("[clic Padel ECHEC]", str(e)[:100])
    time.sleep(1)
    try:
        page.get_by_role("button", name=re.compile("rechercher", re.I)).last.click(timeout=4000)
        print("[clic bouton RECHERCHER (role) OK]")
    except Exception as e:
        print("[clic role ECHEC]", str(e)[:100])
        try:
            page.get_by_text("RECHERCHER", exact=False).last.click(timeout=4000)
            print("[clic texte RECHERCHER (last) OK]")
        except Exception as e2:
            print("[clic texte ECHEC]", str(e2)[:100])
    time.sleep(8)
    print("URL apres recherche :", page.url)
    snippet = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ').substring(0, 500)")
    print("Body apres recherche :", snippet)
    browser.close()

print(f"\n=== APPELS XHR/FETCH ({len(captured)}) - TOUS ===")
for e in captured:
    print(f"\n{e['method']} {e['url']}  -> {e['status']}")
    if e.get("post"):
        print("  POST :", e["post"])
    if e.get("body"):
        print("  JSON :", e["body"].replace(chr(10), " ")[:400])

print("\n=== ANALYSE DES BUNDLES JS (endpoints back/public) ===")
s = requests.Session()
s.headers.update({"User-Agent": UA})
for k, v in cookies.items():
    s.cookies.set(k, v)
endpoints = set()
for u in nuxt_js[:15]:
    try:
        js = s.get(u, timeout=30).text
    except Exception:
        continue
    for m in re.findall(r'back/public/[A-Za-z0-9_/${}.\-]{2,80}', js):
        endpoints.add(m)
    # imports dynamiques : recuperer aussi les chunks references
    for chunk in re.findall(r'"(\./)?([A-Za-z0-9_.\-]+\.js)"', js)[:0]:
        pass
print(f"Endpoints trouves dans {len(nuxt_js[:15])} bundles :")
for e in sorted(endpoints):
    print("   ", e)

if not endpoints:
    print("(aucun - les endpoints sont peut-etre dans des chunks lazy-loades)")
    # fallback : lister les chunks du manifest
    try:
        js = s.get(nuxt_js[0], timeout=30).text if nuxt_js else ""
        chunks = sorted(set(re.findall(r'[A-Za-z0-9_.\-]+\.js', js)))[:60]
        print("Chunks references par l entry :", len(chunks))
        for c in chunks[:40]:
            print("   ", c)
    except Exception:
        pass

print("\nDIAGNOSTIC PHASE 3 TERMINE")
