"""
Padel Alert — Diagnostic ligue v3
Deux approches parallèles :
1. Playwright : click sur le label visible + force=True + screenshot + capture HTML complet
2. AJAX direct : teste ~20 codes ligue FFT classiques pour trouver ceux qui marchent
Résultat commité dans data/diag_ligue.json + data/diag_screenshot.png
"""
import json, re, math, time, subprocess, os, base64
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

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

# Codes ligue FFT à tester par AJAX (classiques 2-3 lettres + alternatives)
CANDIDATE_CODES = [
    ("IDF",   "Ile-de-France"),
    ("PACA",  "Provence-Alpes-Côte d'Azur"),
    ("ARA",   "Auvergne-Rhône-Alpes"),
    ("OCC",   "Occitanie"),
    ("NA",    "Nouvelle-Aquitaine"),
    ("HDF",   "Hauts-de-France"),
    ("GE",    "Grand Est"),
    ("BRE",   "Bretagne"),
    ("NOR",   "Normandie"),
    ("PDL",   "Pays de la Loire"),
    ("BFC",   "Bourgogne-Franche-Comté"),
    ("CVL",   "Centre-Val de Loire"),
    ("COR",   "Corse"),
    ("MAR",   "Martinique"),
    ("GUA",   "Guadeloupe"),
    ("GUY",   "Guyane"),
    ("REU",   "Réunion-Mayotte"),
    ("NCAL",  "Nouvelle-Calédonie"),
    ("ALL",   "Toutes ligues (ALL)"),
    ("",      "Vide"),
    ("ligue", "Valeur 'ligue'"),
]


