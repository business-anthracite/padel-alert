"""
Diagnostic — Intercepter la vraie requête "page suivante" du navigateur

Observation clé : page=1 avec le fbid initial (post-chargement page) retourne
30 items réels (nb_total=136) — la session serveur a un cache de recherche.
Notre fetch synthétique (fresh fbid, page=1) retourne les mêmes items que page=0.

Hypothèse : Ten'Up stocke l'état de la recherche en session PHP côté serveur.
Le submit réel initialise cette session → page=1,2,3 fonctionnent depuis le browser.

Plan :
1. Remplir le formulaire via jQuery (invisible radio + autocomplete)
2. Intercepter TOUTES les requêtes réseau vers /system/ajax
3. Cliquer Rechercher (vrai submit) → capturer la requête page=0
4. Cliquer "page suivante" → capturer la requête page=1
5. Comparer les paramètres des deux requêtes
6. Vérifier que les items sont différents
"""
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, Route, Request

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
TENUP_AJAX   = "https://tenup.fft.fr/system/ajax"
HORIZON_DAYS = 90

date_start = datetime.now().strftime("%d/%m/%y")
date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")


def parse_post_body(body_str):
    """Parse une query string POST en dict."""
    from urllib.parse import parse_qs
    parsed = parse_qs(body_str, keep_blank_values=True)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def main():
    captured_requests = []  # [(label, params, response_ids, nb_total)]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # ── Intercepteur de requêtes réseau ───────────────────────────────────
        ajax_bodies   = {}   # request_id → post body string
        ajax_results  = {}   # request_id → (ids, nb_total)

        def on_request(request):
            if TENUP_AJAX in request.url and request.method == "POST":
                body = request.post_data or ""
                ajax_bodies[request._impl_obj._guid] = body

        def on_response(response):
            if TENUP_AJAX in response.url:
                req_id = response.request._impl_obj._guid
                try:
                    data = response.json()
                    for cmd in data:
                        if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                            items = cmd["results"].get("items", [])
                            ids   = [str(it.get("id","")) for it in items]
                            nb    = cmd["results"].get("nb_results", 0)
                            ajax_results[req_id] = (ids, nb)
                except Exception:
                    pass

        page.on("request",  on_request)
        page.on("response", on_response)

        # ── 1. Charger la page ────────────────────────────────────────────────
        print("1. Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        fbid_initial = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value || ''")
        print(f"   fbid initial: {fbid_initial[:50]}...")
        print(f"   Requêtes AJAX capturées au chargement: {len(ajax_results)}")

        # ── 2. Remplir le formulaire via jQuery ───────────────────────────────
        print("\n2. Remplissage formulaire via jQuery...")

        fill_result = page.evaluate(f"""() => {{
            const $ = jQuery || window.$;
            if (!$) return {{error: 'jQuery absent'}};

            // Cocher PADEL (radio caché — jQuery bypass la visibilité)
            $('[name="pratique"][value="PADEL"]').prop('checked', true).trigger('change');

            // Dates
            $('[name="date[start]"]').val("{date_start}").trigger('change');
            $('[name="date[end]"]').val("{date_end}").trigger('change');

            // Distance 100km
            $('[name="ville[distance][value_field]"]').val("100").trigger('change');

            // Critères (cocher tous)
            $('input[name^="epreuve["], input[name^="categorie_age["], input[name^="type["], input[name^="famille_tournois["], input[name^="surface["]')
                .prop('checked', true).trigger('change');

            return {{
                padel: $('[name="pratique"][value="PADEL"]').prop('checked'),
                criteriaCount: $('input[name^="epreuve["], input[name^="categorie_age["], input[name^="type["], input[name^="famille_tournois["], input[name^="surface["]').length,
                submitDisabled: $('[name="submit_main"]').prop('disabled'),
            }};
        }}""")
        print(f"   PADEL coché: {fill_result.get('padel')}, critères: {fill_result.get('criteriaCount')}, btn disabled: {fill_result.get('submitDisabled')}")

        # ── 3. Remplir l'autocomplete ville ───────────────────────────────────
        print("\n3. Autocomplete ville Paris...")
        ville_input = page.locator('input[name="ville[autocomplete][textfield]"]')
        ville_input.fill("Paris", timeout=5000)
        page.wait_for_timeout(3000)

        # Chercher les suggestions
        suggestion_found = False
        for sel in ['.ui-autocomplete .ui-menu-item', '.ui-menu .ui-menu-item', '[role="option"]']:
            count = page.locator(sel).count()
            if count > 0:
                print(f"   {count} suggestions ({sel})")
                # Afficher les premières
                for i in range(min(3, count)):
                    txt = page.locator(sel).nth(i).text_content()
                    print(f"     [{i}] {txt!r}")
                # Cliquer Paris 75001 si trouvé, sinon premier
                target = None
                for i in range(count):
                    txt = page.locator(sel).nth(i).text_content() or ""
                    if "75" in txt or "Paris" in txt.lower():
                        target = page.locator(sel).nth(i)
                        break
                if not target:
                    target = page.locator(sel).first
                target.click(timeout=3000)
                page.wait_for_timeout(1500)
                suggestion_found = True
                break

        if not suggestion_found:
            print("   Pas de suggestions — injection JS directe des hidden fields")
            page.evaluate("""() => {
                const $ = jQuery || window.$;
                $('[name="ville[autocomplete][value_container][value_field]"]').val("Paris, 75001").trigger('change');
                $('[name="ville[autocomplete][value_container][label_field]"]').val("Paris, 75, Paris, Île-de-France").trigger('change');
                $('[name="ville[autocomplete][value_container][lat_field]"]').val("48.859489").trigger('change');
                $('[name="ville[autocomplete][value_container][lng_field]"]').val("2.347880").trigger('change');
                // Forcer l'activation du bouton
                $('[name="submit_main"]').prop('disabled', false).removeAttr('disabled');
            }""")
            page.wait_for_timeout(500)

        # Vérifier état du bouton
        btn_state = page.evaluate("""() => ({
            disabled: document.querySelector('[name="submit_main"]')?.disabled,
            class: document.querySelector('[name="submit_main"]')?.className,
        })""")
        print(f"   Bouton submit: disabled={btn_state.get('disabled')}")

        # ── 4. Soumettre le formulaire ─────────────────────────────────────────
        print("\n4. Submit formulaire...")
        req_count_before = len(ajax_results)

        if not btn_state.get("disabled", True):
            page.locator('[name="submit_main"]').click(timeout=5000)
            print("   Click natif Playwright")
        else:
            # Forcer via jQuery trigger
            result = page.evaluate("""() => {
                const $ = jQuery || window.$;
                $('[name="submit_main"]').prop('disabled', false).removeAttr('disabled');
                $('[name="submit_main"]').trigger('click');
                return {clicked: true, method: 'jQuery trigger'};
            }""")
            print(f"   {result}")

        page.wait_for_timeout(12000)
        req_count_after = len(ajax_results)
        print(f"   Requêtes AJAX après submit: {req_count_after - req_count_before} nouvelles")

        # Screenshot
        page.screenshot(path="diag_after_submit.png")

        # ── 5. Analyser la requête de submit ──────────────────────────────────
        print("\n5. Analyse des requêtes interceptées...")
        print(f"   Total requêtes AJAX capturées: {len(ajax_results)}")
        for req_id, (ids, nb) in ajax_results.items():
            body = ajax_bodies.get(req_id, "")
            params = parse_post_body(body)
            page_num = params.get("page", "?")
            print(f"\n   --- Requête (page={page_num}, nb_total={nb}, items={len(ids)}) ---")
            # Afficher les paramètres clés
            key_params = {k: v for k, v in params.items()
                         if k in ("page", "sort", "form_build_id", "_triggering_element_name",
                                  "ajax_page_state[theme]", "ajax_page_state[theme_token]",
                                  "ajax_page_state[css]", "ajax_page_state[js]",
                                  "cbrappel[]", "ville[autocomplete][value_container][value_field]")}
            for k, v in key_params.items():
                val_str = str(v)[:80] if len(str(v)) > 80 else str(v)
                print(f"     {k} = {val_str!r}")
            if "ajax_page_state" not in str(params):
                print("     ajax_page_state: ABSENT")
            print(f"     IDs: {ids[:5]}")

        # ── 6. Chercher et cliquer "page suivante" ─────────────────────────────
        print("\n6. Recherche pagination dans le DOM...")
        pager_info = page.evaluate("""() => {
            const links = [...document.querySelectorAll('a')];
            const nextLinks = links.filter(a =>
                a.getAttribute('rel') === 'next' ||
                a.textContent.trim().toLowerCase().includes('suivant') ||
                (a.className || '').toLowerCase().includes('next') ||
                a.textContent.trim() === '›' || a.textContent.trim() === '»' || a.textContent.trim() === '>'
            );
            const pagerEls = document.querySelectorAll('[class*="pager"], nav[aria-label*="page"], .pagination');
            return {
                nextLinks: nextLinks.map(a => ({text: a.textContent.trim(), href: a.href, rel: a.rel, class: a.className})).slice(0,5),
                pagerCount: pagerEls.length,
                pagerHtml: pagerEls[0]?.outerHTML?.substring(0, 600),
            };
        }""")
        print(f"   Pagers trouvés: {pager_info['pagerCount']}")
        print(f"   Liens suivant: {pager_info['nextLinks']}")
        if pager_info.get("pagerHtml"):
            print(f"   Pager HTML:\n{pager_info['pagerHtml']}")

        if pager_info["nextLinks"]:
            print("\n   Clic 'page suivante'...")
            req_before_p2 = len(ajax_results)
            # Cliquer le lien via evaluate (pas de contrainte de visibilité)
            page.evaluate("""() => {
                const links = [...document.querySelectorAll('a')];
                const next = links.find(a =>
                    a.getAttribute('rel') === 'next' ||
                    a.textContent.trim().toLowerCase().includes('suivant') ||
                    a.textContent.trim() === '›' || a.textContent.trim() === '»'
                );
                if (next) next.click();
            }""")
            page.wait_for_timeout(8000)
            page_screenshot_2 = page.screenshot(path="diag_page2.png")
            req_after_p2 = len(ajax_results)
            print(f"   Nouvelles requêtes après clic: {req_after_p2 - req_before_p2}")

        browser.close()

    # ── Analyse finale ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ANALYSE FINALE")
    print("=" * 60)
    print(f"Total requêtes AJAX capturées: {len(ajax_results)}")

    pages_data = []
    for req_id, (ids, nb) in ajax_results.items():
        body = ajax_bodies.get(req_id, "")
        params = parse_post_body(body)
        pages_data.append({
            "page": params.get("page", "?"),
            "nb_total": nb,
            "ids": ids,
            "has_ajax_page_state": "ajax_page_state" in body,
            "fbid": (params.get("form_build_id", "") or "")[:30],
        })

    for i, pd in enumerate(pages_data):
        print(f"\nRequête {i}: page={pd['page']}, nb_total={pd['nb_total']}, items={len(pd['ids'])}")
        print(f"  ajax_page_state: {pd['has_ajax_page_state']}, fbid: {pd['fbid']}...")
        print(f"  IDs: {pd['ids'][:5]}")

    if len(pages_data) >= 2:
        ids0 = set(pages_data[0]["ids"])
        ids1 = set(pages_data[1]["ids"])
        overlap = len(ids0 & ids1)
        print(f"\nComparaison requête 0 vs requête 1:")
        print(f"  Overlap: {overlap}/{len(ids0)}")
        if overlap == 0:
            print("  → PAGINATION FONCTIONNE ! (items complètement différents)")
        elif overlap < len(ids0):
            print(f"  → Pagination partielle ({len(ids0)-overlap} nouveaux items)")
        else:
            print("  → Pagination cassée (items identiques)")


if __name__ == "__main__":
    main()
