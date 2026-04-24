"""
Padel Alert — Scraper France entière (v3)
Recherche ligue=ALL via AJAX manuel (même endpoint que ville, params ligue).
Écrit data/tournaments.json + commit GitHub.
WordPress pull ce fichier via WP-Cron.
"""
import os
import math
import json
import subprocess
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
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


# ── Session (Playwright — juste pour les cookies + form_build_id) ─────────────

def get_session():
    """
    Ouvre Ten'Up, bascule en mode ligue via click forcé (radio caché),
    attend le rechargement AJAX du formulaire, récupère le form_build_id
    spécifique au mode ligue + les cookies.
    """
    print("Ouverture session Ten'Up via Playwright...")
    ligue_fbid    = None
    ligue_fields  = {}  # champs supplémentaires capturés depuis l'AJAX de reload

    ajax_responses = []

    def on_response(resp):
        if TENUP_AJAX in resp.url and resp.status == 200:
            try:
                ajax_responses.append(resp.json())
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.on("response", on_response)

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Cliquer le radio "ligue" avec force=True (bypass hidden)
        ligue_radio = page.query_selector("input[value='ligue'][name='recherche_type']")
        if ligue_radio:
            ligue_radio.click(force=True)
            page.wait_for_timeout(4000)   # attendre le reload AJAX du formulaire
            print("Radio 'ligue' cliqué (force=True) — attente AJAX reload...")
        else:
            print("Radio 'ligue' introuvable")

        # form_build_id après reload du formulaire
        ligue_fbid = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        html_after = page.content()
        cookies    = ctx.cookies()
        browser.close()

    if not ligue_fbid:
        raise RuntimeError("form_build_id introuvable après switch ligue")

    print(f"Session ligue-mode OK — fbid: {ligue_fbid[:30]}...")
    return ligue_fbid, {c["name"]: c["value"] for c in cookies}


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
    m = re.search(r'form_build_id[^>]+value="([^"]+)"', resp.text)
    if m:
        return m.group(1)
    raise RuntimeError("Impossible de rafraîchir form_build_id")


# ── Recherche ligue=ALL ───────────────────────────────────────────────────────

def build_ligue_params(date_start, date_end):
    """
    Params AJAX pour recherche ligue=ALL — SANS ALL_CRITERIA.
    En mode ligue, les checkboxes epreuve/categorie_age/type/categorie_tournoi
    n'existent pas dans le formulaire → envoyer = "choix interdit" Drupal.
    Sans filtre, Ten'Up retourne tous les tournois padel (toutes catégories).
    Le filtre par critères se fait au moment du matching dans WordPress.
    """
    return {
        "recherche_type": "ligue",
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
    }


def search_page(session, fbid, base_params, page_num):
    """Exécute une page de recherche avec le fbid fourni. Retourne (items, nb_total, new_fbid)."""
    data = {**base_params, "form_build_id": fbid, "page": str(page_num)}
    resp = session.post(TENUP_AJAX, data=data, timeout=45)
    resp.raise_for_status()
    cmds = resp.json()

    # Extraire un fbid rafraîchi depuis la réponse si disponible
    new_fbid = fbid
    for cmd in cmds:
        if isinstance(cmd, dict) and cmd.get("command") == "insert":
            snippet = cmd.get("data", "")
            m = re.search(r'name="form_build_id"[^>]*value="([^"]+)"', snippet)
            if m:
                new_fbid = m.group(1)
                break

    for cmd in cmds:
        if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
            results = cmd.get("results", {})
            return results.get("items", []), results.get("nb_results", 0), new_fbid

    if page_num == 0:
        cmds_names = [c.get("command") for c in cmds if isinstance(c, dict)]
        for cmd in cmds:
            if isinstance(cmd, dict) and cmd.get("command") == "insert":
                d = cmd.get("data","")
                if "interdit" in d or "erreur" in d.lower():
                    print(f"[p0-err] {d[:200]}")
        print(f"[p0] commandes={cmds_names} → 0 résultats")
    return [], 0, new_fbid


