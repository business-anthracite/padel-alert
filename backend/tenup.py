"""
Scraper Ten'Up — gestion de session et requêtes AJAX.
Refactorisé pour supporter des critères dynamiques par alerte.
"""
import math
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from config import SEARCH_DATE_HORIZON_DAYS
from criteria import build_tenup_criteria
from geo import city_to_tenup_params


TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


# ── Session ────────────────────────────────────────────────────────────────────

def get_session() -> tuple[str, dict]:
    """
    Ouvre Ten'Up avec Playwright pour récupérer form_build_id + cookies.
    À appeler une seule fois par exécution du cron.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        form_build_id = page.evaluate("""
            () => {
                const el = document.querySelector('input[name="form_build_id"]');
                return el ? el.value : null;
            }
        """)
        cookies = ctx.cookies()
        browser.close()

    if not form_build_id:
        raise RuntimeError("form_build_id introuvable sur Ten'Up")

    return form_build_id, {c["name"]: c["value"] for c in cookies}


def make_session(cookies_dict: dict) -> requests.Session:
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


def refresh_form_build_id(session: requests.Session) -> str:
    resp = session.get(TENUP_SEARCH, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    field = soup.find("input", {"name": "form_build_id"})
    if field:
        return field["value"]
    import re
    m = re.search(r'form_build_id[^>]+value="([^"]+)"', resp.text)
    if m:
        return m.group(1)
    raise RuntimeError("Impossible de rafraîchir form_build_id")


# ── Recherche ──────────────────────────────────────────────────────────────────

def _search_page(session: requests.Session, base_params: dict, page: int) -> tuple[list, int]:
    """Exécute une page de recherche AJAX. Retourne (items, nb_total)."""
    fbid = refresh_form_build_id(session)
    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=SEARCH_DATE_HORIZON_DAYS)).strftime("%d/%m/%y")

    data = {
        **base_params,
        "date[start]":              date_start,
        "date[end]":                date_end,
        "page":                     str(page),
        "sort":                     "_DIST_",
        "form_build_id":            fbid,
        "form_id":                  "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value":"Rechercher",
    }

    resp = session.post(TENUP_AJAX, data=data, timeout=30)
    resp.raise_for_status()

    for cmd in resp.json():
        if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
            results = cmd.get("results", {})
            return results.get("items", []), results.get("nb_results", 0)

    return [], 0


def fetch_tournaments_for_alert(session: requests.Session, alert: dict) -> list[dict]:
    """
    Récupère tous les tournois correspondant aux critères d'une alerte,
    filtre par distance GPS réelle, et retourne les données parsées.
    """
    location_params  = city_to_tenup_params(alert)
    criteria_params  = build_tenup_criteria(alert)
    base_params      = {**location_params, **criteria_params}

    all_items: list = []
    seen_ids: set   = set()
    page            = 0
    nb_pages        = 1

    while page < nb_pages:
        items, nb_total = _search_page(session, base_params, page)
        nb_pages = math.ceil(nb_total / 30) if nb_total > 0 else 1

        new_items = [it for it in items if it.get("id") not in seen_ids]
        if page > 0 and not new_items:
            break  # l'API boucle, on arrête

        for it in new_items:
            seen_ids.add(it.get("id"))
        all_items.extend(new_items)
        page += 1

    return _parse_and_filter(all_items, alert)


# ── Parsing & filtrage GPS ─────────────────────────────────────────────────────

def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _parse_and_filter(items: list, alert: dict) -> list[dict]:
    result  = []
    centre_lat = float(alert["lat"])
    centre_lng = float(alert["lng"])
    radius_km  = float(alert["radius_km"])

    for item in items:
        tid = str(item.get("id", ""))
        if not tid:
            continue

        installation = item.get("installation", {})
        inst_lat = installation.get("lat")
        inst_lng = installation.get("lng")

        try:
            lat_f = float(inst_lat) if inst_lat not in (None, "", "0", 0, 0.0) else None
            lng_f = float(inst_lng) if inst_lng not in (None, "", "0", 0, 0.0) else None
            if lat_f is not None and lng_f is not None:
                dist_km = _haversine(centre_lat, centre_lng, lat_f, lng_f)
                if dist_km > radius_km:
                    continue
                distance_str = f"{dist_km:.1f} km"
            else:
                distance_str = ""
        except (ValueError, TypeError):
            distance_str = ""

        date_debut_raw = item.get("dateDebut")
        date_debut     = date_debut_raw.get("date", "") if isinstance(date_debut_raw, dict) else ""
        date_fin_raw   = item.get("dateFin")
        date_fin       = date_fin_raw.get("date", "") if isinstance(date_fin_raw, dict) else ""

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

        epreuves = item.get("epreuves", [])
        cats = sorted({e.get("typeEpreuve", {}).get("code", "") for e in epreuves if e.get("typeEpreuve", {}).get("code")})

        ville   = installation.get("ville", item.get("villeEngagement", ""))
        cp      = installation.get("codePostal", item.get("codePostalEngagement", ""))
        adresse = installation.get("adresse2", item.get("adresse2Engagement", ""))

        result.append({
            "id":           tid,
            "nom":          item.get("libelle", "Tournoi"),
            "club":         item.get("nomClub", ""),
            "adresse":      f"{adresse}, {cp} {ville}".strip(", "),
            "ville":        ville,
            "distance":     distance_str,
            "date":         date_str,
            "date_raw":     date_debut[:10] if date_debut else "9999-12-31",
            "categories":   ", ".join(cats),
            "link":         f"{TENUP_BASE}/tournoi/{tid}",
            "detected_at":  datetime.now().isoformat(),
        })

    result.sort(key=lambda t: t["date_raw"])
    return result
