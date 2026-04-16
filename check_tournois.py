import json
import os
import smtplib
import re
import math
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

# ── Configuration ──────────────────────────────────────────────────────────────
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = "baptiste.chable@gmail.com"
KNOWN_TOURNAMENTS_FILE = "known_tournaments.json"

# Centre de recherche et rayon maximum
CENTRE_LAT = 47.478419   # Angers
CENTRE_LNG = -0.563166
RAYON_KM   = 80

def distance_km(lat1, lng1, lat2, lng2):
    """Distance en km entre deux points GPS (formule haversine)."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Recherches multi-ligues toutes centrées sur Angers.
# Ten'Up filtre par ligue selon la ville saisie — en utilisant des villes
# de chaque ligue proche d'Angers, on récupère les tournois de chaque ligue
# dans le rayon voulu. Le filtre GPS final garantit le rayon réel de 80km.
# Plusieurs points de recherche par ligue pour couvrir toute la zone de 80km.
# L'API plafonne à 30 résultats uniques par requête, triés par distance depuis
# la ville centre. On multiplie donc les centres pour ne rien manquer.
# Le filtre GPS final à 80km depuis Angers garantit la zone réelle.
RECHERCHES = [
    # Ligue 61 - Pays de la Loire (44, 49, 53, 72, 85)
    {
        "ligue": "61", "desc": "Angers",
        "ville_value": "Angers, 49000",
        "ville_label": "Angers, 49, Maine-et-Loire, Pays de la Loire",
        "lat": "47.478419", "lng": "-0.563166", "distance": "100",
    },
    {
        "ligue": "61", "desc": "Laval",
        "ville_value": "Laval, 53000",
        "ville_label": "Laval, 53, Mayenne, Pays de la Loire",
        "lat": "48.073477", "lng": "-0.771800", "distance": "100",
    },
    {
        "ligue": "61", "desc": "Nantes",
        "ville_value": "Nantes, 44000",
        "ville_label": "Nantes, 44, Loire-Atlantique, Pays de la Loire",
        "lat": "47.218371", "lng": "-1.553621", "distance": "100",
    },
    {
        "ligue": "61", "desc": "Le Mans",
        "ville_value": "Le Mans, 72000",
        "ville_label": "Le Mans, 72, Sarthe, Pays de la Loire",
        "lat": "47.995651", "lng": "0.192060", "distance": "100",
    },
    # Ligue 52 - Bretagne (35, 22, 29, 56)
    {
        "ligue": "52", "desc": "Argentré-du-Plessis",
        "ville_value": "Argentré-du-Plessis, 35370",
        "ville_label": "Argentré-du-Plessis, 35, Ille-et-Vilaine, Bretagne",
        "lat": "48.076", "lng": "-1.177", "distance": "100",
    },
    # Ligue 59 - Nouvelle-Aquitaine (79, 17, 16, 86)
    {
        "ligue": "59", "desc": "Bressuire",
        "ville_value": "Bressuire, 79300",
        "ville_label": "Bressuire, 79, Deux-Sèvres, Nouvelle-Aquitaine",
        "lat": "46.836", "lng": "-0.492", "distance": "100",
    },
]

# ── Étape 1 : récupérer form_build_id + cookies via Playwright ────────────────
def get_session_data():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = context.new_page()
        print("  → Ouverture de Ten'Up...")
        page.goto("https://tenup.fft.fr/recherche/tournois", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)

        form_build_id = page.evaluate("""
            () => {
                const el = document.querySelector('input[name="form_build_id"]');
                return el ? el.value : null;
            }
        """)
        print(f"  → form_build_id : {'OK' if form_build_id else 'NON TROUVÉ'}")

        cookies = context.cookies()
        browser.close()

        if not form_build_id:
            raise RuntimeError("form_build_id introuvable")

        return form_build_id, {c["name"]: c["value"] for c in cookies}

# ── Étape 2 : rafraîchir le form_build_id via requests ───────────────────────
def refresh_form_build_id(session):
    resp = session.get(
        "https://tenup.fft.fr/recherche/tournois",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=30,
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    field = soup.find("input", {"name": "form_build_id"})
    if field:
        return field["value"]
    import re
    match = re.search(r'form_build_id[^>]+value="([^"]+)"', resp.text)
    if match:
        return match.group(1)
    raise RuntimeError("Impossible de récupérer un nouveau form_build_id")

# ── Étape 3 : faire une requête AJAX par ligue ────────────────────────────────
def fetch_one_recherche(session, form_build_id, recherche):
    """Récupère tous les tournois pour une ligue donnée (toutes pages)."""
    all_items = []
    seen_page_ids = set()
    page = 0
    nb_pages = 1

    while page < nb_pages:
        data = {
            "recherche_type": "ville",
            "ville[autocomplete][country]": "fr",
            "ville[autocomplete][textfield]": "",
            "ville[autocomplete][value_container][value_field]": recherche["ville_value"],
            "ville[autocomplete][value_container][label_field]": recherche["ville_label"],
            "ville[autocomplete][value_container][lat_field]": recherche["lat"],
            "ville[autocomplete][value_container][lng_field]": recherche["lng"],
            "ville[distance][value_field]": recherche["distance"],
            "club[autocomplete][textfield]": "",
            "club[autocomplete][value_container][value_field]": "",
            "club[autocomplete][value_container][label_field]": "",
            "pratique": "PADEL",
            "date[start]": "11/04/26",
            "date[end]": "31/12/26",
            "epreuve[DM]": "DM",
            "categorie_age[200]": "200",
            "type[P]": "P",
            "categorie_tournoi[P50]": "P50",
            "categorie_tournoi[P100]": "P100",
            "page": str(page),
            "sort": "_DIST_",
            "form_build_id": form_build_id,
            "form_id": "recherche_tournois_form",
            "_triggering_element_name": "submit_main",
            "_triggering_element_value": "Rechercher",
        }

        if page > 0:
            new_fbid = refresh_form_build_id(session)
            data["form_build_id"] = new_fbid

        resp = session.post("https://tenup.fft.fr/system/ajax", data=data, timeout=30)
        resp.raise_for_status()

        found = False
        for cmd in resp.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                results = cmd.get("results", {})
                items = results.get("items", [])
                nb_total = results.get("nb_results", 0)
                nb_pages = math.ceil(nb_total / 30) if nb_total > 0 else 1

                # Compter les nouveaux ids sur cette page
                new_ids = [it for it in items if it.get("id") not in seen_page_ids]
                for it in new_ids:
                    seen_page_ids.add(it.get("id"))

                print(f"    Page {page}/{nb_pages-1} : {len(items)} items | {len(new_ids)} nouveaux ids | total : {nb_total}")
                all_items.extend(items)
                found = True

                # Arrêter si aucun nouvel id sur cette page (l'API boucle)
                if page > 0 and len(new_ids) == 0:
                    print(f"    → Plus de nouveaux ids, arrêt pagination")
                    return all_items

                break

        if not found:
            print(f"    ⚠️ Pas de résultats page {page}")
            break

        page += 1

    return all_items


def fetch_all_tournaments(form_build_id, cookies_dict):
    """Interroge toutes les ligues et déduplique les résultats."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://tenup.fft.fr",
        "Referer": "https://tenup.fft.fr/recherche/tournois",
        "X-Requested-With": "XMLHttpRequest",
    })
    for name, value in cookies_dict.items():
        session.cookies.set(name, value)

    all_items = []
    seen_ids = set()

    for recherche in RECHERCHES:
        print(f"  → Ligue {recherche['ligue']} - {recherche['desc']}...")
        # Récupérer un form_build_id frais pour chaque ligue
        fbid = refresh_form_build_id(session)
        items = fetch_one_recherche(session, fbid, recherche)
        new_count = 0
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_items.append(item)
                new_count += 1
        print(f"  → Ligue {recherche['ligue']} : {new_count} nouveaux tournois uniques (total : {len(all_items)})")

    print(f"  → Total toutes ligues : {len(all_items)} tournois uniques")
    return all_items