def playwright_full_session(date_start, date_end):
    """
    Utilise Playwright click() natif (vraie simulation souris) pour déclencher l'AJAX.
    Retourne (cookies, items_page0, nb_total, params_page0).
    """
    captured_requests  = []
    captured_responses = []

    def on_request(req):
        if TENUP_AJAX in req.url and req.method == "POST":
            captured_requests.append({"body": req.post_data or "", "url": req.url})

    def on_response(resp):
        if TENUP_AJAX in resp.url and resp.status == 200:
            try:
                captured_responses.append(resp.json())
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

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 1. Cliquer le radio "ligue" — click() natif
        ligue_radio = page.locator("input[value='ligue'][name='recherche_type']")
        ligue_radio.click(force=True)
        page.wait_for_timeout(2000)

        # 2. Remplir les dates en JS (les champs peuvent être masqués)
        page.evaluate(f"""() => {{
            const ds = document.querySelector('[name="date[start]"]');
            const de = document.querySelector('[name="date[end]"]');
            if (ds) {{ ds.value = '{date_start}'; }}
            if (de) {{ de.value = '{date_end}'; }}
        }}""")
        page.wait_for_timeout(500)

        # 3. Cliquer "Rechercher" avec click() natif
        submit = page.locator("input[name='submit_main']")
        n_before = len(captured_requests)
        submit.click(force=True)
        page.wait_for_timeout(8000)

        print(f"[PW] Après click submit : {len(captured_requests) - n_before} nouvelles requêtes AJAX")

        # 4. Si résultats OK, chercher et cliquer "page 2"
        n_before2 = len(captured_requests)
        next_locator = page.locator("li.pager-next a, .pager__item--next a, [class*='next'] a").first
        if next_locator.count() > 0:
            next_locator.click()
            page.wait_for_timeout(5000)
            print(f"[PW] Après click next : {len(captured_requests) - n_before2} nouvelles requêtes AJAX")
        else:
            print("[PW] Aucun bouton 'next' trouvé dans le DOM")
            # Screenshot du DOM pour debug
            pager_html = page.evaluate("() => document.querySelector('[class*=\"pager\"]')?.outerHTML || 'no pager'")
            print(f"[PW] Pager HTML: {str(pager_html)[:300]}")

        cookies = ctx.cookies()
        browser.close()

    # Analyser requêtes interceptées
    print(f"\n[PW] Total requêtes AJAX interceptées: {len(captured_requests)}")
    for i, req in enumerate(captured_requests):
        import urllib.parse
        parsed = urllib.parse.parse_qs(req["body"], keep_blank_values=True)
        interesting = {k: v[0] for k, v in parsed.items()
                       if k in ("page","sort","recherche_type","_triggering_element_name","_triggering_element_value","pratique")}
        print(f"  Req {i}: {interesting}")

    # Extraire items page 0 des réponses capturées
    items_p0 = []
    nb_total  = 0
    for resp_data in captured_responses:
        for cmd in resp_data:
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                r = cmd.get("results", {})
                if r.get("nb_results", 0) > nb_total:
                    nb_total  = r["nb_results"]
                    items_p0  = r.get("items", [])

    print(f"[PW] Via Playwright click: {nb_total} résultats totaux, {len(items_p0)} items capturés")

    return {c["name"]: c["value"] for c in cookies}, items_p0, nb_total, captured_requests


