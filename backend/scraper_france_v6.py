"""
Padel Alert — Scraper France v6 — par ligue FFT (cbrappel[])
Architecture : Playwright session initiale → AJAX paginé par ligue.

Paramètres clés découverts via diagnostics (06/05/2026) :
- sort="dateDebut asc"  ← CRITIQUE (ancienne valeur "_DATE_" était invalide)
- recherche_type="ligue" + cbrappel[]=ID  (IDs 50-67 découverts dans HTML)
- Pas de ALL_CRITERIA (anciens codes invalides depuis redesign Ten'Up)
- pratique="PADEL" suffit pour tous les tournois padel

Mapping ligue → ID cbrappel :
  50=ARA 51=BFC 52=BRE 53=CVL 54=COR 55=GE 56=HDF 57=IDF
  58=NOR 59=NA  60=OCC 61=PDL 62=PACA 63=GUA 64=GUY 65=MAR 66=NC 67=REU
"""
import os, json, math, subprocess, time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90
RETRY_MAX    = 3

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Mapping ligue → ID cbrappel (découvert dans HTML Ten'Up le 06/05/2026)
LIGUES = [
    ("50", "AUVERGNE RHONE-ALPES"),
    ("51", "BOURGOGNE FRANCHE COMTE"),
    ("52", "BRETAGNE"),
    ("53", "CENTRE VAL DE LOIRE"),
    ("54", "CORSE"),
    ("55", "GRAND EST"),
    ("63", "GUADELOUPE ST MARTIN ST BARTH"),
    ("64", "GUYANE"),
    ("56", "HAUTS DE FRANCE"),
    ("57", "ILE DE FRANCE"),
    ("65", "MARTINIQUE"),
    ("58", "NORMANDIE"),
    ("59", "NOUVELLE AQUITAINE"),
    ("66", "NOUVELLE CALEDONIE"),
    ("60", "OCCITANIE"),
    ("61", "PAYS DE LA LOIRE"),
    ("62", "PROVENCE ALPES COTE D'AZUR"),
    ("67", "REUNION - MAYOTTE"),
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


# ── AJAX ───────────────────────────────────────────────────────────────────────

def ajax_page(session, fbid, ligue_id, date_start, date_end, page_num):
    """Un appel AJAX ligue. Retourne (items, nb_total)."""
    data = {
        "recherche_type": "ligue",
        "cbrappel[]": ligue_id,
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        "sort": "dateDebut asc",          # ← valeur valide découverte le 06/05/2026
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
            # Commande absente → log les commandes reçues
            cmds = [c.get("command") for c in resp.json() if isinstance(c, dict)]
            print(f"    WARN page {page_num} attempt {attempt}: commandes={cmds}")
            return [], 0
        except Exception as e:
            print(f"    Erreur page {page_num} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
    return [], 0


def scrape_ligue(session, fbid, ligue_id, ligue_name, date_start, date_end):
    """Scrape toutes les pages d'une ligue. Retourne liste raw items."""
    print(f"\n  ► {ligue_name} (id={ligue_id})")
    all_items = {}

    items0, nb_total = ajax_page(session, fbid, ligue_id, date_start, date_end, 0)
    for it in items0:
        all_items[str(it.get("id", ""))] = it

    if nb_total == 0:
        print(f"    0 résultats — ligue vide ou ID invalide")
        return list(all_items.values()), 0

    nb_pages = math.ceil(nb_total / 30)
    print(f"    {nb_total} résultats annoncés → {nb_pages} pages")

    empty_streak = 0
    for page_num in range(1, nb_pages):
        items, _ = ajax_page(session, fbid, ligue_id, date_start, date_end, page_num)
        if not items:
            empty_streak += 1
            if empty_streak >= 3:
                print(f"    3 pages vides consécutives — arrêt")
                break
            continue
        empty_streak = 0
        for it in items:
            all_items[str(it.get("id", ""))] = it
        if page_num % 25 == 0 or page_num == nb_pages - 1:
            print(f"    page {page_num}/{nb_pages - 1} — {len(all_items)} collectés")
        time.sleep(0.25)

    print(f"    → {len(all_items)} uniques")
    return list(all_items.values()), nb_total


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_item(item, ligue_name):
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
        "ligues":           [ligue_name],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v6 — {len(LIGUES)} ligues ({date_start}→{date_end})")

    fbid, cookies = get_session()
    session = make_session(cookies)

    all_tournaments = {}
    stats = {}

    for ligue_id, ligue_name in LIGUES:
        raw_items, nb_total = scrape_ligue(session, fbid, ligue_id, ligue_name, date_start, date_end)
        stats[ligue_name] = {"id": ligue_id, "nb_total_tenup": nb_total, "scraped": len(raw_items)}

        for item in raw_items:
            parsed = parse_item(item, ligue_name)
            if not parsed:
                continue
            tid = parsed["tenup_id"]
            if tid in all_tournaments:
                if ligue_name not in all_tournaments[tid]["ligues"]:
                    all_tournaments[tid]["ligues"].append(ligue_name)
            else:
                all_tournaments[tid] = parsed

    tournaments = list(all_tournaments.values())

    print(f"\n{'='*60}")
    print(f"Total France : {len(tournaments)} tournois uniques")
    print("\nDétail par ligue :")
    for name, s in stats.items():
        print(f"  {name}: {s['nb_total_tenup']} annoncés → {s['scraped']} scrapés")

    # Écrire JSON
    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":       len(tournaments),
        "tournaments": tournaments,
        "stats":       stats,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier écrit : {OUTPUT_FILE}")

    # Git commit + push
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
