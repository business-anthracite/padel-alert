"""
Padel Alert — Scraper France entière
Scrape toutes les ligues françaises sur Ten'Up, envoie les résultats
à l'endpoint WordPress /wp-json/pa/v1/ingest pour matching + notifications.
Tourne sur GitHub Actions toutes les heures.
"""
import os
import math
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ── Config ─────────────────────────────────────────────────────────────────────
WP_INGEST_URL    = os.environ["WP_INGEST_URL"]
WP_INGEST_SECRET = os.environ["WP_INGEST_SECRET"]

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 180

JOURS = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]

# ── 13 ligues françaises — une ville centrale par ligue ───────────────────────
LIGUES_FRANCE = [
    {"region":"Pays de la Loire",            "ville_value":"Nantes, 44000",      "ville_label":"Nantes, 44, Loire-Atlantique, Pays de la Loire",                          "lat":"47.218371","lng":"-1.553621","distance":"200"},
    {"region":"Bretagne",                    "ville_value":"Rennes, 35000",      "ville_label":"Rennes, 35, Ille-et-Vilaine, Bretagne",                                   "lat":"48.117266","lng":"-1.677793","distance":"200"},
    {"region":"Normandie",                   "ville_value":"Rouen, 76000",       "ville_label":"Rouen, 76, Seine-Maritime, Normandie",                                    "lat":"49.443232","lng":"1.099971", "distance":"200"},
    {"region":"Hauts-de-France",             "ville_value":"Lille, 59000",       "ville_label":"Lille, 59, Nord, Hauts-de-France",                                        "lat":"50.629250","lng":"3.057256", "distance":"200"},
    {"region":"Grand Est",                   "ville_value":"Strasbourg, 67000",  "ville_label":"Strasbourg, 67, Bas-Rhin, Grand Est",                                     "lat":"48.573405","lng":"7.752111", "distance":"200"},
    {"region":"Île-de-France",               "ville_value":"Paris, 75001",       "ville_label":"Paris, 75, Paris, Île-de-France",                                         "lat":"48.859489","lng":"2.347880", "distance":"200"},
    {"region":"Centre-Val de Loire",         "ville_value":"Orléans, 45000",     "ville_label":"Orléans, 45, Loiret, Centre-Val de Loire",                                "lat":"47.902964","lng":"1.909251", "distance":"200"},
    {"region":"Bourgogne-Franche-Comté",     "ville_value":"Dijon, 21000",       "ville_label":"Dijon, 21, Côte-d'Or, Bourgogne-Franche-Comté",                          "lat":"47.322047","lng":"5.041480", "distance":"200"},
    {"region":"Auvergne-Rhône-Alpes",        "ville_value":"Lyon, 69001",        "ville_label":"Lyon 1er Arrondissement, 69, Rhône, Auvergne-Rhône-Alpes",               "lat":"45.748834","lng":"4.846788", "distance":"200"},
    {"region":"Provence-Alpes-Côte d'Azur",  "ville_value":"Marseille, 13001",   "ville_label":"Marseille 1er Arrondissement, 13, Bouches-du-Rhône, Provence-Alpes-Côte d'Azur", "lat":"43.296482","lng":"5.381824","distance":"200"},
    {"region":"Occitanie",                   "ville_value":"Toulouse, 31000",    "ville_label":"Toulouse, 31, Haute-Garonne, Occitanie",                                  "lat":"43.604652","lng":"1.444209", "distance":"200"},
    {"region":"Nouvelle-Aquitaine",          "ville_value":"Bordeaux, 33000",    "ville_label":"Bordeaux, 33, Gironde, Nouvelle-Aquitaine",                               "lat":"44.837789","lng":"-0.579180","distance":"200"},
    {"region":"Corse",                       "ville_value":"Ajaccio, 20000",     "ville_label":"Ajaccio, 20, Corse-du-Sud, Corse",                                        "lat":"41.919775","lng":"8.738635", "distance":"200"},
]

