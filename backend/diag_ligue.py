"""
Padel Alert — Diagnostic ligue v10
Fix : sort="_DIST_" (valeur valide découverte en v9) au lieu de "_DATE_" invalide.
+ force=True pour cliquer PADEL radio caché
+ test ligue avec sort="dateDebut asc"
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

LIGUES = [
    ("57","ILE DE FRANCE"), ("62","PROVENCE ALPES COTE D'AZUR"),
    ("52","BRETAGNE"),      ("50","AUVERGNE RHONE-ALPES"),
]
ALL_LIGUES = [
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

        fbid = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    print(f"  fbid: {(fbid or 'MANQUANT')[:40]}")
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


def ajax(session, params):
    try:
        r = session.post(TENUP_AJAX, data=params, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        nb, msgs = 0, []
        for c in cmds:
            if not isinstance(c, dict): continue
            if c.get("command") == "recherche_tournois_update":
                nb = c.get("results", {}).get("nb_results", 0)
                msgs.append(f"update(nb={nb})")
                first_id = (c.get("results", {}).get("items") or [{}])[0].get("id")
            elif c.get("command") == "insert":
                msgs.append(f"insert({str(c.get('data',''))[:80]})")
            else:
                msgs.append(c.get("command", "?"))
        return {"nb": nb, "msgs": msgs, "http": r.status_code}
    except Exception as e:
        return {"nb": 0, "error": str(e)}


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "working_ligues": [], "conclusion": ""}

    print("=== Session ===")
    fbid, cookies = get_session()
    session = make_session(cookies)

    now = datetime.now()
    ds  = now.strftime("%d/%m/%y")
    de  = (now + timedelta(days=90)).strftime("%d/%m/%y")

    base_common = {
        "pratique": "PADEL",
        "date[start]": ds, "date[end]": de,
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": "0",
    }

    # ── Test 1 : Ville Paris avec sort="_DIST_" (valeur valide) ──────────────
    print("\n[1] Ville Paris sort=_DIST_")
    r = ajax(session, {**base_common,
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
        "sort": "_DIST_",
    })
    print(f"  → nb={r['nb']} msgs={r.get('msgs')}")
    output["tests"].append({"label": "ville Paris sort=_DIST_", **r})
    time.sleep(0.5)

    # ── Test 2 : Ville Paris sort="dateDebut asc" ────────────────────────────
    print("\n[2] Ville Paris sort='dateDebut asc'")
    r = ajax(session, {**base_common,
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
        "sort": "dateDebut asc",
    })
    print(f"  → nb={r['nb']} msgs={r.get('msgs')}")
    output["tests"].append({"label": "ville Paris sort=dateDebut asc", **r})
    time.sleep(0.5)

    ville_ok   = any(t["nb"] > 0 for t in output["tests"][:2])
    ville_sort = "dateDebut asc" if output["tests"][1]["nb"] > 0 else ("_DIST_" if output["tests"][0]["nb"] > 0 else None)
    print(f"\n  ville OK={ville_ok}, meilleur sort={ville_sort}")

    # ── Tests ligue avec sort valides ────────────────────────────────────────
    for sort_val in ["dateDebut asc", "_DIST_"]:
        print(f"\n[3] Ligue IDF cbrappel[]=57 sort='{sort_val}'")
        r = ajax(session, {**base_common,
            "recherche_type": "ligue",
            "cbrappel[]": "57",
            "sort": sort_val,
        })
        print(f"  → nb={r['nb']} msgs={r.get('msgs')}")
        output["tests"].append({"label": f"ligue IDF sort={sort_val}", **r})
        time.sleep(0.4)
        if r["nb"] > 0:
            break

    ligue_ok   = any(t["nb"] > 0 and "ligue" in t["label"] for t in output["tests"])
    ligue_sort = next((t["label"].split("sort=")[1] for t in output["tests"] if t.get("nb",0)>0 and "ligue" in t["label"]), None)

    # ── Si ligue fonctionne : tester les 18 ligues ───────────────────────────
    if ligue_ok:
        print(f"\n[4] Test 18 ligues (sort='{ligue_sort}')")
        for lid, name in ALL_LIGUES:
            r0 = ajax(session, {**base_common, "recherche_type": "ligue", "cbrappel[]": lid, "sort": ligue_sort})
            nb = r0["nb"]
            pg_ok = None
            if nb > 30:
                time.sleep(0.3)
                r1 = ajax(session, {**base_common, "recherche_type": "ligue", "cbrappel[]": lid, "sort": ligue_sort, "page": "1"})
                pg_ok = r1["nb"] > 0
            print(f"  {'✓' if nb>0 else '✗'} id={lid} '{name}': {nb} résultats | p.1={pg_ok}")
            output["tests"].append({"label": f"ligue {lid} {name}", "ligue_id": lid, "pagination_ok": pg_ok, **r0})
            if nb > 0:
                output["working_ligues"].append({"id": lid, "name": name, "nb_results": nb, "pagination_ok": pg_ok})
            time.sleep(0.3)

    # Résumé
    print(f"\n=== RÉSUMÉ ===")
    print(f"Ville : {'✓' if ville_ok else '✗'} ({ville_sort})")
    print(f"Ligue : {'✓' if ligue_ok else '✗'} ({ligue_sort})")
    print(f"Ligues avec résultats : {len(output['working_ligues'])}/18")

    output["conclusion"] = (
        f"ville={'OK('+ville_sort+')' if ville_ok else 'KO'}, "
        f"ligue={'OK('+ligue_sort+')' if ligue_ok else 'KO'}, "
        f"working={len(output['working_ligues'])}/18"
    )

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("Sauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v10 sort_fix [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
