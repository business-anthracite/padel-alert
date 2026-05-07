"""
Diagnostic — Test submit_page + ajax_page_state + ajax_html_ids

DÉCOUVERTE CLÉ (07/05/2026) :
La vraie requête "page suivante" envoie :
  _triggering_element_name  = submit_page   (pas submit_main !)
  _triggering_element_value = Submit page
  + ajax_page_state[theme/theme_token/css/js/jquery_version_token]
  + ajax_html_ids[] (liste de tous les IDs DOM — incl. card-collapse0..29)

Notre v6 envoie toujours submit_main → Drupal lance une nouvelle recherche → page 0.
Avec submit_page → Drupal navigue dans les résultats en session → page 1, 2, 3...

Ce diagnostic teste :
A. submit_page seul (sans ajax_page_state ni ajax_html_ids)
B. submit_page + ajax_page_state
C. submit_page + ajax_page_state + ajax_html_ids[] (requête la plus fidèle)
=> Confirmer lequel débloque la pagination.
"""
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
HORIZON_DAYS = 90

VILLE_TEST = {
    "value": "Montereau-Fault-Yonne, 77130",
    "label": "Montereau-Fault-Yonne, 77, Seine-et-Marne, Île-de-France",
    "lat":   "48.3833",
    "lng":   "2.9500",
}

NEW_CRITERIA = {
    "epreuve[DX]": "DX", "epreuve[DM]": "DM", "epreuve[DD]": "DD",
    "categorie_age[70|80|96|97|98|90|95|65|99|100]": "70|80|96|97|98|90|95|65|99|100",
    "categorie_age[110]": "110", "categorie_age[120]": "120", "categorie_age[125]": "125",
    "categorie_age[130]": "130", "categorie_age[140]": "140", "categorie_age[145]": "145",
    "categorie_age[160]": "160", "categorie_age[180]": "180", "categorie_age[200]": "200",
    "categorie_age[350]": "350", "categorie_age[400]": "400", "categorie_age[450]": "450",
    "categorie_age[500]": "500", "categorie_age[550]": "550", "categorie_age[600]": "600",
    "categorie_age[650]": "650", "categorie_age[700]": "700", "categorie_age[750]": "750",
    "categorie_age[800]": "800",
    "type[T]": "T", "type[C]": "C",
    "famille_tournois[TRADI]": "TRADI", "famille_tournois[MULTI]": "MULTI",
    "famille_tournois[TMC_D]": "TMC_D", "famille_tournois[TMC_M]": "TMC_M",
    "famille_tournois[COURT_ADUL]": "COURT_ADUL", "famille_tournois[TRADI_V]": "TRADI_V",
    "famille_tournois[MULTI_V]": "MULTI_V", "famille_tournois[GALAXIE_O]": "GALAXIE_O",
    "famille_tournois[GALAXIE_V]": "GALAXIE_V", "famille_tournois[CNGT]": "CNGT",
    "famille_tournois[NTC]": "NTC",
    "surface[B_PIL]": "B_PIL", "surface[DUR  ]": "DUR  ",
    "surface[GAZON]": "GAZON", "surface[AUTRE]": "AUTRE",
}

