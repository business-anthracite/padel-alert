"""
Padel Alert — Diagnostic ligue v7
Découverte v6 : "Un choix interdit" = form_token CSRF manquant.
Ten'Up a ajouté form_token entre le 05/05 et 06/05/2026.
Ce diagnostic : extrait form_token via Playwright + teste ville (contrôle) + ligue (cbrappel[]).
"""
import json, time, subprocess, os, re
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"
RAYON = "50"

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

LIGUES = [
    ("50","AUVERGNE RHONE-ALPES"), ("51","BOURGOGNE FRANCHE COMTE"),
    ("52","BRETAGNE"),             ("53","CENTRE VAL DE LOIRE"),
    ("54","CORSE"),                ("55","GRAND EST"),
    ("63","GUADELOUPE ST MARTIN ST BARTH"), ("64","GUYANE"),
    ("56","HAUTS DE FRANCE"),      ("57","ILE DE FRANCE"),
    ("65","MARTINIQUE"),           ("58","NORMANDIE"),
    ("59","NOUVELLE AQUITAINE"),   ("66","NOUVELLE CALEDONIE"),
    ("60","OCCITANIE"),            ("61","PAYS DE LA LOIRE"),
    ("62","PROVENCE ALPES COTE D'AZUR"), ("67","REUNION - MAYOTTE"),
]


