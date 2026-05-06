"""
Padel Alert — Diagnostic ligue v5
Découverte clé (v4) : les ligues utilisent des checkboxes id="57_cbrappel" etc.
Le paramètre AJAX est probablement cbrappel[]=57 (pas ligue=IDF).
Ce diagnostic teste le format cbrappel[] avec les 18 ligues découvertes.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

# Mapping découvert en v4 (id_cbrappel → nom ligue)
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


def get_session():
    """Obtenir fbid + cookies via Playwright (page initiale seulement)."""
    print("  Ouverture Ten'Up...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    print(f"  fbid: {fbid[:40] if fbid else 'MANQUANT'}")
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


def ajax_call(session, extra_params, fbid, page_num=0):
    """AJAX Ten'Up avec extra_params pour la ligue."""
    now = datetime.now()
    params = {
        "recherche_type": "ligue",
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": str(page_num),
    }
    params.update(extra_params)
    try:
        r = requests.Session()
        r = session.post(TENUP_AJAX, data=params, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        for cmd in cmds:
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                return {
                    "nb_results": res.get("nb_results", 0),
                    "nb_items": len(res.get("items", [])),
                    "first_id": (res.get("items") or [{}])[0].get("id"),
                    "http": r.status_code,
                }
        return {
            "nb_results": 0, "nb_items": 0,
            "commands": [c.get("command") for c in cmds if isinstance(c, dict)],
            "raw": r.text[:300], "http": r.status_code,
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ligue_mapping": {lid: name for lid, name in LIGUES},
        "tests": [],
        "working": [],
        "conclusion": "",
    }

    print("=== Session Playwright ===")
    fbid, cookies = get_session()
    session = make_session(cookies)

    print("\n=== Test 1 : cbrappel[]=XX par ligue individuelle ===")
    for lid, name in LIGUES:
        extra = {f"cbrappel[]": lid}
        r0 = ajax_call(session, extra, fbid, 0)
        nb = r0.get("nb_results", 0)
        result = {"ligue_id": lid, "ligue_name": name, "format": "cbrappel[]=XX", "page_0": r0}

        if nb > 30:
            time.sleep(0.3)
            r1 = ajax_call(session, extra, fbid, 1)
            result["page_1"] = r1
            result["pagination_ok"] = (
                r0.get("first_id") is not None and r1.get("first_id") is not None
                and r0["first_id"] != r1["first_id"]
            )
        else:
            result["pagination_ok"] = None

        print(f"  {'✓' if nb > 0 else '✗'} {name} (id={lid}): {nb} résultats | pagination={result.get('pagination_ok','N/A')}")
        output["tests"].append(result)
        if nb > 0:
            output["working"].append({"id": lid, "name": name, "nb_results": nb, "pagination_ok": result.get("pagination_ok")})
        time.sleep(0.3)

    print("\n=== Test 2 : formats alternatifs (si test 1 échoue) ===")
    if not output["working"]:
        alt_tests = [
            # ligue=57
            ({"ligue": "57"},      "ligue=57 (IDF)"),
            ({"ligue": "62"},      "ligue=62 (PACA)"),
            # cbrappel=57 (sans crochets)
            ({"cbrappel": "57"},   "cbrappel=57 sans [] (IDF)"),
            # ligue[cbrappel][]=57
            ({"ligue[cbrappel][]": "57"}, "ligue[cbrappel][]=57 (IDF)"),
            # comite_ligue[]=57
            ({"comite_ligue[]": "57"}, "comite_ligue[]=57 (IDF)"),
        ]
        for extra, label in alt_tests:
            r0 = ajax_call(session, extra, fbid, 0)
            nb = r0.get("nb_results", 0)
            print(f"  {'✓' if nb > 0 else '✗'} {label}: {nb} résultats")
            output["tests"].append({"format": label, "page_0": r0, "nb_results": nb})
            if nb > 0:
                output["working"].append({"format": label, "nb_results": nb})
            time.sleep(0.3)

    print("\n=== Test 3 : toutes ligues en même temps ===")
    all_ids_extra = {}
    for lid, _ in LIGUES:
        # requests encode les paramètres en lists automatiquement si on passe une list
        # Mais avec data=dict, cbrappel[]=XX doit être encodé différemment
    # Utiliser une liste de tuples pour multi-value
    all_ids_params_list = [("cbrappel[]", lid) for lid, _ in LIGUES]
    all_ids_params_list += [
        ("recherche_type", "ligue"),
        ("pratique", "PADEL"),
        ("date[start]", datetime.now().strftime("%d/%m/%y")),
        ("date[end]", (datetime.now() + timedelta(days=90)).strftime("%d/%m/%y")),
        ("sort", "_DATE_"),
        ("form_id", "recherche_tournois_form"),
        ("_triggering_element_name", "submit_main"),
        ("_triggering_element_value", "Rechercher"),
        ("form_build_id", fbid),
        ("page", "0"),
    ] + list(ALL_CRITERIA.items())

    try:
        r = session.post(TENUP_AJAX, data=all_ids_params_list, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        nb_all = 0
        for cmd in cmds:
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                nb_all = cmd.get("results", {}).get("nb_results", 0)
                break
        print(f"  Toutes ligues (cbrappel[]=50..67): {nb_all} résultats")
        output["all_ligues_test"] = {"nb_results": nb_all}
    except Exception as e:
        print(f"  Erreur: {e}")
        output["all_ligues_test"] = {"error": str(e)}

    # Résumé
    print(f"\n=== RÉSUMÉ ===")
    print(f"Format cbrappel[] : {len(output['working'])} ligues avec résultats")
    for w in output["working"]:
        print(f"  {w}")

    output["conclusion"] = f"working={len(output['working'])}/18, all_ligues={output.get('all_ligues_test', {}).get('nb_results', 'N/A')}"

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v5 cbrappel[] [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
