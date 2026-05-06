"""
Diagnostic ligue v11 — Test chevauchement inter-ligues + approche optimale
Vérifie si CORSE (54) et IDF (57) retournent des IDs différents.
Si oui : approche par ligue nécessaire.
Si non : une seule requête "toutes ligues" suffit (10k uniques en ~5 min).
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

ALL_LIGUES_IDS = ["50","51","52","53","54","55","63","64","56","57","65","58","59","66","60","61","62","67"]

def get_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", locale="fr-FR")
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

def get_page(session, fbid, extra, page_num=0):
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
                    "ids": [str(it.get("id","")) for it in items],
                    "nb_items": len(items),
                }
        return {"nb_results": 0, "ids": [], "nb_items": 0, "raw": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}

def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": {}, "conclusion": ""}

    print("Session Playwright...")
    fbid, cookies = get_session()
    session = make_session(cookies)
    print(f"fbid: {fbid[:35]}")

    # Test 1 : IDF (57) page 0
    print("\n[1] IDF (57) page 0...")
    r_idf_0 = get_page(session, fbid, {"recherche_type": "ligue", "cbrappel[]": "57"}, 0)
    print(f"  nb={r_idf_0.get('nb_results')} ids_p0={r_idf_0.get('ids', [])[:5]}")
    output["tests"]["idf_page0"] = r_idf_0
    time.sleep(0.4)

    # Test 2 : CORSE (54) page 0
    print("\n[2] CORSE (54) page 0...")
    r_cor_0 = get_page(session, fbid, {"recherche_type": "ligue", "cbrappel[]": "54"}, 0)
    print(f"  nb={r_cor_0.get('nb_results')} ids_p0={r_cor_0.get('ids', [])[:5]}")
    output["tests"]["corse_page0"] = r_cor_0
    time.sleep(0.4)

    # Comparer IDs page 0
    idf_ids  = set(r_idf_0.get("ids", []))
    cor_ids  = set(r_cor_0.get("ids", []))
    overlap  = idf_ids & cor_ids
    pct      = len(overlap) / max(len(idf_ids), 1) * 100
    print(f"\nChevauchement IDF/CORSE page 0 : {len(overlap)}/{len(idf_ids)} = {pct:.0f}%")
    output["overlap_pct"] = pct
    output["overlap_ids"] = list(overlap)[:10]

    # Test 3 : toutes ligues en même temps (multi cbrappel[])
    print("\n[3] Toutes ligues (cbrappel[] multiple) page 0...")
    multi_params = [("cbrappel[]", lid) for lid in ALL_LIGUES_IDS]
    multi_params += [
        ("recherche_type", "ligue"), ("pratique", "PADEL"),
        ("date[start]", datetime.now().strftime("%d/%m/%y")),
        ("date[end]", (datetime.now() + timedelta(days=90)).strftime("%d/%m/%y")),
        ("sort", "dateDebut asc"),
        ("form_id", "recherche_tournois_form"),
        ("_triggering_element_name", "submit_main"),
        ("_triggering_element_value", "Rechercher"),
        ("form_build_id", fbid), ("page", "0"),
    ]
    try:
        r_all = session.post(TENUP_AJAX, data=multi_params, timeout=45)
        r_all.raise_for_status()
        r_all_data = {"nb_results": 0, "ids": []}
        for cmd in r_all.json():
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                r_all_data = {
                    "nb_results": res.get("nb_results", 0),
                    "ids": [str(it.get("id","")) for it in res.get("items", [])],
                    "nb_items": len(res.get("items", [])),
                }
        print(f"  nb={r_all_data['nb_results']} ids={r_all_data['ids'][:5]}")
        output["tests"]["all_ligues"] = r_all_data
    except Exception as e:
        print(f"  Erreur: {e}")
        output["tests"]["all_ligues"] = {"error": str(e)}
    time.sleep(0.4)

    # Test 4 : sans cbrappel[] du tout (recherche_type=ligue seul)
    print("\n[4] Ligue sans cbrappel (recherche_type=ligue seul) page 0...")
    r_no_cb = get_page(session, fbid, {"recherche_type": "ligue"}, 0)
    print(f"  nb={r_no_cb.get('nb_results')} ids={r_no_cb.get('ids', [])[:5]}")
    output["tests"]["ligue_sans_cbrappel"] = r_no_cb

    # Conclusion
    if pct > 80:
        conclusion = "GLOBAL: IDF et CORSE retournent ~memes resultats → une seule requete suffit"
        approach   = "single_global"
    else:
        conclusion = "DISTINCT: IDF et CORSE ont des resultats differents → approche par ligue necessaire"
        approach   = "per_ligue"

    output["conclusion"] = conclusion
    output["recommended_approach"] = approach

    nb_all = output["tests"].get("all_ligues", {}).get("nb_results", 0)
    nb_idf = output["tests"].get("idf_page0", {}).get("nb_results", 0)
    nb_cor = output["tests"].get("corse_page0", {}).get("nb_results", 0)
    print(f"\n=== RÉSUMÉ ===")
    print(f"IDF nb={nb_idf} | CORSE nb={nb_cor} | ALL nb={nb_all}")
    print(f"Chevauchement IDF/CORSE : {pct:.0f}%")
    print(f"Approche recommandée : {approach}")
    print(f"Conclusion : {conclusion}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v11 overlap test [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")

if __name__ == "__main__":
    main()
