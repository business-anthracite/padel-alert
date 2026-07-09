"""Diagnostic Ten'Up phase 2 (09/07/2026) - TEMPORAIRE.
Le site est desormais une app Nuxt (Vue). Objectif : capturer les appels
reseau (XHR/fetch) emis lors d'une recherche Padel pour decouvrir la nouvelle API.
"""
import json
import time
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

captured = []

def on_response(resp):
    req = resp.request
    if req.resource_type not in ("xhr", "fetch"):
        return
    entry = {
        "method": req.method,
        "url": req.url[:200],
        "status": resp.status,
        "post": (req.post_data or "")[:300],
    }
    try:
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            entry["body"] = resp.text()[:400]
    except Exception:
        pass
    captured.append(entry)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR")
    page = ctx.new_page()
    page.on("response", on_response)
    page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass

    # Popup cookies eventuelle
    for label in ["Tout accepter", "Accepter", "J'accepte", "OK pour moi", "Continuer sans accepter"]:
        try:
            page.get_by_role("button", name=label).first.click(timeout=2500)
            print(f"[popup cookies : clic '{label}']")
            break
        except Exception:
            pass

    # Selectionner la pratique Padel puis lancer la recherche
    try:
        page.get_by_text("Padel", exact=True).first.click(timeout=5000)
        print("[clic Padel OK]")
    except Exception as e:
        print("[clic Padel ECHEC]", str(e)[:120])
    time.sleep(1)
    n_before = len(captured)
    try:
        page.get_by_text("RECHERCHER", exact=False).first.click(timeout=5000)
        print("[clic RECHERCHER OK]")
    except Exception as e:
        print("[clic RECHERCHER ECHEC]", str(e)[:120])

    # Laisser les appels partir
    time.sleep(8)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    print("URL apres recherche :", page.url)

    browser.close()

print(f"\n=== APPELS XHR/FETCH CAPTURES ({len(captured)}) ===")
for e in captured:
    if "tenup" not in e["url"] and "fft" not in e["url"]:
        continue  # ignorer pubs/analytics
    print(f"\n{e['method']} {e['url']}  -> {e['status']}")
    if e.get("post"):
        print("  POST data :", e["post"])
    if e.get("body"):
        print("  JSON :", e["body"].replace(chr(10), " ")[:400])

print("\nDIAGNOSTIC PHASE 2 TERMINE")
