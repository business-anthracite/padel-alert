"""
Diagnostic — Test ajax_page_state dans les requêtes synthétiques

Découverte v7 : le vrai navigateur envoie ajax_page_state[theme] et
ajax_page_state[theme_token] dans ses requêtes AJAX. Nos appels synthétiques
(v6 scraper, diagnostics précédents) n'envoyaient pas ces paramètres.

Ce diagnostic :
1. Extrait theme_token depuis le JS de la page (Drupal.settings)
2. Teste les requêtes synthétiques AVEC et SANS ajax_page_state
3. Compare page=0 vs page=1 dans les deux cas
=> Si page=1 avec ajax_page_state retourne des items différents : SOLUTION TROUVÉE
"""
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
HORIZON_DAYS = 90

# Paris avec distance 100km — devrait avoir >30 résultats
VILLE_TEST = {
    "value": "Paris, 75001",
    "label": "Paris, 75, Paris, Île-de-France",
    "lat":   "48.859489",
    "lng":   "2.347880",
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


def ajax_fetch(page, fbid, page_num, date_start, date_end, theme_token=None):
    """Requête AJAX via fetch() browser. Optionnel : inclure ajax_page_state."""
    base = {
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
    if theme_token:
        base["ajax_page_state[theme]"]       = "met"
        base["ajax_page_state[theme_token]"] = theme_token

    return page.evaluate("""async (params) => {
        try {
            const r = await fetch('/system/ajax', {
                method: 'POST', credentials: 'include',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                },
                body: new URLSearchParams(params).toString(),
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
            const cmds = data.map(c => c?.command).filter(Boolean);
            return {ok: false, status: r.status, commands: cmds};
        } catch(e) { return {ok: false, error: String(e)}; }
    }""", base)


def main():
    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

    print("=" * 60)
    print("Diagnostic — ajax_page_state dans les requêtes synthétiques")
    print(f"Ville: Paris 100km, période: {date_start} → {date_end}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # 1. Charger la page
        print("\n1. Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # Extraire fbid et theme_token
        info = page.evaluate("""() => {
            const fbid = document.querySelector('[name="form_build_id"]')?.value || '';
            let theme_token = null;
            // Drupal 7 : Drupal.settings.ajaxPageState
            try { theme_token = Drupal.settings.ajaxPageState.theme_token; } catch(e) {}
            if (!theme_token) {
                const m = document.documentElement.innerHTML.match(/"theme_token":"([^"]+)"/);
                if (m) theme_token = m[1];
            }
            return {fbid, theme_token};
        }""")
        fbid         = info["fbid"]
        theme_token  = info["theme_token"]
        print(f"   fbid:         {fbid[:50]}...")
        print(f"   theme_token:  {(theme_token or 'NON TROUVÉ')[:50]}")

        # ── 2. SANS ajax_page_state (approche actuelle v6) ────────────────────
        print("\n2. Page=0 SANS ajax_page_state (approche v6 actuelle)...")
        r0_sans = ajax_fetch(page, fbid, 0, date_start, date_end, theme_token=None)
        print(f"   → {r0_sans}")
        page.wait_for_timeout(1500)

        print("\n3. Page=1 SANS ajax_page_state...")
        r1_sans = ajax_fetch(page, fbid, 1, date_start, date_end, theme_token=None)
        print(f"   → {r1_sans}")
        page.wait_for_timeout(1500)

        # ── 3. AVEC ajax_page_state ───────────────────────────────────────────
        # Recharger pour avoir un fbid frais
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        info2 = page.evaluate("""() => {
            const fbid = document.querySelector('[name="form_build_id"]')?.value || '';
            let tt = null;
            try { tt = Drupal.settings.ajaxPageState.theme_token; } catch(e) {}
            if (!tt) { const m = document.documentElement.innerHTML.match(/"theme_token":"([^"]+)"/); if(m) tt=m[1]; }
            return {fbid, theme_token: tt};
        }""")
        fbid2  = info2["fbid"]
        token2 = info2["theme_token"]
        print(f"\n4. Page=0 AVEC ajax_page_state (theme_token={token2 and token2[:30]}...)...")
        r0_avec = ajax_fetch(page, fbid2, 0, date_start, date_end, theme_token=token2)
        print(f"   → {r0_avec}")
        page.wait_for_timeout(1500)

        print("\n5. Page=1 AVEC ajax_page_state (même fbid)...")
        r1_avec = ajax_fetch(page, fbid2, 1, date_start, date_end, theme_token=token2)
        print(f"   → {r1_avec}")
        page.wait_for_timeout(1500)

        # Page=2 et =3 si page=1 est différente
        if r1_avec.get("ok") and r0_avec.get("ok"):
            ids0 = set(r0_avec.get("ids", []))
            ids1 = set(r1_avec.get("ids", []))
            if ids1 - ids0:
                print("\n   Page=1 différente ! Test page=2...")
                r2_avec = ajax_fetch(page, fbid2, 2, date_start, date_end, theme_token=token2)
                print(f"   Page=2: {r2_avec}")
                page.wait_for_timeout(1500)
                r3_avec = ajax_fetch(page, fbid2, 3, date_start, date_end, theme_token=token2)
                print(f"   Page=3: {r3_avec}")

        browser.close()

    # ── Analyse ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ANALYSE")
    print("=" * 60)

    def compare(label_a, ra, label_b, rb):
        if not ra.get("ok") or not rb.get("ok"):
            print(f"{label_a}: {ra}")
            print(f"{label_b}: {rb}")
            return
        ids_a = set(ra["ids"])
        ids_b = set(rb["ids"])
        overlap = len(ids_a & ids_b)
        new_in_b = len(ids_b - ids_a)
        print(f"{label_a}: {len(ids_a)} items (nb_total={ra.get('nb_total')})")
        print(f"{label_b}: {len(ids_b)} items (nb_total={rb.get('nb_total')})")
        print(f"  Overlap: {overlap}, Nouveaux dans B: {new_in_b}")
        if ids_a == ids_b:
            print("  → IDENTIQUES")
        elif new_in_b > 0:
            print(f"  → DIFFÉRENTS ! {new_in_b} nouveaux items")

    print("\nSANS ajax_page_state :")
    compare("  Page=0", r0_sans, "  Page=1", r1_sans)

    print("\nAVEC ajax_page_state :")
    compare("  Page=0", r0_avec, "  Page=1", r1_avec)

    # Conclusion
    ids0_avec = set(r0_avec.get("ids", []))
    ids1_avec = set(r1_avec.get("ids", []))
    ids0_sans = set(r0_sans.get("ids", []))
    ids1_sans = set(r1_sans.get("ids", []))

    print("\n" + "=" * 60)
    if ids1_avec - ids0_avec:
        print("✓ SOLUTION TROUVÉE : ajax_page_state débloque la pagination !")
        print("  Ajouter ajax_page_state[theme] + [theme_token] dans le scraper v7.")
    elif ids1_sans - ids0_sans:
        print("✓ Pagination fonctionne même SANS ajax_page_state")
        print("  Autre explication à trouver.")
    else:
        print("✗ Pagination toujours cassée même avec ajax_page_state")
        print("  Autre mécanisme à investiguer (cbrappel[], cookie session, etc.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
