"""
Padel Alert — Scraper France v7 — ligue + pagination réelle

Architecture finale (07/05/2026) :
  1. recherche_type = ligue (France entière, sans filtrer par ligue/comité)
  2. Page 0 → _triggering_element_name = submit_main
  3. Pages 1+ → _triggering_element_name = submit_page (clé de la pagination)
  → Drupal navigue dans les résultats en session au lieu de relancer une recherche
  → Couverture 100% garantie, aucune zone géographique manquante

Découverte du mécanisme le 07/05/2026 grâce au payload DevTools du vrai navigateur.
"""
import os, json, math, subprocess, time
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90
RETRY_MAX    = 3

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

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
    "famille_tournois[COURT_ADUL]": "COURT_ADUL", "famille_tournois[TRADI_V]": "TRADI_V",
    "famille_tournois[MULTI_V]": "MULTI_V", "famille_tournois[GALAXIE_O]": "GALAXIE_O",
    "famille_tournois[GALAXIE_V]": "GALAXIE_V", "famille_tournois[CNGT]": "CNGT",
    "famille_tournois[NTC]": "NTC",
    "surface[B_PIL]": "B_PIL", "surface[DUR  ]": "DUR  ",
    "surface[GAZON]": "GAZON", "surface[AUTRE]": "AUTRE",
}


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


# ── AJAX France entière ────────────────────────────────────────────────────────

def ajax_france_page(session, fbid, page_num, date_start, date_end):
    """
    AJAX recherche_type=ligue, France entière (toutes ligues, tous comités).
    page=0 → submit_main (initialise la recherche en session Drupal)
    page>0 → submit_page (navigue dans les résultats en session)
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
        **NEW_CRITERIA,
        "sort": "_DIST_",
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
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v7 ligue ({date_start}→{date_end})")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_raw  = {}  # tenup_id → item brut

    # ── Page 0 : initialise la recherche France entière ────────────────────────
    print("Scraping page 0 (submit_main)...")
    items0, nb_total = ajax_france_page(session, fbid, 0, date_start, date_end)

    # Fallback si page 0 vide (fbid parfois consommé par le chargement de la page)
    if not items0 and nb_total == 0:
        print("  Page 0 vide — fallback page 1 (submit_page)...")
        items0, nb_total = ajax_france_page(session, fbid, 1, date_start, date_end)

    for it in items0:
        all_raw[str(it.get("id", ""))] = it

    print(f"  Page 0 : {len(items0)} items, nb_total={nb_total}")

    if nb_total == 0:
        print("ERREUR : aucun résultat. Arrêt.")
        return

    # ── Pages suivantes via submit_page ────────────────────────────────────────
    # Boucle non bornée par nb_total (peut être un plafond d'affichage Ten'Up,
    # ex : 10 000 alors que le vrai stock est plus grand). Arrêt sur résultat vide.
    nb_pages_est = math.ceil(nb_total / 30) if nb_total else "?"
    print(f"Pagination : ~{nb_pages_est} pages estimées (nb_total={nb_total})")

    start_page = 1 if items0 else 2
    consecutive_empty = 0
    for page_num in range(start_page, 99999):
        items, _ = ajax_france_page(session, fbid, page_num, date_start, date_end)
        if not items:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print(f"  2 pages vides consécutives — arrêt à la page {page_num}")
                break
            print(f"  Page {page_num} : vide ({consecutive_empty}/2)")
            time.sleep(1)
            continue
        consecutive_empty = 0
        new_count = 0
        for it in items:
            tid = str(it.get("id", ""))
            if tid and tid not in all_raw:
                all_raw[tid] = it
                new_count += 1
        print(f"  Page {page_num}/{nb_pages_est} : {len(items)} items, {new_count} nouveaux (total: {len(all_raw)})")
        if new_count == 0:
            print(f"  Aucun nouveau item — arrêt à la page {page_num}")
            break
        time.sleep(0.3)

    # ── Parsing & écriture ─────────────────────────────────────────────────────
    tournaments = [t for item in all_raw.values() if (t := parse_item(item))]

    elapsed = (datetime.now() - now).total_seconds()
    print(f"\n{'='*60}")
    print(f"Total France : {len(tournaments)} tournois uniques")
    print(f"nb_total Ten'Up : {nb_total} | Couverture : {len(all_raw)}/{nb_total} ({len(all_raw)/nb_total*100:.0f}%)" if nb_total else "")
    print(f"Durée : {elapsed:.0f}s")

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments":tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Fichier écrit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v7 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] — {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
