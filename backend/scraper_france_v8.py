"""
Padel Alert — Scraper France v8 — par ligue via session PHP

Architecture finale (08/05/2026) :
Pour filtrer par ligue, Ten'Up utilise deux endpoints Vue.js AVANT la recherche :
  1. POST /recherche/tournois/vuejs/comite/ajax     → lit les comités d'une ligue
  2. POST /recherche/tournois/vuejs/ligue_sumbit/ajax → stocke le filtre en session PHP
Ensuite /system/ajax retourne les résultats filtrés pour cette ligue uniquement.

Flow par ligue :
  comite/ajax(ligue_id) → ligue_sumbit/ajax(comités) → system/ajax(submit_main) →
  [system/ajax(submit_page)] × N pages → déduplication

18 ligues × ~300-600 tournois chacune ≈ 10 000 tournois uniques.
"""
import os, json, math, subprocess, time
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

# 18 ligues FFT (IDs confirmés depuis le HTML Ten'Up)
LIGUES = [
    {"id": 50, "name": "Auvergne-Rhône-Alpes"},
    {"id": 51, "name": "Bourgogne-Franche-Comté"},
    {"id": 52, "name": "Bretagne"},
    {"id": 53, "name": "Centre-Val de Loire"},
    {"id": 54, "name": "Corse"},
    {"id": 55, "name": "Grand Est"},
    {"id": 56, "name": "Hauts-de-France"},
    {"id": 57, "name": "Île-de-France"},
    {"id": 58, "name": "Normandie"},
    {"id": 59, "name": "Nouvelle-Aquitaine"},
    {"id": 60, "name": "Occitanie"},
    {"id": 61, "name": "Pays de la Loire"},
    {"id": 62, "name": "Provence-Alpes-Côte d'Azur"},
    {"id": 63, "name": "Guadeloupe"},
    {"id": 64, "name": "Guyane"},
    {"id": 65, "name": "Martinique"},
    {"id": 66, "name": "Nouvelle-Calédonie"},
    {"id": 67, "name": "Réunion"},
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


# ── Vue.js endpoints (filtre ligue) ───────────────────────────────────────────

def get_comites(session, ligue_id):
    """
    Appelle /vuejs/comite/ajax pour récupérer les comités d'une ligue.
    Retourne le dict comite_id → comite_name, ou {} en cas d'erreur.
    """
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
            # Log format sur premier appel pour debug
            if attempt == 1 and ligue_id == LIGUES[0]["id"]:
                print(f"    [comite/ajax format] keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
                print(f"    [comite/ajax sample] {str(result)[:300]}")
            # Format confirmé : [{"code": "50", "option": {"5001": "AIN", ...}, ...}]
            comites = {}
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and str(item.get("code", "")) == str(ligue_id):
                        comites = {str(k): str(v) for k, v in item.get("option", {}).items()}
                        break
            return comites
        except Exception as e:
            if attempt < RETRY_MAX:
                time.sleep(2)
    return {}


def set_ligue_filter(session, ligue_id, comites):
    """
    Appelle /vuejs/ligue_sumbit/ajax pour stocker le filtre ligue en session PHP.
    Envoie les comités récupérés + [all]=1.
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
        except Exception as e:
            if attempt < RETRY_MAX:
                time.sleep(2)
    return False


# ── AJAX recherche ─────────────────────────────────────────────────────────────

def ajax_ligue_page(session, fbid, page_num, date_start, date_end, sort_order="dateDebut asc"):
    """
    Requête AJAX /system/ajax pour la ligue courante (définie en session PHP).
    page=0 → submit_main | page>0 → submit_page
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
        "sort": sort_order,
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


# ── Scraping d'une ligue ───────────────────────────────────────────────────────

def scrape_ligue(session, fbid, ligue, date_start, date_end):
    """Scrape tous les tournois d'une ligue via session PHP + pagination."""
    ligue_id   = ligue["id"]
    ligue_name = ligue["name"]
    all_items  = {}

    # 1. Récupérer les comités
    comites = get_comites(session, ligue_id)
    print(f"  {ligue_name} : {len(comites)} comités")

    # 2. Définir le filtre ligue en session PHP
    ok = set_ligue_filter(session, ligue_id, comites)
    if not ok:
        print(f"  ERREUR ligue_sumbit/ajax pour {ligue_name}")
        return [], 0

    # 3. Deux passes pour maximiser la couverture :
    #    - dateDebut asc  : couvre les tournois proches en date chronologique
    #    - dateDebut desc : couvre depuis la fin → différents groupes de date
    nb_total = 0  # initialisé ici pour éviter UnboundLocalError
    sample_logged = False

    for sort_order in ["dateDebut asc", "dateDebut desc"]:
        items0, nb_total_pass = ajax_ligue_page(session, fbid, 0, date_start, date_end,
                                                sort_order=sort_order)

        fallback_used = False
        if not items0 and nb_total_pass == 0:
            items0, nb_total_pass = ajax_ligue_page(session, fbid, 1, date_start, date_end,
                                                    sort_order=sort_order)
            fallback_used = True

        if nb_total == 0 and nb_total_pass > 0:
            nb_total = nb_total_pass

        # Log structure epreuves sur le premier item trouvé (pour debug colonnes WP)
        if not sample_logged and items0:
            sample_logged = True
            sample = items0[0]
            epreuves = sample.get("epreuves", [])
            if epreuves:
                print(f"    [DEBUG epreuves[0]] {json.dumps(epreuves[0])[:300]}")

        for it in items0:
            tid = str(it.get("id", ""))
            if tid:
                it["_ligue"] = ligue_name  # injection contexte ligue
                all_items[tid] = it

        if nb_total_pass == 0:
            continue

        start_page        = 2 if fallback_used else 1
        consecutive_empty = 0

        for page_num in range(start_page, 99999):
            items, _ = ajax_ligue_page(session, fbid, page_num, date_start, date_end,
                                       sort_order=sort_order)
            if not items:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                time.sleep(0.5)
                continue
            consecutive_empty = 0
            new_count = 0
            for it in items:
                tid = str(it.get("id", ""))
                if tid and tid not in all_items:
                    it["_ligue"] = ligue_name
                    all_items[tid] = it
                    new_count += 1
            if new_count == 0:
                break
            time.sleep(0.2)

    print(f"  {ligue_name} : nb_total={nb_total} → {len(all_items)} uniques scrapés")
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
                raise ValueError
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

    epreuves_raw = item.get("epreuves", [])
    match_types, age_codes, niveau_codes, competition_codes = set(), set(), set(), set()
    NIVEAU_PREFIXES = ("P", "NC", "NR")  # P25, P50, P100..., NC, NR
    MATCH_CODES     = {"DM", "DD", "DX", "SM", "SD", "SX"}

    for e in epreuves_raw:
        # typeEpreuve → DM/DD/DX (type d'épreuve / sexe)
        t = (e.get("typeEpreuve") or {}).get("code", "")
        if t:
            if t in MATCH_CODES:
                match_types.add(t)
            elif t and t[0] in "P" or any(t.startswith(p) for p in NIVEAU_PREFIXES):
                niveau_codes.add(t)   # parfois le niveau est dans typeEpreuve
            else:
                match_types.add(t)

        # categorieEpreuve → P25/P50/P100... (niveau)
        n = (e.get("categorieEpreuve") or {}).get("code", "")
        if n:
            niveau_codes.add(n)

        # categoriePratiquant → codes âge (Senior, U18...)
        a = (e.get("categoriePratiquant") or {}).get("code", "")
        if not a:
            a = (e.get("categoriePratiquant") or {}).get("libelle", "")
        if a:
            age_codes.add(a)

        # typeCompetition → T/C/etc.
        c = (e.get("typeCompetition") or {}).get("code", "")
        if c:
            competition_codes.add(c)

    match_types       = sorted(match_types)
    age_codes         = sorted(age_codes)
    niveau_codes      = sorted(niveau_codes)
    competition_codes = sorted(competition_codes)

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
        "ligues":           [item["_ligue"]] if item.get("_ligue") else [],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v8 — {len(LIGUES)} ligues ({date_start}→{date_end})")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_raw = {}  # tenup_id → item brut
    stats   = {}

    for ligue in LIGUES:
        items, nb_total = scrape_ligue(session, fbid, ligue, date_start, date_end)
        stats[ligue["name"]] = {"nb_total": nb_total, "scraped": len(items)}
        for item in items:
            tid = str(item.get("id", ""))
            if tid and tid not in all_raw:
                all_raw[tid] = item
        print(f"  → Total cumulé : {len(all_raw)} uniques")
        time.sleep(0.5)

    tournaments = [t for item in all_raw.values() if (t := parse_item(item))]

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'='*60}")
    print(f"Total France : {len(tournaments)} tournois uniques ({elapsed:.0f}s)")
    print("\nDétail par ligue :")
    for name, s in sorted(stats.items(), key=lambda x: -x[1]["nb_total"]):
        print(f"  {name}: {s['nb_total']} → {s['scraped']} scrapés")

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments":tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier écrit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v8 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] — {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
