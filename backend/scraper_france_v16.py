"""
Padel Alert - Scraper France v16 - nouvelle API Ten'Up (Nuxt / Spring)

CONTEXTE (08/07/2026) : la FFT a remplace le site Drupal de Ten'Up par une app
Nuxt derriere Queue-it/CloudFront. Les mecanismes v15 (form_build_id Drupal,
/system/ajax, endpoints vuejs) sont tous morts. v15 tombe en echec systematique
("form_build_id introuvable").

NOUVELLE API (decouverte par diagnostic, phases 6-9 du 09/07/2026) :
  POST https://tenup.fft.fr/back/public/v1/tournois   (Content-Type: application/json)
  - Repond 200 JSON SANS aucun cookie (Queue-it non requis pour l'API back/public)
    -> plus de Playwright du tout.
  - Body : {pratique, from, size, dateDebut, dateFin, ligues:[codes], sort, ...}
  - Reponse : {nbResultats, cards:[{club{code,libelle,lat,lng}, dateDebut, dateFin,
    idHomologation, libelleTournoi, ville, pratique, naturesEpreuves:[DD/DM/DX], ...}]}

STRATEGIE v16 : une requete par ligue (18 codes) pour taguer chaque tournoi de sa
ligue (indispensable au matching par ligue), dedup par tenup_id. ~18 POST, ~30s au lieu
de 9-12 min en v15.

CHAMPS MANQUANTS DANS L'API (vs ancienne) - deduits du libelleTournoi :
  - niveau_codes (P25/P50/.../P2000) : extraits du libelle (regex, casse/espace tolerants)
  - competition_codes (P/CE/CEQ) : "championnat"+"equipe"->CEQ, "championnat"->CE, sinon P
  - age_codes : "+45"->345, "+55"->355, sinon Senior 200 (padel quasi 100% Senior)
  - cp : absent, remplace par lat/lng direct (club.lat/lng), toujours presents

CONTINUITE tenup_id : idHomologation = "FED_82559985" / "MOJA_243827" -> partie numerique.
A valider : recouvrement avec les tenup_id de l'ancien tournaments.json (sinon
l'ingest WP re-notifierait tout). Verifie en phase de recette staging.
"""
import os, json, subprocess, re, time
from datetime import datetime, timedelta, timezone
import requests

OUTPUT_FILE  = "data/tournaments.json"
TENUP_BASE   = "https://tenup.fft.fr"
API_TOURNOIS = f"{TENUP_BASE}/back/public/v1/tournois"
HORIZON_DAYS = 90
PAGE_SIZE    = 5000          # marge large : la plus grosse ligue (IdF) ~775 padel
RETRY_MAX    = 3
MIN_EXPECTED = 3000          # garde-fou coherence : refus de commit sous ce seuil

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# 18 ligues FFT - codes et noms IDENTIQUES a v15 (continuite du champ ligue_name
# stocke dans pa_pa_alerts : ne surtout pas renommer).
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Niveaux valides FFT
NIVEAUX = ("25", "50", "100", "250", "500", "1000", "1500", "2000")

# 1) Niveau avec prefixe P : espace/tiret optionnels ("P 250", "p-500", "P  25"),
#    colle au suffixe de genre ("P50H", "P100MIXTE") via (?!\d) au lieu de \b (sinon
#    "P50H" echoue : "0" et "H" tous deux word-chars = pas de frontiere). (?!\d) evite
#    aussi que "P1000" soit lu "P100".
NIVEAU_P_RE = re.compile(r'P[\s\-]*(25|50|100|250|500|1000|1500|2000)(?!\d)', re.IGNORECASE)

# 2) Fallback : niveau ecrit SANS prefixe P ("ALL IN 100H", "25 H et F", "PADEL 100
#    Hommes"). Uniquement si aucun P## trouve. Le nombre doit correspondre EXACTEMENT a
#    un niveau valide (borne par des non-chiffres) pour limiter les faux positifs.
NIVEAU_BARE_RE = re.compile(r'(?<!\d)(25|50|100|250|500|1000|1500|2000)(?!\d)')


# -- Resolution des coordonnees ---------------------------------------------------
# La nouvelle API ne renvoie PAS les coords des clubs (sauf clubs "ligue" DROM/COM).
# Resolution en 3 couches :
#   1) coords presentes dans la card (rare)
#   2) table club -> coords batie depuis l'ancien scraper (backend/clubs_coords.json,
#      748 clubs, coords PRECISES du site) -> ~99% de couverture (clubs recurrents)
#   3) geocodage de la ville via geo.api.gouv.fr (meme API que l'autocomplete du site)

GEO_API = "https://geo.api.gouv.fr/communes"

_CLUBS_COORDS = None
_GEO_CACHE = {}


