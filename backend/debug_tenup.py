"""Diagnostic Ten'Up phase 6 (09/07/2026) - TEMPORAIRE. Decisif.
1. Capture TOUS les XHR/fetch (tous hosts) pendant une recherche
2. Grep elargi des chunks : /back/, environment=web_prod, base URL API, tournoi/search
"""
import re
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

captured = []

def on_request(req):
    if req.resource_type in ("xhr", "fetch"):
        captured.append({"method": req.method, "url": req.url, "post": (req.post_data or "")[:500]})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR", viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("request", on_request)
    page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name=re.compile("tout refuser", re.I)).first.click(timeout=4000)
        print("[popup ferme]")
        time.sleep(2)
    except Exception:
        print("[popup absent]")

    page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Padel'); if(b)b.click(); }""")
    time.sleep(1)
    n0 = len(captured)
    page.evaluate("""() => { const bs=[...document.querySelectorAll('button')].filter(x=>/rechercher/i.test(x.innerText.trim())); if(bs.length)bs[bs.length-1].click(); }""")
    print("[recherche declenchee]")
    time.sleep(12)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    print("URL apres :", page.url)
    body = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ')")
    # indices de resultats : mots "tournoi(s)", "resultat", codes P25/P100
    print("Body contient 'tournoi' x", body.lower().count("tournoi"), "| 'resultat' x", body.lower().count("sultat"))
    m = re.findall(r'P\d{2,4}\b', body)
    print("codes niveaux visibles :", sorted(set(m))[:15])
    loaded_js = page.evaluate("() => performance.getEntriesByType('resource').map(r=>r.name).filter(n=>n.includes('_nuxt')&&n.endsWith('.js'))")
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()

print(f"\n=== TOUS LES XHR/FETCH ({len(captured)}) - filtre hors pub ===")
AD_HOSTS = ("doubleclick", "googlesyndication", "adtrafficquality", "googletag", "google-analytics", "gstatic", "sodar")
for e in captured:
    if any(h in e["url"] for h in AD_HOSTS):
        continue
    print(f"\n{e['method']} {e['url'][:230]}")
    if e.get("post"):
        print("  POST :", e["post"])

print("\n=== GREP ELARGI DES CHUNKS ===")
s = requests.Session()
s.headers.update({"User-Agent": UA})
for k, v in cookies.items():
    s.cookies.set(k, v)
paths, bases, searchy = set(), set(), set()
scanned = 0
for u in loaded_js[:80]:
    try:
        r = s.get(u, timeout=20)
        if r.status_code != 200:
            continue
        scanned += 1
        js = r.text
        for m in re.findall(r'/back/[A-Za-z0-9_/${}.\-]{2,80}', js):
            paths.add(m)
        for m in re.findall(r'https?://[A-Za-z0-9.\-]*(?:fft|tenup|api)[A-Za-z0-9.\-]*', js):
            bases.add(m)
        for m in re.findall(r'["`](/[A-Za-z0-9_/\-]*(?:tournoi|recherche|search|competition)[A-Za-z0-9_/\-]*)["`]', js, re.I):
            searchy.add(m if isinstance(m, str) else m[0])
        for m in re.findall(r'environment=web_prod', js):
            pass
    except Exception:
        pass
print(f"chunks scannes: {scanned}")
print(f"\nPATHS /back/* ({len(paths)}) :")
for x in sorted(paths):
    print("   ", x)
print(f"\nBASES URL fft/tenup/api ({len(bases)}) :")
for x in sorted(bases):
    print("   ", x)
print(f"\nPATHS tournoi/recherche/search ({len(searchy)}) :")
for x in sorted(searchy):
    print("   ", x)

print("\nDIAGNOSTIC PHASE 6 TERMINE")
