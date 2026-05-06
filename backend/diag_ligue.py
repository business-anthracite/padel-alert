"""
Diag v14 — Vérification pagination avec nouveaux critères
Test : les pages 0..5 ont-elles des IDs différents avec les nouveaux critères ?
Si oui : on peut paginer, on obtient 1147 uniques.
Si non : pagination cyclique, on obtient seulement 30 uniques avec critères.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

NEW_CRITERIA_PADEL = {
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


def get_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)", locale="fr-FR")
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        fbid = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    return fbid, cookies


def make_session(cookies):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0", "Accept": "application/json, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE, "Referer": TENUP_SEARCH, "X-Requested-With": "XMLHttpRequest",
    })
    for k, v in cookies.items():
        s.cookies.set(k, v)
    return s


def call(session, fbid, extra, page_num=0):
    now = datetime.now()
    p = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
        "sort": "dateDebut asc",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid, "page": str(page_num),
    }
    p.update(extra)
    try:
        r = session.post(TENUP_AJAX, data=p, timeout=45)
        r.raise_for_status()
        for cmd in r.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                items = res.get("items", [])
                return res.get("nb_results", 0), [str(it.get("id","")) for it in items]
        return 0, []
    except Exception as e:
        return 0, []


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "pagination_tests": [], "scrape_test": {}}

    print("Session...")
    fbid, cookies = get_session()
    session = make_session(cookies)
    base = {"recherche_type": "ligue", "cbrappel[]": "57"}

    print("\n=== Test pagination pages 0-5 avec critères ===")
    all_ids = set()
    for pg in range(6):
        nb, ids = call(session, fbid, {**base, **NEW_CRITERIA_PADEL}, pg)
        overlap = set(ids) & all_ids
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        print(f"  Page {pg}: nb={nb} items={len(ids)} new_unique={len(new_ids)} overlap={len(overlap)}")
        output["pagination_tests"].append({
            "page": pg, "nb_results": nb, "nb_items": len(ids),
            "new_unique": len(new_ids), "overlap_with_prev": len(overlap),
            "ids": ids[:5],  # juste les 5 premiers
        })
        time.sleep(0.3)

    total_unique = len(all_ids)
    print(f"\n  Total unique après 6 pages : {total_unique}")
    output["unique_after_6_pages"] = total_unique
    output["pagination_works"] = total_unique > 30

    # Si pagination fonctionne, scraper les 38 premières pages
    if output["pagination_works"]:
        print("\n=== Scraping pages 0-37 (1147/30 ≈ 38 pages) ===")
        all_scraped = {}
        for pg in range(38):
            nb, ids = call(session, fbid, {**base, **NEW_CRITERIA_PADEL}, pg)
            if not ids:
                print(f"  Page {pg}: vide — arrêt")
                break
            for iid in ids:
                all_scraped[iid] = True
            if pg % 10 == 0:
                print(f"  Page {pg}: {len(all_scraped)} uniques")
            time.sleep(0.2)
        print(f"  Total unique scraping : {len(all_scraped)}")
        output["scrape_test"] = {"total_unique": len(all_scraped), "pages_scraped": pg + 1}

    # Test étendu : date range plus large (180 jours)
    print("\n=== Test date range élargi (180 jours) ===")
    now = datetime.now()
    nb_180, ids_180 = call(session, fbid, {
        **base, **NEW_CRITERIA_PADEL,
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=180)).strftime("%d/%m/%y"),
    })
    print(f"  180 jours : nb={nb_180} items={len(ids_180)}")
    output["date_180_nb"] = nb_180

    print(f"\n=== RÉSUMÉ ===")
    print(f"pagination_works: {output['pagination_works']}")
    print(f"unique après 6 pages: {output['unique_after_6_pages']}")
    if output.get("scrape_test"):
        print(f"unique scraping 38p: {output['scrape_test'].get('total_unique')}")
    print(f"nb avec 180 jours: {nb_180}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v14 pagination_check [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
