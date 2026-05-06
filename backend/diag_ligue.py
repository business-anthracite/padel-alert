"""
Padel Alert — Diagnostic ligue v4
Objectif : extraire les vrais noms de champs et valeurs du bloc #edit-ligue (autocomplete)
- Force l'affichage CSS du div ligue caché
- Extrait tous les inputs/data-refer dans ce div
- Intercept une vraie soumission ligue via Playwright pour capturer les paramètres exacts
- Commite data/diag_ligue.json + data/diag_screenshot_ligue.png
"""
import json, re, time, subprocess, os, base64
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


def explore_playwright():
    result = {
        "fbid": None, "error": None,
        "ligue_section_html": "",
        "ligue_section_inputs": [],
        "ligue_dropdown_items": [],
        "all_inputs_after_ligue_active": [],
        "intercepted_ajax_params": None,
        "intercepted_ajax_response_excerpt": None,
        "screenshot_b64": None,
    }
    captured_reqs  = []
    captured_resps = []

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
                    captured_reqs.append({"post_data": req.post_data or "", "t": datetime.utcnow().isoformat()})
            def on_response(resp):
                if "/system/ajax" in resp.url:
                    try:
                        captured_resps.append({"body": resp.text()[:3000], "status": resp.status})
                    except:
                        pass
            page.on("request", on_request)
            page.on("response", on_response)

            print("  Chargement Ten'Up...")
            page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)

            fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            result["fbid"]    = fbid
            result["cookies"] = cookies
            print(f"  fbid: {fbid[:40] if fbid else 'MANQUANT'}")

            # ── Activer la section ligue via JS (contourne CSS display:none) ──
            print("  Activation section ligue via JS...")
            page.evaluate("""
                () => {
                    // Cliquer le radio via JS
                    const radio = document.querySelector('#edit-recherche-type-ligue');
                    if (radio) {
                        radio.checked = true;
                        ['change','input','click'].forEach(ev =>
                            radio.dispatchEvent(new Event(ev, {bubbles:true, cancelable:true}))
                        );
                    }
                    // Force-afficher la section ligue
                    const sec = document.querySelector('#edit-ligue');
                    if (sec) sec.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
                }
            """)
            page.wait_for_timeout(4000)

            # ── Extraire HTML complet de #edit-ligue ──────────────────────────
            ligue_html = page.evaluate("""
                () => {
                    const s = document.querySelector('#edit-ligue');
                    return s ? s.outerHTML : 'NOT FOUND';
                }
            """)
            result["ligue_section_html"] = ligue_html[:15000]
            print(f"  Section #edit-ligue HTML : {len(ligue_html)} chars")

            # ── Tous les inputs dans #edit-ligue ──────────────────────────────
            ligue_inputs = page.evaluate("""
                () => {
                    const sec = document.querySelector('#edit-ligue');
                    if (!sec) return [];
                    return Array.from(sec.querySelectorAll('input,select,textarea,button')).map(el => ({
                        tag:         el.tagName,
                        name:        el.name        || '',
                        id:          el.id          || '',
                        type:        el.type        || '',
                        value:       el.value       || '',
                        placeholder: el.placeholder || '',
                        dataRefer:   el.dataset && el.dataset.refer ? el.dataset.refer : '',
                        class:       (el.className || '').substring(0,80),
                    }));
                }
            """)
            result["ligue_section_inputs"] = ligue_inputs
            print(f"  Inputs dans #edit-ligue : {len(ligue_inputs)}")
            for inp in ligue_inputs:
                print(f"    <{inp['tag']}> name='{inp['name']}' id='{inp['id']}' value='{inp['value']}' placeholder='{inp['placeholder']}'")

            # ── Items du dropdown (data-refer) ────────────────────────────────
            dropdown_items = page.evaluate("""
                () => {
                    const sec = document.querySelector('#edit-ligue');
                    if (!sec) return [];
                    // Chercher li, [role=option], [data-refer]
                    const items = sec.querySelectorAll('li, [role="option"], [data-refer]');
                    return Array.from(items).map(el => ({
                        tag:       el.tagName,
                        text:      (el.textContent || '').trim().substring(0,80),
                        dataRefer: el.dataset && el.dataset.refer ? el.dataset.refer : '',
                        id:        el.id || '',
                        value:     el.getAttribute('value') || '',
                    })).filter(el => el.text || el.dataRefer);
                }
            """)
            result["ligue_dropdown_items"] = dropdown_items
            print(f"  Dropdown items ligue : {len(dropdown_items)}")
            for item in dropdown_items[:20]:
                print(f"    text='{item['text'][:50]}' data-refer='{item['dataRefer']}' id='{item['id']}'")

            # ── Screenshot ────────────────────────────────────────────────────
            try:
                os.makedirs("data", exist_ok=True)
                page.screenshot(path="data/diag_screenshot_ligue.png")
                with open("data/diag_screenshot_ligue.png", "rb") as f:
                    result["screenshot_b64"] = base64.b64encode(f.read()).decode()[:5000]
                print("  Screenshot pris")
            except Exception as e:
                print(f"  Screenshot erreur: {e}")

            # ── Tous les inputs du formulaire après activation ligue ──────────
            all_inputs = page.evaluate("""
                () => Array.from(document.querySelectorAll('input,select')).map(el => ({
                    name:  el.name  || '',
                    id:    el.id    || '',
                    type:  el.type  || '',
                    value: el.value || '',
                    visible: el.offsetParent !== null,
                    opts:    el.tagName==='SELECT' ? el.options.length : null,
                })).filter(el => el.name)
            """)
            result["all_inputs_after_ligue_active"] = all_inputs

            # ── Essai de sélection d'une ligue et soumission ──────────────────
            # Utiliser les items dropdown trouvés pour sélectionner la première ligue réelle
            ligue_items_real = [it for it in dropdown_items if it.get("dataRefer") and "toutes" not in it.get("text","").lower()]
            if ligue_items_real:
                first_ligue = ligue_items_real[0]
                print(f"\n  Essai sélection ligue '{first_ligue['text']}' (data-refer={first_ligue['dataRefer']})...")
                try:
                    # Cliquer le bouton autocomplete pour ouvrir le dropdown
                    page.click('#edit-ligue-autocomplete', force=True, timeout=5000)
                    page.wait_for_timeout(2000)
                    # Cliquer l'item
                    if first_ligue["id"]:
                        page.click(f'#{first_ligue["id"]}', force=True, timeout=5000)
                    elif first_ligue["dataRefer"]:
                        page.click(f'[data-refer="{first_ligue["dataRefer"]}"]', force=True, timeout=5000)
                    page.wait_for_timeout(2000)
                    print("  Ligue sélectionnée")
                except Exception as e:
                    print(f"  Erreur sélection ligue: {e}")

            # ── Soumission et capture AJAX ─────────────────────────────────────
            now = datetime.now()
            ds  = now.strftime("%d/%m/%y")
            de  = (now + timedelta(days=90)).strftime("%d/%m/%y")
            for fname, val in [("date[start]", ds), ("date[end]", de)]:
                try:
                    el = page.query_selector(f'input[name="{fname}"]')
                    if el:
                        el.evaluate("(el, v) => { el.value=v; el.dispatchEvent(new Event('change',{bubbles:true})); }", val)
                except:
                    pass

            print("  Soumission du formulaire...")
            captured_reqs.clear(); captured_resps.clear()
            try:
                submit = page.query_selector('[name="submit_main"]')
                if submit:
                    submit.click(force=True, timeout=5000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except:
                        page.wait_for_timeout(6000)
                    if captured_reqs:
                        result["intercepted_ajax_params"] = captured_reqs[-1]["post_data"]
                        print(f"  AJAX capturé : {captured_reqs[-1]['post_data'][:200]}")
                    if captured_resps:
                        result["intercepted_ajax_response_excerpt"] = captured_resps[-1]["body"][:1000]
                else:
                    print("  WARN: bouton submit non trouvé")
            except Exception as e:
                print(f"  Erreur soumission: {e}")

            browser.close()

    except Exception as e:
        result["error"] = str(e)
        print(f"  Erreur globale: {e}")

    return result


def test_structured_ligue_ajax(cookies, fbid, ligue_value, ligue_label, ligue_name_fr):
    """
    Teste l'AJAX avec une structure ligue[autocomplete][...] identique à ville[autocomplete][...].
    """
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

    params = {
        "recherche_type": "ligue",
        # Structure identique à ville[autocomplete]...
        "ligue[autocomplete][textfield]": ligue_name_fr,
        "ligue[autocomplete][value_container][value_field]": ligue_value,
        "ligue[autocomplete][value_container][label_field]": ligue_label,
        "pratique": "PADEL",
        "date[start]": ds, "date[end]": de,
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": "0",
    }
    try:
        r = s.post(TENUP_AJAX, data=params, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        for cmd in cmds:
            if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                res = cmd.get("results", {})
                return {"nb_results": res.get("nb_results", 0), "nb_items": len(res.get("items", [])), "http": r.status_code}
        return {"nb_results": 0, "commands": [c.get("command") for c in cmds if isinstance(c, dict)], "raw": r.text[:500], "http": r.status_code}
    except Exception as e:
        return {"error": str(e)}


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "playwright": {},
        "structured_ajax_tests": [],
        "conclusion": "",
    }

    print("=== PHASE 1 : Exploration Playwright approfondie ===")
    pw = explore_playwright()
    pw_export = {k: v for k, v in pw.items() if k not in ("cookies", "screenshot_b64")}
    output["playwright"] = pw_export

    fbid    = pw.get("fbid")
    cookies = pw.get("cookies", {})

    # Extraire les vraies valeurs ligue des dropdown items
    dropdown_items = pw.get("ligue_dropdown_items", [])
    real_ligues = [it for it in dropdown_items if it.get("dataRefer") and "toutes" not in it.get("text","").lower()]
    print(f"\nLigues réelles trouvées dans dropdown : {len(real_ligues)}")
    for l in real_ligues:
        print(f"  data-refer='{l['dataRefer']}' text='{l['text']}'")

    # Extraire le nom du champ autocomplete ligue depuis les inputs
    ligue_inputs = pw.get("ligue_section_inputs", [])
    print(f"\nInputs section ligue: {ligue_inputs}")

    print("\n=== PHASE 2 : Tests AJAX structurés ligue[autocomplete][...] ===")
    # Test avec structure style ville[autocomplete]...
    test_values = []
    # Depuis dropdown items découverts
    for it in real_ligues[:5]:
        test_values.append((it["dataRefer"], it["text"], it["text"]))
    # Fallback : quelques ligues hardcodées si rien trouvé
    if not test_values:
        test_values = [
            ("ILE-DE-FRANCE",        "ILE-DE-FRANCE",        "Île-de-France"),
            ("PROVENCE-ALPES-COTE",  "PROVENCE-ALPES-COTE",  "Provence-Alpes-Côte d'Azur"),
        ]

    for val, label, name_fr in test_values[:5]:
        print(f"  Test ligue[autocomplete] value='{val}'...")
        t = test_structured_ligue_ajax(cookies, fbid, val, label, name_fr)
        print(f"    → {t}")
        output["structured_ajax_tests"].append({"value": val, "label": label, "result": t})
        time.sleep(0.5)

    # Analyse du paramètre AJAX intercepté
    intercepted = pw.get("intercepted_ajax_params", "")
    if intercepted:
        print(f"\n=== PARAMÈTRE AJAX INTERCEPTÉ ===")
        print(intercepted[:1000])
        output["intercepted_params_raw"] = intercepted

    print(f"\n=== RÉSUMÉ ===")
    working = [t for t in output["structured_ajax_tests"] if t["result"].get("nb_results", 0) > 0]
    print(f"Tests structurés avec résultats: {len(working)}/{len(output['structured_ajax_tests'])}")
    if intercepted:
        print(f"Paramètre AJAX intercepté: OUI ({len(intercepted)} chars)")
    else:
        print("Paramètre AJAX intercepté: NON")

    output["conclusion"] = (
        f"dropdown_items={len(real_ligues)}, "
        f"intercepted={'OUI' if intercepted else 'NON'}, "
        f"ajax_working={len(working)}/{len(output['structured_ajax_tests'])}"
    )

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    files = ["data/diag_ligue.json"]
    if os.path.exists("data/diag_screenshot_ligue.png"):
        files.append("data/diag_screenshot_ligue.png")
    subprocess.run(["git", "add"] + files, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v4 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