def explore_with_playwright():
    """Ouvre Ten'Up, essaie de cliquer le label Ligue, capture HTML + screenshot."""
    result = {
        "fbid": None,
        "cookies": {},
        "html_initial_selects": [],
        "html_initial_radios": [],
        "click_label_success": False,
        "click_force_success": False,
        "ajax_reqs_after_click": [],
        "html_after_click_selects": [],
        "html_after_click_ligue_elements": [],
        "html_full_excerpt": "",
        "screenshot_b64": None,
        "error": None,
    }

    ajax_captured = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="fr-FR",
            )
            page = ctx.new_page()

            def on_request(req):
                if "/system/ajax" in req.url and req.method == "POST":
                    ajax_captured.append({"post_data": req.post_data or "", "t": datetime.utcnow().isoformat()})
            page.on("request", on_request)

            print("  Chargement Ten'Up...")
            page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)

            fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            result["fbid"]    = fbid
            result["cookies"] = cookies
            print(f"  fbid: {fbid[:30] if fbid else 'MANQUANT'}")

            # Dump selects et radios initiaux
            result["html_initial_selects"] = page.evaluate("""
                () => Array.from(document.querySelectorAll('select')).map(s => ({
                    name: s.name, id: s.id, opts: s.options.length
                }))
            """)
            result["html_initial_radios"] = page.evaluate("""
                () => Array.from(document.querySelectorAll('input[type="radio"]')).map(r => ({
                    name: r.name, value: r.value, id: r.id,
                    visible: r.offsetParent !== null,
                    label: document.querySelector('label[for="'+r.id+'"]')?.textContent?.trim() || ''
                }))
            """)

            # ── Approche 1 : cliquer le label visible ─────────────────────────
            try:
                label = page.query_selector('label[for="edit-recherche-type-ligue"]')
                if label:
                    label.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except:
                        page.wait_for_timeout(4000)
                    result["click_label_success"] = True
                    print("  Label 'Ligue' cliqué avec succès")
                else:
                    print("  Label pour ligue non trouvé, essai texte...")
                    page.click('label:has-text("Ligue"), text=Ligue', timeout=5000)
                    page.wait_for_timeout(4000)
                    result["click_label_success"] = True
            except Exception as e:
                print(f"  Erreur click label: {e}")

            # ── Approche 2 : force=True sur le radio caché ────────────────────
            if not result["click_label_success"]:
                try:
                    page.click('#edit-recherche-type-ligue', force=True, timeout=5000)
                    page.wait_for_timeout(4000)
                    result["click_force_success"] = True
                    print("  Radio ligue cliqué avec force=True")
                except Exception as e:
                    print(f"  Erreur force click: {e}")

            # ── Approche 3 : JS direct ────────────────────────────────────────
            if not result["click_label_success"] and not result["click_force_success"]:
                try:
                    page.evaluate("""
                        () => {
                            const r = document.querySelector('#edit-recherche-type-ligue');
                            if (r) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles:true})); }
                        }
                    """)
                    page.wait_for_timeout(4000)
                    print("  Radio ligue activé via JS")
                except Exception as e:
                    print(f"  Erreur JS: {e}")

            result["ajax_reqs_after_click"] = ajax_captured.copy()
            print(f"  AJAX reqs capturées après click: {len(ajax_captured)}")

            # ── Dump HTML complet et selects après click ──────────────────────
            html = page.content()
            result["html_full_excerpt"] = html[:60000]

            result["html_after_click_selects"] = page.evaluate("""
                () => Array.from(document.querySelectorAll('select')).map(s => ({
                    name: s.name, id: s.id, visible: s.offsetParent !== null, opts: s.options.length,
                    options: Array.from(s.options).map(o => ({v: o.value, t: o.text.trim()}))
                }))
            """)

            # Tous éléments avec "ligue" dans leurs attributs
            result["html_after_click_ligue_elements"] = page.evaluate("""
                () => {
                    const res = [];
                    document.querySelectorAll('*').forEach(el => {
                        const attrs = Array.from(el.attributes||[]).map(a => a.name+'='+a.value).join(' ');
                        if (attrs.toLowerCase().includes('ligue')) {
                            res.push({
                                tag: el.tagName, name: el.getAttribute('name')||'',
                                id: el.getAttribute('id')||'',
                                class: (el.getAttribute('class')||'').substring(0,60),
                                visible: el.offsetParent !== null,
                                value: el.tagName==='SELECT' ? el.value : (el.getAttribute('value')||''),
                                innerText: (el.innerText||'').trim().substring(0,80),
                                options: el.tagName==='SELECT'
                                    ? Array.from(el.options).map(o=>({v:o.value,t:o.text.trim()}))
                                    : null
                            });
                        }
                    });
                    return res.slice(0,60);
                }
            """)

            # Screenshot
            try:
                os.makedirs("data", exist_ok=True)
                page.screenshot(path="data/diag_screenshot.png", full_page=False)
                with open("data/diag_screenshot.png", "rb") as f:
                    result["screenshot_b64"] = base64.b64encode(f.read()).decode()
                print("  Screenshot capturé")
            except Exception as e:
                print(f"  Screenshot erreur: {e}")

            browser.close()

    except Exception as e:
        result["error"] = str(e)
        print(f"  Erreur Playwright: {e}")

    return result


