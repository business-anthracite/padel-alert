"""
Padel Alert â€” Scraper France v9 â€” par COMITÃ‰ (couverture 100%)

ProblÃ¨me v8 : recherche par ligue â†’ ~2000+ rÃ©sultats â†’ plafond pagination Drupal
atteint Ã  ~40 pages â†’ 50% de couverture seulement.

Solution v9 : scinde chaque ligue en comitÃ©s individuels (<700 rÃ©sultats max,
ISÃˆRE Ã©tant le plus grand). Chaque comitÃ© est entiÃ¨rement paginable sans
atteindre le plafond. Couverture ~100%.

Flow par comitÃ© :
  comite/ajax(ligue_id) â†’ pour chaque comitÃ© :
    ligue_sumbit/ajax(comitÃ©_seul) â†’ fbid frais â†’
    system/ajax(submit_main) â†’ [system/ajax(submit_page)] Ã— N â†’ dÃ©duplication

Cron : toutes les 4h (0 */4 * * *) â€” run ~25-35 min.
"""
import os, json, subprocess, time, re
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
VUEJS_BASE   = f"{TENUP_BASE}/recherche/tournois/vuejs"
HORIZON_DAYS = 90
RETRY_MAX    = 3

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

LIGUES = [
    {"id": 50, "name": "Auvergne-RhÃ´ne-Alpes"},
    {"id": 51, "name": "Bourgogne-Franche-ComtÃ©"},
    {"id": 52, "name": "Bretagne"},
    {"id": 53, "name": "Centre-Val de Loire"},
    {"id": 54, "name": "Corse"},
    {"id": 55, "name": "Grand Est"},
    {"id": 56, "name": "Hauts-de-France"},
    {"id": 57, "name": "ÃŽle-de-France"},
    {"id": 58, "name": "Normandie"},
    {"id": 59, "name": "Nouvelle-Aquitaine"},
    {"id": 60, "name": "Occitanie"},
    {"id": 61, "name": "Pays de la Loire"},
    {"id": 62, "name": "Provence-Alpes-CÃ´te d'Azur"},
    {"id": 63, "name": "Guadeloupe"},
    {"id": 64, "name": "Guyane"},
    {"id": 65, "name": "Martinique"},
    {"id": 66, "name": "Nouvelle-CalÃ©donie"},
    {"id": 67, "name": "RÃ©union"},
]


# â”€â”€ Session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    print(f"Session OK â€” fbid: {fbid[:35]}...")
    return fbid, cookies