def intercept_next_page_click(date_start, date_end):
    """
    Utilise Playwright pour soumettre la recherche ligue=ALL, intercepte page 0,
    clique sur "page suivante", et intercepte les paramètres EXACTS de cette requête.
    Retourne (cookies, params_page0, params_page1) pour comparer.
    """
    requests_intercepted = []

    def on_request(req):
        if TENUP_AJAX in req.url and req.method == "POST":
            requests_intercepted.append({
                "body": req.post_data or "",
                "time": datetime.now().isoformat(),
            })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.on("request", on_request)

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Cliquer ligue radio
        ligue_radio = page.query_selector("input[value='ligue'][name='recherche_type']")
        if ligue_radio:
            ligue_radio.click(force=True)
            page.wait_for_timeout(2000)

        # Remplir dates via JS
        page.evaluate(f"""() => {{
            const ds = document.querySelector('[name="date[start]"]');
            const de = document.querySelector('[name="date[end]"]');
            if (ds) {{ ds.value = '{date_start}'; ds.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            if (de) {{ de.value = '{date_end}'; de.dispatchEvent(new Event('change', {{bubbles:true}})); }}
        }}""")

        # Soumettre via JS
        page.evaluate("() => { document.querySelector('input[name=\"submit_main\"]')?.click(); }")
        page.wait_for_timeout(5000)

        n_before_click = len(requests_intercepted)
        print(f"[INTERCEPT] Requêtes après submit: {n_before_click}")

        # Cliquer sur "page suivante" (li.pager-next > a ou bouton de pagination)
        next_btn = page.query_selector(".pager-next a, .pager__item--next a, [data-drupal-pager-page] a, li.next a")
        if next_btn:
            next_btn.click()
            page.wait_for_timeout(3000)
            print(f"[INTERCEPT] Bouton 'next' cliqué — nouvelles requêtes: {len(requests_intercepted) - n_before_click}")
        else:
            # Essayer via JS : chercher un lien avec page=1
            clicked = page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="page="], button, [role="button"]');
                for (const el of links) {
                    const txt = el.textContent.trim();
                    if (txt === '2' || txt === 'next' || txt === '›' || txt === '>') {
                        el.click(); return txt;
                    }
                }
                return null;
            }""")
            if clicked:
                page.wait_for_timeout(3000)
                print(f"[INTERCEPT] Cliqué via JS '{clicked}' — nouvelles requêtes: {len(requests_intercepted) - n_before_click}")
            else:
                print("[INTERCEPT] Aucun bouton 'next' trouvé")

        cookies = ctx.cookies()
        browser.close()

    # Analyser les requêtes
    print(f"\n[INTERCEPT] Total requêtes capturées: {len(requests_intercepted)}")
    for i, req in enumerate(requests_intercepted):
        import urllib.parse
        parsed = urllib.parse.parse_qs(req["body"], keep_blank_values=True)
        interesting = {k: v[0] for k, v in parsed.items() if k in ("page", "sort", "recherche_type", "_triggering_element_name", "_triggering_element_value", "form_id")}
        print(f"  Req {i}: page={interesting.get('page','?')} trigger={interesting.get('_triggering_element_name','?')} sort={interesting.get('sort','?')}")

    return {c["name"]: c["value"] for c in cookies}


def fetch_all(session, fbid, base_params):
    """Pagine toute la recherche avec le fbid ligue-mode. Retourne tous les items."""
    all_items = {}
    start_time = datetime.now()
    current_fbid = fbid

    # Page 0
    items, nb_total, current_fbid = search_page(session, current_fbid, base_params, 0)
    print(f"Page 0 AJAX : {nb_total} résultats totaux, {len(items)} items reçus")
    for item in items:
        all_items[str(item.get("id"))] = item

    nb_pages = math.ceil(nb_total / 30) if nb_total > 0 else 1
    if nb_pages > 1:
        print(f"Pagination : {nb_pages} pages à traiter...")

    for page_num in range(1, min(nb_pages, 5)):  # Test limité à 5 pages pour le diag
        elapsed = (datetime.now() - start_time).total_seconds()
        try:
            items, _, current_fbid = search_page(session, current_fbid, base_params, page_num)
            n_new = sum(1 for it in items if str(it.get("id")) not in all_items)
            print(f"  Page {page_num} AJAX : {len(items)} items reçus, {n_new} nouveaux uniques")
            for item in items:
                all_items[str(item.get("id"))] = item
        except Exception as e:
            print(f"  Erreur page {page_num}: {e}")

    return list(all_items.values())


# ── Parsing ───────────────────────────────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Scraping France ligue=ALL ({date_start} → {date_end})")

    form_build_id, cookies = get_session()
    session     = make_session(cookies)

    base_params = build_ligue_params(date_start, date_end)
    # Test Playwright click() natif
    print("\n--- PLAYWRIGHT CLICK NATIF ---")
    playwright_full_session(date_start, date_end)
    print("--- FIN PLAYWRIGHT ---\n")

    raw_items   = fetch_all(session, form_build_id, base_params)
    tournaments = [t for item in raw_items if (t := parse_item(item))]
    print(f"\nTotal : {len(tournaments)} tournois uniques")

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
        # Pull --rebase avant push pour gérer les commits automatiques parallèles
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")
    else:
        print("Aucun changement.")

    # Supprimer le fichier diagnostic s'il existe
    import os as _os
    for diag in ["backend/diag_form.py"]:
        if _os.path.exists(diag):
            _os.remove(diag)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Terminé.")


if __name__ == "__main__":
    main()