def load_clubs_coords():
    global _CLUBS_COORDS
    if _CLUBS_COORDS is None:
        path = os.path.join(os.path.dirname(__file__), "clubs_coords.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _CLUBS_COORDS = json.load(f)
        except Exception:
            _CLUBS_COORDS = {}
        print(f"clubs_coords.json : {len(_CLUBS_COORDS)} clubs charges")
    return _CLUBS_COORDS


def norm_ville(v):
    v = (v or "").strip()
    v = re.sub(r'\s+CEDEX.*$', '', v, flags=re.IGNORECASE)   # "NOUMEA CEDEX" -> "NOUMEA"
    v = re.sub(r'\s+\d+\s*$', '', v)                         # "PARIS 16" -> "PARIS"
    return v.strip()


def geocode_ville(session, ville):
    """geo.api.gouv.fr : nom de ville -> (lat, lng, cp). Cache en memoire."""
    key = (ville or "").strip().upper()
    if not key:
        return (None, None, "")
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    result = (None, None, "")
    try:
        r = session.get(GEO_API, params={
            "nom": ville, "fields": "centre,codesPostaux",
            "boost": "population", "limit": 1,
        }, timeout=15)
        arr = r.json()
        if arr and arr[0].get("centre", {}).get("coordinates"):
            lon, lat = arr[0]["centre"]["coordinates"]
            cps = arr[0].get("codesPostaux") or []
            result = (float(lat), float(lon), cps[0] if cps else "")
    except Exception:
        pass
    _GEO_CACHE[key] = result
    return result


def resolve_coords(session, card):
    """Retourne (lat, lng, cp) pour une card, via les 3 couches."""
    club = card.get("club") or {}
    # Couche 1 : coords dans la card
    lat, lng = club.get("lat"), club.get("lng")
    if lat and lng:
        return (float(lat), float(lng), "")
    # Couche 2 : table club -> coords
    nom = (club.get("libelle") or "").strip().upper()
    ref = load_clubs_coords().get(nom)
    if ref and ref.get("lat") and ref.get("lng"):
        return (float(ref["lat"]), float(ref["lng"]), ref.get("cp", "") or "")
    # Couche 3 : geocodage de la ville
    return geocode_ville(session, norm_ville(card.get("ville")))


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": TENUP_BASE,
        "Referer": f"{TENUP_BASE}/recherche/tournois/resultats",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    return s


def fetch_ligue(session, ligue_id, date_debut_iso, date_fin_iso):
    """Retourne la liste des cards padel d'une ligue (une requete POST)."""
    payload = {
        "pratique": "PADEL", "from": 0, "size": PAGE_SIZE,
        "lat": None, "lng": None, "distance": 30,
        "type": [], "codeClub": None,
        "ligues": [str(ligue_id)], "comites": [],
        "dateDebut": date_debut_iso, "dateFin": date_fin_iso,
        "utiliserMesDonnees": False,
        "naturesEpreuves": [], "typesEpreuves": [], "naturesTerrains": [],
        "categoriesJeu": [], "categoriesAge": [], "familles": [],
        "tournoiInterne": False, "classements": [],
        "inscriptionEnLigne": None, "paiementEnLigne": None,
        "filtres": True, "sort": "DISTANCE",
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            r = session.post(API_TOURNOIS, data=json.dumps(payload), timeout=60)
            r.raise_for_status()
            d = r.json()
            return d.get("cards", []), d.get("nbResultats", 0)
        except Exception as e:
            print(f"    tentative {attempt} ligue {ligue_id} : {e}")
            if attempt < RETRY_MAX:
                time.sleep(2 * attempt)
    return [], 0


# -- Parsing / mapping vers le format tournaments.json (identique v15) -------------

def parse_niveaux(libelle):
    lib = libelle or ""
    # Coquille "P1OO" / "P5OO" : lettre O au lieu du zero. Normaliser O->0 pour la
    # detection (sans risque : "HOMME"->"H0MME" ne cree aucun niveau valide).
    lib_norm = lib.replace("O", "0").replace("o", "0")
    codes = {"P" + m for m in NIVEAU_P_RE.findall(lib_norm)}
    if not codes:
        # Aucun "P##" : tenter le niveau sans prefixe ("ALL IN 100H", "25 H et F"...).
        codes = {"P" + m for m in NIVEAU_BARE_RE.findall(lib_norm)}
    return sorted(codes)


def parse_competition(libelle):
    lib = (libelle or "").lower()
    if "championnat" in lib:
        if "équipe" in lib or "equipe" in lib:
            return ["CEQ"]
        return ["CE"]
    return ["P"]


def parse_ages(libelle):
    lib = (libelle or "").lower()
    codes = set()
    if "+45" in lib or "45 ans" in lib:
        codes.add("345")
    if "+55" in lib or "55 ans" in lib:
        codes.add("355")
    if not codes:
        codes.add("200")   # Senior par defaut (padel quasi exclusivement Senior)
    return sorted(codes)


def numeric_id(id_homologation):
    m = re.search(r'(\d{5,})', id_homologation or "")
    return m.group(1) if m else None


def build_date_str(date_debut, date_fin):
    if not date_debut:
        return "Date inconnue"
    try:
        d = datetime.strptime(date_debut[:10], "%Y-%m-%d")
        s = f"{JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
        if date_fin and date_fin[:10] != date_debut[:10]:
            d2 = datetime.strptime(date_fin[:10], "%Y-%m-%d")
            s += f" -> {JOURS[d2.weekday()]} {d2.strftime('%d/%m/%Y')}"
        return s
    except Exception:
        return date_debut[:10]


def parse_card(session, card, ligue_name):
    idh = card.get("idHomologation", "")
    tid = numeric_id(idh)
    if not tid:
        return None

    club = card.get("club") or {}
    ville = card.get("ville", "") or ""
    lib   = card.get("libelleTournoi", "Tournoi") or "Tournoi"

    lat_f, lng_f, cp = resolve_coords(session, card)

    date_debut = card.get("dateDebut")
    date_fin   = card.get("dateFin")

    match_types = sorted({m for m in (card.get("naturesEpreuves") or []) if m})

    return {
        "tenup_id":          tid,
        "libelle":           lib,
        "club":              club.get("libelle", "") or "",
        "ville":             ville,
        "cp":                cp or "",
        "adresse":           (f"{cp} {ville}".strip() if cp else ville),
        "lat":               lat_f,
        "lng":               lng_f,
        "date_debut":        date_debut[:10] if date_debut else None,
        "date_fin":          date_fin[:10]   if date_fin   else None,
        "date_str":          build_date_str(date_debut, date_fin),
        "match_types":       match_types,
        "age_codes":         parse_ages(lib),
        "niveau_codes":      parse_niveaux(lib),
        "competition_codes": parse_competition(lib),
        "ligues":            [ligue_name],
        "link":              f"{TENUP_BASE}/tournoi/{tid}",
    }


# -- Main -------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    date_debut_iso = now.strftime("%Y-%m-%dT00:00:00.000Z")
    date_fin_iso   = (now + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%dT00:00:00.000Z")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')} UTC] Padel Alert - Scraper v16 - "
          f"{len(LIGUES)} ligues ({date_debut_iso[:10]} -> {date_fin_iso[:10]})")

    session = make_session()
    by_id = {}          # tenup_id -> tournoi parse (dedup)
    stats = {}

    for ligue in LIGUES:
        cards, nb = fetch_ligue(session, ligue["id"], date_debut_iso, date_fin_iso)
        added = 0
        for c in cards:
            t = parse_card(session, c, ligue["name"])
            if not t:
                continue
            if t["tenup_id"] not in by_id:
                by_id[t["tenup_id"]] = t
                added += 1
            else:
                # tournoi deja capte par une autre ligue : fusionner le tag ligue
                existing = by_id[t["tenup_id"]]["ligues"]
                if ligue["name"] not in existing:
                    existing.append(ligue["name"])
        stats[ligue["name"]] = {"nb": nb, "cards": len(cards), "added": added}
        print(f"  {ligue['name']}: {nb} resultats -> {added} nouveaux "
              f"(cumul {len(by_id)})")
        time.sleep(0.3)

    tournaments = list(by_id.values())
    elapsed = (datetime.now(timezone.utc) - now).total_seconds()

    # -- Garde-fou de coherence (regle Baptiste 09/07) : ne jamais commit un JSON
    #    manifestement casse (volume plancher + champs critiques presents). --------
    with_niveau = sum(1 for t in tournaments if t["niveau_codes"])
    with_coords = sum(1 for t in tournaments if t["lat"] and t["lng"])
    with_dates  = sum(1 for t in tournaments if t["date_debut"])
    print(f"\n{'='*60}")
    print(f"Total padel France : {len(tournaments)} tournois uniques ({elapsed:.0f}s)")
    print(f"  avec niveau P## : {with_niveau} ({100*with_niveau//max(len(tournaments),1)}%)")
    print(f"  avec lat/lng    : {with_coords} ({100*with_coords//max(len(tournaments),1)}%)")
    print(f"  avec date_debut : {with_dates} ({100*with_dates//max(len(tournaments),1)}%)")
    print(f"  geocodages ville (couche 3) : {len(_GEO_CACHE)}")

    errors = []
    if len(tournaments) < MIN_EXPECTED:
        errors.append(f"volume {len(tournaments)} < seuil {MIN_EXPECTED}")
    if with_dates < len(tournaments) * 0.95:
        errors.append(f"trop de tournois sans date ({len(tournaments)-with_dates})")
    if with_coords < len(tournaments) * 0.80:
        errors.append(f"trop de tournois sans coordonnees ({len(tournaments)-with_coords})")
    if errors:
        print("\nGARDE-FOU : commit REFUSE ->", " ; ".join(errors))
        raise SystemExit(1)

    os.makedirs("data", exist_ok=True)
    payload = {
        "scraped_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":       len(tournaments),
        "tournaments": tournaments,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nFichier ecrit : {OUTPUT_FILE}")

    # Commit sur la branche courante (le workflow controle sur quelle branche il tourne)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", OUTPUT_FILE], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        msg = f"Scraping v16 [{now.strftime('%Y-%m-%d %H:%M')} UTC] - {len(tournaments)} tournois"
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pousse.")
    else:
        print("Aucun changement.")

    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC] Termine.")


if __name__ == "__main__":
    main()
