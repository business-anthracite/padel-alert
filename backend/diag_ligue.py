"""
Padel Alert — Diagnostic ligue v8
Diagnostic : "Un choix interdit" = une valeur de checkbox invalide dans ALL_CRITERIA.
Objectif : isoler quel critère est invalide par élimination + tester une recherche bare.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

LIGUES = [
    ("50","AUVERGNE RHONE-ALPES"), ("52","BRETAGNE"),
    ("57","ILE DE FRANCE"), ("62","PROVENCE ALPES COTE D'AZUR"),
]

def get_session():
    print("  Ouverture Ten'Up...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # Dump TOUS les checkboxes et selects du formulaire
        form_values = page.evaluate("""
            () => {
                const res = {};
                document.querySelectorAll('input[type="checkbox"], input[type="radio"], select').forEach(el => {
                    if (el.name) {
                        if (!res[el.name]) res[el.name] = [];
                        const val = el.tagName === 'SELECT'
                            ? Array.from(el.options).map(o => o.value)
                            : el.value;
                        res[el.name].push(val);
                    }
                });
                return res;
            }
        """)
        fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    print(f"  fbid: {(fbid or 'MANQUANT')[:40]}")
    return fbid, cookies, form_values


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


def ajax(session, extra, fbid, page_num=0):
    now = datetime.now()
    params = {
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]":   (now + timedelta(days=90)).strftime("%d/%m/%y"),
        "sort": "_DATE_",
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
        cmds = r.json()
        nb = 0
        msgs = []
        for c in cmds:
            if not isinstance(c, dict): continue
            if c.get("command") == "recherche_tournois_update":
                nb = c.get("results", {}).get("nb_results", 0)
                msgs.append(f"update(nb={nb})")
            elif c.get("command") == "insert":
                txt = str(c.get("data", ""))[:80]
                msgs.append(f"insert({txt})")
        return {"nb": nb, "msgs": msgs, "http": r.status_code, "raw": r.text[:300]}
    except Exception as e:
        return {"nb": 0, "error": str(e)}


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "form_values_from_page": {}, "conclusion": ""}

    print("=== Session Playwright ===")
    fbid, cookies, form_values = get_session()
    output["form_values_from_page"] = form_values
    session = make_session(cookies)

    print("\nValeurs des checkboxes/selects trouvées dans le formulaire:")
    for name, vals in form_values.items():
        print(f"  {name} = {vals}")

    ville_params = {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
        "pratique": "PADEL",
    }

    print("\n=== TEST 1 : Ville BARE (sans critères) ===")
    r = ajax(session, ville_params, fbid)
    print(f"  nb={r['nb']} msgs={r['msgs']}")
    output["tests"].append({"label": "ville bare sans critères", **r})
    time.sleep(0.5)

    # Groupe de critères à tester individuellement
    CRITERIA_GROUPS = {
        "epreuve": {"epreuve[DM]": "DM", "epreuve[DD]": "DD", "epreuve[DX]": "DX"},
        "categorie_age_standard": {
            "categorie_age[910]": "910", "categorie_age[1112]": "1112",
            "categorie_age[1314]": "1314", "categorie_age[1516]": "1516",
            "categorie_age[1718]": "1718", "categorie_age[200]": "200",
        },
        "categorie_age_plus45_55": {
            "categorie_age[345]": "345", "categorie_age[355]": "355",
        },
        "type_competition": {"type[P]": "P", "type[CE]": "CE", "type[CEQ]": "CEQ"},
        "categorie_tournoi": {
            "categorie_tournoi[P25]": "P25", "categorie_tournoi[P50]": "P50",
            "categorie_tournoi[P100]": "P100", "categorie_tournoi[P250]": "P250",
            "categorie_tournoi[P500]": "P500", "categorie_tournoi[P1000]": "P1000",
            "categorie_tournoi[P1500]": "P1500", "categorie_tournoi[P2000]": "P2000",
        },
    }

    print("\n=== TEST 2 : Ville + chaque groupe de critères individuellement ===")
    for grp_name, grp_params in CRITERIA_GROUPS.items():
        r = ajax(session, {**ville_params, **grp_params}, fbid)
        ok = r["nb"] > 0 or not any("interdit" in m for m in r["msgs"])
        print(f"  {'✓' if r['nb']>0 else ('⚠' if ok else '✗')} +{grp_name}: nb={r['nb']} msgs={r['msgs']}")
        output["tests"].append({"label": f"ville + {grp_name}", **r})
        time.sleep(0.4)

    # Tester avec tous les critères sauf les potentiellement invalides
    ALL_CRITERIA_SAFE = {
        "epreuve[DM]": "DM", "epreuve[DD]": "DD", "epreuve[DX]": "DX",
        "categorie_age[910]": "910", "categorie_age[1112]": "1112",
        "categorie_age[1314]": "1314", "categorie_age[1516]": "1516",
        "categorie_age[1718]": "1718", "categorie_age[200]": "200",
        "type[P]": "P", "type[CE]": "CE", "type[CEQ]": "CEQ",
        "categorie_tournoi[P25]": "P25", "categorie_tournoi[P50]": "P50",
        "categorie_tournoi[P100]": "P100", "categorie_tournoi[P250]": "P250",
        "categorie_tournoi[P500]": "P500", "categorie_tournoi[P1000]": "P1000",
        "categorie_tournoi[P1500]": "P1500", "categorie_tournoi[P2000]": "P2000",
    }

    print("\n=== TEST 3 : Ville + tous critères SAUF +45/+55 ===")
    r = ajax(session, {**ville_params, **ALL_CRITERIA_SAFE}, fbid)
    print(f"  nb={r['nb']} msgs={r['msgs']}")
    output["tests"].append({"label": "ville + all SAUF +45/55", **r})
    time.sleep(0.5)

    # Si ville fonctionne, tester ligue
    ville_bare_ok = output["tests"][0]["nb"] > 0
    ville_safe_ok = output["tests"][-1]["nb"] > 0

    if ville_bare_ok or ville_safe_ok:
        best_criteria = ALL_CRITERIA_SAFE if ville_safe_ok else {}
        print("\n=== TEST 4 : Ligue cbrappel[] avec critères valides ===")
        for lid, name in LIGUES:
            r = ajax(session, {
                "recherche_type": "ligue",
                "cbrappel[]": lid,
                "pratique": "PADEL",
                **best_criteria,
            }, fbid)
            print(f"  {'✓' if r['nb']>0 else '✗'} id={lid} '{name}': nb={r['nb']} msgs={r['msgs']}")
            output["tests"].append({"label": f"ligue id={lid} {name}", "ligue_id": lid, **r})
            time.sleep(0.4)

    # Résumé
    t1 = output["tests"][0]
    t_safe = next((t for t in output["tests"] if "SAUF" in t["label"]), {})
    t_ligue = [t for t in output["tests"] if "ligue" in t["label"] and t.get("nb", 0) > 0]

    print(f"\n=== RÉSUMÉ ===")
    for t in output["tests"]:
        nb = t.get("nb", 0)
        interdit = any("interdit" in m for m in t.get("msgs", []))
        sym = "✓" if nb > 0 else ("✗(interdit)" if interdit else "✗")
        print(f"  {sym} '{t['label']}' → nb={nb}")

    output["conclusion"] = (
        f"ville_bare={'OK' if t1.get('nb',0)>0 else 'KO'}, "
        f"ville_sans_45_55={'OK' if t_safe.get('nb',0)>0 else 'KO'}, "
        f"ligues_ok={len(t_ligue)}"
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
        subprocess.run(["git", "commit", "-m", f"diag_ligue v8 isolation criteres [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
