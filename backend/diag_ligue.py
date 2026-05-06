"""
Padel Alert — Diagnostic ligue v2
Améliorations v2 :
- wait_for_load_state("networkidle") après click radio (+ wait_for_selector)
- Capture de TOUS les éléments avec "ligue" dans leurs attributs (select + custom listbox)
- Interception réseau pour capturer les requêtes AJAX faites lors du click radio
- Dump HTML complet après click (50 000 chars)
- Tests AJAX avec codes devinés (IDF, PACA, ...) si select non trouvé
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
    "AUVERGNE RHONE-ALPES", "BOURGOGNE FRANCHE COMTE", "BRETAGNE",
    "CENTRE VAL DE LOIRE", "CORSE", "GRAND EST",
    "GUADELOUPE ST MARTIN ST BARTH", "GUYANE", "HAUTS DE FRANCE",
    "ILE DE FRANCE", "MARTINIQUE", "NORMANDIE", "NOUVELLE AQUITAINE",
    "NOUVELLE CALEDONIE", "OCCITANIE", "PAYS DE LA LOIRE",
    "PROVENCE ALPES COTE D'AZUR", "REUNION - MAYOTTE",
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
    result = {
        "ajax_requests_on_radio_click": [],
        "ajax_responses_on_radio_click": [],
        "ligue_elements_found": [],
        "ligue_select_name": None,
        "ligue_options": [],
        "comite_elements_found": [],
        "fbid": None,
        "html_after_ligue_radio_click": "",
        "html_selects_after_click": [],
        "intercepted_submit_request": None,
        "intercepted_submit_response_excerpt": None,
    }

    ajax_reqs  = []
    ajax_resps = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # ── Interception réseau ───────────────────────────────────────────────
        def on_request(req):
            if "/system/ajax" in req.url and req.method == "POST":
                ajax_reqs.append({
                    "url": req.url,
                    "post_data": req.post_data or "",
                    "timing": datetime.utcnow().isoformat(),
                })
        def on_response(resp):
            if "/system/ajax" in resp.url:
                try:
                    body = resp.text()
                    ajax_resps.append({
                        "url": resp.url,
                        "status": resp.status,
                        "body_excerpt": body[:2000],
                        "timing": datetime.utcnow().isoformat(),
                    })
                except:
                    pass
        page.on("request", on_request)
        page.on("response", on_response)

        # ── Chargement initial ────────────────────────────────────────────────
        print("  Ouverture Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        fbid    = page.evaluate("() => document.querySelector('input[name=\"form_build_id\"]')?.value")
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        result["fbid"]    = fbid
        result["cookies"] = cookies
        print(f"  fbid initial: {fbid[:30] if fbid else 'MANQUANT'}")

        # ── Click radio "ligue" ───────────────────────────────────────────────
        radio_ligue = page.query_selector('#edit-recherche-type-ligue, [name="recherche_type"][value="ligue"]')
        if radio_ligue:
            print("  Click radio recherche_type=ligue...")
            radio_ligue.click()
            # Attendre la fin de toutes les requêtes réseau
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except:
                page.wait_for_timeout(5000)
            print(f"  Réseau idle — {len(ajax_reqs)} req AJAX interceptées")
        else:
            print("  WARN: radio ligue non trouvé")

        result["ajax_requests_on_radio_click"]  = ajax_reqs.copy()
        result["ajax_responses_on_radio_click"] = ajax_resps.copy()

        # ── Dump HTML complet après click ─────────────────────────────────────
        html_after = page.content()
        result["html_after_ligue_radio_click"] = html_after[:50000]

        # ── Chercher select ligue (standard ou caché) ─────────────────────────
        selects_after = page.evaluate("""
            () => Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name, id: s.id, visible: s.offsetParent !== null,
                class: s.className,
                options: Array.from(s.options).map(o => ({v: o.value, t: o.text.trim()}))
            }))
        """)
        result["html_selects_after_click"] = selects_after
        print(f"  {len(selects_after)} select(s) trouvés après click")
        for s in selects_after:
            print(f"    name='{s['name']}' id='{s['id']}' visible={s['visible']} opts={len(s['options'])}")
            if "ligue" in (s["name"] + s["id"]).lower() and s["options"]:
                result["ligue_select_name"] = s["name"]
                result["ligue_options"]     = s["options"]

        # ── Chercher TOUS les éléments contenant "ligue" ──────────────────────
        ligue_els = page.evaluate("""
            () => {
                const res = [];
                document.querySelectorAll('*').forEach(el => {
                    const name    = el.getAttribute('name')  || '';
                    const id      = el.getAttribute('id')    || '';
                    const cls     = el.getAttribute('class') || '';
                    const dataRef = el.getAttribute('data-refer') || '';
                    if ((name+id+cls+dataRef).toLowerCase().includes('ligue')) {
                        res.push({
                            tag:     el.tagName,
                            name:    name,
                            id:      id,
                            class:   cls.substring(0,80),
                            value:   el.tagName === 'SELECT' ? el.value : (el.getAttribute('value') || dataRef),
                            visible: el.offsetParent !== null,
                            text:    (el.textContent || '').trim().substring(0, 100),
                            options: el.tagName === 'SELECT'
                                ? Array.from(el.options).map(o => ({v: o.value, t: o.text.trim()}))
                                : null,
                        });
                    }
                });
                return res.slice(0, 50);
            }
        """)
        result["ligue_elements_found"] = ligue_els
        print(f"  {len(ligue_els)} élément(s) avec 'ligue' dans leurs attributs:")
        for el in ligue_els:
            print(f"    <{el['tag']}> name='{el['name']}' id='{el['id']}' visible={el['visible']} opts={len(el['options'] or [])} text='{el['text'][:60]}'")

        # ── Chercher custom listbox (role="listbox" / role="option") ──────────
        listboxes = page.evaluate("""
            () => {
                const uls = document.querySelectorAll('[role="listbox"]');
                return Array.from(uls).map(ul => ({
                    id: ul.id, class: (ul.getAttribute('class')||'').substring(0,80),
                    items: Array.from(ul.querySelectorAll('[role="option"], li')).map(li => ({
                        dataRefer: li.getAttribute('data-refer') || '',
                        text: (li.textContent || '').trim().substring(0,60),
                        id: li.id || '',
                    }))
                }));
            }
        """)
        result["custom_listboxes"] = listboxes
        print(f"  {len(listboxes)} custom listbox(es) trouvé(s):")
        for lb in listboxes:
            items_preview = [f"{i['dataRefer']}={i['text'][:20]}" for i in lb['items'][:5]]
            print(f"    id='{lb['id']}' items={len(lb['items'])} preview={items_preview}")

        # ── Si options ligue trouvées : sélectionner IDF, chercher comités ────
        if result["ligue_options"]:
            idf_opt = next((o for o in result["ligue_options"] if "ILE" in normalize(o.get("t","")) or "IDF" == o.get("v","").upper()), None)
            if not idf_opt:
                idf_opt = result["ligue_options"][1] if len(result["ligue_options"]) > 1 else None
            if idf_opt and result["ligue_select_name"]:
                print(f"  Sélection ligue '{idf_opt['t']}' (v={idf_opt['v']}) pour détecter comités...")
                ajax_reqs.clear(); ajax_resps.clear()
                page.select_option(f'select[name="{result["ligue_select_name"]}"]', value=idf_opt["v"])
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except:
                    page.wait_for_timeout(3000)
                # Chercher éléments comité
                comite_els = page.evaluate("""
                    () => {
                        const res = [];
                        document.querySelectorAll('*').forEach(el => {
                            const name = el.getAttribute('name') || '';
                            const id   = el.getAttribute('id')   || '';
                            if ((name+id).toLowerCase().includes('comite') || (name+id).toLowerCase().includes('comité')) {
                                res.push({
                                    tag: el.tagName, name, id,
                                    value: el.tagName === 'SELECT' ? el.value : (el.getAttribute('value') || ''),
                                    visible: el.offsetParent !== null,
                                    options: el.tagName === 'SELECT'
                                        ? Array.from(el.options).map(o => ({v: o.value, t: o.text.trim()}))
                                        : null,
                                });
                            }
                        });
                        return res.slice(0, 30);
                    }
                """)
                result["comite_elements_found"]         = comite_els
                result["ajax_reqs_after_ligue_select"]  = ajax_reqs.copy()
                result["ajax_resps_after_ligue_select"] = [r for r in ajax_resps]
                print(f"  Comité elements: {len(comite_els)}, AJAX reqs: {len(ajax_reqs)}")

                # ── Essai soumission formulaire (intercepter la requête AJAX) ──
                print("  Soumission du formulaire pour intercepter les paramètres...")
                ajax_reqs.clear(); ajax_resps.clear()
                now = datetime.now()
                ds  = now.strftime("%d/%m/%y")
                de  = (now + timedelta(days=90)).strftime("%d/%m/%y")
                # Remplir dates
                for fname, val in [("date[start]", ds), ("date[end]", de)]:
                    el = page.query_selector(f'input[name="{fname}"]')
                    if el:
                        el.evaluate("(el, v) => { el.value = v; }", val)
                # Cliquer Rechercher
                submit = page.query_selector('[name="submit_main"], input[value="Rechercher"]')
                if submit:
                    submit.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except:
                        page.wait_for_timeout(5000)
                    result["intercepted_submit_request"] = ajax_reqs[-1] if ajax_reqs else None
                    result["intercepted_submit_response_excerpt"] = ajax_resps[-1]["body_excerpt"] if ajax_resps else None
                    print(f"  Submit: {len(ajax_reqs)} req capturée(s)")

        browser.close()

    result.pop("cookies", None)  # Ne pas commiter les cookies
    return result


def test_ajax_ligue(cookies, fbid, ligue_code, ligue_name):
    now = datetime.now()
    ds  = now.strftime("%d/%m/%y")
    de  = (now + timedelta(days=90)).strftime("%d/%m/%y")

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

    def do_req(page_num, extra_params=None):
        params = {
            "recherche_type": "ligue",
            "ligue": ligue_code,
            "pratique": "PADEL",
            "date[start]": ds, "date[end]": de,
            **ALL_CRITERIA,
            "sort": "_DATE_",
            "form_id": "recherche_tournois_form",
            "_triggering_element_name": "submit_main",
            "_triggering_element_value": "Rechercher",
            "form_build_id": fbid,
            "page": str(page_num),
        }
        if extra_params:
            params.update(extra_params)
        try:
            r = s.post(TENUP_AJAX, data=params, timeout=45)
            r.raise_for_status()
            cmds = r.json()
            for cmd in cmds:
                if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                    res = cmd.get("results", {})
                    return {
                        "http": r.status_code,
                        "nb_results": res.get("nb_results", 0),
                        "nb_items": len(res.get("items", [])),
                        "first_id": (res.get("items") or [{}])[0].get("id"),
                        "commands": [c.get("command") for c in cmds if isinstance(c, dict)],
                    }
            return {"http": r.status_code, "nb_results": 0, "nb_items": 0,
                    "commands": [c.get("command") for c in cmds if isinstance(c, dict)],
                    "raw": r.text[:300]}
        except Exception as e:
            return {"error": str(e)}

    print(f"  AJAX test code='{ligue_code}' ({ligue_name})...")
    r = {"ligue_name": ligue_name, "ligue_code": ligue_code}
    r["page_0"] = do_req(0)
    print(f"    page_0: {r['page_0']}")

    nb = r["page_0"].get("nb_results", 0)
    if nb > 30:
        time.sleep(0.5)
        r["page_1"] = do_req(1)
        print(f"    page_1: {r['page_1']}")
        r["pagination_ok"] = (
            r["page_0"].get("first_id") is not None and
            r["page_1"].get("first_id") is not None and
            r["page_0"]["first_id"] != r["page_1"]["first_id"]
        )
    return r


def main():
    output = {
        "run_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "discovery": {},
        "ligue_tests": [],
        "matched_ligues": [],
    }

    print("=== PHASE 1 : Découverte formulaire ===")
    disc = discover_form_and_ligues()
    output["discovery"] = disc
    fbid    = disc.get("fbid")
    cookies = disc.get("cookies", {})
    ligue_options = disc.get("ligue_options", [])

    print(f"\nfbid: {fbid}")
    print(f"Ligues trouvées dans select : {len(ligue_options)}")
    for o in ligue_options:
        print(f"  v='{o.get('v','')}' t='{o.get('t','')}'")

    print("\n=== PHASE 2 : Tests AJAX avec codes connus/devinés ===")
    # Combiner : options découvertes + codes FFT classiques à tester
    codes_to_test = []
    if ligue_options:
        # Extraire codes depuis les options découvertes
        idf_code  = next((o["v"] for o in ligue_options if "ILE" in normalize(o.get("t",""))), None)
        paca_code = next((o["v"] for o in ligue_options if "PROVENCE" in normalize(o.get("t","")) or "PACA" in normalize(o.get("t",""))), None)
        bre_code  = next((o["v"] for o in ligue_options if normalize(o.get("t","")) == "BRETAGNE"), None)
        if idf_code:  codes_to_test.append((idf_code,  "ILE DE FRANCE (découvert)"))
        if paca_code: codes_to_test.append((paca_code, "PACA (découvert)"))
        if bre_code:  codes_to_test.append((bre_code,  "BRETAGNE (découvert)"))
    else:
        # Aucun select trouvé — tester des codes FFT classiques
        codes_to_test = [
            ("IDF",  "ILE DE FRANCE (guess IDF)"),
            ("PACA", "PACA (guess PACA)"),
            ("ARA",  "AUVERGNE RHONE ALPES (guess ARA)"),
            ("OCC",  "OCCITANIE (guess OCC)"),
            ("NA",   "NOUVELLE AQUITAINE (guess NA)"),
            ("HDF",  "HAUTS DE FRANCE (guess HDF)"),
            ("GE",   "GRAND EST (guess GE)"),
            ("BRE",  "BRETAGNE (guess BRE)"),
            ("ALL",  "Toutes ligues (ligue=ALL)"),
            ("",     "Vide (ligue=vide)"),
        ]

    for code, name in codes_to_test[:8]:  # Max 8 tests
        t = test_ajax_ligue(cookies, fbid, code, name)
        output["ligue_tests"].append(t)
        time.sleep(0.5)

    # Matching
    print("\n=== PHASE 3 : Matching ligues cibles ===")
    matched = []
    norms = [(o, normalize(o.get("t", ""))) for o in ligue_options]
    for target in TARGET_LIGUE_NAMES:
        nt = normalize(target)
        found = next((o for o, n in norms if n == nt), None) or \
                next((o for o, n in norms if nt in n or (n and n in nt)), None)
        matched.append({"target": target, "code": found["v"] if found else None, "label": found["t"] if found else None})
        status = "✓" if found else "✗"
        print(f"  {status} {target} → {found['t'] if found else 'NON TROUVÉ'}")
    output["matched_ligues"] = matched

    # Résumé
    working = [t for t in output["ligue_tests"] if t.get("page_0", {}).get("nb_results", 0) > 0]
    print(f"\n=== RÉSUMÉ ===")
    print(f"Ligues dans select : {len(ligue_options)}")
    print(f"AJAX tests avec résultats : {len(working)}/{len(output['ligue_tests'])}")
    for t in working:
        print(f"  code='{t['ligue_code']}' → {t['page_0']['nb_results']} résultats, pagination_ok={t.get('pagination_ok','N/A')}")

    os.makedirs("data", exist_ok=True)
    with open("data/diag_ligue.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nSauvegardé dans data/diag_ligue.json")

    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name",  "padel-alert-bot"],    check=True)
    subprocess.run(["git", "add", "data/diag_ligue.json"], check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if diff.returncode != 0:
        subprocess.run(["git", "commit", "-m", f"diag_ligue v2 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Commit pushé.")


if __name__ == "__main__":
    main()