# CSS/JS statiques connus de Ten'Up (from real browser capture)
STATIC_CSS = [
    "modules/system/system.base.css", "misc/ui/jquery.ui.core.css",
    "misc/ui/jquery.ui.theme.css", "misc/ui/jquery.ui.menu.css",
    "misc/ui/jquery.ui.autocomplete.css", "misc/ui/jquery.ui.button.css",
    "misc/ui/jquery.ui.slider.css", "misc/ui/jquery.ui.datepicker.css",
    "modules/field/theme/field.css", "modules/node/node.css",
    "sites/all/modules/contrib/views/css/views.css",
    "sites/all/modules/contrib/back_to_top/css/back_to_top.css",
    "sites/all/modules/custom/recherche/css/select_icon.css",
    "sites/all/modules/custom/recherche/css/slider_custom.css",
    "sites/all/modules/custom/recherche/css/autocomplete_custom.css",
    "sites/all/modules/custom/recherche/css/date_range_custom.css",
    "sites/all/modules/custom/recherche/css/container_custom.css",
    "https://cdn.jsdelivr.net/npm/bootstrap@3.4.1/dist/css/bootstrap.min.css",
    "sites/all/themes/met/public/css/met.css",
]
STATIC_JS = [
    "https://cdn.jsdelivr.net/npm/bootstrap@3.4.1/dist/js/bootstrap.min.js",
    "misc/jquery.once.js", "misc/drupal.js",
    "sites/all/modules/contrib/jquery_update/replace/ui/ui/minified/jquery.ui.core.min.js",
    "sites/all/modules/contrib/jquery_update/replace/ui/ui/minified/jquery.ui.autocomplete.min.js",
    "misc/ajax.js",
    "sites/all/modules/custom/recherche/js/autocomplete_ville.js",
    "sites/all/modules/custom/recherche/modules/recherche_tournois/js/recherche_tournois.js",
    "sites/all/themes/met/public/js/rechercheTournoisResultats.js",
    "sites/all/themes/met/js/met.js",
]
# IDs DOM statiques (sans les card-collapse dynamiques)
STATIC_HTML_IDS = [
    "main-content", "block-system-main", "recherche-tournois-form",
    "form-tournois-errors", "edit-recherche-type", "edit-recherche-type-ville",
    "edit-recherche-type-club", "edit-recherche-type-ligue",
    "edit-ville", "edit-ville-autocomplete-country",
    "edit-ville-autocomplete-value-container",
    "edit-ville-autocomplete-value-container-value-field",
    "edit-ville-autocomplete-value-container-label-field",
    "all_cbrappel",
    "50_cbrappel", "51_cbrappel", "52_cbrappel", "53_cbrappel", "54_cbrappel",
    "55_cbrappel", "56_cbrappel", "57_cbrappel", "58_cbrappel", "59_cbrappel",
    "60_cbrappel", "61_cbrappel", "62_cbrappel", "63_cbrappel", "64_cbrappel",
    "65_cbrappel", "66_cbrappel", "67_cbrappel",
    "edit-submit", "edit-submit-sort", "edit-submit-page",
    "edit-pratique", "edit-pratique-tennis", "edit-pratique-padel",
    "epreuves-checkboxes-replace", "edit-epreuve",
    "edit-epreuve-dx", "edit-epreuve-dm", "edit-epreuve-dd",
    "categorie-age-checkboxes-replace", "edit-categorie-age",
    "type-container-replace", "edit-type",
    "more-container-replace", "categorie-tournoi-container-replace",
    "edit-categorie-tournoi",
    "edit-sort", "recherche-tournois-content-results-head",
    "recherche-tournois-pagination",
    "block-branding-branding-footer", "backtotop", "ui-datepicker-div",
]


def make_ajax_html_ids(n_cards=30):
    """Génère la liste des IDs DOM incluant les cards de résultats."""
    ids = list(STATIC_HTML_IDS)
    for i in range(n_cards):
        ids.append(f"card-collapse{i}")
    return ids


