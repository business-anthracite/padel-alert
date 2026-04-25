"""
Padel Alert — Scraper France entière (v5 — ville multi-points)
45 villes, rayon 100km, recherche par ville avec ALL_CRITERIA.
Pagination par ville (fonctionne, contrairement à ligue=ALL dont la pagination est cassée côté Ten'Up).
Écrit data/tournaments.json + commit GitHub.
WordPress pull ce fichier via WP-Cron.
"""
import os
import math
import json
import subprocess
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90

JOURS = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]

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

# ── 45 villes couvrant toute la France métropolitaine, rayon 100km ─────────────
VILLES_FRANCE = [
    # Île-de-France
    {"ville_value":"Paris, 75001","ville_label":"Paris, 75, Paris, Île-de-France","lat":"48.859489","lng":"2.347880"},
    # Auvergne-Rhône-Alpes
    {"ville_value":"Lyon, 69001","ville_label":"Lyon, 69, Rhône, Auvergne-Rhône-Alpes","lat":"45.748834","lng":"4.846788"},
    {"ville_value":"Grenoble, 38000","ville_label":"Grenoble, 38, Isère, Auvergne-Rhône-Alpes","lat":"45.188529","lng":"5.724524"},
    {"ville_value":"Clermont-Ferrand, 63000","ville_label":"Clermont-Ferrand, 63, Puy-de-Dôme, Auvergne-Rhône-Alpes","lat":"45.777222","lng":"3.087025"},
    # Provence-Alpes-Côte d'Azur
    {"ville_value":"Marseille, 13001","ville_label":"Marseille, 13, Bouches-du-Rhône, PACA","lat":"43.296482","lng":"5.381824"},
    {"ville_value":"Nice, 06000","ville_label":"Nice, 06, Alpes-Maritimes, PACA","lat":"43.710173","lng":"7.261953"},
    {"ville_value":"Toulon, 83000","ville_label":"Toulon, 83, Var, PACA","lat":"43.124228","lng":"5.928000"},
    # Occitanie
    {"ville_value":"Toulouse, 31000","ville_label":"Toulouse, 31, Haute-Garonne, Occitanie","lat":"43.604652","lng":"1.444209"},
    {"ville_value":"Montpellier, 34000","ville_label":"Montpellier, 34, Hérault, Occitanie","lat":"43.610769","lng":"3.876716"},
    {"ville_value":"Perpignan, 66000","ville_label":"Perpignan, 66, Pyrénées-Orientales, Occitanie","lat":"42.698611","lng":"2.895833"},
    {"ville_value":"Nîmes, 30000","ville_label":"Nîmes, 30, Gard, Occitanie","lat":"43.836699","lng":"4.360054"},
    # Nouvelle-Aquitaine
    {"ville_value":"Bordeaux, 33000","ville_label":"Bordeaux, 33, Gironde, Nouvelle-Aquitaine","lat":"44.837789","lng":"-0.579180"},
    {"ville_value":"Bayonne, 64100","ville_label":"Bayonne, 64, Pyrénées-Atlantiques, Nouvelle-Aquitaine","lat":"43.493131","lng":"-1.474836"},
    {"ville_value":"Limoges, 87000","ville_label":"Limoges, 87, Haute-Vienne, Nouvelle-Aquitaine","lat":"45.849998","lng":"1.250000"},
    {"ville_value":"Poitiers, 86000","ville_label":"Poitiers, 86, Vienne, Nouvelle-Aquitaine","lat":"46.580224","lng":"0.340375"},
    {"ville_value":"La Rochelle, 17000","ville_label":"La Rochelle, 17, Charente-Maritime, Nouvelle-Aquitaine","lat":"46.160329","lng":"-1.151139"},
    # Pays de la Loire
    {"ville_value":"Nantes, 44000","ville_label":"Nantes, 44, Loire-Atlantique, Pays de la Loire","lat":"47.218371","lng":"-1.553621"},
    {"ville_value":"Le Mans, 72000","ville_label":"Le Mans, 72, Sarthe, Pays de la Loire","lat":"48.006382","lng":"0.199556"},
    {"ville_value":"Angers, 49000","ville_label":"Angers, 49, Maine-et-Loire, Pays de la Loire","lat":"47.478419","lng":"-0.563166"},
    # Bretagne
    {"ville_value":"Rennes, 35000","ville_label":"Rennes, 35, Ille-et-Vilaine, Bretagne","lat":"48.117266","lng":"-1.677793"},
    {"ville_value":"Brest, 29200","ville_label":"Brest, 29, Finistère, Bretagne","lat":"48.390394","lng":"-4.486076"},
    # Normandie
    {"ville_value":"Rouen, 76000","ville_label":"Rouen, 76, Seine-Maritime, Normandie","lat":"49.443232","lng":"1.099971"},
    {"ville_value":"Caen, 14000","ville_label":"Caen, 14, Calvados, Normandie","lat":"49.182863","lng":"-0.370679"},
    # Hauts-de-France
    {"ville_value":"Lille, 59000","ville_label":"Lille, 59, Nord, Hauts-de-France","lat":"50.629250","lng":"3.057256"},
    {"ville_value":"Amiens, 80000","ville_label":"Amiens, 80, Somme, Hauts-de-France","lat":"49.894067","lng":"2.295753"},
    {"ville_value":"Valenciennes, 59300","ville_label":"Valenciennes, 59, Nord, Hauts-de-France","lat":"50.357888","lng":"3.523341"},
    # Grand Est
    {"ville_value":"Strasbourg, 67000","ville_label":"Strasbourg, 67, Bas-Rhin, Grand Est","lat":"48.573405","lng":"7.752111"},
    {"ville_value":"Metz, 57000","ville_label":"Metz, 57, Moselle, Grand Est","lat":"49.119309","lng":"6.175716"},
    {"ville_value":"Reims, 51100","ville_label":"Reims, 51, Marne, Grand Est","lat":"49.258329","lng":"4.031696"},
    {"ville_value":"Nancy, 54000","ville_label":"Nancy, 54, Meurthe-et-Moselle, Grand Est","lat":"48.692054","lng":"6.184417"},
    {"ville_value":"Mulhouse, 68100","ville_label":"Mulhouse, 68, Haut-Rhin, Grand Est","lat":"47.750839","lng":"7.335888"},
    # Bourgogne-Franche-Comté
    {"ville_value":"Dijon, 21000","ville_label":"Dijon, 21, Côte-d'Or, Bourgogne-Franche-Comté","lat":"47.322047","lng":"5.041480"},
    {"ville_value":"Besançon, 25000","ville_label":"Besançon, 25, Doubs, Bourgogne-Franche-Comté","lat":"47.237829","lng":"6.024054"},
    # Centre-Val de Loire
    {"ville_value":"Orléans, 45000","ville_label":"Orléans, 45, Loiret, Centre-Val de Loire","lat":"47.902964","lng":"1.909251"},
    {"ville_value":"Tours, 37000","ville_label":"Tours, 37, Indre-et-Loire, Centre-Val de Loire","lat":"47.394144","lng":"0.688229"},
    {"ville_value":"Bourges, 18000","ville_label":"Bourges, 18, Cher, Centre-Val de Loire","lat":"47.083332","lng":"2.400000"},
    # Autres villes importantes pour la couverture
    {"ville_value":"Nîmes, 30000","ville_label":"Nîmes, 30, Gard, Occitanie","lat":"43.836699","lng":"4.360054"},
    {"ville_value":"Aix-en-Provence, 13100","ville_label":"Aix-en-Provence, 13, Bouches-du-Rhône, PACA","lat":"43.529742","lng":"5.447427"},
    {"ville_value":"Annecy, 74000","ville_label":"Annecy, 74, Haute-Savoie, Auvergne-Rhône-Alpes","lat":"45.899247","lng":"6.129384"},
    {"ville_value":"Valence, 26000","ville_label":"Valence, 26, Drôme, Auvergne-Rhône-Alpes","lat":"44.933333","lng":"4.891667"},
    {"ville_value":"Béziers, 34500","ville_label":"Béziers, 34, Hérault, Occitanie","lat":"43.344597","lng":"3.215395"},
    {"ville_value":"Pau, 64000","ville_label":"Pau, 64, Pyrénées-Atlantiques, Nouvelle-Aquitaine","lat":"43.296346","lng":"-0.370797"},
    {"ville_value":"Lorient, 56100","ville_label":"Lorient, 56, Morbihan, Bretagne","lat":"47.748460","lng":"-3.366950"},
    {"ville_value":"Ajaccio, 20000","ville_label":"Ajaccio, 20, Corse-du-Sud, Corse","lat":"41.919775","lng":"8.738635"},
]
RAYON = "100"  # km


