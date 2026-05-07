"""
Padel Alert — Scraper France v6 — multi-villes 43 communes + nouveaux critères

Architecture : identique au v5 (ville + rayon 100km) mais avec les nouveaux critères
Ten'Up post-redesign (mai 2026) :
  - sort="dateDebut asc" ou "_DIST_" (valide)
  - famille_tournois[], categorie_age[] nouvelle nomenclature
  - Anciens critères (type[P], categorie_age[910], P25...) → "Un choix interdit"
  - Pagination ville fonctionne (getConfirmé v13 : Paris 100km → 137 résultats)

43 communes = couverture optimale métropole + Corse, rayon 100km
"""
import os, json, math, subprocess, time
from math import radians, cos
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90
RAYON        = "100"
RETRY_MAX    = 3

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Nouveaux critères Ten'Up (redesign mai 2026)
NEW_CRITERIA = {
    "epreuve[DX]": "DX", "epreuve[DM]": "DM", "epreuve[DD]": "DD",
    "categorie_age[70|80|96|97|98|90|95|65|99|100]": "70|80|96|97|98|90|95|65|99|100",
    "categorie_age[110]": "110", "categorie_age[120]": "120", "categorie_age[125]": "125",
    "categorie_age[130]": "130", "categorie_age[140]": "140", "categorie_age[145]": "145",
    "categorie_age[160]": "160", "categorie_age[180]": "180", "categorie_age[200]": "200",
    "categorie_age[350]": "350", "categorie_age[400]": "400", "categorie_age[450]": "450",
    "categorie_age[500]": "500", "categorie_age[550]": "550", "categorie_age[600]": "600",
    "categorie_age[650]": "650", "categorie_age[700]": "700", "categorie_age[750]": "750",
    "categorie_age[800]": "800",
    "type[T]": "T", "type[C]": "C",
    "famille_tournois[TRADI]": "TRADI", "famille_tournois[MULTI]": "MULTI",
    "famille_tournois[TMC_D]": "TMC_D", "famille_tournois[TMC_M]": "TMC_M",
    "famille_tournois[COURT_ADUL]": "COURT_ADUL",
    "famille_tournois[TRADI_V]": "TRADI_V", "famille_tournois[MULTI_V]": "MULTI_V",
    "famille_tournois[GALAXIE_O]": "GALAXIE_O", "famille_tournois[GALAXIE_V]": "GALAXIE_V",
    "famille_tournois[CNGT]": "CNGT", "famille_tournois[NTC]": "NTC",
    "surface[B_PIL]": "B_PIL", "surface[DUR  ]": "DUR  ",
    "surface[GAZON]": "GAZON", "surface[AUTRE]": "AUTRE",
}

