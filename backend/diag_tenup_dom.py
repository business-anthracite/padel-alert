"""
Diagnostic — Hypothèse fbid chaîné

Observation : la pagination fonctionne sur le vrai site (12 pages vues par l'utilisateur).
Notre page=1 retourne les mêmes 30 items que page=0.

Hypothèse : Drupal renouvelle le form_build_id dans sa réponse AJAX.
Le vrai clic "page suivante" utilise ce nouveau fbid — pas l'original.
Nous envoyons toujours l'ancien fbid → serveur retourne la même page.

Ce diagnostic :
1. Requête page=0 → log TOUS les commands AJAX retournés
2. Cherche un nouveau form_build_id dans la réponse (settings, HTML, data...)
3. Utilise ce fbid renouvelé pour page=1
4. Compare les IDs page=0 vs page=1
"""
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
HORIZON_DAYS = 90

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


def make_post_data(fbid, page_num, date_start, date_end):
    return {
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


def ajax_full(page, fbid, page_num, date_start, date_end):
    """
    Requête AJAX depuis le browser Playwright.
    Retourne TOUS les commands + items extraits + nouveau fbid si trouvé.
    """
    post_data = make_post_data(fbid, page_num, date_start, date_end)

    return page.evaluate("""async (params) => {
        const body = new URLSearchParams(params).toString();
        let response;
        try {
            response = await fetch('/system/ajax', {
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
        } catch(e) { return {error: String(e)}; }

        let rawData;
        try { rawData = await response.json(); }
        catch(e) { return {error: 'JSON parse error: ' + String(e), status: response.status}; }

        const result = {
            http_status: response.status,
            commands: [],
            items: [],
            nb_total: 0,
            new_fbid: null,
            new_fbid_source: null,
        };

        // Regex pour trouver form_build_id dans du HTML
        const fbidRegex = /name=[\'""]form_build_id[\'""]\s+value=[\'""]([^\'"">]+)[\'""]|value=[\'""]([^\'"">]+)[\'""][^>]*name=[\'""]form_build_id[\'"\"]/;

        for (const cmd of rawData) {
            if (!cmd || typeof cmd !== 'object') continue;

            const cmdName = cmd.command || '(no command)';
            const cmdKeys = Object.keys(cmd).filter(k => k !== 'command');
            result.commands.push({name: cmdName, keys: cmdKeys});

            // Extraction items + nb_total
            if (cmdName === 'recherche_tournois_update') {
                result.items = (cmd.results?.items || []).map(i => String(i.id || ''));
                result.nb_total = cmd.results?.nb_results || 0;
            }

            // Chercher nouveau fbid dans settings Drupal
            if (cmdName === 'settings' && cmd.settings) {
                const s = JSON.stringify(cmd.settings);
                const m = s.match(/"form_build_id":"([^"]+)"/);
                if (m) { result.new_fbid = m[1]; result.new_fbid_source = 'settings'; }
                // Parfois dans ajaxPageState
                if (cmd.settings.ajaxPageState) {
                    result.ajax_page_state = JSON.stringify(cmd.settings.ajaxPageState).substring(0, 200);
                }
            }

            // Chercher dans le HTML injecté (insert, replace, html, prepend, append)
            if (['insert', 'replace', 'html', 'prepend', 'append', 'changed'].includes(cmdName)) {
                const html = typeof cmd.data === 'string' ? cmd.data :
                             typeof cmd.html === 'string' ? cmd.html : '';
                if (html && html.includes('form_build_id')) {
                    const m = html.match(fbidRegex);
                    if (m && !result.new_fbid) {
                        result.new_fbid = m[1] || m[2];
                        result.new_fbid_source = `${cmdName}:${cmd.selector || ''}`;
                    }
                }
                // Log le selector pour comprendre ce qui est mis à jour
                if (cmd.selector) result.commands[result.commands.length-1].selector = cmd.selector;
            }

            // Chercher dans n'importe quel champ string de la commande
            if (!result.new_fbid) {
                for (const [k, v] of Object.entries(cmd)) {
                    if (typeof v === 'string' && v.includes('form_build_id')) {
                        const m = v.match(fbidRegex);
                        if (m) {
                            result.new_fbid = m[1] || m[2];
                            result.new_fbid_source = `field:${k}`;
                        }
                    }
                }
            }
        }

        return result;
    }""", post_data)


def main():
    date_start = datetime.now().strftime("%d/%m/%y")
    date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

    print("=" * 60)
    print("Diagnostic — Hypothèse fbid chaîné (Ten'Up)")
    print(f"Ville: {VILLE_TEST['value']}, période: {date_start} → {date_end}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page_pw = ctx.new_page()

        print("\n1. Chargement Ten'Up...")
        page_pw.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page_pw.wait_for_timeout(8000)

        fbid0 = page_pw.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value || ''")
        print(f"   fbid initial : {fbid0[:50]}...")

        # ── Page 0 ────────────────────────────────────────────────────────────
        print("\n2. Requête page=0 (fbid initial)...")
        r0 = ajax_full(page_pw, fbid0, 0, date_start, date_end)
        print(f"   HTTP: {r0.get('http_status')}, items: {len(r0.get('items',[]))}, nb_total: {r0.get('nb_total')}")
        print(f"   Commandes retournées:")
        for c in r0.get("commands", []):
            print(f"     [{c['name']}] keys={c['keys']} {c.get('selector','')}")
        print(f"   Nouveau fbid trouvé: {r0.get('new_fbid', 'NON')}")
        if r0.get("new_fbid"):
            print(f"   Source: {r0.get('new_fbid_source')}")
        if r0.get("ajax_page_state"):
            print(f"   ajaxPageState: {r0['ajax_page_state']}")
        ids_p0 = r0.get("items", [])
        print(f"   IDs page 0: {ids_p0[:5]}")

        # ── Page 1 avec fbid initial (notre approche actuelle) ────────────────
        print("\n3. Requête page=1 (fbid INITIAL — approche actuelle)...")
        page_pw.wait_for_timeout(1000)
        r1_old = ajax_full(page_pw, fbid0, 1, date_start, date_end)
        print(f"   HTTP: {r1_old.get('http_status')}, items: {len(r1_old.get('items',[]))}, nb_total: {r1_old.get('nb_total')}")
        ids_p1_old = r1_old.get("items", [])
        print(f"   IDs page 1 (fbid initial): {ids_p1_old[:5]}")
        overlap_old = len(set(ids_p0) & set(ids_p1_old))
        print(f"   Chevauchement avec page 0: {overlap_old}/{len(ids_p0)}")

        # ── Page 1 avec nouveau fbid (hypothèse) ─────────────────────────────
        new_fbid = r0.get("new_fbid")
        if new_fbid and new_fbid != fbid0:
            print(f"\n4. Requête page=1 (NOUVEAU fbid de la réponse page=0)...")
            page_pw.wait_for_timeout(1000)
            r1_new = ajax_full(page_pw, new_fbid, 1, date_start, date_end)
            print(f"   HTTP: {r1_new.get('http_status')}, items: {len(r1_new.get('items',[]))}, nb_total: {r1_new.get('nb_total')}")
            ids_p1_new = r1_new.get("items", [])
            print(f"   IDs page 1 (nouveau fbid): {ids_p1_new[:5]}")
            overlap_new = len(set(ids_p0) & set(ids_p1_new))
            print(f"   Chevauchement avec page 0: {overlap_new}/{len(ids_p0)}")
            fbid1 = r1_new.get("new_fbid")
        else:
            print(f"\n4. Pas de nouveau fbid dans la réponse page=0 — hypothèse non vérifiable")
            print(f"   Essai avec fbid DOM rechargé...")
            # Recharger la page et prendre un fbid frais
            page_pw.reload(wait_until="domcontentloaded", timeout=30000)
            page_pw.wait_for_timeout(5000)
            fbid_fresh = page_pw.evaluate("() => document.querySelector('[name=\"form_build_id\"]')?.value || ''")

            # Faire page=0 pour "initialiser" le contexte de session
            print(f"   Page=0 avec fbid frais pour initialiser...")
            r0_init = ajax_full(page_pw, fbid_fresh, 0, date_start, date_end)
            fbid_after_p0 = r0_init.get("new_fbid") or fbid_fresh
            print(f"   Résultat init: items={len(r0_init.get('items',[]))}, new_fbid={r0_init.get('new_fbid','aucun')}")

            print(f"   Page=1 avec fbid post-p0...")
            r1_new = ajax_full(page_pw, fbid_after_p0, 1, date_start, date_end)
            ids_p1_new = r1_new.get("items", [])
            overlap_new = len(set(r0_init.get("items",[])) & set(ids_p1_new))
            print(f"   items={len(ids_p1_new)}, overlap={overlap_new}")
            print(f"   IDs: {ids_p1_new[:5]}")
            fbid1 = r1_new.get("new_fbid")

        # ── Page 2 pour confirmer la chaîne ───────────────────────────────────
        if fbid1 and fbid1 != new_fbid:
            print(f"\n5. Page=2 avec fbid chaîné (depuis réponse page=1)...")
            page_pw.wait_for_timeout(1000)
            r2 = ajax_full(page_pw, fbid1, 2, date_start, date_end)
            print(f"   HTTP: {r2.get('http_status')}, items: {len(r2.get('items',[]))}, nb_total: {r2.get('nb_total')}")
            print(f"   IDs page 2: {r2.get('items', [])[:5]}")
        else:
            print(f"\n5. Pas de fbid chaîné en page=1 — impossible de tester page=2")

        browser.close()

    # ── Analyse finale ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    if new_fbid and new_fbid != fbid0:
        print(f"Nouveau fbid trouvé dans réponse page=0 (source: {r0.get('new_fbid_source')})")
        if overlap_new < len(ids_p0):
            print(f"→ HYPOTHÈSE CONFIRMÉE : page=1 avec fbid renouvelé = {len(ids_p0)-overlap_new} items nouveaux !")
            print("  Solution : chaîner les fbid entre les requêtes de pagination.")
        else:
            print(f"→ Fbid renouvelé trouvé MAIS page=1 reste identique ({overlap_new}/{len(ids_p0)} overlap)")
            print("  Le fbid chaîné seul ne suffit pas.")
    else:
        print("Aucun nouveau fbid dans la réponse — la réponse AJAX ne renouvelle pas le fbid.")
        print("Hypothèse fbid-chaîné non confirmée.")
        print("→ Chercher une autre explication à la pagination côté navigateur.")


if __name__ == "__main__":
    main()
