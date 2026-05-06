"""
Padel Alert — Diagnostic ligue v6
Tourne UNE seule fois (workflow_dispatch) pour :
1. Découvrir les codes ligue dans le dropdown Ten'Up
2. Tester page 0 et page 1 pour chaque ligue cible
3. Confirmer que la pagination par ligue individuelle fonctionne
Résultat commité dans data/diag_ligue.json
"""
import json, re, math, time, subprocess, os
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

TARGET_LIGUE_NAMES = [
    "AUVERGNE RHONE-ALPES",
    "BOURGOGNE FRANCHE COMTE",
    "BRETAGNE",
    "CENTRE VAL DE LOIRE",
    "CORSE",
    "GRAND EST",
    "GUADELOUPE ST MARTIN ST BARTH",
    "GUYANE",
    "HAUTS DE FRANCE",
    "ILE DE FRANCE",
    "MARTINIQUE",
    "NORMANDIE",
    "NOUVELLE AQUITAINE",
    "NOUVELLE CALEDONIE",
    "OCCITANIE",
    "PAYS DE LA LOIRE",
    "PROVENCE ALPES COTE D'AZUR",
    "REUNION - MAYOTTE",
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


def normalize(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9 ]", " ", s.upper()).strip()


def discover_form_and_ligues():
    """Ouvre Ten'Up avec Playwright, découvre la structure du formulaire et les codes ligue."""
    result = {
        "form_fields": [],
        "ligue_select_name": None,
        "ligue_options": [],
        "comite_select_name": None,
        "comite_options_sample": [],
        "fbid": None,
        "cookies": {},
        "html_selects": [],
        "html_inputs_recherche_type": [],
        "all_input_names": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        print("  Ouverture Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        fbid = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        result["fbid"] = fbid
        result["cookies"] = {c["name"]: c["value"] for c in ctx.cookies()}

        # Dump tous les inputs de la page initiale
        all_fields = page.evaluate("""
            () => Array.from(document.querySelectorAll('input, select, textarea')).map(el => ({
                tag: el.tagName.toLowerCase(),
                name: el.name || '',
                id: el.id || '',
                type: el.type || '',
                value: el.value || '',
                visible: el.offsetParent !== null,
                options: el.tagName === 'SELECT'
                    ? Array.from(el.options).map(o => ({v: o.value, t: o.text.trim()}))
                    : null
            }))
        """)
        result["all_input_names"] = [f["name"] for f in all_fields if f["name"]]
        result["html_selects"] = [f for f in all_fields if f["tag"] == "select"]
        result["html_inputs_recherche_type"] = [f for f in all_fields if "recherche" in f["name"].lower()]

        # Chercher select ligue dans l'état initial
        for f in all_fields:
            if f["tag"] == "select" and "ligue" in (f["name"] + f["id"]).lower():
                result["ligue_select_name"] = f["name"]
                result["ligue_options"] = f["options"] or []
                print(f"  Select ligue trouvé (initial) : name='{f['name']}', {len(result['ligue_options'])} options")
                break

        # Essayer de cliquer le radio "ligue" pour révéler les options
        ligue_radio_clicked = False
        for f in all_fields:
            if f["tag"] == "input" and f["type"] == "radio" and "ligue" in (f["value"] + f["name"] + f["id"]).lower():
                try:
                    sel = f'[name="{f["name"]}"][value="{f["value"]}"]'
                    page.click(sel, timeout=3000)
                    page.wait_for_timeout(2500)
                    ligue_radio_clicked = True
                    print(f"  Cliqué radio name='{f['name']}' value='{f['value']}'")
                    break
                except Exception as e:
                    print(f"  Impossible de cliquer radio '{f['name']}'='{f['value']}': {e}")

        if not ligue_radio_clicked:
            # Essayer par texte
            for txt in ["Ligue", "Par ligue", "ligue"]:
                try:
                    page.click(f'text="{txt}"', timeout=2000)
                    page.wait_for_timeout(2500)
                    ligue_radio_clicked = True
                    print(f"  Cliqué '{txt}' par texte")
                    break
                except:
                    pass

        # Re-dump après click radio
        all_fields_after = page.evaluate("""
            () => Array.from(document.querySelectorAll('input, select, textarea')).map(el => ({
                tag: el.tagName.toLowerCase(),
                name: el.name || '',
                id: el.id || '',
                type: el.type || '',
                value: el.value || '',
                visible: el.offsetParent !== null,
                options: el.tagName === 'SELECT'
                    ? Array.from(el.options).map(o => ({v: o.value, t: o.text.trim()}))
                    : null
            }))
        """)

        for f in all_fields_after:
            if f["tag"] == "select" and "ligue" in (f["name"] + f["id"]).lower() and not result["ligue_options"]:
                result["ligue_select_name"] = f["name"]
                result["ligue_options"] = f["options"] or []
                print(f"  Select ligue trouvé (après radio) : name='{f['name']}', {len(result['ligue_options'])} options")
                break

        # Si on a les options ligue, sélectionner ILE DE FRANCE pour voir les comités
        if result["ligue_options"]:
            ile_de_france_opt = next(
                (o for o in result["ligue_options"] if "ILE DE FRANCE" in normalize(o.get("t", "")) or "IDF" == o.get("v", "").upper()),
                None
            )
            if not ile_de_france_opt and result["ligue_options"]:
                ile_de_france_opt = result["ligue_options"][1] if len(result["ligue_options"]) > 1 else result["ligue_options"][0]

            if ile_de_france_opt and result["ligue_select_name"]:
                try:
                    page.select_option(f'select[name="{result["ligue_select_name"]}"]', value=ile_de_france_opt["v"])
                    page.wait_for_timeout(3000)
                    print(f"  Sélectionné ligue : {ile_de_france_opt['t']} (v={ile_de_france_opt['v']})")

                    # Dump comités apparus
                    comite_fields = page.evaluate("""
                        () => Array.from(document.querySelectorAll('input, select')).map(el => ({
                            tag: el.tagName.toLowerCase(),
                            name: el.name || '',
                            id: el.id || '',
                            type: el.type || '',
                            value: el.value || '',
                            visible: el.offsetParent !== null,
                            options: el.tagName === 'SELECT'
                                ? Array.from(el.options).map(o => ({v: o.value, t: o.text.trim()}))
                                : null
                        }))
                    """)
                    for f2 in comite_fields:
                        if "comite" in (f2["name"] + f2["id"]).lower() and f2["tag"] == "select":
                            result["comite_select_name"] = f2["name"]
                            result["comite_options_sample"] = (f2["options"] or [])[:20]
                            print(f"  Select comité : name='{f2['name']}', {len(f2['options'] or [])} options")
                            break
                        if "comite" in (f2["name"] + f2["id"]).lower() and f2["tag"] == "input":
                            result["comite_options_sample"].append({"tag": "input", "name": f2["name"], "value": f2["value"], "type": f2["type"]})
                except Exception as e:
                    print(f"  Erreur sélection ligue IDF: {e}")

        # Dump full form HTML pour inspection
        form_html = page.evaluate("""
            () => {
                const form = document.querySelector('form');
                return form ? form.outerHTML.substring(0, 8000) : 'form not found';
            }
        """)
        result["form_html_excerpt"] = form_html

        # Dump all select/input field names pour debug
        result["form_fields"] = [
            {"name": f["name"], "id": f["id"], "type": f["type"], "tag": f["tag"], "visible": f["visible"]}
            for f in all_fields_after if f["name"]
        ]

        browser.close()

    return result


def test_ajax_ligue(cookies, fbid, ligue_code, ligue_name):
    """Teste pages 0 et 1 pour un code ligue donné. Retourne dict avec résultats."""
    now = datetime.now()
    date_start = now.strftime("%d/%m/%y")
    date_end   = (now + timedelta(days=90)).strftime("%d/%m/%y")

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": TENUP_BASE,
        "Referer": TENUP_SEARCH,
        "X-Requested-With": "XMLHttpRequest",
    })
    for k, v in cookies.items():
        s.cookies.set(k, v)

    base_params = {
        "recherche_type": "ligue",
        "ligue": ligue_code,
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]": date_end,
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
    }

    def do_request(page_num):
        params = {**base_params, "page": str(page_num)}
        try:
            resp = s.post(TENUP_AJAX, data=params, timeout=45)
            resp.raise_for_status()
            raw_cmds = resp.json()
            for cmd in raw_cmds:
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return {
                        "http_status": resp.status_code,
                        "nb_results": res.get("nb_results", 0),
                        "nb_items": len(res.get("items", [])),
                        "first_item_id": res.get("items", [{}])[0].get("id") if res.get("items") else None,
                        "commands": [c.get("command") for c in raw_cmds if isinstance(c, dict)],
                    }
            return {
                "http_status": resp.status_code,
                "nb_results": 0,
                "nb_items": 0,
                "commands": [c.get("command") for c in raw_cmds if isinstance(c, dict)],
                "raw_excerpt": resp.text[:500],
            }
        except Exception as e:
            return {"error": str(e)}

    result = {"ligue_name": ligue_name, "ligue_code": ligue_code}
    print(f"  Test AJAX ligue='{ligue_code}' ({ligue_name})...")
    result["page_0"] = do_request(0)
    print(f"    page_0: {result['page_0']}")

    nb_total = result["page_0"].get("nb_results", 0)
    if nb_total > 30:
        time.sleep(0.5)
        result["page_1"] = do_request(1)
        print(f"    page_1: {result['page_1']}")
        # Vérifier que page_1 a des items DIFFÉRENTS de page_0
        if result["page_0"].get("first_item_id") and result["page_1"].get("first_item_id"):
            result["pagination_ok"] = (result["page_0"]["first_item_id"] != result["page_1"]["first_item_id"])
        else:
            result["pagination_ok"] = None
    else:
        result["pagination_ok"] = None

    return result


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "discovery": {},
        "ligue_tests": [],
        "matched_ligues": [],
        "recommendations": [],
    }

    print("=== PHASE 1 : Découverte formulaire ===")
    disc = discover_form_and_ligues()
    output["discovery"] = {
        k: v for k, v in disc.items()
        if k not in ("cookies",)  # ne pas sauvegarder les cookies
    }
    fbid    = disc["fbid"]
    cookies = disc["cookies"]
    ligue_options = disc["ligue_options"]

    print(f"\nform_build_id: {fbid}")
    print(f"Ligues trouvées ({len(ligue_options)}) :")
    for o in ligue_options:
        print(f"  value='{o.get('v','')}' text='{o.get('t','')}'")

    print("\n=== PHASE 2 : Matching ligues cibles ===")
    matched = []
    for target in TARGET_LIGUE_NAMES:
        norm_t = normalize(target)
        found  = next((o for o in ligue_options if normalize(o.get("t", "")) == norm_t), None)
        if not found:
            found = next((o for o in ligue_options if norm_t in normalize(o.get("t", "")) or normalize(o.get("t", "")) in norm_t), None)
        if found:
            matched.append({"target": target, "code": found["v"], "label": found["t"]})
            print(f"  ✓ {target} → {found['t']} (code={found['v']})")
        else:
            matched.append({"target": target, "code": None, "label": None})
            print(f"  ✗ {target} → NON TROUVÉ")
    output["matched_ligues"] = matched

    print("\n=== PHASE 3 : Tests AJAX paginés ===")
    # Tester 3 ligues : ILE DE FRANCE (dense), PACA (dense), BRETAGNE (moyen)
    test_targets = [
        m for m in matched
        if m["code"] and m["target"] in ("ILE DE FRANCE", "PROVENCE ALPES COTE D'AZUR", "BRETAGNE")
    ]
    if not test_targets and matched:
        # Fallback : tester les 3 premières ligues trouvées
        test_targets = [m for m in matched if m["code"]][:3]

    for m in test_targets:
        test_res = test_ajax_ligue(cookies, fbid, m["code"], m["target"])
        output["ligue_tests"].append(test_res)
        time.sleep(1)

    # Test avec ligue=ALL pour comparaison (connu comme étant limité)
    print("\n  Test ligue=ALL (comparaison)...")
    all_test = test_ajax_ligue(cookies, fbid, "ALL", "ALL_LIGUES")
    output["ligue_all_test"] = all_test

    # Recommandations
    working = [t for t in output["ligue_tests"] if t.get("page_0", {}).get("nb_results", 0) > 0]
    pagination_ok = [t for t in working if t.get("pagination_ok") is True]

    output["recommendations"] = {
        "ligues_with_results": len(working),
        "ligues_pagination_ok": len(pagination_ok),
        "total_matched": len([m for m in matched if m["code"]]),
        "total_unmatched": len([m for m in matched if not m["code"]]),
    }

    print(f"\n=== RÉSUMÉ ===")
    print(f"Ligues trouvées dans Ten'Up : {len(ligue_options)}")
    print(f"Ligues cibles matchées : {output['recommendations']['total_matched']}/{len(TARGET_LIGUE_NAMES)}")
    print(f"Tests avec résultats : {output['recommendations']['ligues_with_results']}/{len(test_targets)}")
    print(f"Pagination fonctionne : {output['recommendations']['ligues_pagination_ok']}/{len(working)}")

    # Écrire les résultats
    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nRésultats sauvegardés dans data/diag_ligue.json")

    # Commit
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