# 43 communes — couverture complète métropole + Corse, rayon 100km
VILLES_FRANCE = [
    # Hauts-de-France
    {"ville_value": "Montdidier, 80500",          "ville_label": "Montdidier, 80, Somme, Hauts-de-France",                               "lat": "49.6483",  "lng": "2.5711"},
    {"ville_value": "Bouquemaison, 62270",         "ville_label": "Bouquemaison, 62, Pas-de-Calais, Hauts-de-France",                     "lat": "50.2167",  "lng": "2.3000"},
    # Grand Est
    {"ville_value": "Charleville-Mézières, 08000","ville_label": "Charleville-Mézières, 08, Ardennes, Grand Est",                        "lat": "49.7716",  "lng": "4.7158"},
    {"ville_value": "Bar-le-Duc, 55000",           "ville_label": "Bar-le-Duc, 55, Meuse, Grand Est",                                     "lat": "48.7728",  "lng": "5.1639"},
    {"ville_value": "Marigny-le-Châtel, 10350",    "ville_label": "Marigny-le-Châtel, 10, Aube, Grand Est",                               "lat": "48.3333",  "lng": "3.8167"},
    {"ville_value": "Vahl-lès-Bénestroff, 57670",  "ville_label": "Vahl-lès-Bénestroff, 57, Moselle, Grand Est",                          "lat": "48.9167",  "lng": "6.8667"},
    {"ville_value": "Mulhouse, 68100",             "ville_label": "Mulhouse, 68, Haut-Rhin, Grand Est",                                   "lat": "47.7508",  "lng": "7.3359"},
    # Normandie
    {"ville_value": "Flers, 61100",                "ville_label": "Flers, 61, Orne, Normandie",                                           "lat": "48.7469",  "lng": "-0.5738"},
    {"ville_value": "Saint-Lô, 50000",             "ville_label": "Saint-Lô, 50, Manche, Normandie",                                     "lat": "49.1167",  "lng": "-1.0833"},
    {"ville_value": "Bernay, 27300",               "ville_label": "Bernay, 27, Eure, Normandie",                                         "lat": "49.0863",  "lng": "0.5993"},
    # Bretagne
    {"ville_value": "Châteaulin, 29150",           "ville_label": "Châteaulin, 29, Finistère, Bretagne",                                  "lat": "48.1942",  "lng": "-4.0842"},
    {"ville_value": "Pontivy, 56300",              "ville_label": "Pontivy, 56, Morbihan, Bretagne",                                      "lat": "48.0714",  "lng": "-2.9736"},
    # Pays de la Loire
    {"ville_value": "Ancenis-Saint-Géréon, 44150", "ville_label": "Ancenis-Saint-Géréon, 44, Loire-Atlantique, Pays de la Loire",         "lat": "47.3667",  "lng": "-1.1667"},
    {"ville_value": "Fontenay-le-Comte, 85200",    "ville_label": "Fontenay-le-Comte, 85, Vendée, Pays de la Loire",                     "lat": "46.4677",  "lng": "-0.8076"},
    # Centre-Val de Loire
    {"ville_value": "Orléans, 45000",              "ville_label": "Orléans, 45, Loiret, Centre-Val de Loire",                            "lat": "47.9027",  "lng": "1.9090"},
    {"ville_value": "Tours, 37000",                "ville_label": "Tours, 37, Indre-et-Loire, Centre-Val de Loire",                      "lat": "47.3941",  "lng": "0.6848"},
    {"ville_value": "Châteauroux, 36000",          "ville_label": "Châteauroux, 36, Indre, Centre-Val de Loire",                         "lat": "46.8113",  "lng": "1.6924"},
    # Île-de-France
    {"ville_value": "Montereau-Fault-Yonne, 77130","ville_label": "Montereau-Fault-Yonne, 77, Seine-et-Marne, Île-de-France",            "lat": "48.3833",  "lng": "2.9500"},
    # Bourgogne-Franche-Comté
    {"ville_value": "Besançon, 25000",             "ville_label": "Besançon, 25, Doubs, Bourgogne-Franche-Comté",                        "lat": "47.2378",  "lng": "6.0241"},
    {"ville_value": "Chalon-sur-Saône, 71100",     "ville_label": "Chalon-sur-Saône, 71, Saône-et-Loire, Bourgogne-Franche-Comté",       "lat": "46.7786",  "lng": "4.8537"},
    # Nouvelle-Aquitaine
    {"ville_value": "Ruffec, 16700",               "ville_label": "Ruffec, 16, Charente, Nouvelle-Aquitaine",                            "lat": "46.0333",  "lng": "0.1833"},
    {"ville_value": "Saintes, 17100",              "ville_label": "Saintes, 17, Charente-Maritime, Nouvelle-Aquitaine",                  "lat": "45.7470",  "lng": "-0.6319"},
    {"ville_value": "Tulle, 19000",                "ville_label": "Tulle, 19, Corrèze, Nouvelle-Aquitaine",                              "lat": "45.2688",  "lng": "1.7726"},
    {"ville_value": "Périgueux, 24000",            "ville_label": "Périgueux, 24, Dordogne, Nouvelle-Aquitaine",                         "lat": "45.1854",  "lng": "0.7218"},
    {"ville_value": "Morcenx-la-Nouvelle, 40110",  "ville_label": "Morcenx-la-Nouvelle, 40, Landes, Nouvelle-Aquitaine",                 "lat": "44.0342",  "lng": "-0.9131"},
    {"ville_value": "Oloron-Sainte-Marie, 64400",  "ville_label": "Oloron-Sainte-Marie, 64, Pyrénées-Atlantiques, Nouvelle-Aquitaine",   "lat": "43.1942",  "lng": "-0.6058"},
    # Auvergne-Rhône-Alpes
    {"ville_value": "Aurouër, 03460",              "ville_label": "Aurouër, 03, Allier, Auvergne-Rhône-Alpes",                           "lat": "46.7167",  "lng": "3.3167"},
    {"ville_value": "Évaux-les-Bains, 23110",      "ville_label": "Évaux-les-Bains, 23, Creuse, Nouvelle-Aquitaine",                     "lat": "46.1764",  "lng": "2.4792"},
    {"ville_value": "Brioude, 43100",              "ville_label": "Brioude, 43, Haute-Loire, Auvergne-Rhône-Alpes",                      "lat": "45.2952",  "lng": "3.3830"},
    {"ville_value": "Saint-Maurice-de-Lignon, 43200","ville_label": "Saint-Maurice-de-Lignon, 43, Haute-Loire, Auvergne-Rhône-Alpes",    "lat": "45.2167",  "lng": "4.0833"},
    {"ville_value": "Saint-François-de-Sales, 73700","ville_label": "Saint-François-de-Sales, 73, Savoie, Auvergne-Rhône-Alpes",         "lat": "45.6833",  "lng": "6.3167"},
    {"ville_value": "Montélimar, 26200",           "ville_label": "Montélimar, 26, Drôme, Auvergne-Rhône-Alpes",                        "lat": "44.5567",  "lng": "4.7492"},
    # Provence-Alpes-Côte d'Azur
    {"ville_value": "Pertuis, 84120",              "ville_label": "Pertuis, 84, Vaucluse, Provence-Alpes-Côte d'Azur",                   "lat": "43.6942",  "lng": "5.5028"},
    {"ville_value": "Thorame-Basse, 04170",        "ville_label": "Thorame-Basse, 04, Alpes-de-Haute-Provence, Provence-Alpes-Côte d'Azur","lat": "44.0833","lng": "6.4833"},
    # Occitanie
    {"ville_value": "Cahors, 46000",               "ville_label": "Cahors, 46, Lot, Occitanie",                                          "lat": "44.4484",  "lng": "1.4411"},
    {"ville_value": "Tarbes, 65000",               "ville_label": "Tarbes, 65, Hautes-Pyrénées, Occitanie",                              "lat": "43.2333",  "lng": "0.0783"},
    {"ville_value": "Albi, 81000",                 "ville_label": "Albi, 81, Tarn, Occitanie",                                           "lat": "43.9267",  "lng": "2.1483"},
    {"ville_value": "Lodève, 34700",               "ville_label": "Lodève, 34, Hérault, Occitanie",                                      "lat": "43.7319",  "lng": "3.3195"},
    {"ville_value": "Foix, 09000",                 "ville_label": "Foix, 09, Ariège, Occitanie",                                         "lat": "42.9647",  "lng": "1.6064"},
    {"ville_value": "Perpignan, 66000",            "ville_label": "Perpignan, 66, Pyrénées-Orientales, Occitanie",                       "lat": "42.6983",  "lng": "2.8954"},
    # Corse
    {"ville_value": "Ajaccio, 20000",              "ville_label": "Ajaccio, 20, Corse-du-Sud, Corse",                                    "lat": "41.9197",  "lng": "8.7386"},
    {"ville_value": "Porto-Vecchio, 20137",        "ville_label": "Porto-Vecchio, 20, Corse-du-Sud, Corse",                              "lat": "41.5928",  "lng": "9.2794"},
    {"ville_value": "Corte, 20250",                "ville_label": "Corte, 20, Haute-Corse, Corse",                                       "lat": "42.3064",  "lng": "9.1498"},
]


