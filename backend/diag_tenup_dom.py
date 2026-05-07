"""
Diagnostic Piste 4 — Test pagination via fetch() dans le contexte browser Playwright

Question centrale : quand on envoie page=0 puis page=1 depuis le VRAI navigateur
(avec ses vrais cookies, headers, contexte JS), les items sont-ils différents ?
Notre requests.Session retourne les mêmes 30 items sur page=1 — est-ce un problème
de cookies manquants, ou la pagination est vraiment cassée côté serveur ?

Méthode : page.evaluate(async ...) = fetch() depuis le browser Playwright,
pas via requests.Session externe. Si les résultats diffèrent → réécrire v7 avec
cette approche. Si identiques → pagination vraiment cassée, même niveau serveur.
"""
import json
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
TENUP_AJAX   = "https://tenup.fft.fr/system/ajax"
HORIZON_DAYS = 90

# Ville test : Montereau (~111 résultats, idéale pour tester la pagination)
VILLE_TEST = {
    "value":  "Montereau-Fault-Yonne, 77130",
    "label":  "Montereau-Fault-Yonne, 77, Seine-et-Marne, Île-de-France",
    "lat":    "48.3833",
    "lng":    "2.9500",
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


def ajax_via_browser(page, fbid, page_num, date_start, date_end):
    """
    Envoie une requête AJAX Ten'Up depuis le contexte browser Playwright (fetch interne).
    Utilise les vrais cookies/headers du browser, pas requests.Session externe.
    Retourne (items, nb_total) ou ([], 0) en cas d'erreur.
    """
    post_data = {
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
        "_triggering_element_name":  "submit_main",
        "_triggering_element_value": "Rechercher",
        "form_build_id": fbid,
        "page": str(page_num),
    }

    # Utiliser fetch() depuis le browser Playwright (vrais cookies, same-origin)
    result = page.evaluate("""async (params) => {
        try {
            const body = new URLSearchParams(params).toString();
            const response = await fetch('/system/ajax', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'Accept-Language': 'fr-FR,fr;q=0.9',
                },
                body: body,
            });
            const data = await response.json();
            for (const cmd of data) {
                if (cmd && cmd.command === 'recherche_tournois_update') {
                    const items = cmd.results?.items || [];
                    return {
                        ok: true,
                        status: response.status,
                        nb_total: cmd.results?.nb_results || 0,
                        count: items.length,
                        ids: items.map(it => String(it.id || '')),
                        first_item: items[0] ? {id: items[0].id, libelle: items[0].libelle} : null,
                    };
                }
            }
            return {ok: false, status: response.status, commands: data.map(c => c?.command)};
        } catch (e) {
            return {ok: false, error: String(e)};
        }
    }""", post_data)

    return result


def main():
    print("=" * 60)
    print("Diagnostic Piste 4 — fetch() browser Playwright")
    print("=" * 60)

    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")
    print(f"Ville: {VILLE_TEST['value']}, période: {date_start} → {date_end}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # ── 1. Charger Ten'Up ──────────────────────────────────────────────────
        print("\n1. Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        fbid = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value || ''")
        print(f"   form_build_id: {fbid[:40]}..." if fbid else "   ERREUR: form_build_id introuvable")

        if not fbid:
            print("Abandon — pas de form_build_id")
            browser.close()
            return

        # ── 2. Page 0 via fetch() browser ──────────────────────────────────────
        print("\n2. Requête AJAX page 0 (via fetch browser)...")
        r0 = ajax_via_browser(page, fbid, 0, date_start, date_end)
        print(f"   Résultat: {r0}")
        page.wait_for_timeout(2000)

        if not r0.get("ok"):
            print(f"\nErreur page 0 — arrêt. Détails: {r0}")
            page.screenshot(path="diag_error.png")
            browser.close()
            return

        ids_p0    = set(r0["ids"])
        nb_total  = r0["nb_total"]
        print(f"   Page 0 : {r0['count']} items, nb_total={nb_total}")
        print(f"   Premiers IDs: {r0['ids'][:5]}")
        print(f"   Premier item: {r0.get('first_item')}")

        # ── 3. Page 1 via fetch() browser ──────────────────────────────────────
        print("\n3. Requête AJAX page 1 (même fbid, page=1)...")
        r1 = ajax_via_browser(page, fbid, 1, date_start, date_end)
        print(f"   Résultat: {r1}")
        page.wait_for_timeout(2000)

        ids_p1 = set(r1.get("ids", [])) if r1.get("ok") else set()

        # ── 4. Page 2 si on en a besoin ────────────────────────────────────────
        r2 = None
        if r1.get("ok") and nb_total > 60:
            print("\n4. Requête AJAX page 2...")
            r2 = ajax_via_browser(page, fbid, 2, date_start, date_end)
            print(f"   Résultat: {r2}")
            page.wait_for_timeout(2000)

        # ── 5. Refresh fbid et tester avec un nouveau fbid ─────────────────────
        print("\n5. Refresh form_build_id et re-test page 1...")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        fbid2 = page.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value || ''")
        print(f"   Nouveau fbid: {fbid2[:40]}...")

        r1_fresh = None
        if fbid2 and fbid2 != fbid:
            print("   Test page 0 avec fbid frais...")
            r0_fresh = ajax_via_browser(page, fbid2, 0, date_start, date_end)
            print(f"   Page 0 (fbid frais): {r0_fresh}")
            page.wait_for_timeout(2000)
            print("   Test page 1 avec fbid frais...")
            r1_fresh = ajax_via_browser(page, fbid2, 1, date_start, date_end)
            print(f"   Page 1 (fbid frais): {r1_fresh}")

        browser.close()

    # ── Analyse finale ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ANALYSE FINALE")
    print("=" * 60)

    print(f"\nPage 0 : {len(ids_p0)} items (nb_total={nb_total})")

    if r1.get("ok"):
        ids_p1 = set(r1["ids"])
        overlap   = len(ids_p0 & ids_p1)
        new_in_p1 = len(ids_p1 - ids_p0)
        print(f"Page 1 : {len(ids_p1)} items")
        print(f"  Chevauchement avec page 0 : {overlap}/{len(ids_p0)}")
        print(f"  Nouveaux items en page 1   : {new_in_p1}")
        print(f"  Premiers IDs page 1: {r1['ids'][:5]}")

        if ids_p0 == ids_p1:
            print("\n→ RÉSULTAT : PAGINATION CASSÉE (page 1 == page 0, même depuis browser)")
            print("  Le problème est côté serveur Ten'Up, pas dans notre requests.Session.")
            print("  Piste 4 (DOM) ne résout pas le problème fondamental.")
        elif new_in_p1 > 0:
            print(f"\n→ RÉSULTAT : PAGINATION FONCTIONNE DEPUIS LE BROWSER !")
            print(f"  {new_in_p1} items nouveaux en page 1 → requests.Session manquait quelque chose.")
            print("  Solution : utiliser page.evaluate(fetch) dans le scraper v7 pour paginer.")
        else:
            print("\n→ RÉSULTAT AMBIGU")
    else:
        print(f"Page 1 : ÉCHEC — {r1}")

    if r2 and r2.get("ok"):
        ids_p2 = set(r2["ids"])
        overlap_p2 = len(ids_p0 & ids_p2)
        print(f"\nPage 2 : {len(ids_p2)} items, overlap avec p0={overlap_p2}")

    if r1_fresh:
        if r1_fresh.get("ok"):
            ids_p1f = set(r1_fresh["ids"])
            overlap_f = len(ids_p0 & ids_p1f)
            print(f"\nPage 1 (fbid frais) : {len(ids_p1f)} items, overlap avec p0={overlap_f}")
            if ids_p0 == ids_p1f:
                print("  → Même résultat avec fbid frais : pagination vraiment cassée")
            elif len(ids_p1f - ids_p0) > 0:
                print(f"  → {len(ids_p1f - ids_p0)} items nouveaux avec fbid frais !")
        else:
            print(f"\nPage 1 (fbid frais) : ÉCHEC — {r1_fresh}")


if __name__ == "__main__":
    main()
