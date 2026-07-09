"""Diagnostic Ten'Up phase 8 (09/07/2026) - TEMPORAIRE. Validation API v16.
1. Cookies via Playwright (passage Queue-it) - minimal
2. Test API PADEL sans navigateur : gros size, champs niveaux, volume national
"""
import json
import time
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE = "https://tenup.fft.fr"
API = f"{TENUP_BASE}/back/public/v1/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 1. Recuperer les cookies Queue-it via Playwright (une seule fois)
print("=== 1. Obtention cookies via Playwright ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=UA, locale="fr-FR")
    page = ctx.new_page()
    page.goto(f"{TENUP_BASE}/recherche/tournois", wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    browser.close()
print("cookies obtenus :", sorted(cookies.keys()))

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": TENUP_BASE,
    "Referer": f"{TENUP_BASE}/recherche/tournois/resultats",
})
for k, v in cookies.items():
    s.cookies.set(k, v)

def q(payload, label):
    print(f"\n=== {label} ===")
    try:
        r = s.post(API, data=json.dumps(payload), timeout=60)
        print("HTTP:", r.status_code, "| taille:", len(r.text))
        if r.status_code != 200:
            print("body:", r.text[:300])
            return None
        d = r.json()
        print("nbResultats:", d.get("nbResultats"), "| cards:", len(d.get("cards", [])))
        return d
    except Exception as e:
        print("EXCEPTION:", str(e)[:200])
        return None

# 2. PADEL national, gros size
base = {
    "pratique": "PADEL", "from": 0, "size": 500, "lat": None, "lng": None,
    "distance": 30, "type": [], "codeClub": None, "ligues": [], "comites": [],
    "dateDebut": "2026-07-09T00:00:00.000Z", "dateFin": "2026-10-09T00:00:00.000Z",
    "utiliserMesDonnees": False, "naturesEpreuves": [], "typesEpreuves": [],
    "naturesTerrains": [], "categoriesJeu": [], "categoriesAge": [], "familles": [],
    "tournoiInterne": False, "classements": [], "inscriptionEnLigne": None,
    "paiementEnLigne": None, "filtres": True, "sort": "DISTANCE",
}
d = q(base, "PADEL national size=500 (sans lat/lng)")
if d and d.get("cards"):
    print("\n--- PREMIERE CARD PADEL (champs complets) ---")
    print(json.dumps(d["cards"][0], ensure_ascii=False, indent=1)[:1500])
    print("\n--- CLES PRESENTES ---")
    print(sorted(d["cards"][0].keys()))
    # combien de cards vraiment retournees vs size demande
    print("\ncards retournees:", len(d["cards"]), "/ size demande 500 / total", d.get("nbResultats"))

# 3. Test size tres grand (tout d'un coup ?)
d2 = q({**base, "size": 10000}, "PADEL national size=10000 (tout en une requete ?)")
if d2:
    print("cards retournees avec size=10000 :", len(d2.get("cards", [])))

# 4. Test pagination from
d3 = q({**base, "from": 500, "size": 500}, "PADEL from=500 (page 2)")
if d3 and d3.get("cards"):
    print("premiere card page 2 idHomologation:", d3["cards"][0].get("idHomologation"))

# 5. Filtre par ligue (ex IdF = 57) pour voir si sous-total coherent
d4 = q({**base, "ligues": ["57"], "size": 10}, "PADEL ligue Ile-de-France (57)")

# 6. Sondage : l'API repond-elle SANS cookies queue-it du tout ?
print("\n=== 6. API SANS cookies (nouvelle session vierge) ===")
s2 = requests.Session()
s2.headers.update(s.headers)
try:
    r = s2.post(API, data=json.dumps(base), timeout=60, allow_redirects=False)
    print("HTTP:", r.status_code, "| ct:", r.headers.get("content-type", "")[:40])
    if r.status_code == 200:
        print(">>> nbResultats:", r.json().get("nbResultats"), " => COOKIES QUEUE-IT NON REQUIS !")
    else:
        print("location:", r.headers.get("location", "-")[:100], "| body:", r.text[:150])
except Exception as e:
    print("EXCEPTION:", str(e)[:150])

print("\nDIAGNOSTIC PHASE 8 TERMINE")
