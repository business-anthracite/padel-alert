"""
Padel Alert â€” Scraper France v10 â€” par comitÃ© Ã— pÃ©riode (couverture 100%)

ProblÃ¨me v8/v9 : plafond pagination Drupal ~40 pages (1200 items).
Avec 18 ligues Ã— rÃ©sultats cumulÃ©s : 50% de couverture max.

Solution v10 : double rÃ©duction dimensionnelle.
  Dimension 1 â€” 4 pÃ©riodes de dates (90j â†’ 4 tranches â‰¤ 30j)
  Dimension 2 â€” filtre par comitÃ© individuel (ligue Ã· ~8 comitÃ©s)
RÃ©sultat max par requÃªte : ~200 items = 7 pages â†’ bien sous le plafond.

Bug v9 corrigÃ© : [all]=1 rÃ©intÃ©grÃ© dans set_comite_filter pour activer le filtre
cÃ´tÃ© session Drupal (sans lui, le filtre comitÃ© Ã©tait ignorÃ©).

PÃ©riodes :
  P1 : J+0  â†’ J+14  (15 jours, tournois imminents)
  P2 : J+15 â†’ J+29  (15 jours)
  P3 : J+30 â†’ J+59  (30 jours, M+2)
  P4 : J+60 â†’ J+89  (30 jours, M+3)

Cron : 0 */4 * * *  (~35-40 min par run, confortable sous 120 min de timeout)
"""
import os, json, calendar, subprocess, time, re
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


