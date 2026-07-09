"""Diagnostic Ten'Up phase 11 (09/07/2026) - Export tournois SANS niveau extractible.
Dump CSV (tab-separated) des cards padel dont le libelle n'a ni P## ni 'championnat',
pour livrable Excel. Categorisation pour comprendre ce que sont ces 12%.
"""
import json
import re
import requests

TENUP_BASE = "https://tenup.fft.fr"
API = f"{TENUP_BASE}/back/public/v1/tournois"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Codes ligue -> nom (pour tagger)
LIGUES = {50:"Auvergne-Rhone-Alpes",51:"Bourgogne-Franche-Comte",52:"Bretagne",
53:"Centre-Val de Loire",54:"Corse",55:"Grand Est",56:"Hauts-de-France",
57:"Ile-de-France",58:"Normandie",59:"Nouvelle-Aquitaine",60:"Occitanie",
61:"Pays de la Loire",62:"Provence-Alpes-Cote d'Azur",63:"Guadeloupe",64:"Guyane",
65:"Martinique",66:"Nouvelle-Caledonie",67:"Reunion"}

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Content-Type": "application/json", "Origin": TENUP_BASE,
                  "Referer": f"{TENUP_BASE}/recherche/tournois/resultats"})

NIV = re.compile(r'P[\s\-]?(25|50|100|250|500|1000|1500|2000)(?!\d)', re.IGNORECASE)

base = {"pratique":"PADEL","from":0,"size":5000,"lat":None,"lng":None,"distance":30,
"type":[],"codeClub":None,"ligues":[],"comites":[],"dateDebut":"2026-07-09T00:00:00.000Z",
"dateFin":"2026-10-09T00:00:00.000Z","utiliserMesDonnees":False,"naturesEpreuves":[],
"typesEpreuves":[],"naturesTerrains":[],"categoriesJeu":[],"categoriesAge":[],"familles":[],
"tournoiInterne":False,"classements":[],"inscriptionEnLigne":None,"paiementEnLigne":None,
"filtres":True,"sort":"DISTANCE"}

# Une requete par ligue pour avoir le tag ligue
by_id = {}
for lid, lname in LIGUES.items():
    d = s.post(API, data=json.dumps({**base, "ligues":[str(lid)]}), timeout=60).json()
    for c in d.get("cards", []):
        idh = c.get("idHomologation","")
        if idh not in by_id:
            c["_ligue"] = lname
            by_id[idh] = c

cards = list(by_id.values())
no_level = []
for c in cards:
    lib = c.get("libelleTournoi","") or ""
    if NIV.search(lib):
        continue
    if "championnat" in lib.lower():
        continue
    no_level.append(c)

print(f"TOTAL cards (dedup ligue): {len(cards)}")
print(f"SANS niveau ni championnat: {len(no_level)}")

# Categorisation rapide
cats = {}
for c in no_level:
    lib = (c.get("libelleTournoi","") or "").lower()
    if "jeune" in lib or "u10" in lib or "u12" in lib or "u14" in lib or "u16" in lib or "u18" in lib:
        k = "jeunes"
    elif "beach" in lib:
        k = "beach"
    elif re.search(r'\bp\d', lib):
        k = "p_minuscule_ou_colle"
    elif "tmc" in lib:
        k = "TMC"
    else:
        k = "autre"
    cats[k] = cats.get(k,0)+1
print("CATEGORIES:", cats)

# Dump CSV (marqueur pour extraction)
print("###CSV_START###")
print("\t".join(["idHomologation","libelleTournoi","club","ville","dateDebut","dateFin","ligue","naturesEpreuves"]))
for c in no_level:
    club = (c.get("club") or {}).get("libelle","") or ""
    row = [
        c.get("idHomologation",""),
        (c.get("libelleTournoi","") or "").replace("\t"," ").replace("\n"," "),
        club.replace("\t"," "),
        (c.get("ville","") or "").replace("\t"," "),
        c.get("dateDebut","") or "",
        c.get("dateFin","") or "",
        c.get("_ligue",""),
        ",".join(c.get("naturesEpreuves") or []),
    ]
    print("###ROW###" + "\t".join(row))
print("###CSV_END###")
print("DIAGNOSTIC PHASE 11 TERMINE")
