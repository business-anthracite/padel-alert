"""
Padel Alert — Scraper France v6 — fenêtres 1-jour

Découvertes diagnostics 06-07/05/2026 :
- Ten'Up a redesigné son formulaire : nouveaux critères famille_tournois[], categorie_age[], etc.
- Anciens critères (P25/P50, type[P], categorie_age[910]) → "Un choix interdit"
- sort="dateDebut asc" valide (vs "_DATE_" invalide)
- La pagination est cassée avec les nouveaux critères (pages 1,2,3... = même 30 items)
- Solution : fenêtres de 1 jour → ~12 tournois/jour, pas besoin de pagination
- 90 jours × 0.15s = ~15 secondes de scraping
"""
import os, json, subprocess, time
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

# Nouveaux critères Ten'Up (redesign entre avril et mai 2026)
# Remplacent les anciens P25/P50/type[P]/categorie_age[910] qui causaient "Un choix interdit"
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


# ── AJAX ───────────────────────────────────────────────────────────────────────

def ajax_day(session, fbid, date_day):
    """AJAX pour un jour précis. Retourne (items, nb_total).
    Stratégie fenêtre 1-jour : contourne la pagination cassée avec les nouveaux critères.
    Avec ~12 tournois/jour en moyenne, on reste sous le seuil de 30/page.
    """
    data = {
        "recherche_type": "ligue",
        "cbrappel[]": "57",          # requis pour la session (filtre non appliqué côté serveur)
        "pratique": "PADEL",
        "date[start]": date_day,
        "date[end]":   date_day,
        "sort": "dateDebut asc",
        **NEW_CRITERIA,
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
            print(f"  Erreur jour {date_day} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
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
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v6 fenêtres 1-jour ({HORIZON_DAYS} jours)")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_items = {}
    overflow_days = []  # jours avec 30 items (possiblement tronqués)

    for day_offset in range(HORIZON_DAYS):
        date_day = (now + timedelta(days=day_offset)).strftime("%d/%m/%y")
        items, nb = ajax_day(session, fbid, date_day)
        for it in items:
            all_items[str(it.get("id", ""))] = it
        if nb >= 30:
            overflow_days.append({"date": date_day, "nb": nb})
        if day_offset % 15 == 0 and day_offset > 0:
            elapsed = (datetime.now() - now).total_seconds()
            print(f"  Jour {day_offset}/{HORIZON_DAYS} — {len(all_items)} collectés ({elapsed:.0f}s)")
        time.sleep(0.15)

    if overflow_days:
        print(f"\nATTENTION : {len(overflow_days)} jours avec 30+ résultats (pagination non tentée) :")
        for d in overflow_days:
            print(f"  {d['date']} : nb={d['nb']}")

    tournaments = [t for item in all_items.values() if (t := parse_item(item))]
    elapsed_total = (datetime.now() - now).total_seconds()

    print(f"\n{'='*60}")
    print(f"Total : {len(tournaments)} tournois uniques en {elapsed_total:.0f}s")
    print(f"({HORIZON_DAYS} fenêtres 1-jour, {len(overflow_days)} jours avec overflow potentiel)")

    # Écrire JSON
    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":       len(tournaments),
        "tournaments": tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Fichier écrit : {OUTPUT_FILE}")

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
