"""
Padel Alert — Scraper France v6 — par ligue FFT individuelle
Remplace l'approche 45 villes (angle mort en zones denses).
Architecture : Playwright pour session initiale + découverte codes ligue,
               requests pour scraping AJAX paginé.
Écrit data/tournaments.json + commit GitHub.

NOTES DE DÉVELOPPEMENT :
- v5 (villes) : 717 tournois — angle mort zones denses (Paris = 55+ pages)
- v6 (ligues) : approche par ligue individuelle, pagination complète
- ligue=ALL : pagination cassée côté Ten'Up → on itère sur chaque ligue
- comité : non spécifié = serveur retourne tous les comités (à confirmer via diag_ligue.py)
- Si nb_results=0 sur une ligue → code ligue probablement incorrect (relancer diag_ligue.py)
"""
import os, json, math, re, subprocess, time
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

TARGET_LIGUE_NAMES = [
    "AUVERGNE RHONE-ALPES",
    "BOURGOGNE FRANCHE COMTE",
    "BRETAGNE",
    "CENTRE VAL DE LOIRE",
    "CORSE",
    "GRAND EST",
    "GUADELOUPE ST MARTIN ST BARTH",
    "GUYANE",
    "HAUTS DE FRANCE",
    "ILE DE FRANCE",
    "MARTINIQUE",
    "NORMANDIE",
    "NOUVELLE AQUITAINE",
    "NOUVELLE CALEDONIE",
    "OCCITANIE",
    "PAYS DE LA LOIRE",
    "PROVENCE ALPES COTE D'AZUR",
    "REUNION - MAYOTTE",
]

ALL_CRITERIA = {
    "epreuve[DM]": "DM", "epreuve[DD]": "DD", "epreuve[DX]": "DX",
    "categorie_age[910]": "910", "categorie_age[1112]": "1112",
    "categorie_age[1314]": "1314", "categorie_age[1516]": "1516",
    "categorie_age[1718]": "1718", "categorie_age[200]": "200",
    "categorie_age[345]": "345", "categorie_age[355]": "355",
    "type[P]": "P", "type[CE]": "CE", "type[CEQ]": "CEQ",
    "categorie_tournoi[P25]": "P25", "categorie_tournoi[P50]": "P50",
    "categorie_tournoi[P100]": "P100", "categorie_tournoi[P250]": "P250",
    "categorie_tournoi[P500]": "P500", "categorie_tournoi[P1000]": "P1000",
    "categorie_tournoi[P1500]": "P1500", "categorie_tournoi[P2000]": "P2000",
}


def normalize(s):
    """Supprime accents + ponctuation, met en majuscules (fuzzy match)."""
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9 ]", " ", s.upper()).strip()


# ── Session Playwright ─────────────────────────────────────────────────────────

def get_session_playwright():
    """
    Ouvre Ten'Up, récupère fbid + cookies.
    Découvre aussi les options du select ligue (name + value) pour le matching.
    """
    print("Ouverture Ten'Up via Playwright...")
    ligue_options = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}

        if not fbid:
            raise RuntimeError("form_build_id introuvable — Ten'Up a changé sa structure")

        # Découverte options ligue
        # 1) Essai direct depuis le HTML initial
        ligue_options = _extract_ligue_options_js(page)

        # 2) Si vide, cliquer le radio "ligue" et réessayer
        if not ligue_options:
            _click_ligue_radio(page)
            ligue_options = _extract_ligue_options_js(page)

        # 3) Fallback BeautifulSoup sur le HTML brut
        if not ligue_options:
            html = page.content()
            ligue_options = _extract_ligue_options_html(html)

        browser.close()

    if not ligue_options:
        print("  WARN: impossible de récupérer les options ligue depuis Ten'Up")
    else:
        print(f"  {len(ligue_options)} ligues trouvées dans Ten'Up")

    print(f"Session OK — fbid: {fbid[:30]}...")
    return fbid, cookies, ligue_options


