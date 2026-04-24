"""
Diagnostic : dump du formulaire Ten'Up et test params ligue=ALL.
A executer une seule fois localement ou en GitHub Actions.
"""
import json, requests, re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="fr-FR",
    )
    page = ctx.new_page()
    page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    html      = page.content()
    fbid      = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
    cookies   = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()

soup = BeautifulSoup(html, "html.parser")

print("=== FORM FIELDS (name + value + type) ===")
for el in soup.find_all(["input","select","textarea"]):
    name = el.get("name","")
    val  = el.get("value","")
    typ  = el.get("type","select")
    if name and ("ligue" in name.lower() or "recherche" in name.lower() or "form_id" in name.lower() or "pratique" in name.lower()):
        print(f"  [{typ}] {name} = {val!r}")
        if el.name == "select":
            for opt in el.find_all("option"):
                print(f"    <option value={opt.get('value','')!r}> {opt.text.strip()}")

print(f"\nform_build_id: {fbid}")

print("\n=== TEST AJAX ligue=ALL ===")
s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0", "Accept": "application/json, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": TENUP_BASE, "Referer": TENUP_SEARCH, "X-Requested-With": "XMLHttpRequest",
})
for k, v in cookies.items():
    s.cookies.set(k, v)

now = datetime.now()
ds = now.strftime("%d/%m/%y")
de = (now + timedelta(days=30)).strftime("%d/%m/%y")

# Test 1 : ligue=ALL simple
params1 = {
    "recherche_type": "ligue", "ligue": "ALL", "pratique": "PADEL",
    "date[start]": ds, "date[end]": de,
    "sort": "_DATE_", "form_build_id": fbid,
    "form_id": "recherche_tournois_form",
    "_triggering_element_name": "submit_main",
    "_triggering_element_value": "Rechercher",
}
r1 = s.post(TENUP_AJAX, data=params1, timeout=30)
print(f"Test1 (ligue=ALL simple) HTTP {r1.status_code}")
for cmd in r1.json():
    if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
        res = cmd.get("results", {})
        print(f"  nb_results={res.get('nb_results')} items={len(res.get('items',[]))}")
        break
else:
    cmds = [c.get("command") for c in r1.json() if isinstance(c, dict)]
    print(f"  Commandes reçues: {cmds}")

# Test 2 : recherche_type=ligue sans ligue param
params2 = {**params1}
del params2["ligue"]
r2 = s.post(TENUP_AJAX, data=params2, timeout=30)
print(f"\nTest2 (recherche_type=ligue, sans ligue) HTTP {r2.status_code}")
for cmd in r2.json():
    if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
        res = cmd.get("results", {})
        print(f"  nb_results={res.get('nb_results')} items={len(res.get('items',[]))}")
        break
else:
    cmds = [c.get("command") for c in r2.json() if isinstance(c, dict)]
    print(f"  Commandes reçues: {cmds}")

# Test 3 : ville par défaut (contrôle — on sait que ça marche)
params3 = {
    "recherche_type": "ville",
    "ville[autocomplete][country]": "fr",
    "ville[autocomplete][textfield]": "",
    "ville[autocomplete][value_container][value_field]": "Paris, 75001",
    "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
    "ville[autocomplete][value_container][lat_field]": "48.859489",
    "ville[autocomplete][value_container][lng_field]": "2.347880",
    "ville[distance][value_field]": "200",
    "pratique": "PADEL", "date[start]": ds, "date[end]": de,
    "sort": "_DIST_", "form_build_id": fbid,
    "form_id": "recherche_tournois_form",
    "_triggering_element_name": "submit_main",
    "_triggering_element_value": "Rechercher",
}
r3 = s.post(TENUP_AJAX, data=params3, timeout=30)
print(f"\nTest3 (ville=Paris contrôle) HTTP {r3.status_code}")
for cmd in r3.json():
    if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
        res = cmd.get("results", {})
        print(f"  nb_results={res.get('nb_results')} items={len(res.get('items',[]))}")
        break