# ── Étape 3 : parser les items JSON ───────────────────────────────────────────
def parse_tournaments(items):
    tournaments = []
    JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    for item in items:
        tournament_id = str(item.get("id", ""))
        if not tournament_id:
            continue

        nom = item.get("libelle", "Nom inconnu")
        club = item.get("nomClub", "Club inconnu")
        installation = item.get("installation", {})
        ville = installation.get("ville", item.get("villeEngagement", ""))
        cp = installation.get("codePostal", item.get("codePostalEngagement", ""))
        adresse = installation.get("adresse2", item.get("adresse2Engagement", ""))
        distance = item.get("distanceEnMetres", "")

        date_debut_raw = item.get("dateDebut")
        date_debut = date_debut_raw.get("date", "") if isinstance(date_debut_raw, dict) else ""
        date_fin_raw = item.get("dateFin")
        date_fin = date_fin_raw.get("date", "") if isinstance(date_fin_raw, dict) else ""
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
        cats = list({e.get("typeEpreuve", {}).get("code", "") for e in epreuves if e.get("typeEpreuve", {}).get("code")})

        # Filtrer par distance réelle depuis Angers
        inst_lat = installation.get("lat")
        inst_lng = installation.get("lng")
        try:
            # Convertir en float en gérant None, 0, "0", etc.
            lat_f = float(inst_lat) if inst_lat not in (None, "", "0", 0, 0.0) else None
            lng_f = float(inst_lng) if inst_lng not in (None, "", "0", 0, 0.0) else None
            if lat_f is not None and lng_f is not None:
                dist_reelle = distance_km(CENTRE_LAT, CENTRE_LNG, lat_f, lng_f)
                distance = f"{dist_reelle:.1f} km"
                if dist_reelle > RAYON_KM:
                    continue  # Tournoi hors zone, on l'ignore
            else:
                distance = item.get("distanceEnMetres", "")
        except (ValueError, TypeError):
            # Coordonnées invalides → on garde sans filtrer
            distance = item.get("distanceEnMetres", "")

        tournaments.append({
            "id": tournament_id,
            "nom": nom,
            "club": club,
            "adresse": f"{adresse}, {cp} {ville}".strip(", "),
            "ville": ville,
            "distance": distance,
            "date": date_str,
            "date_raw": date_debut[:10] if date_debut else "9999-12-31",
            "categories": ", ".join(sorted(cats)),
            "link": f"https://tenup.fft.fr/tournoi/{tournament_id}",
            "detected_at": datetime.now().isoformat(),
        })

    return tournaments

