"""
Diag v16 — Test fbid frais + random sampling
Hypothèse : chaque fbid frais retourne un sous-ensemble différent des 1147 résultats.
Si oui : faire N appels avec N fbids frais = N×30 uniques → couvre les 1147.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

NEW_CRITERIA = {
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

VILLE_PARAMS = {
    "recherche_type": "ville",
    "ville[autocomplete][country]": "fr",
    "ville[autocomplete][textfield]": "",
    "ville[autocomplete][value_container][value_field]": "Paris, 75001",
    "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
    "ville[autocomplete][value_container][lat_field]": "48.859489",
    "ville[autocomplete][value_container][lng_field]": "2.347880",
    "ville[distance][value_field]": "100",
    "sort": "_DIST_",
}
LIGUE_PARAMS = {"recherche_type": "ligue", "cbrappel[]": "57", "sort": "dateDebut asc"}


def get_playwright_session():
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

def refresh_fbid(session):
    """Obtenir un fbid frais via GET (rapide, ~0.5s)."""
    resp = session.get(TENUP_SEARCH, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    el = soup.find("input", {"name": "form_build_id"})
    return el["value"] if el else None

def call(session, fbid, extra, page_num=0):
    now = datetime.now()
    p = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
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
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "conclusion": ""}

    print("Session Playwright...")
    fbid_initial, cookies = get_playwright_session()
    session = make_session(cookies)
    print(f"fbid initial: {fbid_initial[:35]}")

    # ── Test 1 : 5 appels avec fbid FRAIS (refresh_fbid) ──────────────────────
    print("\n[1] 5 appels ligue + critères avec fbid FRAIS (refresh_fbid)")
    all_ids = set()
    for i in range(5):
        fbid_fresh = refresh_fbid(session)
        print(f"  fbid_{i}: {(fbid_fresh or '')[:30]}")
        nb, ids = call(session, fbid_fresh, {**LIGUE_PARAMS, **NEW_CRITERIA}, 0)
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        print(f"  Call {i}: nb={nb} items={len(ids)} new={len(new_ids)}")
        output["tests"].append({"label": f"ligue_fresh_fbid_{i}", "nb": nb, "new_ids": len(new_ids), "total_unique": len(all_ids)})
        time.sleep(0.4)

    random_sampling_works = len(all_ids) > 30
    print(f"\n  Total unique après 5 calls fresh fbid : {len(all_ids)}")
    print(f"  random_sampling_works : {random_sampling_works}")
    output["random_sampling_unique_5"] = len(all_ids)
    output["random_sampling_works"] = random_sampling_works

    # ── Test 2 : Estimer le total avec N calls ────────────────────────────────
    if random_sampling_works:
        print("\n[2] Estimation total avec 40 calls (sampling)")
        for i in range(5, 40):
            fbid_fresh = refresh_fbid(session)
            nb, ids = call(session, fbid_fresh, {**LIGUE_PARAMS, **NEW_CRITERIA}, 0)
            new_ids = set(ids) - all_ids
            all_ids.update(ids)
            if i % 10 == 0:
                print(f"  Call {i}: total_unique={len(all_ids)}")
            output["tests"].append({"label": f"ligue_fresh_fbid_{i}", "new_ids": len(new_ids), "total_unique": len(all_ids)})
            time.sleep(0.3)
        print(f"  Total unique après 40 calls : {len(all_ids)}")
        output["random_sampling_unique_40"] = len(all_ids)

    # ── Test 3 : Ville Paris, même approche ───────────────────────────────────
    print("\n[3] 5 appels VILLE Paris + critères avec fbid frais")
    all_ville = set()
    for i in range(5):
        fbid_fresh = refresh_fbid(session)
        nb, ids = call(session, fbid_fresh, {**VILLE_PARAMS, **NEW_CRITERIA}, 0)
        new_ids = set(ids) - all_ville
        all_ville.update(ids)
        print(f"  Call {i}: nb={nb} new={len(new_ids)} total={len(all_ville)}")
        output["tests"].append({"label": f"ville_fresh_fbid_{i}", "nb": nb, "new_ids": len(new_ids)})
        time.sleep(0.4)
    print(f"  Total unique ville 5 calls : {len(all_ville)}")
    output["ville_sampling_unique_5"] = len(all_ville)

    # Résumé
    output["conclusion"] = (
        f"ligue_fresh_fbid_unique_5={output.get('random_sampling_unique_5',0)}, "
        f"ligue_fresh_fbid_unique_40={output.get('random_sampling_unique_40','N/A')}, "
        f"sampling_works={random_sampling_works}"
    )
    print(f"\n=== CONCLUSION : {output['conclusion']}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v16 fresh_fbid [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