# ── Session ────────────────────────────────────────────────────────────────────

def get_session():
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
        raise RuntimeError("form_build_id introuvable")
    print(f"Session OK — fbid: {form_build_id[:30]}...")
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



# ── Recherche par ville ────────────────────────────────────────────────────────

def search_ville_page(session, fbid, ville, date_start, date_end, page_num):
    """Recherche AJAX d'une ville, page donnée. Retourne (items, nb_total)."""
    data = {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": ville["ville_value"],
        "ville[autocomplete][value_container][label_field]": ville["ville_label"],
        "ville[autocomplete][value_container][lat_field]":   ville["lat"],
        "ville[autocomplete][value_container][lng_field]":   ville["lng"],
        "ville[distance][value_field]": RAYON,
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        **ALL_CRITERIA,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": str(page_num),
    }
    try:
        resp = session.post(TENUP_AJAX, data=data, timeout=30)
        resp.raise_for_status()
        for cmd in resp.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                results = cmd.get("results", {})
                return results.get("items", []), results.get("nb_results", 0)
    except Exception as e:
        print(f"    Erreur page {page_num}: {e}")
    return [], 0


def scrape_ville(session, fbid, ville, date_start, date_end):
    """Scrape tous les tournois d'une ville (toutes les pages). Réutilise le fbid Playwright."""
    name = ville["ville_value"].split(",")[0]
    all_items = {}

    items, nb_total = search_ville_page(session, fbid, ville, date_start, date_end, 0)
    for it in items:
        all_items[str(it.get("id",""))] = it

    nb_pages = math.ceil(nb_total / 30) if nb_total > 0 else 1
    for page_num in range(1, nb_pages):
        items, _ = search_ville_page(session, fbid, ville, date_start, date_end, page_num)
        if not items:
            break
        for it in items:
            all_items[str(it.get("id",""))] = it

    n = len(all_items)
    if nb_total > 0:
        print(f"  {name} ({RAYON}km) : {nb_total} résultats → {n} uniques")
    return list(all_items.values())


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_item(item):
    tid = str(item.get("id", ""))
    if not tid:
        return None
    installation   = item.get("installation", {})
    ville   = installation.get("ville",      item.get("villeEngagement",      ""))
    cp      = installation.get("codePostal", item.get("codePostalEngagement", ""))
    adresse = installation.get("adresse2",   item.get("adresse2Engagement",   ""))
    lat     = installation.get("lat")
    lng     = installation.get("lng")
    date_debut_raw = item.get("dateDebut")
    date_debut     = date_debut_raw.get("date", "") if isinstance(date_debut_raw, dict) else ""
    date_fin_raw   = item.get("dateFin")
    date_fin       = date_fin_raw.get("date", "")   if isinstance(date_fin_raw,  dict) else ""
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
    epreuves_raw      = item.get("epreuves", [])
    match_types       = list({e.get("typeEpreuve",        {}).get("code", "") for e in epreuves_raw if e.get("typeEpreuve",        {}).get("code")})
    age_codes         = list({e.get("categoriePratiquant",{}).get("code", "") for e in epreuves_raw if e.get("categoriePratiquant",{}).get("code")})
    niveau_codes      = list({e.get("categorieEpreuve",   {}).get("code", "") for e in epreuves_raw if e.get("categorieEpreuve",   {}).get("code")})
    competition_codes = list({e.get("typeCompetition",    {}).get("code", "") for e in epreuves_raw if e.get("typeCompetition",    {}).get("code")})
    try:
        lat_f = float(lat) if lat not in (None, "", "0", 0, 0.0) else None
        lng_f = float(lng) if lng not in (None, "", "0", 0, 0.0) else None
    except (ValueError, TypeError):
        lat_f = lng_f = None
    return {
        "tenup_id":         tid,
        "libelle":          item.get("libelle", "Tournoi"),
        "club":             item.get("nomClub", ""),
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
        "ligues":           [],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# ── Main ───────────────────────────────────────────────────────────────────────


def test_ligue_codes(session, fbid, date_start, date_end):
    """Test rapide : les codes de ligue FFT fonctionnent-ils en AJAX ?"""
    # Codes possibles : abréviations régions, nombres, formats FFT
    CODES = [
        # Abréviations courantes
        "IDF", "ARA", "PACA", "OCC", "NAQ", "PDL", "BRE", "NOR", "HDF", "GES", "BFC", "CVL", "COR",
        # En minuscules
        "idf", "ara", "paca",
        # Numéros
        "1", "2", "3", "4", "5",
        # Formats alternatifs FFT
        "LR-IDF", "LR11", "RA",
    ]
    print(f"\n=== TEST CODES LIGUE FFT ({len(CODES)} codes) ===")
    for code in CODES:
        data = {
            "recherche_type": "ligue",
            "ligue": code,
            "pratique": "PADEL",
            "date[start]": date_start,
            "date[end]": date_end,
            "sort": "_DIST_",
            "form_id": "recherche_tournois_form",
            "_triggering_element_name": "submit_main",
            "_triggering_element_value": "Rechercher",
            "form_build_id": fbid,
            "page": "0",
        }
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=15)
            for cmd in resp.json():
                if isinstance(cmd, dict):
                    if cmd.get("command") == "recherche_tournois_update":
                        r = cmd.get("results", {})
                        n = r.get("nb_results", 0)
                        print(f"  ligue={code!r:12} → ✅ nb_results={n} items={len(r.get('items',[]))}")
                        break
                    if cmd.get("command") == "insert" and "interdit" in cmd.get("data", ""):
                        print(f"  ligue={code!r:12} → ❌ choix interdit")
                        break
            else:
                print(f"  ligue={code!r:12} → ? (aucune commande résultats)")
        except Exception as e:
            print(f"  ligue={code!r:12} → exception: {e}")
    print("=== FIN TEST ===\n")


def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Scraping France — {len(VILLES_FRANCE)} villes, rayon {RAYON}km ({date_start}→{date_end})")

    form_build_id, cookies = get_session()
    session = make_session(cookies)

    # Test codes ligue avant le scraping principal
    test_ligue_codes(session, form_build_id, date_start, date_end)

    all_raw = {}  # tenup_id → item
    for i, ville in enumerate(VILLES_FRANCE, 1):
        for item in scrape_ville(session, form_build_id, ville, date_start, date_end):
            tid = str(item.get("id", ""))
            if tid and tid not in all_raw:
                all_raw[tid] = item
        if i % 10 == 0:
            elapsed = (datetime.now() - now).total_seconds()
            print(f"  [{i}/{len(VILLES_FRANCE)}] {len(all_raw)} uniques ({elapsed:.0f}s)")

    tournaments = [t for item in all_raw.values() if (t := parse_item(item))]
    print(f"\nTotal France : {len(tournaments)} tournois uniques ({len(all_raw)} bruts)")

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":       len(tournaments),
        "tournaments": tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Fichier écrit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping France [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] — {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