# ── Étape 4 : comparer avec les tournois connus ────────────────────────────────
def load_known_tournaments():
    if os.path.exists(KNOWN_TOURNAMENTS_FILE):
        with open(KNOWN_TOURNAMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_known_tournaments(known):
    with open(KNOWN_TOURNAMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False, indent=2)

def find_new_tournaments(current, known):
    return [t for t in current if t["id"] not in known]

# ── Étape 5 : envoyer l'email ──────────────────────────────────────────────────
def send_email(new_tournaments):
    subject = f"🎾 {len(new_tournaments)} nouveau(x) tournoi(s) de padel détecté(s) !"

    # Tri chronologique
    new_tournaments = sorted(new_tournaments, key=lambda t: t.get("date_raw", "9999-12-31"))

    html_body = "<html><body>"
    html_body += "<h2 style='color:#2e7d32;'>🎾 Nouveaux tournois de padel près de chez vous !</h2>"
    html_body += "<p>Les tournois suivants viennent d'être publiés sur Ten'Up :</p><hr>"

    for t in new_tournaments:
        html_body += f"""
        <div style="margin-bottom:20px;padding:15px;border-left:4px solid #2e7d32;background:#f9f9f9;">
            <h3 style="margin:0 0 8px 0;">{t['nom']} <span style="font-size:14px;color:#666;">({t['categories']})</span></h3>
            <p style="margin:4px 0;">📅 <strong>Date :</strong> {t['date']}</p>
            <p style="margin:4px 0;">🏟️ <strong>Club :</strong> {t['club']}</p>
            <p style="margin:4px 0;">📍 <strong>Adresse :</strong> {t['adresse']}</p>
            <p style="margin:4px 0;">📏 <strong>Distance :</strong> {t['distance']}</p>
            <p style="margin:4px 0;"><a href="{t['link']}" style="color:#2e7d32;">👉 Voir sur Ten'Up</a></p>
        </div>"""

    html_body += "<hr><p style='color:#888;font-size:12px;'>Padel · Angers 80km · Messieurs Sénior · P50/P100</p></body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, EMAIL_TO, msg.as_string())
    print(f"✅ Email envoyé pour {len(new_tournaments)} nouveau(x) tournoi(s).")

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Vérification des tournois...")

    form_build_id, cookies_dict = get_session_data()
    items = fetch_all_tournaments(form_build_id, cookies_dict)
    current_tournaments = parse_tournaments(items)
    print(f"  → {len(current_tournaments)} tournoi(s) parsés.")

    known = load_known_tournaments()
    new_tournaments = find_new_tournaments(current_tournaments, known)

    if new_tournaments:
        print(f"  → {len(new_tournaments)} NOUVEAU(X) !")
        send_email(new_tournaments)
    else:
        print("  → Aucun nouveau tournoi.")

    for t in current_tournaments:
        known[t["id"]] = t
    save_known_tournaments(known)

if __name__ == "__main__":
    main()
