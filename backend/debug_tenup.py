"""Diagnostic Ten'Up phase 15 (09/07) - VALIDATION SOURCE COORDS.
Strategie coords v16 : 1) card coords si presentes (clubs ligue DROM/COM),
2) club-name -> coords depuis l'ancien tournaments.json (precis, clubs recurrents),
3) geo.api.gouv.fr sur la ville (fallback, centre-ville).
Mesure la couverture de chaque couche.
"""
import json
import re
import time
import requests

TENUP_BASE = "https://tenup.fft.fr"
API = f"{TENUP_BASE}/back/public/v1/tournois"
OLD = "https://raw.githubusercontent.com/business-anthracite/padel-alert/main/data/tournaments.json"
GEO = "https://geo.api.gouv.fr/communes"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept":"application/json, text/plain, */*",
                  "Content-Type":"application/json","Origin":TENUP_BASE,
                  "Referer":f"{TENUP_BASE}/recherche/tournois/resultats"})

# Echantillon national 400
base = {"pratique":"PADEL","from":0,"size":400,"lat":None,"lng":None,"distance":30,
"type":[],"codeClub":None,"ligues":[],"comites":[],"dateDebut":"2026-07-09T00:00:00.000Z",
"dateFin":"2026-10-09T00:00:00.000Z","utiliserMesDonnees":False,"naturesEpreuves":[],
"typesEpreuves":[],"naturesTerrains":[],"categoriesJeu":[],"categoriesAge":[],"familles":[],
"tournoiInterne":False,"classements":[],"inscriptionEnLigne":None,"paiementEnLigne":None,
"filtres":True,"sort":"DISTANCE"}
cards = s.post(API, data=json.dumps(base), timeout=60).json().get("cards", [])
print(f"echantillon: {len(cards)} tournois")

# Couche 1 : coords dans la card
c1 = sum(1 for c in cards if (c.get("club") or {}).get("lat"))
print(f"Couche 1 (card coords) : {c1}")

# Couche 2 : club-name -> coords depuis l'ancien JSON
old = requests.get(OLD, timeout=30).json().get("tournaments", [])
club2coord = {}
for t in old:
    nom = (t.get("club") or "").strip().upper()
    if nom and t.get("lat") and t.get("lng"):
        club2coord.setdefault(nom, (t["lat"], t["lng"]))
print(f"clubs distincts dans l'ancien JSON : {len(club2coord)}")
c2 = 0
for c in cards:
    if (c.get("club") or {}).get("lat"): continue
    nom = ((c.get("club") or {}).get("libelle") or "").strip().upper()
    if nom in club2coord: c2 += 1
print(f"Couche 2 (club-name match ancien JSON) : {c2}")

# Couche 3 : geo.api.gouv.fr sur la ville, pour le reste
def norm_ville(v):
    v = (v or "").strip()
    v = re.sub(r'\s+CEDEX.*$', '', v, flags=re.IGNORECASE)   # "NOUMEA CEDEX" -> "NOUMEA"
    v = re.sub(r'\s+\d+$', '', v)                             # "PARIS 16" -> "PARIS"
    return v.strip()

reste = []
for c in cards:
    if (c.get("club") or {}).get("lat"): continue
    nom = ((c.get("club") or {}).get("libelle") or "").strip().upper()
    if nom in club2coord: continue
    reste.append(c)
print(f"\nreste pour geocodage ville : {len(reste)}")

# tester le geocodage sur les villes uniques du reste (echantillon 40)
villes = []
seen = set()
for c in reste:
    v = norm_ville(c.get("ville"))
    if v and v.upper() not in seen:
        seen.add(v.upper()); villes.append(v)
print(f"villes uniques a geocoder (reste) : {len(villes)}")

geo_ok = 0; geo_fail = []
for v in villes[:40]:
    try:
        r = requests.get(GEO, params={"nom": v, "fields":"centre,codesPostaux","boost":"population","limit":1}, timeout=15)
        arr = r.json()
        if arr and arr[0].get("centre"):
            geo_ok += 1
        else:
            geo_fail.append(v)
    except Exception as e:
        geo_fail.append(v + f"(err {str(e)[:30]})")
    time.sleep(0.05)
print(f"geocodage reussi : {geo_ok}/{min(40,len(villes))}")
print("echecs:", geo_fail[:15])

# exemple de reponse geo
r = requests.get(GEO, params={"nom":"Rennes","fields":"centre,codesPostaux,codeDepartement","boost":"population","limit":1}, timeout=15)
print("\nexemple geo Rennes:", json.dumps(r.json()[0], ensure_ascii=False)[:300])

tot = c1 + c2 + geo_ok*len(reste)//max(min(40,len(villes)),1)
print(f"\nCOUVERTURE ESTIMEE : couche1={c1} + couche2={c2} + geocodage~{round(100*geo_ok/max(min(40,len(villes)),1))}% du reste")

print("\nDIAGNOSTIC PHASE 15 TERMINE")