# Tous les critères — on veut TOUS les tournois, sans filtre
ALL_CRITERIA = {
    "epreuve[DM]":"DM","epreuve[DD]":"DD","epreuve[DX]":"DX",
    "categorie_age[910]":"910","categorie_age[1112]":"1112","categorie_age[1314]":"1314",
    "categorie_age[1516]":"1516","categorie_age[1718]":"1718","categorie_age[200]":"200",
    "categorie_age[345]":"345","categorie_age[355]":"355",
    "type[P]":"P","type[CE]":"CE","type[CEQ]":"CEQ",
    "categorie_tournoi[P25]":"P25","categorie_tournoi[P50]":"P50",
    "categorie_tournoi[P100]":"P100","categorie_tournoi[P250]":"P250",
    "categorie_tournoi[P500]":"P500","categorie_tournoi[P1000]":"P1000",
    "categorie_tournoi[P1500]":"P1500","categorie_tournoi[P2000]":"P2000",
}


# ── Session Ten'Up (Playwright requis pour passer le challenge JS) ─────────────

def get_session():
    """Ouvre Ten'Up avec Playwright, récupère form_build_id + cookies."""
    print("Ouverture session Ten'Up via Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        form_build_id = page.evaluate("() => { const el=document.querySelector('input[name=\"form_build_id\"]'); return el?el.value:null; }")
        cookies = ctx.cookies()
        browser.close()
    if not form_build_id:
        raise RuntimeError("form_build_id introuvable — Ten'Up a peut-être changé sa structure")
    print(f"Session OK — form_build_id: {form_build_id[:30]}...")
    return form_build_id, {c["name"]: c["value"] for c in cookies}


def make_session(cookies_dict):
    s = requests.Session()
    s.headers.update({
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "Accept-Language":  "fr-FR,fr;q=0.9",
        "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin":           TENUP_BASE,
        "Referer":          TENUP_SEARCH,
        "X-Requested-With": "XMLHttpRequest",
    })
    for name, value in cookies_dict.items():
        s.cookies.set(name, value)
    return s


def refresh_fbid(session):
    resp = session.get(TENUP_SEARCH, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    el = soup.find("input", {"name": "form_build_id"})
    if el:
        return el["value"]
    import re
    m = re.search(r'form_build_id[^>]+value="([^"]+)"', resp.text)
    if m:
        return m.group(1)
    raise RuntimeError("Impossible de rafraîchir form_build_id")


# ── Scraping d'une ligue ───────────────────────────────────────────────────────

def scrape_ligue(session, ligue):
    """Scrape tous les tournois padel d'une région. Retourne liste de tournois bruts."""
    region = ligue["region"]
    print(f"  Scraping {region}...")

    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

    base_params = {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": ligue["ville_value"],
        "ville[autocomplete][value_container][label_field]": ligue["ville_label"],
        "ville[autocomplete][value_container][lat_field]":   ligue["lat"],
        "ville[autocomplete][value_container][lng_field]":   ligue["lng"],
        "ville[distance][value_field]": ligue["distance"],
        "club[autocomplete][textfield]": "",
        "club[autocomplete][value_container][value_field]": "",
        "club[autocomplete][value_container][label_field]": "",
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        **ALL_CRITERIA,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
    }

    all_items = []
    seen_ids  = set()
    page      = 0
    nb_pages  = 1

    while page < nb_pages:
        fbid = refresh_fbid(session)
        data = {**base_params, "form_build_id": fbid, "page": str(page)}
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=30)
            resp.raise_for_status()
            for cmd in resp.json():
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    results  = cmd.get("results", {})
                    items    = results.get("items", [])
                    nb_total = results.get("nb_results", 0)
                    nb_pages = math.ceil(nb_total / 30) if nb_total > 0 else 1
                    new_items = [it for it in items if it.get("id") not in seen_ids]
                    if page > 0 and not new_items:
                        nb_pages = 0
                        break
                    for it in new_items:
                        seen_ids.add(it.get("id"))
                    all_items.extend(new_items)
                    break
        except Exception as e:
            print(f"    Erreur page {page}: {e}")
            break
        page += 1

    print(f"    → {len(all_items)} tournoi(s)")
    return all_items, region


# ── Parsing des items ──────────────────────────────────────────────────────────

def parse_item(item, region):
    tid = str(item.get("id", ""))
    if not tid:
        return None

    installation = item.get("installation", {})
    ville   = installation.get("ville",      item.get("villeEngagement",      ""))
    cp      = installation.get("codePostal", item.get("codePostalEngagement", ""))
    adresse = installation.get("adresse2",   item.get("adresse2Engagement",   ""))
    lat     = installation.get("lat")
    lng     = installation.get("lng")

    # Dates
    date_debut_raw = item.get("dateDebut")
    date_debut     = date_debut_raw.get("date","") if isinstance(date_debut_raw, dict) else ""
    date_fin_raw   = item.get("dateFin")
    date_fin       = date_fin_raw.get("date","")   if isinstance(date_fin_raw,  dict) else ""

    if date_debut:
        try:
            d = datetime.strptime(date_debut[:10], "%Y-%m-%d")
            date_str = f"{JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
            if date_fin and date_fin[:10] != date_debut[:10]:
                d2 = datetime.strptime(date_fin[:10], "%Y-%m-%d")
                date_str += f" → {JOURS[d2.weekday()]} {d2.strftime('%d/%m/%Y')}"
        except Exception:
            date_str = date_debut[:10]
    else:
        date_str = "Date inconnue"

    # Critères depuis les épreuves
    epreuves_raw       = item.get("epreuves", [])
    match_types        = list({e.get("typeEpreuve",        {}).get("code","") for e in epreuves_raw if e.get("typeEpreuve",        {}).get("code")})
    age_codes          = list({e.get("categoriePratiquant",{}).get("code","") for e in epreuves_raw if e.get("categoriePratiquant",{}).get("code")})
    niveau_codes       = list({e.get("categorieEpreuve",   {}).get("code","") for e in epreuves_raw if e.get("categorieEpreuve",   {}).get("code")})
    competition_codes  = list({e.get("typeCompetition",    {}).get("code","") for e in epreuves_raw if e.get("typeCompetition",    {}).get("code")})

    try:
        lat_f = float(lat) if lat not in (None,"","0",0,0.0) else None
        lng_f = float(lng) if lng not in (None,"","0",0,0.0) else None
    except (ValueError, TypeError):
        lat_f = lng_f = None

    return {
        "tenup_id":         tid,
        "libelle":          item.get("libelle","Tournoi"),
        "club":             item.get("nomClub",""),
        "ville":            ville,
        "cp":               cp,
        "adresse":          f"{adresse}, {cp} {ville}".strip(", "),
        "lat":              lat_f,
        "lng":              lng_f,
        "date_debut":       date_debut[:10] if date_debut else None,
        "date_fin":         date_fin[:10]   if date_fin   else None,
        "date_str":         date_str,
        "match_types":      match_types,
        "age_codes":        age_codes,
        "niveau_codes":     niveau_codes,
        "competition_codes":competition_codes,
        "ligues":           [region],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraping France entière")

    form_build_id, cookies = get_session()
    session = make_session(cookies)

    all_tournaments = {}  # tenup_id → tournament dict

    for ligue in LIGUES_FRANCE:
        raw_items, region = scrape_ligue(session, ligue)
        for item in raw_items:
            parsed = parse_item(item, region)
            if not parsed:
                continue
            tid = parsed["tenup_id"]
            if tid in all_tournaments:
                # Tournoi déjà vu dans une autre ligue — ajouter la région
                if region not in all_tournaments[tid]["ligues"]:
                    all_tournaments[tid]["ligues"].append(region)
            else:
                all_tournaments[tid] = parsed

    tournaments = list(all_tournaments.values())
    print(f"\nTotal France : {len(tournaments)} tournois uniques")

    # POST vers WordPress
    print(f"Envoi vers {WP_INGEST_URL}...")
    payload = {"secret": WP_INGEST_SECRET, "tournaments": tournaments}
    resp = requests.post(WP_INGEST_URL, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    print(f"Résultat : {result}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