def ajax_test(cookies, fbid, code, name):
    """Teste un code ligue sur l'endpoint AJAX. Retourne dict résultat."""
    now = datetime.now()
    ds  = now.strftime("%d/%m/%y")
    de  = (now + timedelta(days=90)).strftime("%d/%m/%y")

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

    def req(page_num):
        params = {
            "recherche_type": "ligue", "ligue": code,
            "pratique": "PADEL", "date[start]": ds, "date[end]": de,
            **ALL_CRITERIA, "sort": "_DATE_",
            "form_id": "recherche_tournois_form",
            "_triggering_element_name": "submit_main",
            "_triggering_element_value": "Rechercher",
            "form_build_id": fbid, "page": str(page_num),
        }
        try:
            r = s.post(TENUP_AJAX, data=params, timeout=45)
            r.raise_for_status()
            cmds = r.json()
            for cmd in cmds:
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return {
                        "http": r.status_code, "nb_results": res.get("nb_results", 0),
                        "nb_items": len(res.get("items", [])),
                        "first_id": (res.get("items") or [{}])[0].get("id"),
                    }
            return {"http": r.status_code, "nb_results": 0, "nb_items": 0,
                    "commands": [c.get("command") for c in cmds if isinstance(c, dict)],
                    "raw": r.text[:400]}
        except Exception as e:
            return {"error": str(e)}

    r0 = req(0)
    nb = r0.get("nb_results", 0)
    result = {"code": code, "name": name, "page_0": r0}

    if nb > 30:
        time.sleep(0.4)
        r1 = req(1)
        result["page_1"] = r1
        result["pagination_ok"] = (
            r0.get("first_id") is not None and r1.get("first_id") is not None
            and r0["first_id"] != r1["first_id"]
        )

    return result


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "playwright": {},
        "ajax_tests": [],
        "working_codes": [],
    }

    print("=== PHASE 1 : Exploration Playwright ===")
    pw = explore_with_playwright()
    # Ne pas sauvegarder cookies ni screenshot_b64 dans le JSON principal
    pw_clean = {k: v for k, v in pw.items() if k not in ("cookies", "screenshot_b64", "html_full_excerpt")}
    output["playwright"] = pw_clean
    output["html_excerpt"] = pw.get("html_full_excerpt", "")[:30000]

    fbid    = pw.get("fbid")
    cookies = pw.get("cookies", {})

    print(f"\nfbid: {fbid}")
    print(f"Selects après click: {[s['name'] for s in pw.get('html_after_click_selects', [])]}")
    print(f"Éléments ligue trouvés: {len(pw.get('html_after_click_ligue_elements', []))}")
    for el in pw.get("html_after_click_ligue_elements", []):
        print(f"  <{el['tag']}> name='{el['name']}' id='{el['id']}' visible={el['visible']} opts={len(el.get('options') or [])} text='{el['innerText'][:50]}'")

    # Vérifier si un select ligue a été découvert
    discovered_codes = []
    for s in pw.get("html_after_click_selects", []):
        if "ligue" in (s.get("name","") + s.get("id","")).lower() and s.get("options"):
            print(f"  ✓ Select ligue trouvé: {s['name']}, {len(s['options'])} options")
            for o in s["options"]:
                discovered_codes.append((o["v"], f"découvert: {o['t']}"))
    for el in pw.get("html_after_click_ligue_elements", []):
        if el.get("options"):
            for o in (el["options"] or []):
                if o.get("v") and (o["v"], f"découvert: {o.get('t','')}") not in discovered_codes:
                    discovered_codes.append((o["v"], f"découvert ligue-el: {o.get('t','')}"))

    print(f"\n{len(discovered_codes)} codes découverts via Playwright")

    print("\n=== PHASE 2 : Tests AJAX ===")
    # Combiner codes découverts + candidats classiques (dédoublonnés)
    all_codes = discovered_codes + [(c, n) for c, n in CANDIDATE_CODES if c not in [x[0] for x in discovered_codes]]

    for code, name in all_codes[:25]:
        print(f"  Test '{code}' ({name})...", end=" ")
        t = ajax_test(cookies, fbid, code, name)
        nb = t["page_0"].get("nb_results", 0)
        print(f"nb_results={nb}")
        output["ajax_tests"].append(t)
        if nb > 0:
            output["working_codes"].append({
                "code": code, "name": name, "nb_results": nb,
                "pagination_ok": t.get("pagination_ok"),
            })
        time.sleep(0.3)

    print(f"\n=== RÉSUMÉ ===")
    print(f"Codes qui fonctionnent ({len(output['working_codes'])}) :")
    for wc in output["working_codes"]:
        print(f"  code='{wc['code']}' → {wc['nb_results']} résultats, pagination={wc.get('pagination_ok','N/A')}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    files_to_add = ["data/diag_ligue.json"]
    if os.path.exists("data/diag_screenshot.png"):
        files_to_add.append("data/diag_screenshot.png")
    subprocess.run(["git", "add"] + files_to_add, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v3 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
