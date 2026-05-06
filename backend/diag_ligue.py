"""
Padel Alert — Diagnostic ligue v6
Objectif : voir la RÉPONSE BRUTE de Ten'Up pour recherche_type=ligue
- Imprime les commandes reçues, le raw JSON, pour comprendre pourquoi 0 résultats
- Compare avec une recherche ville (qui fonctionne) pour différence de réponse
- Teste aussi : ligue mode avec fbid obtenu APRÈS activation du radio ligue via JS
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
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


def get_session_initial():
    """Session standard (fbid depuis page initiale)."""
    print("  Ouverture Ten'Up (session initiale)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()
    print(f"  fbid initial: {fbid[:40] if fbid else 'MANQUANT'}")
    return fbid, cookies


def get_session_after_ligue_click():
    """Session avec fbid obtenu APRÈS activation ligue via JS + AJAX intercepté."""
    print("  Ouverture Ten'Up (session après clic ligue)...")
    captured_fbid_after = [None]
    captured_resp = [None]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        def on_response(resp):
            if "/system/ajax" in resp.url:
                try:
                    body = resp.text()
                    captured_resp[0] = body[:2000]
                    # Chercher un nouveau fbid dans la réponse
                    import re
                    m = re.search(r'"form_build_id":"([^"]+)"', body)
                    if m:
                        captured_fbid_after[0] = m.group(1)
                except:
                    pass
        page.on("response", on_response)

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        fbid_initial = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")

        # Activer ligue via JS (dispatch events sur le radio)
        page.evaluate("""
            () => {
                const radio = document.querySelector('#edit-recherche-type-ligue');
                if (radio) {
                    radio.checked = true;
                    ['change', 'input', 'click'].forEach(ev =>
                        radio.dispatchEvent(new Event(ev, {bubbles:true, cancelable:true}))
                    );
                }
                // Aussi essayer via jQuery si disponible
                if (window.jQuery) {
                    jQuery('#edit-recherche-type-ligue').prop('checked', true).trigger('change');
                }
            }
        """)
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except:
            page.wait_for_timeout(3000)

        fbid_after = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    fbid_ajax_new = captured_fbid_after[0]
    print(f"  fbid initial: {fbid_initial[:30] if fbid_initial else 'N/A'}")
    print(f"  fbid après ligue click: {fbid_after[:30] if fbid_after else 'N/A'}")
    print(f"  fbid dans réponse AJAX: {fbid_ajax_new[:30] if fbid_ajax_new else 'N/A'}")
    print(f"  AJAX resp après click: {captured_resp[0][:200] if captured_resp[0] else 'AUCUNE'}")
    return fbid_initial, fbid_after, fbid_ajax_new, cookies


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


def ajax_raw(session, extra_params, fbid, label):
    """AJAX call et retourne le JSON brut complet pour debug."""
    now = datetime.now()
    base = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]": (now + timedelta(days=90)).strftime("%d/%m/%y"),
        **ALL_CRITERIA,
        "sort": "_DATE_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": "0",
    }
    base.update(extra_params)

    try:
        r = session.post(TENUP_AJAX, data=base, timeout=45)
        r.raise_for_status()
        cmds = r.json()
        # Extraire commandes + données clés
        result = {
            "label": label,
            "http": r.status_code,
            "commands": [],
            "nb_results": 0,
            "raw_excerpt": r.text[:800],
        }
        for cmd in cmds:
            if isinstance(cmd, dict):
                cmd_name = cmd.get("command", "?")
                if cmd_name == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    result["nb_results"] = res.get("nb_results", 0)
                    result["commands"].append(f"{cmd_name}(nb={result['nb_results']})")
                elif cmd_name in ("settings", "drupalSettings"):
                    result["commands"].append(f"{cmd_name}(settings)")
                else:
                    # Extraire le début du HTML si présent
                    data_preview = str(cmd.get("data", ""))[:100]
                    result["commands"].append(f"{cmd_name}({data_preview})")
        return result
    except Exception as e:
        return {"label": label, "error": str(e)}


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tests": [],
        "conclusion": "",
    }

    print("=== SESSION 1 : fbid initial ===")
    fbid_init, cookies_init = get_session_initial()
    sess_init = make_session(cookies_init)

    print("\n=== SESSION 2 : fbid après activation ligue ===")
    fbid_init2, fbid_after_click, fbid_from_ajax, cookies2 = get_session_after_ligue_click()
    sess2 = make_session(cookies2)

    now = datetime.now()
    ds  = now.strftime("%d/%m/%y")
    de  = (now + timedelta(days=90)).strftime("%d/%m/%y")

    print("\n=== TESTS AJAX ===")

    # 1. Contrôle : recherche ville (doit fonctionner)
    print("\n--- Test contrôle ville (Paris) ---")
    t1 = ajax_raw(sess_init, {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
    }, fbid_init, "ville=Paris 50km")
    print(f"  → nb={t1.get('nb_results')} commands={t1.get('commands')}")
    print(f"  raw: {t1.get('raw_excerpt','')[:300]}")
    output["tests"].append(t1)
    time.sleep(0.5)

    # 2. Ligue cbrappel[]=57 avec fbid initial
    print("\n--- Test ligue cbrappel[]=57 (IDF) fbid initial ---")
    t2 = ajax_raw(sess_init, {
        "recherche_type": "ligue",
        "cbrappel[]": "57",
    }, fbid_init, "ligue cbrappel[]=57 fbid_initial")
    print(f"  → nb={t2.get('nb_results')} commands={t2.get('commands')}")
    print(f"  raw: {t2.get('raw_excerpt','')[:300]}")
    output["tests"].append(t2)
    time.sleep(0.5)

    # 3. Ligue avec fbid après click (si différent)
    fbid_ligue = fbid_from_ajax or fbid_after_click or fbid_init2
    if fbid_ligue and fbid_ligue != fbid_init2:
        print(f"\n--- Test ligue cbrappel[]=57 avec fbid AJAX ({fbid_ligue[:20]}) ---")
        t3 = ajax_raw(sess2, {
            "recherche_type": "ligue",
            "cbrappel[]": "57",
        }, fbid_ligue, "ligue cbrappel[]=57 fbid_ajax_new")
        print(f"  → nb={t3.get('nb_results')} commands={t3.get('commands')}")
        print(f"  raw: {t3.get('raw_excerpt','')[:300]}")
        output["tests"].append(t3)
        time.sleep(0.5)

    # 4. Ligue sans aucun param ligue (juste recherche_type=ligue)
    print("\n--- Test recherche_type=ligue SEUL (sans cbrappel) ---")
    t4 = ajax_raw(sess_init, {"recherche_type": "ligue"}, fbid_init, "ligue seul sans params")
    print(f"  → nb={t4.get('nb_results')} commands={t4.get('commands')}")
    print(f"  raw: {t4.get('raw_excerpt','')[:300]}")
    output["tests"].append(t4)
    time.sleep(0.5)

    # 5. Tenter une soumission complète via Playwright et intercepter
    print("\n--- Test via Playwright : soumission réelle ligue ---")
    try:
        submit_result = intercept_real_ligue_submission()
        output["playwright_submit"] = submit_result
        print(f"  → params capturés: {submit_result.get('params_captured', False)}")
        print(f"  → nb_results: {submit_result.get('nb_results', 'N/A')}")
        print(f"  → raw params: {submit_result.get('raw_params', '')[:400]}")
    except Exception as e:
        output["playwright_submit"] = {"error": str(e)}
        print(f"  Erreur: {e}")

    # Résumé
    working = [t for t in output["tests"] if t.get("nb_results", 0) > 0]
    print(f"\n=== RÉSUMÉ ===")
    for t in output["tests"]:
        nb = t.get("nb_results", 0)
        print(f"  {'✓' if nb>0 else '✗'} '{t['label']}' → nb={nb}")
    if output.get("playwright_submit"):
        print(f"  Playwright submit → nb={output['playwright_submit'].get('nb_results', 'N/A')}")

    output["conclusion"] = f"ville_controle={output['tests'][0].get('nb_results',0)}, ligue_tests_working={len(working)}"

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v6 raw [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


def intercept_real_ligue_submission():
    """Tente une vraie soumission ligue via Playwright en cliquant dans le modal Vue.js."""
    result = {"params_captured": False, "raw_params": None, "nb_results": None}
    captured_reqs = []
    captured_resps = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        def on_req(req):
            if "/system/ajax" in req.url and req.method == "POST":
                captured_reqs.append(req.post_data or "")
        def on_resp(resp):
            if "/system/ajax" in resp.url:
                try:
                    captured_resps.append(resp.text()[:3000])
                except:
                    pass
        page.on("request", on_req)
        page.on("response", on_resp)

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        # Étape 1 : activer ligue radio
        page.evaluate("""
            () => {
                const r = document.querySelector('#edit-recherche-type-ligue');
                if (r) { r.checked = true; r.dispatchEvent(new Event('change',{bubbles:true})); }
                if (window.jQuery) jQuery('#edit-recherche-type-ligue').prop('checked',true).trigger('change');
            }
        """)
        page.wait_for_timeout(2000)

        # Étape 2 : forcer l'affichage du modal et cliquer la checkbox IDF
        page.evaluate("""
            () => {
                // Forcer l'affichage de la section ligue et du modal
                const app = document.querySelector('#app');
                const overlay = document.querySelector('#overlay-modal-creneau');
                const editLigue = document.querySelector('#edit-ligue');
                if (editLigue) editLigue.style.cssText = 'display:block!important';
                if (app) app.style.cssText = 'display:block!important';
                if (overlay) overlay.style.cssText = 'display:block!important';

                // Cocher ILE DE FRANCE (id=57_cbrappel)
                const idf = document.querySelector('#\\\\35 7_cbrappel');
                if (idf) { idf.checked = true; idf.dispatchEvent(new Event('change',{bubbles:true})); }

                // Alternative: chercher par label text
                document.querySelectorAll('label').forEach(l => {
                    if (l.textContent.trim() === 'ILE DE FRANCE') {
                        const cb = document.querySelector('#' + l.getAttribute('for'));
                        if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change',{bubbles:true})); }
                    }
                });
            }
        """)
        page.wait_for_timeout(2000)

        # Étape 3 : cliquer SUIVANT
        try:
            suivant = page.query_selector('a:has-text("SUIVANT"), .btn-primary:has-text("SUIVANT")')
            if suivant:
                suivant.click(force=True)
                page.wait_for_timeout(2000)
                print("  SUIVANT cliqué")
        except Exception as e:
            print(f"  SUIVANT non cliqué: {e}")

        # Étape 4 : soumettre
        now = datetime.now()
        for fname, val in [("date[start]", now.strftime("%d/%m/%y")), ("date[end]", (now + timedelta(days=90)).strftime("%d/%m/%y"))]:
            try:
                el = page.query_selector(f'input[name="{fname}"]')
                if el:
                    el.evaluate("(el,v)=>{el.value=v;}", val)
            except:
                pass

        captured_reqs.clear(); captured_resps.clear()
        try:
            submit = page.query_selector('[name="submit_main"]')
            if submit:
                submit.click(force=True, timeout=5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except:
                    page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  Submit erreur: {e}")

        if captured_reqs:
            result["params_captured"] = True
            result["raw_params"] = captured_reqs[-1]
        if captured_resps:
            # Chercher nb_results dans la réponse
            import re
            m = re.search(r'"nb_results":(\d+)', captured_resps[-1])
            if m:
                result["nb_results"] = int(m.group(1))
            result["raw_resp_excerpt"] = captured_resps[-1][:500]

        browser.close()

    return result


if __name__ == "__main__":
    main()
