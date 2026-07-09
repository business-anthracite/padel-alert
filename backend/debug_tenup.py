"""Diagnostic Ten'Up phase 10 (09/07/2026) - VALIDATION CONTINUITE tenup_id + v16.
Compare les tenup_id produits par la nouvelle API (partie numerique de idHomologation)
avec ceux de l'ancien tournaments.json (main). Overlap eleve = pas de re-notification.
"""
import json
import re
import requests

TENUP_BASE = "https://tenup.fft.fr"
API = f"{TENUP_BASE}/back/public/v1/tournois"
OLD_JSON = "https://raw.githubusercontent.com/business-anthracite/padel-alert/main/data/tournaments.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Content-Type": "application/json", "Origin": TENUP_BASE,
                  "Referer": f"{TENUP_BASE}/recherche/tournois/resultats"})

# 1. Ancien JSON (main, gele au 08/07)
print("=== 1. Ancien tournaments.json (main) ===")
old = requests.get(OLD_JSON, timeout=30).json()
old_ids = {str(t["tenup_id"]) for t in old.get("tournaments", [])}
print("ancien count:", old.get("count"), "| tenup_id uniques:", len(old_ids))
print("exemples anciens ids:", sorted(list(old_ids))[:5])

# 2. Nouvelle API : tout le padel national
base = {"pratique": "PADEL", "from": 0, "size": 10000, "lat": None, "lng": None,
        "distance": 30, "type": [], "codeClub": None, "ligues": [], "comites": [],
        "dateDebut": "2026-07-09T00:00:00.000Z", "dateFin": "2026-10-09T00:00:00.000Z",
        "utiliserMesDonnees": False, "naturesEpreuves": [], "typesEpreuves": [],
        "naturesTerrains": [], "categoriesJeu": [], "categoriesAge": [], "familles": [],
        "tournoiInterne": False, "classements": [], "inscriptionEnLigne": None,
        "paiementEnLigne": None, "filtres": True, "sort": "DISTANCE"}
d = s.post(API, data=json.dumps(base), timeout=90).json()
cards = d.get("cards", [])
print("\n=== 2. Nouvelle API padel national ===")
print("nbResultats:", d.get("nbResultats"), "| cards:", len(cards))

def num(idh):
    m = re.search(r'(\d{5,})', idh or "")
    return m.group(1) if m else None

new_ids, prefixes = set(), {}
for c in cards:
    idh = c.get("idHomologation", "")
    pre = (idh.split("_")[0] if "_" in idh else "?")
    prefixes[pre] = prefixes.get(pre, 0) + 1
    n = num(idh)
    if n:
        new_ids.add(n)
print("tenup_id numeriques uniques:", len(new_ids))
print("prefixes idHomologation:", prefixes)

# 3. Overlap
inter = old_ids & new_ids
print("\n=== 3. CONTINUITE ===")
print("anciens ids:", len(old_ids), "| nouveaux ids:", len(new_ids))
print("intersection:", len(inter))
if old_ids:
    print(f"  -> {100*len(inter)//len(old_ids)}% des anciens ids retrouves dans la nouvelle API")
print("anciens NON retrouves (peut etre passes/expires):", len(old_ids - new_ids))
print("nouveaux absents de l'ancien (nouvelles publications OU ids differents):", len(new_ids - old_ids))
print("exemples nouveaux ids:", sorted(list(new_ids))[:5])
print("exemples intersection:", sorted(list(inter))[:5])

# 4. Distribution niveaux extractibles
NIV = re.compile(r'P\s?(25|50|100|250|500|1000|1500|2000)\b', re.IGNORECASE)
with_niv = sum(1 for c in cards if NIV.search(c.get("libelleTournoi", "")))
champ = sum(1 for c in cards if "championnat" in (c.get("libelleTournoi", "") or "").lower())
print("\n=== 4. Niveaux ===")
print(f"cards avec niveau P## dans le libelle : {with_niv}/{len(cards)} ({100*with_niv//max(len(cards),1)}%)")
print(f"cards 'championnat' (sans P, normal) : {champ}")
print(f"ni P## ni championnat : {len(cards)-with_niv-champ}")

print("\nDIAGNOSTIC PHASE 10 TERMINE")