def ajax_fetch(page, fbid, page_num, date_start, date_end,
               use_submit_page=False, use_ajax_state=False,
               theme_token=None, jquery_version_token=None,
               use_html_ids=False, n_cards=30):
    """Requête AJAX avec options progressives."""
    if use_submit_page:
        trigger_name  = "submit_page"
        trigger_value = "Submit page"
    else:
        trigger_name  = "submit_main"
        trigger_value = "Rechercher"

    params = {
        "recherche_type": "ville",
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]":  VILLE_TEST["value"],
        "ville[autocomplete][value_container][label_field]":  VILLE_TEST["label"],
        "ville[autocomplete][value_container][lat_field]":    VILLE_TEST["lat"],
        "ville[autocomplete][value_container][lng_field]":    VILLE_TEST["lng"],
        "ville[distance][value_field]": "100",
        "pratique": "PADEL",
        "date[start]": date_start,
        "date[end]":   date_end,
        **NEW_CRITERIA,
        "sort": "_DIST_",
        "form_id": "recherche_tournois_form",
        "_triggering_element_name":  trigger_name,
        "_triggering_element_value": trigger_value,
        "form_build_id": fbid,
        "page": str(page_num),
    }

    if use_ajax_state and theme_token:
        params["ajax_page_state[theme]"]               = "met"
        params["ajax_page_state[theme_token]"]         = theme_token
        params["ajax_page_state[jquery_version]"]      = "2.2"
        for css in STATIC_CSS:
            params[f"ajax_page_state[css][{css}]"] = "1"
        for js in STATIC_JS:
            params[f"ajax_page_state[js][{js}]"] = "1"
        if jquery_version_token:
            params["ajax_page_state[jquery_version_token]"] = jquery_version_token

    if use_html_ids:
        # Les ajax_html_ids[] sont envoyés comme tableau — on les encode en JSON
        # pour les passer à evaluate() puis on reconstruit la query string
        html_ids = make_ajax_html_ids(n_cards)
        params["__html_ids__"] = html_ids  # flag spécial traité côté JS

    return page.evaluate("""async (p) => {
        try {
            const htmlIds = p.__html_ids__;
            delete p.__html_ids__;

            const parts = [];
            for (const [k, v] of Object.entries(p)) {
                parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
            }
            if (htmlIds) {
                for (const id of htmlIds) {
                    parts.push('ajax_html_ids%5B%5D=' + encodeURIComponent(id));
                }
            }
            const body = parts.join('&');

            const r = await fetch('/system/ajax', {
                method: 'POST', credentials: 'include',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                },
                body: body,
            });
            const data = await r.json();
            for (const cmd of data) {
                if (cmd?.command === 'recherche_tournois_update') {
                    const items = cmd.results?.items || [];
                    return {
                        ok: true, status: r.status,
                        nb_total: cmd.results?.nb_results || 0,
                        count: items.length,
                        ids: items.map(i => String(i.id || '')),
                    };
                }
            }
            return {ok: false, status: r.status,
                    commands: data.slice(0,5).map(c => c?.command)};
        } catch(e) { return {ok: false, error: String(e)}; }
    }""", params)


def compare(label, r0, r1):
    if not r0.get("ok") or not r1.get("ok"):
        print(f"  p0: {r0} | p1: {r1}")
        return False
    s0, s1 = set(r0["ids"]), set(r1["ids"])
    overlap = len(s0 & s1)
    new_in_1 = len(s1 - s0)
    print(f"  p0: {len(s0)} items (nb_total={r0.get('nb_total')})  IDs: {r0['ids'][:3]}")
    print(f"  p1: {len(s1)} items (nb_total={r1.get('nb_total')})  IDs: {r1['ids'][:3]}")
    print(f"  Overlap: {overlap}, Nouveaux en p1: {new_in_1}")
    if s0 == s1:
        print(f"  → IDENTIQUES — {label} ne suffit pas")
        return False
    else:
        print(f"  → DIFFÉRENTS ! {new_in_1} nouveaux items — {label} FONCTIONNE !")
        return True