def make_periods(now):
    """
    4 pÃ©riodes couvrant les 90 prochains jours sans chevauchement.
    P1 : J+0  â†’ J+14
    P2 : J+15 â†’ J+29
    P3 : J+30 â†’ J+59
    P4 : J+60 â†’ J+89
    """
    fmt = "%d/%m/%y"
    return [
        (now,                       now + timedelta(days=14),  "P1 J+0â†’J+14"),
        (now + timedelta(days=15),  now + timedelta(days=29),  "P2 J+15â†’J+29"),
        (now + timedelta(days=30),  now + timedelta(days=59),  "P3 M+2"),
        (now + timedelta(days=60),  now + timedelta(days=89),  "P4 M+3"),
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
    [all]=1 requis pour activer le filtre ligue cÃ´tÃ© Drupal (bug v9 : Ã©tait absent).
    """
    data = {
        f"selectedLigue[{ligue_id}][{comite_id}]": comite_name,
        f"selectedLigue[{ligue_id}][all]": "1",
    }
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
    RequÃªte AJAX /system/ajax. page=0 â†’ submit_main | page>0 â†’ submit_page
    Retourne (items, nb_results).
    """
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
        "_triggering_element_name":  "submit_main" if page_num == 0 else "submit_page",
        "_triggering_element_value": "Rechercher"  if page_num == 0 else "Submit page",
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
            print(f"      Erreur page {page_num} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(3 * attempt)
    return [], 0


# â”€â”€ Scraping comitÃ© Ã— pÃ©riode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def scrape_comite_period(session, fbid, ligue_id, ligue_name,
                         comite_id, comite_name,
                         date_start, date_end, all_items):
    """
    Scrape un comitÃ© sur une pÃ©riode donnÃ©e.
    Retourne (items_ajoutÃ©s, nb_total_comite_period).
    """
    ok = set_comite_filter(session, ligue_id, comite_id, comite_name)
    if not ok:
        return 0, 0

    new_fbid = refresh_fbid(session)
    cur_fbid = new_fbid if new_fbid else fbid

    # Page 0 : submit_main
    items0, nb_total = ajax_page(session, cur_fbid, 0, date_start, date_end)
    if not items0 and nb_total == 0:
        items0, nb_total = ajax_page(session, cur_fbid, 1, date_start, date_end)

    if nb_total == 0 and not items0:
        return 0, 0

    added    = 0
    collected = 0

    for it in items0:
        tid = str(it.get("id", ""))
        if tid:
            collected += 1
            if tid not in all_items:
                it["_ligue"] = ligue_name
                all_items[tid] = it
                added += 1

    cap = nb_total if nb_total > 0 else 99999
    consecutive_empty = 0

    for page_num in range(1, 9999):
        if collected >= cap:
            break
        items, _ = ajax_page(session, cur_fbid, page_num, date_start, date_end)
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
        # Dernier page partielle et rien de nouveau â†’ fin
        if page_new == 0 and len(items) < 20:
            break
        time.sleep(0.25)

    return added, nb_total if nb_total > 0 else collected


# â”€â”€ Scraping d'une ligue (toutes pÃ©riodes Ã— tous comitÃ©s) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def scrape_ligue(session, fbid, ligue, periods):
    ligue_id   = ligue["id"]
    ligue_name = ligue["name"]
    all_items  = {}

    comites = get_comites(session, ligue_id)
    print(f"  {ligue_name} : {len(comites)} comitÃ©s Ã— {len(periods)} pÃ©riodes")

    if not comites:
        print(f"  âœ— Aucun comitÃ© pour {ligue_name}")
        return [], 0

    nb_total_ligue = 0

    for p_start, p_end, p_label in periods:
        ds = p_start.strftime("%d/%m/%y")
        de = p_end.strftime("%d/%m/%y")
        period_added = 0

        for comite_id, comite_name in comites.items():
            added, nb = scrape_comite_period(
                session, fbid, ligue_id, ligue_name,
                comite_id, comite_name, ds, de, all_items
            )
            nb_total_ligue += nb
            period_added   += added
            time.sleep(0.4)

        print(f"    [{p_label}] {ds}â†’{de} : +{period_added} nouveaux (cumul: {len(all_items)})")
        time.sleep(0.3)

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
    date_fin       = date_fin_raw.get("date", "") if isinstance(date_fin_raw, dict) else ""

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
        "tenup_id":          tid,
        "libelle":           item.get("libelle", "Tournoi"),
        "club":              item.get("nomClub", ""),
        "ville":             ville,
        "cp":                cp,
        "adresse":           f"{adresse}, {cp} {ville}".strip(", "),
        "lat":               lat_f,
        "lng":               lng_f,
        "date_debut":        date_debut[:10] if date_debut else None,
        "date_fin":          date_fin[:10]   if date_fin   else None,
        "date_str":          date_str,
        "match_types":       sorted(match_types),
        "age_codes":         sorted(age_codes),
        "niveau_codes":      sorted(niveau_codes),
        "competition_codes": sorted(competition_codes),
        "ligues":            [item["_ligue"]] if item.get("_ligue") else [],
        "link":              f"{TENUP_BASE}/tournoi/{tid}",
    }


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    now     = datetime.now()
    periods = make_periods(now)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert â€” Scraper v10 â€” {len(LIGUES)} ligues Ã— {len(periods)} pÃ©riodes")
    for ps, pe, pl in periods:
        print(f"  {pl} : {ps.strftime('%d/%m/%y')} â†’ {pe.strftime('%d/%m/%y')}")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_raw = {}
    stats   = {}

    for ligue in LIGUES:
        items, nb_total = scrape_ligue(session, fbid, ligue, periods)
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
    print(f"Total France : {len(tournaments)} tournois uniques ({elapsed:.0f}s / {elapsed/60:.1f}min)")
    print("\nDÃ©tail par ligue :")
    france_total = sum(s["nb_total"] for s in stats.values())
    france_scraped = sum(s["scraped"] for s in stats.values())
    for name, s in sorted(stats.items(), key=lambda x: -x[1]["nb_total"]):
        pct = round(100 * s["scraped"] / s["nb_total"]) if s["nb_total"] > 0 else 0
        print(f"  {name}: {s['nb_total']} â†’ {s['scraped']} scrapÃ©s ({pct}%)")
    print(f"\n  FRANCE TOTAL : {france_total} â†’ {france_scraped} scrapÃ©s ({round(100*france_scraped/france_total) if france_total else 0}%)")

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments": tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier Ã©crit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v10 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] â€” {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushÃ©.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] TerminÃ©.")


if __name__ == "__main__":
    main()
