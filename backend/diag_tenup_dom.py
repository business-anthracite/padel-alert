"""
Diagnostic — Hypothèse Referer ligue

Hypothèse : le serveur filtre les résultats par ligue via le Referer header.
Referer avec ligue=ALL → tous les tournois
Referer avec ligue=IDF → tournois IDF uniquement

Ce diagnostic compare les résultats de 3 requêtes identiques avec Referers différents :
- ligue=ALL    → référence
- ligue=IDF    → Île-de-France seulement ?
- ligue=PACA   → PACA seulement ?
=> Si les nb_total et IDs diffèrent → Referer contrôle le filtre → implémenter par ligue
"""
import json, time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import requests

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
HORIZON_DAYS = 90


def get_session():
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
    return fbid, cookies


def ajax_test(cookies, fbid, ligue_code, date_start, date_end, page_num=0):
    """Requête AJAX avec Referer ciblé sur une ligue spécifique."""
    referer = f"{TENUP_BASE}/recherche/tournois?type=LIGUE&ligue={ligue_code}&pratique=PADEL"
    trigger = "submit_page" if page_num > 0 else "submit_main"
    trigger_val = "Submit page" if page_num > 0 else "Rechercher"

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    })
    for k, v in cookies.items():
        s.cookies.set(k, v)

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
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  trigger,
        "_triggering_element_value": trigger_val,
        "form_build_id": fbid,
        "page": str(page_num),
    }
    try:
        resp = s.post(TENUP_AJAX, data=data, timeout=30)
        resp.raise_for_status()
        for cmd in resp.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                items = res.get("items", [])
                ids = [str(it.get("id", "")) for it in items]
                return res.get("nb_results", 0), ids
        return 0, []
    except Exception as e:
        return -1, [str(e)]


def main():
    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

    print("=" * 60)
    print("Diagnostic — Referer ligue contrôle-t-il le filtre ?")
    print(f"Période : {date_start} → {date_end}")
    print("=" * 60)

    fbid, cookies = get_session()
    print(f"fbid: {fbid[:40]}...")
    print()

    results = {}
    ligues_test = [
        ("ALL",  "Toutes les ligues"),
        ("IDF",  "Île-de-France"),
        ("PACA", "Provence-Alpes-Côte d'Azur"),
        ("BRE",  "Bretagne"),
        ("ARA",  "Auvergne-Rhône-Alpes"),
    ]

    for code, name in ligues_test:
        nb, ids = ajax_test(cookies, fbid, code, date_start, date_end)
        results[code] = {"name": name, "nb_total": nb, "ids": ids[:5], "count": len(ids)}
        print(f"  ligue={code:4s} ({name}) : nb_total={nb}, items={len(ids)}, first_id={ids[0] if ids else 'N/A'}")
        time.sleep(1)

    print()
    print("=" * 60)
    print("ANALYSE")
    print("=" * 60)

    all_nb = results["ALL"]["nb_total"]
    idf_nb = results["IDF"]["nb_total"]
    paca_nb = results["PACA"]["nb_total"]

    if all_nb <= 0:
        print("ERREUR : requête ALL a échoué")
        return

    # Comparer IDs entre ALL et IDF
    all_ids = set(results["ALL"]["ids"])
    idf_ids = set(results["IDF"]["ids"])
    paca_ids = set(results["PACA"]["ids"])
    bre_ids = set(results["BRE"]["ids"])

    all_same = (all_nb == idf_nb == paca_nb)

    if all_same:
        print(f"→ Tous les nb_total identiques ({all_nb}) — Referer N'INFLUENCE PAS le filtre")
        print("  Autre mécanisme à chercher pour isoler les ligues.")
    else:
        print(f"→ nb_total DIFFÉRENTS selon le Referer !")
        print(f"  ALL={all_nb}, IDF={idf_nb}, PACA={paca_nb}, BRE={results['BRE']['nb_total']}")
        print(f"  → Referer contrôle le filtre ligue !")
        print(f"  → Implémenter 18 requêtes (une par ligue) pour couverture 100%")

        # Vérifier si les IDs diffèrent
        overlap_idf_paca = len(idf_ids & paca_ids)
        print(f"\n  Chevauchement IDF ∩ PACA (page 0) : {overlap_idf_paca} IDs en commun")
        if overlap_idf_paca == 0:
            print("  → Résultats totalement distincts par ligue ✓")
        else:
            print(f"  → {overlap_idf_paca} tournois en commun (multi-ligues possibles)")

    # Vérifier si ligue=IDF donne les bons tournois
    print(f"\n  IDs IDF (page 0): {results['IDF']['ids']}")
    print(f"  IDs PACA (page 0): {results['PACA']['ids']}")
    print(f"  IDs BRE (page 0): {results['BRE']['ids']}")


if __name__ == "__main__":
    main()