# ── Session ────────────────────────────────────────────────────────────────────

def get_session():
    print("Ouverture Ten'Up via Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        fbid    = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    if not fbid:
        raise RuntimeError("form_build_id introuvable")
    print(f"Session OK — fbid: {fbid[:35]}...")
    return fbid, cookies


def make_session(cookies):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE, "Referer": TENUP_SEARCH, "X-Requested-With": "XMLHttpRequest",
    })
    for k, v in cookies.items():
        s.cookies.set(k, v)
    return s


# ── AJAX ville ─────────────────────────────────────────────────────────────────

def ajax_ville_page(session, fbid, ville, date_start, date_end, page_num):
    """AJAX pour une ville, une page. Retourne (items, nb_total)."""
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
        **NEW_CRITERIA,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": str(page_num),
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=45)
            resp.raise_for_status()
            for cmd in resp.json():
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return res.get("items", []), res.get("nb_results", 0)
            return [], 0
        except Exception as e:
            print(f"    Erreur page {page_num} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
    return [], 0


def coord_offsets(base_lat, base_lng, nb_total):
    """
    Génère des centres décalés pour contourner la limite de 30 résultats/requête.
    Avec sort=_DIST_, chaque centre donne un classement différent → 30 autres tournois.
    """
    if nb_total <= 30:
        return []
    extra = min(math.ceil(nb_total / 30) - 1, 10)  # max 10 offsets par ville
    # 8 directions × 3 distances = 24 offsets possibles
    dirs = [(1,0),(-1,0),(0,1),(0,-1),(0.7,0.7),(-0.7,0.7),(0.7,-0.7),(-0.7,-0.7)]
    result = []
    for km in [20, 40, 60]:
        for dlat, dlng in dirs:
            dlat_deg = dlat * km / 111.0
            dlng_deg = dlng * km / (111.0 * cos(radians(base_lat)))
            result.append((base_lat + dlat_deg, base_lng + dlng_deg))
            if len(result) >= extra:
                return result
    return result[:extra]


def ajax_ville_offset(session, fbid, ville, olat, olng, date_start, date_end):
    """Appel AJAX avec des coordonnées décalées (même ville, centre différent)."""
    data = {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": ville["ville_value"],
        "ville[autocomplete][value_container][label_field]": ville["ville_label"],
        "ville[autocomplete][value_container][lat_field]":   f"{olat:.6f}",
        "ville[autocomplete][value_container][lng_field]":   f"{olng:.6f}",
        "ville[distance][value_field]": RAYON,
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        **NEW_CRITERIA,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": "0",
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=45)
            resp.raise_for_status()
            for cmd in resp.json():
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return res.get("items", []), res.get("nb_results", 0)
            return [], 0
        except Exception as e:
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
    return [], 0


def scrape_ville(session, fbid, ville, date_start, date_end):
    """
    Scrape tous les tournois d'une ville.
    Stratégie : si nb_total > 30, décaler le centre de recherche (sort=_DIST_
    donne un classement différent → 30 autres tournois par offset).
    La pagination classique est cassée côté Ten'Up pour les nouvelles requêtes,
    mais les offsets de coordonnées contournent cette limitation.
    """
    name = ville["ville_value"].split(",")[0]
    all_items = {}

    # Page initiale (coordonnées originales)
    items0, nb_total = ajax_ville_page(session, fbid, ville, date_start, date_end, 0)

    # Fallback page 1 si page 0 vide
    if not items0 and nb_total == 0:
        items0, nb_total = ajax_ville_page(session, fbid, ville, date_start, date_end, 1)

    for it in items0:
        all_items[str(it.get("id", ""))] = it

    if nb_total == 0:
        return list(all_items.values()), 0

    # Offsets de coordonnées pour couvrir les résultats au-delà de 30
    if nb_total > 30:
        base_lat = float(ville["lat"])
        base_lng = float(ville["lng"])
        offsets = coord_offsets(base_lat, base_lng, nb_total)
        for olat, olng in offsets:
            items_off, _ = ajax_ville_offset(session, fbid, ville, olat, olng, date_start, date_end)
            if not items_off:
                break
            new_count = sum(
                1 for it in items_off
                if str(it.get("id","")) and str(it.get("id","")) not in all_items
                and not all_items.update({str(it.get("id","")): it})
            )
            if new_count == 0:
                break  # plus rien de nouveau, inutile de continuer
            time.sleep(0.25)

    print(f"  {name} ({RAYON}km) : {nb_total} résultats → {len(all_items)} uniques")
    return list(all_items.values()), nb_total


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_item(item):
    tid = str(item.get("id", ""))
    if not tid:
        return None

    installation = item.get("installation", {})
    ville   = installation.get("ville",      item.get("villeEngagement",      ""))
    cp      = installation.get("codePostal", item.get("codePostalEngagement", ""))
    adresse = installation.get("adresse2",   item.get("adresse2Engagement",   ""))
    lat     = installation.get("lat")
    lng     = installation.get("lng")

    date_debut_raw = item.get("dateDebut")
    date_debut     = date_debut_raw.get("date", "") if isinstance(date_debut_raw, dict) else ""
    date_fin_raw   = item.get("dateFin")
    date_fin       = date_fin_raw.get("date", "")   if isinstance(date_fin_raw, dict) else ""

    if date_debut:
        try:
            d = datetime.strptime(date_debut[:10], "%Y-%m-%d")
            if d.year < 2000:
                raise ValueError("année invalide")
            date_str = f"{JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
            if date_fin and date_fin[:10] != date_debut[:10]:
                try:
                    d2 = datetime.strptime(date_fin[:10], "%Y-%m-%d")
                    if d2.year >= 2000:
                        date_str += f" → {JOURS[d2.weekday()]} {d2.strftime('%d/%m/%Y')}"
                except Exception:
                    pass
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

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v6 — {len(VILLES_FRANCE)} villes ({date_start}→{date_end})")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_raw = {}  # tenup_id → item brut
    stats   = {}

    for i, ville in enumerate(VILLES_FRANCE, 1):
        items, nb_total = scrape_ville(session, fbid, ville, date_start, date_end)
        name = ville["ville_value"].split(",")[0]
        stats[name] = {"nb_total": nb_total, "scraped": len(items)}
        for item in items:
            tid = str(item.get("id", ""))
            if tid and tid not in all_raw:
                all_raw[tid] = item
        if i % 10 == 0:
            elapsed = (datetime.now() - now).total_seconds()
            print(f"  [{i}/{len(VILLES_FRANCE)}] {len(all_raw)} uniques ({elapsed:.0f}s)")
        time.sleep(0.3)

    tournaments = [t for item in all_raw.values() if (t := parse_item(item))]

    print(f"\n{'='*60}")
    print(f"Total France : {len(tournaments)} tournois uniques")
    print("\nDétail par ville (top 10 par nb résultats) :")
    for name, s in sorted(stats.items(), key=lambda x: -x[1]["nb_total"])[:10]:
        print(f"  {name}: {s['nb_total']} Ten'Up → {s['scraped']} scrapés")

    # Écrire JSON
    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments":tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier écrit : {OUTPUT_FILE}")

    # Git
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v6 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] — {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
