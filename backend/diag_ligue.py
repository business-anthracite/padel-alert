"""
Padel Alert — Diagnostic ligue v12
Objectif : intercepter la VRAIE requête AJAX du formulaire Ten'Up (avec comités).
Le modal Vue.js a 2 étapes :
  1. Sélection ligue (cbrappel[]) → SUIVANT
  2. Sélection comités → soumettre
Sans l'étape 2, on n'obtient que 27 résultats (au lieu de 2000+ pour PACA).
On cherche les paramètres comité + comment les soumettre.
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"


def intercept_full_form_submission():
    result = {
        "all_requests": [],
        "ajax_requests": [],
        "intercepted_submit_params": None,
        "intercepted_submit_response_nb": None,
        "dom_snapshots": {},
        "error": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # Intercepter TOUTES les requêtes réseau
        def on_req(req):
            if req.method in ("POST", "GET") and "tenup" in req.url:
                entry = {"url": req.url, "method": req.method, "post_data": req.post_data or ""}
                result["all_requests"].append(entry)
                if "/system/ajax" in req.url or "/api" in req.url:
                    result["ajax_requests"].append(entry)
        def on_resp(resp):
            if "/system/ajax" in resp.url and resp.status == 200:
                try:
                    import re
                    body = resp.text()
                    m = re.search(r'"nb_results":(\d+)', body)
                    if m and int(m.group(1)) > 100:
                        # Requête prometteuse avec beaucoup de résultats
                        result["intercepted_submit_response_nb"] = int(m.group(1))
                        # Trouver la requête correspondante
                        if result["ajax_requests"]:
                            result["intercepted_submit_params"] = result["ajax_requests"][-1]["post_data"]
                        result["successful_response_excerpt"] = body[:2000]
                except:
                    pass
        page.on("request", on_req)
        page.on("response", on_resp)

        print("  Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        fbid = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value")
        print(f"  fbid: {(fbid or '')[:35]}")
        result["fbid"] = fbid

        # ÉTAPE 1 : Activer ligue mode + ouvrir modal
        print("  Activation mode ligue + ouverture modal...")
        page.evaluate("""
            () => {
                // Activer radio ligue
                const r = document.querySelector('#edit-recherche-type-ligue');
                if (r) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles:true})); }
                // Afficher la section ligue
                const s = document.querySelector('#edit-ligue');
                if (s) s.style.cssText = 'display:block!important';
                // Afficher le modal app
                const app = document.querySelector('#app');
                if (app) app.style.cssText = 'display:block!important';
                // Afficher overlay
                const ov = document.querySelector('#overlay-modal-creneau');
                if (ov) ov.style.cssText = 'display:block!important';
            }
        """)
        page.wait_for_timeout(2000)

        # Snapshot DOM initial
        result["dom_snapshots"]["after_show_modal"] = page.evaluate("""
            () => document.querySelector('#app')?.outerHTML?.substring(0, 5000) || ''
        """)

        # ÉTAPE 2 : Cocher PACA (62_cbrappel) via force click
        print("  Cochage PACA (62_cbrappel)...")
        try:
            # Forcer le cochage via JS
            page.evaluate("""
                () => {
                    const cb = document.querySelector('#\\\\36 2_cbrappel');
                    if (cb) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles:true}));
                        cb.dispatchEvent(new Event('input', {bubbles:true}));
                        cb.dispatchEvent(new Event('click', {bubbles:true}));
                    }
                    // Alternative : chercher par label PACA
                    document.querySelectorAll('label').forEach(l => {
                        if (l.textContent.trim().includes("PROVENCE")) {
                            const id = l.getAttribute('for');
                            const inp = document.querySelector('#' + id);
                            if (inp) {
                                inp.checked = true;
                                ['change','input','click'].forEach(e =>
                                    inp.dispatchEvent(new Event(e, {bubbles:true}))
                                );
                            }
                        }
                    });
                }
            """)
            page.wait_for_timeout(2000)
            print("  PACA coché via JS")
        except Exception as e:
            print(f"  Erreur cochage: {e}")

        # Snapshot DOM après cochage
        result["dom_snapshots"]["after_paca_check"] = page.evaluate("""
            () => document.querySelector('#app')?.outerHTML?.substring(0, 5000) || ''
        """)

        # Vérifier état checkbox PACA
        paca_state = page.evaluate("""
            () => {
                const candidates = [];
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    if (cb.id && cb.id.includes('62') || cb.id.includes('cbrappel')) {
                        candidates.push({id: cb.id, checked: cb.checked, name: cb.name});
                    }
                });
                return candidates;
            }
        """)
        print(f"  État checkboxes ligue : {paca_state}")

        # ÉTAPE 3 : Cliquer SUIVANT
        print("  Tentative clic SUIVANT...")
        suivant_clicked = False
        for selector in ['a:has-text("SUIVANT")', '.btn-primary', 'a.btn-primary', 'button:has-text("SUIVANT")', '[class*="suivant"]', 'a[href="#"]']:
            try:
                page.click(selector, force=True, timeout=3000)
                page.wait_for_timeout(2000)
                suivant_clicked = True
                print(f"  SUIVANT cliqué via '{selector}'")
                break
            except:
                pass

        if not suivant_clicked:
            # Essai via JS
            try:
                page.evaluate("""
                    () => {
                        // Chercher le bouton SUIVANT dans le modal
                        document.querySelectorAll('a, button').forEach(el => {
                            if (el.textContent.trim().toUpperCase() === 'SUIVANT') {
                                el.click();
                            }
                        });
                    }
                """)
                page.wait_for_timeout(2000)
                print("  SUIVANT cliqué via JS forEach")
                suivant_clicked = True
            except Exception as e:
                print(f"  SUIVANT impossible: {e}")

        # Snapshot après SUIVANT
        result["dom_snapshots"]["after_suivant"] = page.evaluate("""
            () => document.querySelector('#app')?.outerHTML?.substring(0, 8000) || ''
        """)

        # ÉTAPE 4 : Sélectionner tous les comités
        print("  Recherche éléments comité...")
        comite_elements = page.evaluate("""
            () => {
                const els = [];
                document.querySelectorAll('input[type="checkbox"], [role="checkbox"]').forEach(el => {
                    if (!el.id || !el.id.includes('cbrappel')) {
                        els.push({
                            id: el.id, name: el.name || '', value: el.value || '',
                            checked: el.checked, class: (el.className||'').substring(0,60)
                        });
                    }
                });
                return els.slice(0, 50);
            }
        """)
        result["comite_checkboxes_found"] = comite_elements
        print(f"  Checkboxes non-cbrappel : {len(comite_elements)}")
        for el in comite_elements[:10]:
            print(f"    id={el['id']} name={el['name']} value={el['value']} checked={el['checked']}")

        # ÉTAPE 5 : Cliquer "Tous" comités
        print("  Tentative sélection 'Tous' comités...")
        try:
            page.evaluate("""
                () => {
                    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        if (!cb.id.includes('cbrappel')) {
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {bubbles:true}));
                        }
                    });
                    // Aussi chercher label "Tous"
                    document.querySelectorAll('label').forEach(l => {
                        if (l.textContent.trim().toLowerCase() === 'tous' || l.textContent.trim().toLowerCase() === 'toutes') {
                            const inp = document.querySelector('#' + l.getAttribute('for'));
                            if (inp) { inp.checked = true; inp.dispatchEvent(new Event('change', {bubbles:true})); }
                        }
                    });
                }
            """)
            page.wait_for_timeout(1000)
        except:
            pass

        # ÉTAPE 6 : Soumettre le formulaire
        print("  Soumission formulaire...")
        now = datetime.now()
        for fname, val in [("date[start]", now.strftime("%d/%m/%y")), ("date[end]", (now + timedelta(days=90)).strftime("%d/%m/%y"))]:
            try:
                el = page.query_selector(f'input[name="{fname}"]')
                if el:
                    el.evaluate("(el,v)=>{el.value=v;}", val)
            except:
                pass

        prev_req_count = len(result["ajax_requests"])
        try:
            # Essai de soumission via bouton
            for sel in ['[name="submit_main"]', 'input[value="Rechercher"]', 'button[type="submit"]']:
                try:
                    page.click(sel, force=True, timeout=5000)
                    break
                except:
                    pass
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except:
                page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  Submit error: {e}")

        new_reqs = result["ajax_requests"][prev_req_count:]
        print(f"  Nouvelles requêtes AJAX après submit : {len(new_reqs)}")
        for req in new_reqs[:3]:
            print(f"    {req['url']}")
            print(f"    params: {req['post_data'][:300]}")
        result["post_submit_ajax_requests"] = new_reqs

        browser.close()

    return result


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}

    print("=== Interception formulaire complet ===")
    res = intercept_full_form_submission()
    # Sauvegarder tout sauf les snapshots DOM (trop volumineux)
    res_clean = {k: v for k, v in res.items() if k != "dom_snapshots"}
    output.update(res_clean)

    # Sauvegarder les snapshots séparément (tronqués)
    output["dom_after_suivant_excerpt"] = res.get("dom_snapshots", {}).get("after_suivant", "")[:3000]

    print(f"\n=== RÉSUMÉ ===")
    print(f"Requêtes AJAX totales capturées : {len(res.get('ajax_requests', []))}")
    print(f"Params submit interceptés : {'OUI' if res.get('intercepted_submit_params') else 'NON'}")
    print(f"nb_results > 100 trouvé : {res.get('intercepted_submit_response_nb', 'NON')}")
    print(f"Comité checkboxes trouvés : {len(res.get('comite_checkboxes_found', []))}")
    print(f"Requêtes après submit : {len(res.get('post_submit_ajax_requests', []))}")

    if res.get("intercepted_submit_params"):
        print(f"\nPARAMÈTRES SUBMIT INTERCEPTÉS :")
        print(res["intercepted_submit_params"][:800])

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v12 comites [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
