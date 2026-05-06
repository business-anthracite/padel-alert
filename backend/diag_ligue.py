"""
Padel Alert — Diagnostic ligue v9
Ten'Up a redesigné son formulaire. Ce diagnostic :
1. Lit les options réelles du select 'sort'
2. Sélectionne PADEL via Playwright, attend update AJAX, relit le formulaire
3. Capture le fbid mis à jour après sélection PADEL
4. Teste une recherche bare avec le bon sort + fbid PADEL
5. Liste tous les champs padel disponibles
"""
import json, time, subprocess, os
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright

TENUP_BASE   = "https://tenup.fft.fr"
TENUP_SEARCH = f"{TENUP_BASE}/recherche/tournois"
TENUP_AJAX   = f"{TENUP_BASE}/system/ajax"

def get_session_padel():
    """Ouvre Ten'Up, sélectionne PADEL, attend update, retourne tous les tokens + champs padel."""
    print("  Ouverture Ten'Up + sélection PADEL...")
    ajax_resps = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        def on_resp(resp):
            if "/system/ajax" in resp.url:
                try: ajax_resps.append({"url": resp.url, "body": resp.text()[:2000]})
                except: pass
        page.on("response", on_resp)

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # Dump du formulaire initial complet
        initial = page.evaluate("""
            () => {
                const form = {};
                // Sort options
                const sortEl = document.querySelector('select[name="sort"]');
                form.sort_options = sortEl ? Array.from(sortEl.options).map(o=>({v:o.value,t:o.text.trim()})) : [];
                form.sort_value = sortEl ? sortEl.value : null;
                // pratique radios
                form.pratique_options = Array.from(document.querySelectorAll('[name="pratique"]')).map(r=>({v:r.value,checked:r.checked}));
                // form tokens
                form.form_build_id = document.querySelector('[name="form_build_id"]')?.value;
                form.form_token    = document.querySelector('[name="form_token"]')?.value;
                form.form_id       = document.querySelector('[name="form_id"]')?.value;
                return form;
            }
        """)
        print(f"  Sort options initial : {initial.get('sort_options')}")
        print(f"  Pratique options : {initial.get('pratique_options')}")
        print(f"  fbid initial : {(initial.get('form_build_id') or '')[:40]}")

        fbid_before = initial.get("form_build_id")

        # Sélectionner PADEL
        padel_radio = page.query_selector('[name="pratique"][value="PADEL"]')
        if padel_radio:
            padel_radio.click()
            try: page.wait_for_load_state("networkidle", timeout=8000)
            except: page.wait_for_timeout(4000)
            print(f"  PADEL cliqué ({len(ajax_resps)} AJAX reçus)")
        else:
            print("  WARN: radio PADEL non trouvé")

        # Dump du formulaire après sélection PADEL
        after_padel = page.evaluate("""
            () => {
                const form = {};
                // Tous les checkboxes/radios/selects
                const fields = {};
                document.querySelectorAll('input:not([type="hidden"]), select').forEach(el => {
                    if (!el.name) return;
                    if (!fields[el.name]) fields[el.name] = [];
                    if (el.tagName === 'SELECT') {
                        fields[el.name] = Array.from(el.options).map(o => ({v:o.value, t:o.text.trim()}));
                    } else {
                        const visible = el.offsetParent !== null || el.closest('[style*="display:none"]') === null;
                        fields[el.name].push({v: el.value, checked: el.checked, visible});
                    }
                });
                form.fields = fields;
                form.form_build_id = document.querySelector('[name="form_build_id"]')?.value;
                form.form_token    = document.querySelector('[name="form_token"]')?.value;
                // Chercher les critères padel spécifiques
                form.padel_criteria_section = document.querySelector('#edit-criteres-padel, .criteres-padel, [id*="padel"]')?.outerHTML?.substring(0,3000) || null;
                return form;
            }
        """)
        print(f"  fbid après PADEL : {(after_padel.get('form_build_id') or '')[:40]}")
        print(f"  fbid changé : {fbid_before != after_padel.get('form_build_id')}")

        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    return initial, after_padel, cookies, ajax_resps


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
            elif c.get("command") == "insert":
                msgs.append(f"insert({str(c.get('data',''))[:80]})")
            else:
                msgs.append(c.get("command","?"))
        return {"nb": nb, "msgs": msgs, "http": r.status_code, "raw": r.text[:400]}
    except Exception as e:
        return {"nb": 0, "error": str(e)}


