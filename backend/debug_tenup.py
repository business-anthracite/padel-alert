"""Diagnostic Ten'Up phase 9 (09/07/2026) - TEMPORAIRE. Endpoint DETAIL + niveau/age.
Objectif : trouver ou lire niveau (P25...), categorie age, type competition, lien.
API liste sans cookies (confirme phase 8).
"""
import json
import re
import requests

TENUP_BASE = "https://tenup.fft.fr"
API_LIST = f"{TENUP_BASE}/back/public/v1/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Content-Type": "application/json", "Origin": TENUP_BASE,
                  "Referer": f"{TENUP_BASE}/recherche/tournois/resultats"})

base = {
    "pratique": "PADEL", "from": 0, "size": 30, "lat": None, "lng": None,
    "distance": 30, "type": [], "codeClub": None, "ligues": [], "comites": [],
    "dateDebut": "2026-07-09T00:00:00.000Z", "dateFin": "2026-10-09T00:00:00.000Z",
    "utiliserMesDonnees": False, "naturesEpreuves": [], "typesEpreuves": [],
    "naturesTerrains": [], "categoriesJeu": [], "categoriesAge": [], "familles": [],
    "tournoiInterne": False, "classements": [], "inscriptionEnLigne": None,
    "paiementEnLigne": None, "filtres": True, "sort": "DISTANCE",
}
print("=== 1. Echantillon 30 tournois PADEL ===")
d = s.post(API_LIST, data=json.dumps(base), timeout=60).json()
cards = d.get("cards", [])
print("recus:", len(cards))

print("\n=== 2. Analyse libelleTournoi (niveau P## extractible ?) ===")
niveau_re = re.compile(r'\bP(?:25|50|100|250|500|1000|1500|2000)\b')
found = 0
for c in cards[:30]:
    lib = c.get("libelleTournoi", "")
    m = niveau_re.findall(lib)
    if m:
        found += 1
    print(f"  [{','.join(m) if m else '--'}] {lib[:70]}")
print(f"\n-> {found}/{len(cards[:30])} libelles contiennent un niveau P##")

# Recuperer un id numerique : idHomologation = "FED_82559985" -> extraire 82559985
def numeric_id(idh):
    m = re.search(r'(\d{5,})', idh or "")
    return m.group(1) if m else None

sample = cards[0]
idh = sample.get("idHomologation")
nid = numeric_id(idh)
print(f"\n=== 3. Sondage endpoints DETAIL (idHomologation={idh}, num={nid}) ===")
candidates = [
    f"/back/public/v1/tournois/{nid}",
    f"/back/public/v1/tournois/{idh}",
    f"/back/public/v1/tournois/resultats?idTournoi={nid}",
    f"/back/public/v1/tournois/detail/{nid}",
    f"/back/public/v1/tournois/{nid}/detail",
    f"/back/public/v1/tournois/{nid}/epreuves",
    f"/back/public/v1/tournoi/{nid}",
]
for path in candidates:
    url = TENUP_BASE + path
    try:
        r = s.get(url, timeout=25, allow_redirects=False)
        ct = r.headers.get("content-type", "")[:30]
        print(f"\nGET {path}\n  -> {r.status_code} | {ct}")
        if r.status_code == 200 and "json" in ct:
            body = r.text
            print("  taille:", len(body))
            # chercher niveau / age / cp dans la reponse
            print("  contient 'P25'/'P100':", bool(re.search(r'P(25|50|100|250|500)', body)))
            print("  contient 'niveau':", "niveau" in body.lower(), "| 'categorie':", "categorie" in body.lower(), "| 'age':", "age" in body.lower())
            print("  contient CP/codePostal:", "codePostal" in body.lower() or "codepostal" in body.lower())
            print("  JSON[:900]:", body[:900].replace(chr(10), " "))
        elif "json" in ct:
            print("  body:", r.text[:200].replace(chr(10), " "))
    except Exception as e:
        print(f"\nGET {path} -> EXCEPTION {str(e)[:80]}")

print("\n=== 4. Ancienne fiche tournoi (page HTML detail) ? ===")
# L'app Nuxt a peut-etre une page /tournoi/{id} qui charge un endpoint detail
for path in [f"/tournoi/{nid}", f"/recherche/tournois/{nid}", f"/tournoi/confirmation?id={nid}"]:
    try:
        r = s.get(TENUP_BASE + path, timeout=25, allow_redirects=False)
        print(f"GET {path} -> {r.status_code} | {r.headers.get('content-type','')[:30]} | loc={r.headers.get('location','-')[:80]}")
    except Exception as e:
        print(f"GET {path} -> EXC {str(e)[:60]}")

print("\nDIAGNOSTIC PHASE 9 TERMINE")
