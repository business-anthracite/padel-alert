"""Diagnostic Ten'Up post-Queue-it (09/07/2026) - TEMPORAIRE, a supprimer apres analyse.
Teste depuis l'environnement GitHub Actions (meme contexte que le scraper) :
1. Ce que contient reellement le DOM apres passage Queue-it
2. Si requests + cookies Playwright passe la file (refresh_fbid repare ?)
3. Si les endpoints vuejs repondent encore
4. Si /system/ajax accepte un POST sans form_build_id
"""
import re
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
VUEJS_BASE   = f"{TENUP_BASE}/recherche/tournois/vuejs"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

print("=== 1. Playwright : chargement page ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR")
    page = ctx.new_page()
    page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        print("(networkidle timeout - on continue)")
    print("URL finale :", page.url)
    print("Titre :", page.title())
    inputs = page.evaluate("() => [...document.querySelectorAll('input')].map(i => (i.name||'?') + ' | type=' + (i.type||'?') + ' | id=' + (i.id||'?'))")
    print(f"INPUTS ({len(inputs)}) :")
    for i in inputs:
        print("   ", i)
    forms = page.evaluate("() => [...document.querySelectorAll('form')].map(f => 'id=' + (f.id||'?') + ' action=' + (f.getAttribute('action')||'?'))")
    print("FORMS :", forms)
    html = page.content()
    print("Occurrences 'form_build_id' dans le HTML rendu :", html.count("form_build_id"))
    print("Occurrences 'queueit' dans le HTML rendu :", html.lower().count("queueit"))
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    print("COOKIES :", sorted(cookies.keys()))
    browser.close()

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
for k, v in cookies.items():
    s.cookies.set(k, v)

print("\n=== 2. requests GET /recherche/tournois avec cookies Playwright ===")
r = s.get(TENUP_SEARCH, timeout=30, allow_redirects=False)
print("status :", r.status_code, "| location :", r.headers.get("location", "-")[:100])
if r.status_code == 200:
    print("Occurrences 'form_build_id' dans HTML brut :", r.text.count("form_build_id"))
    m = re.search(r'name="form_build_id"\s+value="([^"]+)"', r.text)
    if not m:
        m = re.search(r'value="([^"]+)"\s+name="form_build_id"', r.text)
    print("fbid extrait :", (m.group(1)[:45] + "...") if m else "AUCUN")

print("\n=== 3. POST vuejs comite/ajax (ligue 57 IdF) ===")
r = s.post(f"{VUEJS_BASE}/comite/ajax", data={"selectedLigue[57]": "57"},
           headers={"Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": TENUP_SEARCH},
           timeout=30, allow_redirects=False)
print("status :", r.status_code)
print("body[:300] :", r.text[:300])

print("\n=== 4. POST /system/ajax SANS form_build_id ===")
data = {
    "recherche_type": "ligue",
    "ville[autocomplete][country]": "fr",
    "ville[autocomplete][textfield]": "",
    "ville[autocomplete][value_container][value_field]": "",
    "ville[autocomplete][value_container][label_field]": "",
    "ville[autocomplete][value_container][lat_field]": "",
    "ville[autocomplete][value_container][lng_field]": "",
    "ville[distance][value_field]": "0",
    "club[autocomplete][textfield]": "",
    "club[autocomplete][value_container][value_field]": "",
    "club[autocomplete][value_container][label_field]": "",
    "pratique": "PADEL",
    "date[start]": "09/07/2026",
    "date[end]": "07/10/2026",
    "sort": "_DIST_",
    "form_id": "recherche_tournois_form",
    "_triggering_element_name": "submit_main",
    "_triggering_element_value": "Rechercher",
    "form_build_id": "",
    "page": "0",
}
r = s.post(TENUP_AJAX, data=data,
           headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": TENUP_BASE, "Referer": TENUP_SEARCH,
                    "X-Requested-With": "XMLHttpRequest"},
           timeout=60, allow_redirects=False)
print("status :", r.status_code)
print("body[:600] :", r.text[:600])

print("\nDIAGNOSTIC TERMINE")