def refresh_fbid(session):
    """GET la page de recherche pour obtenir un nouveau form_build_id."""
    try:
        resp = session.get(TENUP_SEARCH, timeout=30)
        m = re.search(r'name="form_build_id"\s+value="([^"]+)"', resp.text)
        if not m:
            m = re.search(r'value="([^"]+)"\s+name="form_build_id"', resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


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


# â”€â”€ Vue.js endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_comites(session, ligue_id):
    """Retourne dict comite_id â†’ comite_name pour une ligue."""
    data = {f"selectedLigue[{ligue_id}]": str(ligue_id)}
    headers_vue = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": TENUP_SEARCH,
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(f"{VUEJS_BASE}/comite/ajax", data=data,
                                headers=headers_vue, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            comites = {}
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and str(item.get("code", "")) == str(ligue_id):
                        comites = {str(k): str(v) for k, v in item.get("option", {}).items()}
                        break
            return comites
        except Exception:
            if attempt < RETRY_MAX:
                time.sleep(2)
    return {}


def set_comite_filter(session, ligue_id, comite_id, comite_name):
    """
    Stocke en session PHP le filtre pour UN SEUL comitÃ©.
    N'envoie PAS [all]=1 pour Ã©viter que le serveur retourne toute la ligue.
    """
    data = {f"selectedLigue[{ligue_id}][{comite_id}]": comite_name}
    headers_vue = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": TENUP_SEARCH,
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(f"{VUEJS_BASE}/ligue_sumbit/ajax", data=data,
                                headers=headers_vue, timeout=30)
            resp.raise_for_status()
            return True
        except Exception:
            if attempt < RETRY_MAX:
                time.sleep(2)
    return False


def set_ligue_filter_all(session, ligue_id, comites):
    """
    Fallback : filtre toute la ligue (tous comitÃ©s + [all]=1).
    UtilisÃ© si le filtre par comitÃ© individuel retourne 0 rÃ©sultat.
    """
    data = {}
    for comite_id, comite_name in comites.items():
        data[f"selectedLigue[{ligue_id}][{comite_id}]"] = comite_name
    data[f"selectedLigue[{ligue_id}][all]"] = "1"
    headers_vue = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": TENUP_SEARCH,
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(f"{VUEJS_BASE}/ligue_sumbit/ajax", data=data,
                                headers=headers_vue, timeout=30)
            resp.raise_for_status()
            return True
        except Exception:
            if attempt < RETRY_MAX:
                time.sleep(2)
    return False


# â”€â”€ AJAX recherche â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def ajax_page(session, fbid, page_num, date_start, date_end):
    """
    RequÃªte AJAX /system/ajax pour la recherche courante (filtre en session PHP).
    page=0 â†’ submit_main | page>0 â†’ submit_page
    """
    if page_num == 0:
        trigger_name  = "submit_main"
        trigger_value = "Rechercher"
    else:
        trigger_name  = "submit_page"
        trigger_value = "Submit page"

    data = {
        "recherche_type": "ligue",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "",
        "ville[autocomplete][value_container][label_field]": "",
        "ville[autocomplete][value_container][lat_field]": "",
        "ville[autocomplete][value_container][lng_field]": "",
        "ville[distance][value_field]": "0",
        "club[autocomplete][textfield]": "",
        "club[autocomplete][value_container][value_field]": "",
        "club[autocomplete][value_container][label_field]": "",
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        "sort": "dateDebut asc",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  trigger_name,
        "_triggering_element_value": trigger_value,
        "form_build_id": fbid,
        "page": str(page_num),
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=60)
            resp.raise_for_status()
            for cmd in resp.json():
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return res.get("items", []), res.get("nb_results", 0)
            return [], 0
        except Exception as e:
            print(f"    Erreur page {page_num} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(3 * attempt)
    return [], 0


# â”€â”€ Scraping d'un comitÃ© â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def scrape_comite(session, current_fbid, ligue_id, ligue_name, comite_id, comite_name,
                  date_start, date_end, all_items):
    """
    Scrape tous les tournois d'un comitÃ© et les ajoute Ã  all_items.
    Retourne (nombre ajoutÃ©s, nb_total_comite).
    """
    ok = set_comite_filter(session, ligue_id, comite_id, comite_name)
    if not ok:
        print(f"    âœ— ligue_sumbit/ajax Ã©chouÃ© pour {comite_name}")
        return 0, 0

    # Fbid frais pour ce comitÃ©
    new_fbid = refresh_fbid(session)
    fbid = new_fbid if new_fbid else current_fbid

    # Page 0 : submit_main
    items0, nb_total = ajax_page(session, fbid, 0, date_start, date_end)

    # Fallback page 1 si submit_main renvoie vide
    if not items0 and nb_total == 0:
        items0, nb_total = ajax_page(session, fbid, 1, date_start, date_end)

    # Si toujours 0 rÃ©sultat â†’ le filtre par comitÃ© seul n'a pas fonctionnÃ©.
    # Retourner (0, 0) â€” la ligue sera gÃ©rÃ©e en fallback dans scrape_ligue.
    if nb_total == 0 and not items0:
        return 0, 0

    added = 0
    collected = 0

    for it in items0:
        tid = str(it.get("id", ""))
        if tid:
            collected += 1
            if tid not in all_items:
                it["_ligue"] = ligue_name
                all_items[tid] = it
                added += 1

    if nb_total == 0:
        # nb_total non retournÃ© sur page 0 : on continue la pagination quand mÃªme
        nb_total = 99999

    # Pagination : pages 1, 2, 3...
    consecutive_empty = 0
    for page_num in range(1, 9999):
        # ArrÃªt si on a dÃ©jÃ  tout rÃ©cupÃ©rÃ©
        if collected >= nb_total:
            break

        items, _ = ajax_page(session, fbid, page_num, date_start, date_end)

        if not items:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            time.sleep(0.5)
            continue
        consecutive_empty = 0

        page_new = 0
        for it in items:
            tid = str(it.get("id", ""))
            if tid:
                collected += 1
                if tid not in all_items:
                    it["_ligue"] = ligue_name
                    all_items[tid] = it
                    added += 1
                    page_new += 1

        # ArrÃªt anticipÃ© : page entiÃ¨re dÃ©jÃ  vue ET petite (fin de pagination)
        if page_new == 0 and len(items) < 20:
            break

        time.sleep(0.25)

    return added, nb_total if nb_total != 99999 else collected


# â”€â”€ Scraping d'une ligue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def scrape_ligue(session, fbid, ligue, date_start, date_end):
    """
    Scrape tous les comitÃ©s d'une ligue individuellement.
    Fallback : si le filtre par comitÃ© ne retourne rien, tente la ligue entiÃ¨re.
    """
    ligue_id   = ligue["id"]
    ligue_name = ligue["name"]
    all_items  = {}

    comites = get_comites(session, ligue_id)
    print(f"  {ligue_name} : {len(comites)} comitÃ©s")

    if not comites:
        print(f"  âœ— Aucun comitÃ© trouvÃ© pour {ligue_name}")
        return [], 0

    nb_total_ligue  = 0
    first_comite_ok = None  # pour dÃ©tecter si le filtre comitÃ© fonctionne

    for comite_id, comite_name in comites.items():
        added, nb_total_comite = scrape_comite(
            session, fbid, ligue_id, ligue_name,
            comite_id, comite_name,
            date_start, date_end, all_items
        )

        # DÃ©tecter si le filtre individuel fonctionne (premier comitÃ©)
        if first_comite_ok is None:
            first_comite_ok = (nb_total_comite > 0 or added > 0)

        nb_total_ligue += nb_total_comite
        print(f"    {comite_name}: {nb_total_comite} total â†’ {added} nouveaux (cumul ligue: {len(all_items)})")
        time.sleep(0.5)

    # â”€â”€ Fallback : si AUCUN comitÃ© n'a retournÃ© de rÃ©sultats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # (le filtre individuel ne fonctionne pas â†’ utiliser la ligue entiÃ¨re comme v8)
    if first_comite_ok is False and len(all_items) == 0:
        print(f"  âš  Fallback ligue entiÃ¨re pour {ligue_name}")
        ok = set_ligue_filter_all(session, ligue_id, comites)
        if ok:
            new_fbid = refresh_fbid(session)
            fb = new_fbid if new_fbid else fbid
            items0, nb_total_ligue = ajax_page(session, fb, 0, date_start, date_end)
            for it in items0:
                tid = str(it.get("id", ""))
                if tid and tid not in all_items:
                    it["_ligue"] = ligue_name
                    all_items[tid] = it
            # Pagination fallback (comportement v8)
            for page_num in range(1, 9999):
                items, _ = ajax_page(session, fb, page_num, date_start, date_end)
                if not items:
                    break
                new_count = 0
                for it in items:
                    tid = str(it.get("id", ""))
                    if tid and tid not in all_items:
                        it["_ligue"] = ligue_name
                        all_items[tid] = it
                        new_count += 1
                if new_count == 0:
                    break
                time.sleep(0.25)

    print(f"  {ligue_name} : nb_totalâ‰ˆ{nb_total_ligue} â†’ {len(all_items)} uniques scrapÃ©s")
    return list(all_items.values()), nb_total_ligue


# â”€â”€ Parsing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                raise ValueError
            date_str = f"{JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
            if date_fin and date_fin[:10] != date_debut[:10]:
                try:
                    d2 = datetime.strptime(date_fin[:10], "%Y-%m-%d")
                    if d2.year >= 2000:
                        date_str += f" â†’ {JOURS[d2.weekday()]} {d2.strftime('%d/%m/%Y')}"
                except Exception:
                    pass
        except Exception:
            date_str = date_debut[:10]
    else:
        date_str = "Date inconnue"

    epreuves_raw = item.get("epreuves", [])
    match_types, age_codes, niveau_codes, competition_codes = set(), set(), set(), set()
    for e in epreuves_raw:
        nat = (e.get("natureEpreuve") or {}).get("code", "")
        if nat:
            match_types.add(nat)
        niv = (e.get("typeEpreuve") or {}).get("code", "")
        if niv:
            niveau_codes.add(niv)
        age_lib = (e.get("categorieAge") or {}).get("libelle", "")
        if age_lib:
            age_codes.add(age_lib)
        comp = (e.get("typeCompetition") or {}).get("code", "")
        if comp:
            competition_codes.add(comp)

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
        "match_types":      sorted(match_types),
        "age_codes":        sorted(age_codes),
        "niveau_codes":     sorted(niveau_codes),
        "competition_codes":sorted(competition_codes),
        "ligues":           [item["_ligue"]] if item.get("_ligue") else [],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert â€” Scraper v9 â€” {len(LIGUES)} ligues ({date_start}â†’{date_end})")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_raw = {}
    stats   = {}

    for ligue in LIGUES:
        items, nb_total = scrape_ligue(session, fbid, ligue, date_start, date_end)
        stats[ligue["name"]] = {"nb_total": nb_total, "scraped": len(items)}
        for item in items:
            tid = str(item.get("id", ""))
            if tid and tid not in all_raw:
                all_raw[tid] = item
        print(f"  â†’ Total cumulÃ© France : {len(all_raw)} uniques")
        time.sleep(0.5)

    tournaments = [t for item in all_raw.values() if (t := parse_item(item))]

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'='*60}")
    print(f"Total France : {len(tournaments)} tournois uniques ({elapsed:.0f}s)")
    print("\nDÃ©tail par ligue :")
    for name, s in sorted(stats.items(), key=lambda x: -x[1]["nb_total"]):
        pct = round(100 * s['scraped'] / s['nb_total']) if s['nb_total'] > 0 else 0
        print(f"  {name}: {s['nb_total']} â†’ {s['scraped']} scrapÃ©s ({pct}%)")

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments":tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier Ã©crit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v9 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] â€” {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushÃ©.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] TerminÃ©.")


if __name__ == "__main__":
    main()
