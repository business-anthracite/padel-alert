"""Diagnostic Ten'Up phase 13 (09/07) - SOURCE DES COORDONNEES.
L'API tournois ne renvoie pas lat/lng pour la plupart des clubs. Objectif :
1. Mesurer la couverture coords national vs par-ligue
2. Trouver un endpoint club (par code) donnant CP / coords
"""
import json
import re
import requests

TENUP_BASE = "https://tenup.fft.fr"
API = f"{TENUP_BASE}/back/public/v1/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Content-Type": "application/json", "Origin": TENUP_BASE,
                  "Referer": f"{TENUP_BASE}/recherche/tournois/resultats"})

base = {"pratique":"PADEL","from":0,"size":300,"lat":None,"lng":None,"distance":30,
"type":[],"codeClub":None,"ligues":[],"comites":[],"dateDebut":"2026-07-09T00:00:00.000Z",
"dateFin":"2026-10-09T00:00:00.000Z","utiliserMesDonnees":False,"naturesEpreuves":[],
"typesEpreuves":[],"naturesTerrains":[],"categoriesJeu":[],"categoriesAge":[],"familles":[],
"tournoiInterne":False,"classements":[],"inscriptionEnLigne":None,"paiementEnLigne":None,
"filtres":True,"sort":"DISTANCE"}

print("=== 1. Couverture coords (national, 300) ===")
d = s.post(API, data=json.dumps(base), timeout=60).json()
cards = d.get("cards", [])
withc = sum(1 for c in cards if (c.get("club") or {}).get("lat"))
print(f"cards {len(cards)} | avec club.lat : {withc}")
# Exemples de clubs SANS coords
sample_codes = []
for c in cards:
    club = c.get("club") or {}
    if not club.get("lat"):
        sample_codes.append(club.get("code"))
    if len(sample_codes) >= 5:
        break
print("codes clubs sans coords:", sample_codes)
print("cles completes d'une card:", sorted(cards[0].keys()))
print("exemple club complet:", json.dumps(cards[0].get("club"), ensure_ascii=False))

# 2. Endpoints clubs candidats (par code)
code = next((c for c in sample_codes if c), None)
print(f"\n=== 2. Recherche endpoint club (code={code}) ===")
candidates = [
    ("GET", f"/back/public/v1/clubs/{code}"),
    ("GET", f"/back/public/v1/club/{code}"),
    ("GET", f"/back/public/v1/clubs/{code}?environment=web_prod"),
    ("GET", f"/back/public/v1/clubs/formulaire"),
    ("POST","/back/public/v1/clubs"),
    ("POST","/back/public/v1/clubs/resultats"),
    ("GET", f"/back/public/v1/installations/{code}"),
]
for method, path in candidates:
    url = TENUP_BASE + path
    try:
        if method == "GET":
            r = s.get(url, timeout=25, allow_redirects=False)
        else:
            r = s.post(url, data=json.dumps({"pratique":"PADEL","from":0,"size":5,"nom":"","ligues":[],"comites":[]}), timeout=25, allow_redirects=False)
        ct = r.headers.get("content-type","")[:30]
        print(f"\n{method} {path} -> {r.status_code} | {ct}")
        if "json" in ct and r.status_code == 200:
            body = r.text
            print("  a 'codePostal':", "codepostal" in body.lower() or "codePostal" in body)
            print("  a 'lat':", '"lat"' in body, "| a 'adresse':", "adresse" in body.lower())
            print("  JSON[:500]:", body[:500].replace(chr(10)," "))
        elif "json" in ct:
            print("  body:", r.text[:200].replace(chr(10)," "))
    except Exception as e:
        print(f"\n{method} {path} -> EXC {str(e)[:80]}")

# 3. La recherche clubs (page /recherche/clubs) - capturer via l'endpoint devine
print("\n=== 3. POST /back/public/v1/clubs avec filtre nom ===")
for payload in [
    {"nom":"","codeClub":sample_codes[0] if sample_codes else "","from":0,"size":5},
    {"pratique":"PADEL","from":0,"size":5,"nom":"","ligues":[],"comites":[],"lat":None,"lng":None,"distance":30},
]:
    try:
        r = s.post(f"{TENUP_BASE}/back/public/v1/clubs", data=json.dumps(payload), timeout=25)
        print(f"payload {list(payload.keys())} -> {r.status_code} | {r.text[:300].replace(chr(10),' ')}")
    except Exception as e:
        print("EXC", str(e)[:80])

print("\nDIAGNOSTIC PHASE 13 TERMINE")