def _click_ligue_radio(page):
    """Tente de cliquer le radio 'ligue' sur le formulaire de recherche."""
    all_radios = page.evaluate("""
        () => Array.from(document.querySelectorAll('input[type="radio"]'))
               .map(r => ({name: r.name, value: r.value, id: r.id}))
    """)
    for r in all_radios:
        if "ligue" in (r.get("value", "") + r.get("id", "")).lower():
            try:
                page.click(f'input[name="{r["name"]}"][value="{r["value"]}"]', timeout=3000)
                page.wait_for_timeout(2500)
                print(f"  Cliqué radio ligue : name='{r['name']}' value='{r['value']}'")
                return
            except Exception as e:
                print(f"  Impossible de cliquer radio '{r['name']}'='{r['value']}': {e}")
    # Essai par texte
    for txt in ["Ligue", "Par ligue"]:
        try:
            page.click(f'text="{txt}"', timeout=2000)
            page.wait_for_timeout(2500)
            print(f"  Cliqué '{txt}' par texte")
            return
        except:
            pass
    print("  WARN: radio ligue non cliqué")


def _extract_ligue_options_js(page):
    """Extrait les options du premier select contenant 'ligue' dans name/id."""
    opts = page.evaluate("""
        () => {
            const sels = Array.from(document.querySelectorAll('select'));
            for (const s of sels) {
                if ((s.name || '').toLowerCase().includes('ligue') ||
                    (s.id   || '').toLowerCase().includes('ligue')) {
                    return Array.from(s.options)
                        .filter(o => o.value)
                        .map(o => ({v: o.value, t: o.text.trim()}));
                }
            }
            return [];
        }
    """)
    return opts or []


def _extract_ligue_options_html(html):
    """Fallback : BeautifulSoup sur le HTML brut."""
    soup = BeautifulSoup(html, "html.parser")
    for sel in soup.find_all("select"):
        if "ligue" in (sel.get("name", "") + sel.get("id", "")).lower():
            opts = []
            for opt in sel.find_all("option"):
                v = opt.get("value", "")
                t = opt.get_text(strip=True)
                if v and t:
                    opts.append({"v": v, "t": t})
            return opts
    return []


def match_ligues(ligue_options):
    """Associe TARGET_LIGUE_NAMES aux codes Ten'Up découverts."""
    matched = []
    norms = [(o, normalize(o.get("t", ""))) for o in ligue_options]

    for target in TARGET_LIGUE_NAMES:
        norm_t = normalize(target)
        # Exact match
        found = next((o for o, n in norms if n == norm_t), None)
        if not found:
            # Partial : target contenu dans ligue
            found = next((o for o, n in norms if norm_t in n), None)
        if not found:
            # Partial : ligue contenu dans target
            found = next((o for o, n in norms if n and n in norm_t), None)
        if found:
            matched.append({"name": target, "code": found["v"], "label": found["t"]})
            print(f"  ✓ {target} → {found['t']} (code={found['v']})")
        else:
            print(f"  ✗ {target} → NON TROUVÉ dans les options Ten'Up")
    return matched


# ── AJAX ───────────────────────────────────────────────────────────────────────

def make_session(cookies_dict):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE,
        "Referer": TENUP_SEARCH,
        "X-Requested-With": "XMLHttpRequest",
    })
    for name, val in cookies_dict.items():
        s.cookies.set(name, val)
    return s


def ajax_page(session, fbid, ligue_code, date_start, date_end, page_num):
    """Un appel AJAX : ligue_code, page_num. Retourne (items, nb_total)."""
    data = {
        "recherche_type": "ligue",
        "ligue": ligue_code,
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]": date_end,
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
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
            # Commande non trouvée (pas d'erreur HTTP mais réponse inattendue)
            cmds = [c.get("command") for c in resp.json() if isinstance(c, dict)]
            print(f"    WARN page {page_num} attempt {attempt}: commandes reçues={cmds}")
            return [], 0
        except Exception as e:
            print(f"    Erreur page {page_num} attempt {attempt}: {e}")
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
    return [], 0


