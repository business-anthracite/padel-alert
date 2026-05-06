"""
Padel Alert — Diagnostic ligue v13
Découverte v12 : les nouveaux critères sont famille_tournois[], categorie_age[], type[], surface[]
Test : PADEL + nouveaux critères complets → est-ce qu'on obtient beaucoup plus de résultats ?
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

# Nouveaux critères découverts en v12
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
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", locale="fr-FR")
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE, "Referer": TENUP_SEARCH, "X-Requested-With": "XMLHttpRequest",
    })
    for k, v in cookies.items():
        s.cookies.set(k, v)
    return s


def call(session, fbid, extra, page_num=0):
    now = datetime.now()
    params = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
        "sort": "dateDebut asc",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": str(page_num),
    }
    params.update(extra)
    try:
        r = session.post(TENUP_AJAX, data=params, timeout=45)
        r.raise_for_status()
        for cmd in r.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                items = res.get("items", [])
                return {
                    "nb_results": res.get("nb_results", 0),
                    "nb_items": len(items),
                    "first_id": items[0].get("id") if items else None,
                    "http": r.status_code,
                }
        cmds = [c.get("command") for c in r.json() if isinstance(c, dict)]
        return {"nb_results": 0, "nb_items": 0, "commands": cmds, "raw": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "conclusion": ""}

    print("Session...")
    fbid, cookies = get_session()
    session = make_session(cookies)
    print(f"fbid: {fbid[:35]}")

    base_ligue = {"recherche_type": "ligue", "cbrappel[]": "57"}

    # Test 1 : sans critères (baseline = 27)
    print("\n[1] Sans critères (baseline)")
    r = call(session, fbid, base_ligue)
    print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')}")
    output["tests"].append({"label": "sans critères", **r})
    time.sleep(0.5)

    # Test 2 : avec TOUS les nouveaux critères
    print("\n[2] Avec nouveaux critères PADEL complets")
    r = call(session, fbid, {**base_ligue, **NEW_CRITERIA_PADEL})
    print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')}")
    output["tests"].append({"label": "nouveaux critères complets", **r})
    time.sleep(0.5)

    # Test 3 : uniquement famille_tournois (sans âge ni surface)
    print("\n[3] Uniquement famille_tournois")
    famille_only = {k: v for k, v in NEW_CRITERIA_PADEL.items() if "famille_tournois" in k}
    r = call(session, fbid, {**base_ligue, **famille_only})
    print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')}")
    output["tests"].append({"label": "famille_tournois uniquement", **r})
    time.sleep(0.5)

    # Test 4 : uniquement epreuve padel (DM, DD, DX)
    print("\n[4] Uniquement epreuve padel (DM, DD, DX)")
    epreuve_only = {k: v for k, v in NEW_CRITERIA_PADEL.items() if "epreuve" in k and k != "epreuve[SM]" and k != "epreuve[SD]"}
    r = call(session, fbid, {**base_ligue, **epreuve_only})
    print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')}")
    output["tests"].append({"label": "epreuve DM+DD+DX uniquement", **r})
    time.sleep(0.5)

    # Test 5 : page 1 avec critères complets (pagination)
    best_nb = max(t.get("nb_results", 0) for t in output["tests"])
    if best_nb > 30:
        best_test = max(output["tests"], key=lambda t: t.get("nb_results", 0))
        print(f"\n[5] Page 1 avec les meilleurs critères (nb={best_nb})")
        r = call(session, fbid, {**base_ligue, **NEW_CRITERIA_PADEL}, page_num=1)
        print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')} first_id={r.get('first_id')}")
        prev_first = output["tests"][1].get("first_id")
        pagination_ok = r.get("first_id") and prev_first and r["first_id"] != prev_first
        print(f"  pagination_ok: {pagination_ok}")
        output["tests"].append({"label": "page 1 critères complets", "pagination_ok": pagination_ok, **r})

    # Test 6 : ville Paris avec nouveaux critères (contrôle)
    print("\n[6] Ville Paris + nouveaux critères (contrôle)")
    r = call(session, fbid, {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
        "sort": "_DIST_",
        **NEW_CRITERIA_PADEL,
    })
    print(f"  → nb={r.get('nb_results')} items={r.get('nb_items')}")
    output["tests"].append({"label": "ville Paris + nouveaux critères", **r})

    print(f"\n=== RÉSUMÉ ===")
    for t in output["tests"]:
        print(f"  {t['label']}: nb={t.get('nb_results',0)}")
    output["conclusion"] = f"max_nb={max(t.get('nb_results',0) for t in output['tests'])}"

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v13 new_criteria [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
