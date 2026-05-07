"""
Diag v17 — Interception réseau COMPLÈTE pendant une vraie navigation Ten'Up
Objectif : trouver l'endpoint API réel utilisé par le site pour afficher 2000+ résultats.
Capture TOUTES les requêtes HTTP (pas seulement /system/ajax).
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"


def intercept_all_requests():
    result = {
        "all_requests": [],
        "interesting_requests": [],  # Requêtes avec des résultats (nb_results, items, etc.)
        "page_source_excerpt": "",
        "ajax_with_nb": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        def on_request(req):
            if req.method in ("POST", "GET") and "tenup" in req.url.lower():
                entry = {
                    "url": req.url,
                    "method": req.method,
                    "post_data": (req.post_data or "")[:500],
                    "resource_type": req.resource_type,
                }
                result["all_requests"].append(entry)

        def on_response(resp):
            if "tenup" in resp.url.lower():
                try:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct or "javascript" in ct:
                        body = resp.text()
                        if any(kw in body for kw in ["nb_results", "items", "tournoi", "PADEL", "nb_total"]):
                            entry = {
                                "url": resp.url,
                                "status": resp.status,
                                "content_type": ct[:80],
                                "body_excerpt": body[:1500],
                            }
                            result["interesting_requests"].append(entry)
                            import re
                            m = re.search(r'"nb_results":(\d+)', body)
                            if m and int(m.group(1)) > 100:
                                result["ajax_with_nb"].append({
                                    "url": resp.url,
                                    "nb_results": int(m.group(1)),
                                    "body": body[:2000],
                                })
                except:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        # ── 1. Chargement initial ─────────────────────────────────────────────
        print("  Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        print(f"  Requêtes capturées : {len(result['all_requests'])}")

        # ── 2. Sélectionner PADEL via JS ──────────────────────────────────────
        print("  Sélection PADEL...")
        page.evaluate("""
            () => {
                const r = document.querySelector('[name="pratique"][value="PADEL"]');
                if (r) { r.checked = true; r.click(); r.dispatchEvent(new Event('change', {bubbles:true})); }
                if (window.jQuery) jQuery('[name="pratique"][value="PADEL"]').prop('checked',true).trigger('change');
            }
        """)
        try: page.wait_for_load_state("networkidle", timeout=5000)
        except: page.wait_for_timeout(3000)

        # ── 3. Remplir la date ────────────────────────────────────────────────
        now = datetime.now()
        for fname, val in [("date[start]", now.strftime("%d/%m/%y")), ("date[end]", (now + timedelta(days=90)).strftime("%d/%m/%y"))]:
            try:
                el = page.query_selector(f'input[name="{fname}"]')
                if el: el.evaluate("(el,v)=>{el.value=v;}", val)
            except: pass

        # ── 4. Activer le modal ligue + sélectionner PACA ────────────────────
        print("  Activation modal ligue + sélection PACA...")
        page.evaluate("""
            () => {
                // Activer radio ligue
                const r = document.querySelector('#edit-recherche-type-ligue');
                if (r) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles:true})); }
                // Afficher l'app Vue.js
                const app = document.querySelector('#app');
                if (app) app.style.cssText = 'display:block!important';
                // Afficher l'overlay
                const ov = document.querySelector('#overlay-modal-creneau');
                if (ov) ov.style.cssText = 'display:block!important';
            }
        """)
        page.wait_for_timeout(2000)

        # ── 5. Cocher TOUTES les ligues (all_cbrappel) ────────────────────────
        page.evaluate("""
            () => {
                const all = document.querySelector('#all_cbrappel');
                if (all) { all.checked = true; all.dispatchEvent(new Event('change', {bubbles:true})); }
            }
        """)
        page.wait_for_timeout(1000)

        # Vérifier l'état
        checked = page.evaluate("""
            () => Array.from(document.querySelectorAll('[id$="_cbrappel"]')).filter(c=>c.checked).map(c=>c.id)
        """)
        print(f"  Checkboxes ligue cochées : {checked}")

        # ── 6. Cliquer SUIVANT ────────────────────────────────────────────────
        print("  Tentative SUIVANT...")
        suivant_clicked = False
        for selector in ['a.btn-primary', 'a:has-text("SUIVANT")', '.text-center a', '[class*="btn-primary"]:not([class*="disabled"])']:
            try:
                el = page.query_selector(selector)
                if el:
                    el.click(force=True)
                    page.wait_for_timeout(2000)
                    suivant_clicked = True
                    print(f"  SUIVANT cliqué via '{selector}'")
                    break
            except: pass

        if not suivant_clicked:
            # Essai JS
            page.evaluate("""
                () => {
                    document.querySelectorAll('a, button').forEach(el => {
                        if (el.textContent.trim().toUpperCase().includes('SUIVANT') ||
                            el.textContent.trim().toUpperCase().includes('VALIDER')) {
                            el.click();
                        }
                    });
                }
            """)
            page.wait_for_timeout(2000)

        # Snapshot DOM après SUIVANT
        dom_after = page.evaluate("() => document.querySelector('#app')?.innerHTML?.substring(0,5000) || ''")
        result["dom_after_suivant_excerpt"] = dom_after

        # ── 7. Soumettre ──────────────────────────────────────────────────────
        print("  Soumission formulaire...")
        reqs_before = len(result["all_requests"])
        try:
            submit = page.query_selector('[name="submit_main"], input[value="Rechercher"]')
            if submit:
                submit.click(force=True)
                try: page.wait_for_load_state("networkidle", timeout=15000)
                except: page.wait_for_timeout(8000)
        except Exception as e:
            print(f"  Submit error: {e}")

        new_reqs = result["all_requests"][reqs_before:]
        print(f"  Requêtes après submit : {len(new_reqs)}")
        result["post_submit_requests"] = new_reqs

        browser.close()

    return result


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}

    print("=== Interception réseau complète ===")
    res = intercept_all_requests()

    print(f"\nTotal requêtes capturées : {len(res['all_requests'])}")
    print(f"Requêtes avec nb_results > 100 : {len(res['ajax_with_nb'])}")

    print("\nTous les endpoints uniques :")
    urls = list({r["url"].split("?")[0] for r in res["all_requests"]})
    for u in sorted(urls):
        print(f"  {u}")

    print("\nRequêtes intéressantes (JSON avec tournois) :")
    for r in res["interesting_requests"]:
        print(f"  [{r['status']}] {r['url']}")
        print(f"    {r['body_excerpt'][:300]}")

    print("\nRequêtes avec nb_results > 100 :")
    for r in res["ajax_with_nb"]:
        print(f"  nb={r['nb_results']} url={r['url']}")
        print(f"  body: {r['body'][:500]}")

    # Sauvegarder (sans les données trop volumineuses)
    output["unique_urls"] = urls
    output["interesting_count"] = len(res["interesting_requests"])
    output["ajax_with_nb"] = res["ajax_with_nb"][:3]
    output["post_submit_requests"] = res["post_submit_requests"][:10]
    output["dom_after_suivant"] = res.get("dom_after_suivant_excerpt", "")[:3000]
    output["all_requests_urls"] = [r["url"] for r in res["all_requests"]]

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v17 network_intercept [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