def get_session():
    """Récupère fbid + form_token + cookies via Playwright."""
    print("  Ouverture Ten'Up...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        tokens = page.evaluate("""
            () => ({
                form_build_id: document.querySelector('input[name="form_build_id"]')?.value || null,
                form_token:    document.querySelector('input[name="form_token"]')?.value    || null,
                form_id:       document.querySelector('input[name="form_id"]')?.value       || null,
                all_hidden: Array.from(document.querySelectorAll('input[type="hidden"]'))
                               .map(el => ({name: el.name, value: el.value.substring(0,60)}))
                               .filter(el => el.name)
            })
        """)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    print(f"  form_build_id : {(tokens['form_build_id'] or 'MANQUANT')[:40]}")
    print(f"  form_token    : {(tokens['form_token'] or 'MANQUANT')[:40]}")
    print(f"  form_id       : {tokens['form_id']}")
    print(f"  hidden inputs : {[h['name'] for h in tokens['all_hidden']]}")
    return tokens, cookies


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


def ajax_call(session, extra_params, tokens, page_num=0):
    now = datetime.now()
    params = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": tokens.get("form_id") or "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": tokens["form_build_id"],
        "page": str(page_num),
    }
    # Inclure form_token si présent
    if tokens.get("form_token"):
        params["form_token"] = tokens["form_token"]
    params.update(extra_params)

    try:
        r = session.post(TENUP_AJAX, data=params, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        result = {"http": r.status_code, "nb_results": 0, "nb_items": 0, "commands": [], "raw": r.text[:600]}
        for cmd in cmds:
            if not isinstance(cmd, dict): continue
            cn = cmd.get("command","")
            if cn == "recherche_tournois_update":
                res = cmd.get("results", {})
                result["nb_results"] = res.get("nb_results", 0)
                result["nb_items"]   = len(res.get("items", []))
                result["first_id"]   = (res.get("items") or [{}])[0].get("id")
                result["commands"].append(f"recherche_tournois_update(nb={result['nb_results']})")
            elif cn == "insert":
                data_preview = str(cmd.get("data",""))[:120]
                result["commands"].append(f"insert({data_preview})")
            else:
                result["commands"].append(cn)
        return result
    except Exception as e:
        return {"error": str(e)}


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tokens_found": {},
        "tests": [],
        "working": [],
        "conclusion": "",
    }

    print("=== Session Playwright ===")
    tokens, cookies = get_session()
    output["tokens_found"] = {
        "form_build_id_present": bool(tokens.get("form_build_id")),
        "form_token_present":    bool(tokens.get("form_token")),
        "form_id":               tokens.get("form_id"),
        "all_hidden_names":      [h["name"] for h in tokens.get("all_hidden", [])],
    }
    session = make_session(cookies)

    print("\n=== Tests AJAX ===")

    # 1. Contrôle ville Paris (doit fonctionner)
    print("\n[1] Contrôle ville Paris 50km")
    r = ajax_call(session, {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": RAYON,
    }, tokens)
    print(f"  nb={r.get('nb_results')} commands={r.get('commands')}")
    output["tests"].append({"label": "ville Paris 50km", **r})
    time.sleep(0.5)

    # 2. Ligue cbrappel[]=57 IDF
    print("\n[2] Ligue cbrappel[]=57 (ILE DE FRANCE)")
    r = ajax_call(session, {
        "recherche_type": "ligue",
        "cbrappel[]": "57",
    }, tokens)
    print(f"  nb={r.get('nb_results')} commands={r.get('commands')}")
    print(f"  raw: {r.get('raw','')[:300]}")
    output["tests"].append({"label": "ligue cbrappel[]=57 IDF", **r})
    time.sleep(0.5)

    # 3. Ligue cbrappel[]=62 PACA
    print("\n[3] Ligue cbrappel[]=62 (PACA)")
    r = ajax_call(session, {
        "recherche_type": "ligue",
        "cbrappel[]": "62",
    }, tokens)
    print(f"  nb={r.get('nb_results')} commands={r.get('commands')}")
    output["tests"].append({"label": "ligue cbrappel[]=62 PACA", **r})
    time.sleep(0.5)

    # Si ligue fonctionne, tester la pagination
    ligue_idf = output["tests"][1]
    if ligue_idf.get("nb_results", 0) > 30:
        print("\n[4] Pagination IDF page 1")
        r2 = ajax_call(session, {"recherche_type": "ligue", "cbrappel[]": "57"}, tokens, page_num=1)
        pagination_ok = (ligue_idf.get("first_id") != r2.get("first_id") and r2.get("nb_items", 0) > 0)
        print(f"  nb={r2.get('nb_results')} items={r2.get('nb_items')} pagination_ok={pagination_ok}")
        output["tests"].append({"label": "ligue IDF page 1", "pagination_ok": pagination_ok, **r2})
        time.sleep(0.5)

    # 4. Si ville fonctionne mais ligue non → afficher raw ligue pour debug
    if output["tests"][0].get("nb_results", 0) > 0 and output["tests"][1].get("nb_results", 0) == 0:
        print("\n  Ville OK mais ligue KO — raw ligue pour debug:")
        print(f"  {output['tests'][1].get('raw', '')[:500]}")

    # 5. Si tout OK : tester les 18 ligues
    if output["tests"][1].get("nb_results", 0) > 0:
        print("\n[5] Test toutes les 18 ligues")
        for lid, name in LIGUES:
            r = ajax_call(session, {"recherche_type": "ligue", "cbrappel[]": lid}, tokens)
            nb = r.get("nb_results", 0)
            pg = None
            if nb > 30:
                time.sleep(0.3)
                r1 = ajax_call(session, {"recherche_type": "ligue", "cbrappel[]": lid}, tokens, page_num=1)
                pg = (r.get("first_id") != r1.get("first_id") and r1.get("nb_items", 0) > 0)
            print(f"  {'✓' if nb>0 else '✗'} id={lid} '{name}' → {nb} résultats | pagination={pg}")
            output["tests"].append({"label": f"ligue id={lid} {name}", "ligue_id": lid, "pagination_ok": pg, **r})
            if nb > 0:
                output["working"].append({"id": lid, "name": name, "nb_results": nb, "pagination_ok": pg})
            time.sleep(0.3)

    # Résumé
    ville_ok   = output["tests"][0].get("nb_results", 0) > 0
    ligue_ok   = output["tests"][1].get("nb_results", 0) > 0
    token_present = bool(tokens.get("form_token"))
    print(f"\n=== RÉSUMÉ ===")
    print(f"form_token présent : {token_present}")
    print(f"Ville contrôle     : {'✓' if ville_ok else '✗'} ({output['tests'][0].get('nb_results',0)} résultats)")
    print(f"Ligue IDF          : {'✓' if ligue_ok else '✗'} ({output['tests'][1].get('nb_results',0)} résultats)")
    print(f"Ligues avec résultats : {len(output['working'])}/18")

    output["conclusion"] = (
        f"form_token={'OUI' if token_present else 'NON'}, "
        f"ville={'OK' if ville_ok else 'KO'}, "
        f"ligue_IDF={'OK' if ligue_ok else 'KO'}, "
        f"working={len(output['working'])}/18"
    )

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v7 form_token [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