def main():
    output = {"run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tests": [], "conclusion": ""}

    print("=== Session Playwright + PADEL ===")
    initial, after_padel, cookies, ajax_resps = get_session_padel()
    session = make_session(cookies)

    fbid_padel = after_padel.get("form_build_id") or initial.get("form_build_id")
    sort_opts   = initial.get("sort_options", [])
    output["sort_options"]        = sort_opts
    output["fields_after_padel"]  = after_padel.get("fields", {})
    output["ajax_resps_on_click"] = ajax_resps[:3]
    output["padel_criteria_html"] = after_padel.get("padel_criteria_section")

    print(f"\nSort options : {sort_opts}")
    print(f"fbid utilisé : {(fbid_padel or '')[:40]}")
    print(f"\nChamps après PADEL :")
    for name, vals in after_padel.get("fields", {}).items():
        if "padel" in name.lower() or "epreuve" in name.lower() or "famille" in name.lower():
            print(f"  {name} = {vals}")

    now = datetime.now()
    base = {
        "pratique": "PADEL",
        "date[start]": now.strftime("%d/%m/%y"),
        "date[end]":   (now + timedelta(days=90)).strftime("%d/%m/%y"),
        "form_id": "recherche_tournois_form",
        "_triggering_element_name": "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid_padel,
        "page": "0",
    }

    # Tester chaque valeur de sort
    print("\n=== Test sort options ===")
    for opt in sort_opts:
        sv = opt["v"] if isinstance(opt, dict) else opt
        r = ajax(session, {**base, "recherche_type": "ville",
            "ville[autocomplete][country]": "fr",
            "ville[autocomplete][textfield]": "",
            "ville[autocomplete][value_container][value_field]": "Paris, 75001",
            "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
            "ville[autocomplete][value_container][lat_field]": "48.859489",
            "ville[autocomplete][value_container][lng_field]": "2.347880",
            "ville[distance][value_field]": "50",
            "sort": sv,
        })
        sym = "✓" if r["nb"] > 0 else ("⚠" if not any("interdit" in m for m in r["msgs"]) else "✗")
        print(f"  {sym} sort='{sv}' → nb={r['nb']} msgs={r['msgs']}")
        output["tests"].append({"label": f"sort={sv}", **r})
        time.sleep(0.4)
        if r["nb"] > 0:
            break  # On a trouvé un sort valide

    # Trouver le premier sort valide
    valid_sort = next((t["label"].replace("sort=","") for t in output["tests"] if t.get("nb",0) > 0), None)
    if not valid_sort and sort_opts:
        valid_sort = sort_opts[0]["v"] if isinstance(sort_opts[0], dict) else sort_opts[0]

    print(f"\nSort valide trouvé : {valid_sort}")

    # Test ville complet avec le bon sort
    print("\n=== Test ville Paris (sort correct) ===")
    r = ajax(session, {**base, "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": "Paris, 75001",
        "ville[autocomplete][value_container][label_field]": "Paris, 75, Paris, Île-de-France",
        "ville[autocomplete][value_container][lat_field]": "48.859489",
        "ville[autocomplete][value_container][lng_field]": "2.347880",
        "ville[distance][value_field]": "50",
        "sort": valid_sort or "_DIST_",
    })
    print(f"  nb={r['nb']} msgs={r['msgs']}")
    output["tests"].append({"label": "ville Paris sort_correct", **r})
    time.sleep(0.5)

    # Si ville fonctionne, tester ligue
    if r.get("nb", 0) > 0:
        print("\n=== Test ligue IDF ===")
        r2 = ajax(session, {**base, "recherche_type": "ligue", "cbrappel[]": "57", "sort": valid_sort})
        print(f"  nb={r2['nb']} msgs={r2['msgs']}")
        output["tests"].append({"label": "ligue IDF cbrappel[]=57", **r2})

    # Résumé
    ville_ok = any(t.get("nb",0) > 0 and "ville" in t["label"] for t in output["tests"])
    ligue_ok = any(t.get("nb",0) > 0 and "ligue" in t["label"] for t in output["tests"])
    output["conclusion"] = f"sort_valide={valid_sort}, ville={'OK' if ville_ok else 'KO'}, ligue={'OK' if ligue_ok else 'KO'}"
    print(f"\n=== RÉSUMÉ ===")
    print(f"conclusion: {output['conclusion']}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("Sauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v9 sort+padel [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