def scrape_ligue(session, fbid, ligue_code, ligue_label, date_start, date_end):
    """Scrape TOUTES les pages d'une ligue. Retourne (raw_items_dict, nb_total)."""
    print(f"\n  ► {ligue_label} (code={ligue_code})")
    all_items = {}  # id → item

    items_p0, nb_total = ajax_page(session, fbid, ligue_code, date_start, date_end, 0)
    for it in items_p0:
        all_items[str(it.get("id", ""))] = it

    if nb_total == 0:
        print(f"    0 résultats — code ligue peut-être incorrect ?")
        print(f"    → Relancer diag_ligue.py pour vérifier les codes.")
        return list(all_items.values()), 0

    nb_pages = math.ceil(nb_total / 30)
    print(f"    {nb_total} résultats, {nb_pages} pages à scraper")

    consecutive_empty = 0
    for page_num in range(1, nb_pages):
        items, _ = ajax_page(session, fbid, ligue_code, date_start, date_end, page_num)
        if not items:
            consecutive_empty += 1
            print(f"    Page {page_num} vide (#{consecutive_empty})")
            if consecutive_empty >= 3:
                print(f"    3 pages vides consécutives — arrêt pagination")
                break
            continue
        consecutive_empty = 0
        for it in items:
            all_items[str(it.get("id", ""))] = it
        if page_num % 20 == 0 or page_num == nb_pages - 1:
            print(f"    Page {page_num}/{nb_pages - 1} — {len(all_items)} tournois collectés")
        time.sleep(0.3)

    print(f"    → {len(all_items)} tournois uniques")
    return list(all_items.values()), nb_total


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_item(item, ligue_label):
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
        "ligues":           [ligue_label],
        "link":             f"{TENUP_BASE}/tournoi/{tid}",
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now        = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Padel Alert — Scraper v6 — par ligue FFT ({date_start}→{date_end})")

    # Session + découverte
    fbid, cookies, ligue_options = get_session_playwright()
    session = make_session(cookies)

    # Matching ligues cibles
    print("\n=== Matching ligues ===")
    if ligue_options:
        matched = match_ligues(ligue_options)
    else:
        print("WARN: Options ligue non découvertes. Scraper ne peut pas continuer.")
        print("→ Lancer diag_ligue.py (workflow_dispatch) pour diagnostic complet.")
        matched = []

    matched_ok = [m for m in matched if m.get("code")]
    print(f"\n{len(matched_ok)}/{len(TARGET_LIGUE_NAMES)} ligues matchées")

    if not matched_ok:
        print("ERREUR : aucune ligue matchée. Arrêt.")
        raise SystemExit(1)

    # Scraping par ligue
    all_tournaments = {}
    stats = {}

    for ligue in matched_ok:
        raw_items, nb_total = scrape_ligue(
            session, fbid, ligue["code"], ligue["label"], date_start, date_end
        )
        stats[ligue["name"]] = {
            "code": ligue["code"],
            "label": ligue["label"],
            "nb_total_tenup": nb_total,
            "scraped": len(raw_items),
        }
        for item in raw_items:
            parsed = parse_item(item, ligue["label"])
            if not parsed:
                continue
            tid = parsed["tenup_id"]
            if tid in all_tournaments:
                if ligue["label"] not in all_tournaments[tid]["ligues"]:
                    all_tournaments[tid]["ligues"].append(ligue["label"])
            else:
                all_tournaments[tid] = parsed

    tournaments = list(all_tournaments.values())

    print(f"\n{'=' * 60}")
    print(f"Total France : {len(tournaments)} tournois uniques")
    print("\nDétail par ligue :")
    for name, s in stats.items():
        delta = s["scraped"] - s["nb_total_tenup"]
        flag = " ⚠ INCOMPLET" if s["scraped"] < s["nb_total_tenup"] - 5 else ""
        print(f"  {name}: {s['nb_total_tenup']} Ten'Up → {s['scraped']} scrapés{flag}")

    # Write JSON
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
