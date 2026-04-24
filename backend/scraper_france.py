"""
Padel Alert — Scraper France entière (v2)
Recherche ligue=ALL via Playwright (interception requête AJAX réelle).
Écrit data/tournaments.json + commit GitHub.
WordPress pull ce fichier via WP-Cron.
"""
import os
import math
import json
import subprocess
import requests
import urllib.parse
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90   # 3 mois à venir

JOURS = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]


# ── Session + interception paramètres AJAX réels ──────────────────────────────

def get_session_and_params(date_start, date_end):
    """
    Ouvre Ten'Up via Playwright, soumet la recherche ligue=ALL,
    intercepte la vraie requête AJAX pour capturer les paramètres exacts.
    Retourne: (cookies_dict, base_params, first_items, nb_total)
    """
    captured_bodies  = []
    captured_results = []

    def on_request(req):
        if TENUP_AJAX in req.url and req.method == "POST":
            captured_bodies.append(req.post_data or "")

    def on_response(resp):
        if TENUP_AJAX in resp.url and resp.status == 200:
            try:
                captured_results.append(resp.json())
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.on("request",  on_request)
        page.on("response", on_response)

        print("Ouverture Ten'Up via Playwright...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Basculer en mode "par ligue" si le formulaire le permet
        ligue_radio = page.query_selector("input[value='ligue'][name='recherche_type']")
        if ligue_radio:
            ligue_radio.click()
            page.wait_for_timeout(1500)
            print("Mode 'par ligue' sélectionné")
        else:
            print("Pas de radio 'ligue' — formulaire en mode par défaut")

        # Injecter les dates directement dans le DOM
        page.evaluate(f"""() => {{
            const s = document.querySelector('[name="date[start]"]');
            const e = document.querySelector('[name="date[end]"]');
            if (s) {{ s.value = '{date_start}'; s.dispatchEvent(new Event('change')); }}
            if (e) {{ e.value = '{date_end}'; e.dispatchEvent(new Event('change')); }}
        }}""")
        page.wait_for_timeout(500)

        # S'assurer que PADEL est sélectionné
        pratique = page.query_selector("input[name='pratique'][value='PADEL'], select[name='pratique']")
        if pratique:
            tag = pratique.evaluate("el => el.tagName")
            if tag == "SELECT":
                page.select_option("select[name='pratique']", "PADEL")
            else:
                if not pratique.is_checked():
                    pratique.click()

        # Soumettre le formulaire
        page.click("input[name='submit_main']")
        page.wait_for_timeout(8000)

        cookies = ctx.cookies()
        browser.close()

    cookies_dict = {c["name"]: c["value"] for c in cookies}

    # Extraire base_params depuis la requête interceptée
    base_params = {}
    for body in reversed(captured_bodies):
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        if "form_id" in parsed:
            for k, v in parsed.items():
                if k not in ("form_build_id", "page"):
                    base_params[k] = v[0] if len(v) == 1 else v
            break

    if not base_params:
        raise RuntimeError("Aucun paramètre AJAX intercepté — formulaire non soumis")

    # Extraire les premiers résultats
    first_items = []
    nb_total    = 0
    for result_data in reversed(captured_results):
        for cmd in result_data:
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res       = cmd.get("results", {})
                first_items = res.get("items", [])
                nb_total  = res.get("nb_results", 0)
                break
        if nb_total > 0 or first_items:
            break

    print(f"Session OK — {nb_total} tournois détectés sur la période")
    return cookies_dict, base_params, first_items, nb_total


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
    el   = soup.find("input", {"name": "form_build_id"})
    if el:
        return el["value"]
    import re
    m = re.search(r'form_build_id[^>]+value="([^"]+)"', resp.text)
    if m:
        return m.group(1)
    raise RuntimeError("Impossible de rafraîchir form_build_id")


# ── Pagination ────────────────────────────────────────────────────────────────

def fetch_all_pages(session, base_params, first_items, nb_total):
    """Pagine tous les résultats et retourne tous les items."""
    all_items = {str(item.get("id")): item for item in first_items}
    nb_pages  = math.ceil(nb_total / 30) if nb_total > 0 else 1
    print(f"Pagination : {nb_pages} page(s) à récupérer...")

    start_time = datetime.now()
    for page_num in range(1, nb_pages):
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > 1200:  # 20 min max de pagination
            print(f"⚠️  Limite de temps atteinte à la page {page_num}/{nb_pages}")
            break

        fbid = refresh_fbid(session)
        data = {**base_params, "form_build_id": fbid, "page": str(page_num)}
        try:
            resp = session.post(TENUP_AJAX, data=data, timeout=30)
            resp.raise_for_status()
            for cmd in resp.json():
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    items = cmd.get("results", {}).get("items", [])
                    if not items:
                        print(f"  Page {page_num} vide — arrêt")
                        return list(all_items.values())
                    for item in items:
                        all_items[str(item.get("id"))] = item
                    break
        except Exception as e:
            print(f"  Erreur page {page_num}: {e}")

        if page_num % 20 == 0:
            print(f"  Page {page_num}/{nb_pages} — {len(all_items)} tournois ({elapsed:.0f}s)")

    return list(all_items.values())


# ── Parsing ───────────────────────────────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraping France (ligue=ALL, {date_start} → {date_end})")

    cookies_dict, base_params, first_items, nb_total = get_session_and_params(date_start, date_end)
    session = make_session(cookies_dict)

    raw_items = fetch_all_pages(session, base_params, first_items, nb_total)

    tournaments = [t for item in raw_items if (t := parse_item(item))]
    print(f"\nTotal : {len(tournaments)} tournois uniques parsés")

    # Écriture dans data/tournaments.json + commit
    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":      len(tournaments),
        "tournaments": tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Fichier écrit : {OUTPUT_FILE}")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if result.returncode != 0:
        msg = f"Scraping France [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] — {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement — pas de commit.")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