def main():
    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print("=" * 60)
    print("Test submit_page + ajax_page_state + ajax_html_ids")
    print(f"Ville: {VILLE_TEST['value']}, {date_start} → {date_end}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        info = page.evaluate("""() => {
            const fbid = document.querySelector('[name="form_build_id"]')?.value || '';
            let theme_token = null, jquery_version_token = null;
            try { theme_token = Drupal.settings.ajaxPageState.theme_token; } catch(e) {}
            try { jquery_version_token = Drupal.settings.ajaxPageState.jquery_version_token; } catch(e) {}
            if (!theme_token) {
                const m = document.documentElement.innerHTML.match(/"theme_token":"([^"]+)"/);
                if (m) theme_token = m[1];
            }
            if (!jquery_version_token) {
                const m = document.documentElement.innerHTML.match(/"jquery_version_token":"([^"]+)"/);
                if (m) jquery_version_token = m[1];
            }
            return {fbid, theme_token, jquery_version_token};
        }""")
        fbid    = info["fbid"]
        tt      = info["theme_token"]
        jvt     = info["jquery_version_token"]
        print(f"\nfbid: {fbid[:40]}...")
        print(f"theme_token: {(tt or 'NON TROUVÉ')[:40]}")
        print(f"jquery_version_token: {(jvt or 'NON TROUVÉ')[:40]}")

        results = {}

        # ── Test A : submit_main (baseline v6) ────────────────────────────────
        print("\n── A. Baseline v6 (submit_main, sans ajax_page_state) ──")
        r0a = ajax_fetch(page, fbid, 0, date_start, date_end)
        page.wait_for_timeout(1000)
        r1a = ajax_fetch(page, fbid, 1, date_start, date_end)
        results["A"] = compare("submit_main seul", r0a, r1a)
        page.wait_for_timeout(1000)

        # ── Test B : submit_page seul ─────────────────────────────────────────
        print("\n── B. submit_page seul (sans ajax_page_state) ──")
        r0b = ajax_fetch(page, fbid, 0, date_start, date_end,
                         use_submit_page=False)  # p0 avec submit_main pour init
        page.wait_for_timeout(1000)
        r1b = ajax_fetch(page, fbid, 1, date_start, date_end,
                         use_submit_page=True)   # p1 avec submit_page
        results["B"] = compare("submit_page (sans état)", r0b, r1b)
        page.wait_for_timeout(1000)

        # ── Test C : submit_page + ajax_page_state ────────────────────────────
        print("\n── C. submit_page + ajax_page_state ──")
        r0c = ajax_fetch(page, fbid, 0, date_start, date_end,
                         use_submit_page=False, use_ajax_state=True, theme_token=tt, jquery_version_token=jvt)
        page.wait_for_timeout(1000)
        r1c = ajax_fetch(page, fbid, 1, date_start, date_end,
                         use_submit_page=True, use_ajax_state=True, theme_token=tt, jquery_version_token=jvt)
        results["C"] = compare("submit_page + ajax_state", r0c, r1c)
        page.wait_for_timeout(1000)

        # ── Test D : submit_page + ajax_page_state + ajax_html_ids ────────────
        print("\n── D. submit_page + ajax_page_state + ajax_html_ids[] ──")
        n_cards = len(r0c.get("ids", [])) if r0c.get("ok") else 30
        r0d = ajax_fetch(page, fbid, 0, date_start, date_end,
                         use_submit_page=False, use_ajax_state=True,
                         theme_token=tt, jquery_version_token=jvt, use_html_ids=True, n_cards=0)
        page.wait_for_timeout(1000)
        r1d = ajax_fetch(page, fbid, 1, date_start, date_end,
                         use_submit_page=True, use_ajax_state=True,
                         theme_token=tt, jquery_version_token=jvt, use_html_ids=True, n_cards=n_cards)
        results["D"] = compare("submit_page + ajax_state + html_ids", r0d, r1d)

        # ── Test E : si C ou D marche, tester p2, p3 ─────────────────────────
        best = next((k for k in ["D","C","B"] if results.get(k)), None)
        if best:
            print(f"\n── E. Pages 2 et 3 (méthode {best}) ──")
            cfg = dict(use_submit_page=True, use_ajax_state=(best in ["C","D"]),
                       theme_token=tt, jquery_version_token=jvt,
                       use_html_ids=(best=="D"), n_cards=30)
            r2 = ajax_fetch(page, fbid, 2, date_start, date_end, **cfg)
            page.wait_for_timeout(1000)
            r3 = ajax_fetch(page, fbid, 3, date_start, date_end, **cfg)
            print(f"  p2: ok={r2.get('ok')}, items={r2.get('count')}, nb_total={r2.get('nb_total')}, ids={r2.get('ids',[''])[:3]}")
            print(f"  p3: ok={r3.get('ok')}, items={r3.get('count')}, nb_total={r3.get('nb_total')}, ids={r3.get('ids',[''])[:3]}")
            all_ids = set(r0c.get("ids",[])) | set(r1c.get("ids",[])) | set(r2.get("ids",[])) | set(r3.get("ids",[]))
            print(f"  Total unique sur 4 pages: {len(all_ids)}")

        browser.close()

    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    for k, v in results.items():
        print(f"  {k}: {'✓ FONCTIONNE' if v else '✗ identiques'}")
    if any(results.values()):
        print("\n→ PAGINATION DÉBLOQUÉE — intégrer dans scraper v7 !")
    else:
        print("\n→ Aucun test concluant — autres pistes à explorer")
    print("=" * 60)


if __name__ == "__main__":
    main()
