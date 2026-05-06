"""
Diag v15 — Recherche VILLE avec nouveaux critères : pagination fonctionne ?
Si oui : revenir à l'approche multi-villes (v5) mais avec les nouveaux critères.
Bonus : tester sort=dateFin asc pour voir les tournois courts en premier.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
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
                return res.get("nb_results", 0), [str(it.get("id","")) for it in items], items
        return 0, [], []
    except Exception as e:
        return 0, [], []


VILLE_PARIS = {
    "recherche_type": "ville",
    "ville[autocomplete][country]": "fr",
    "ville[autocomplete][textfield]": "",
    "ville[autocomplete][value_container][value_field]": "Paris, 75001",
    "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
    "ville[autocomplete][value_container][lat_field]": "48.859489",
    "ville[autocomplete][value_container][lng_field]": "2.347880",
    "ville[distance][value_field]": "100",
}


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "conclusion": ""}

    print("Session...")
    fbid, cookies = get_session()
    session = make_session(cookies)

    # ── Test 1 : ville Paris + nouveaux critères + sort=_DIST_ (pages 0,1,2) ──
    print("\n[1] Ville Paris 100km + critères + sort=_DIST_ — pages 0,1,2")
    all_ids = set()
    for pg in range(3):
        nb, ids, items = call(session, fbid, {**VILLE_PARIS, "sort": "_DIST_", **NEW_CRITERIA}, pg)
        overlap = set(ids) & all_ids
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        print(f"  Page {pg}: nb={nb} items={len(ids)} new={len(new_ids)} overlap={len(overlap)}")
        if items:
            print(f"    Exemple: {items[0].get('libelle','')} | {items[0].get('installation',{}).get('ville','')} | date={items[0].get('dateDebut',{}).get('date','')[:10]}")
        output["tests"].append({
            "label": f"ville+critères+_DIST_ page{pg}",
            "nb": nb, "new_unique": len(new_ids), "overlap": len(overlap),
        })
        time.sleep(0.4)

    ville_pagination_ok = len(all_ids) > 30
    print(f"\n  Unique après 3 pages : {len(all_ids)} — pagination_ok={ville_pagination_ok}")

    # ── Test 2 : ville Paris + critères + sort=dateFin asc ──────────────────
    print("\n[2] Ville Paris + critères + sort=dateFin asc — pages 0,1")
    all_ids_fin = set()
    for pg in range(2):
        nb, ids, items = call(session, fbid, {**VILLE_PARIS, "sort": "dateFin asc", **NEW_CRITERIA}, pg)
        new_ids = set(ids) - all_ids_fin
        all_ids_fin.update(ids)
        print(f"  Page {pg}: nb={nb} items={len(ids)} new={len(new_ids)}")
        if items:
            raw = items[0].get('dateFin',{})
            fin = raw.get('date','')[:10] if isinstance(raw,dict) else ''
            print(f"    Premier: {items[0].get('libelle','')} | dateFin={fin}")
        output["tests"].append({"label": f"ville+dateFin asc page{pg}", "nb": nb, "new_unique": len(new_ids)})
        time.sleep(0.4)

    # ── Test 3 : ligue + critères + sort=dateFin asc ─────────────────────────
    print("\n[3] Ligue + critères + sort=dateFin asc — pages 0,1")
    all_ids_ligue = set()
    for pg in range(2):
        nb, ids, items = call(session, fbid, {
            "recherche_type": "ligue", "cbrappel[]": "57",
            "sort": "dateFin asc", **NEW_CRITERIA
        }, pg)
        new_ids = set(ids) - all_ids_ligue
        all_ids_ligue.update(ids)
        print(f"  Page {pg}: nb={nb} items={len(ids)} new={len(new_ids)}")
        if items:
            raw = items[0].get('dateFin',{})
            fin = raw.get('date','')[:10] if isinstance(raw,dict) else ''
            print(f"    Premier: {items[0].get('libelle','')} | dateFin={fin}")
        output["tests"].append({"label": f"ligue+dateFin asc page{pg}", "nb": nb, "new_unique": len(new_ids)})
        time.sleep(0.4)

    # ── Test 4 : ville Paris SANS critères + sort=_DIST_ — pages 0,1,2 ──────
    print("\n[4] Ville Paris SANS critères (contrôle pagination) — pages 0,1,2")
    all_sans = set()
    for pg in range(3):
        nb, ids, _ = call(session, fbid, {**VILLE_PARIS, "sort": "_DIST_"}, pg)
        new_ids = set(ids) - all_sans
        all_sans.update(ids)
        print(f"  Page {pg}: nb={nb} items={len(ids)} new={len(new_ids)}")
        output["tests"].append({"label": f"ville sans critères page{pg}", "nb": nb, "new_unique": len(new_ids)})
        time.sleep(0.4)

    sans_pagination_ok = len(all_sans) > 30
    print(f"\n  Sans critères unique 3p: {len(all_sans)} — pagination_ok={sans_pagination_ok}")

    # Résumé
    output["ville_avec_criteres_pagination"] = ville_pagination_ok
    output["ville_sans_criteres_pagination"] = sans_pagination_ok
    output["conclusion"] = (
        f"ville+critères pag={'OK' if ville_pagination_ok else 'KO'}, "
        f"ville sans critères pag={'OK' if sans_pagination_ok else 'KO'}"
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
        subprocess.run(["git", "commit", "-m", f"diag_ligue v15 ville+pag [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
