"""
Diagnostic Piste 4 — Test pagination DOM Ten'Up via Playwright

Question centrale : quand Playwright clique réellement "page suivante",
l'AJAX retourne-t-il des items différents de la page 0 ?
(notre approche AJAX synthétique avec page=1,2... retourne toujours les mêmes 30 items)

Résultats dans les logs GitHub Actions + screenshot en artifact.
"""
import json
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

TENUP_SEARCH = "https://tenup.fft.fr/recherche/tournois"
TENUP_AJAX   = "https://tenup.fft.fr/system/ajax"
HORIZON_DAYS = 90

# Ville test : Montereau (nb_total ~111, v6 n'en scrape que ~91)
VILLE_TEST = {
    "value":  "Montereau-Fault-Yonne, 77130",
    "label":  "Montereau-Fault-Yonne, 77, Seine-et-Marne, Île-de-France",
    "lat":    "48.3833",
    "lng":    "2.9500",
}

NEW_CRITERIA_KEYS = [
    "epreuve[DX]", "epreuve[DM]", "epreuve[DD]",
    "categorie_age[70|80|96|97|98|90|95|65|99|100]",
    "categorie_age[110]", "categorie_age[120]", "categorie_age[125]",
    "categorie_age[130]", "categorie_age[140]", "categorie_age[145]",
    "categorie_age[160]", "categorie_age[180]", "categorie_age[200]",
    "categorie_age[350]", "categorie_age[400]", "categorie_age[450]",
    "categorie_age[500]", "categorie_age[550]", "categorie_age[600]",
    "categorie_age[650]", "categorie_age[700]", "categorie_age[750]",
    "categorie_age[800]",
    "type[T]", "type[C]",
    "famille_tournois[TRADI]", "famille_tournois[MULTI]",
    "famille_tournois[TMC_D]", "famille_tournois[TMC_M]",
    "famille_tournois[COURT_ADUL]", "famille_tournois[TRADI_V]",
    "famille_tournois[MULTI_V]", "famille_tournois[GALAXIE_O]",
    "famille_tournois[GALAXIE_V]", "famille_tournois[CNGT]", "famille_tournois[NTC]",
    "surface[B_PIL]", "surface[DUR  ]", "surface[GAZON]", "surface[AUTRE]",
]


def main():
    intercepted = []  # liste de {page_num, nb_total, count, ids}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = ctx.new_page()

        # ── Intercepter les réponses AJAX ──────────────────────────────────────
        def on_response(response):
            if TENUP_AJAX in response.url:
                try:
                    data = response.json()
                    for cmd in data:
                        if isinstance(cmd, dict) and cmd.get("command") == "recherche_tournois_update":
                            items    = cmd["results"].get("items", [])
                            nb_total = cmd["results"].get("nb_results", 0)
                            ids      = [str(it.get("id", "")) for it in items]
                            entry = {
                                "page_num": len(intercepted),
                                "nb_total": nb_total,
                                "count":    len(ids),
                                "ids":      ids,
                            }
                            intercepted.append(entry)
                            print(f"[AJAX p{entry['page_num']}] {len(ids)} items, nb_total={nb_total}, "
                                  f"first_ids={ids[:3]}")
                except Exception as e:
                    pass

        page.on("response", on_response)

        # ── 1. Charger la page ─────────────────────────────────────────────────
        print("=" * 60)
        print("1. Chargement Ten'Up...")
        page.goto(TENUP_SEARCH, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # ── 2. Inspecter le formulaire ─────────────────────────────────────────
        print("\n2. Inspection formulaire...")
        form_info = page.evaluate("""() => {
            const form = document.querySelector('form');
            if (!form) return {found: false, html: document.body.innerHTML.substring(0, 500)};
            const inputs = [...form.querySelectorAll('input,select')].map(el => ({
                name: el.name, type: el.type, value: (el.value || '').substring(0, 50)
            })).filter(el => el.name);
            return {found: true, id: form.id, action: form.action, inputCount: inputs.length, inputs: inputs.slice(0, 40)};
        }""")
        print(f"Formulaire trouvé: {form_info.get('found')}, id={form_info.get('id')}, inputs={form_info.get('inputCount')}")
        if form_info.get("inputs"):
            for inp in form_info["inputs"][:15]:
                print(f"  [{inp['type']}] {inp['name']} = {inp['value']!r}")

        # ── 3. Remplir le formulaire via JS ────────────────────────────────────
        print("\n3. Remplissage formulaire (JS direct)...")
        date_start = datetime.now().strftime("%d/%m/%y")
        date_end   = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%d/%m/%y")

        fill_values = {
            "recherche_type":                                          "ville",
            "ville[autocomplete][country]":                           "fr",
            "ville[autocomplete][textfield]":                         VILLE_TEST["value"],
            "ville[autocomplete][value_container][value_field]":      VILLE_TEST["value"],
            "ville[autocomplete][value_container][label_field]":      VILLE_TEST["label"],
            "ville[autocomplete][value_container][lat_field]":        VILLE_TEST["lat"],
            "ville[autocomplete][value_container][lng_field]":        VILLE_TEST["lng"],
            "ville[distance][value_field]":                           "100",
            "pratique":                                               "PADEL",
            "date[start]":                                            date_start,
            "date[end]":                                              date_end,
            "sort":                                                   "_DIST_",
        }
        fill_result = page.evaluate("(vals) => { let ok=0, nf=[]; for (const [n,v] of Object.entries(vals)) { const el=document.querySelector(`[name='${n}']`); if(el){el.value=v;ok++;}else{nf.push(n);} } return {ok, notFound: nf}; }", fill_values)
        print(f"  Champs remplis: {fill_result['ok']}, non trouvés: {fill_result['notFound']}")

        # Cocher les checkboxes critères
        checked_result = page.evaluate("(keys) => { let ok=0, nf=[]; for (const k of keys) { const el=document.querySelector(`input[name='${k}']`); if(el){el.checked=true;ok++;}else{nf.push(k);} } return {ok, notFound: nf}; }", NEW_CRITERIA_KEYS)
        print(f"  Critères cochés: {checked_result['ok']}, non trouvés: {checked_result['notFound'][:5]}")

        # ── 4. Soumettre ───────────────────────────────────────────────────────
        print("\n4. Clic Rechercher...")
        submit_result = page.evaluate("""() => {
            const btn = document.querySelector('[name="submit_main"]') ||
                        document.querySelector('input[value="Rechercher"]') ||
                        document.querySelector('input[type="submit"]');
            if (!btn) return {found: false};
            btn.click();
            return {found: true, name: btn.name, value: btn.value};
        }""")
        print(f"  Submit: {submit_result}")
        page.wait_for_timeout(10000)

        # ── 5. Screenshot post-submit ──────────────────────────────────────────
        page.screenshot(path="diag_p0.png")
        print("  Screenshot page 0 sauvegardé.")

        # ── 6. Inspecter la pagination ─────────────────────────────────────────
        print("\n5. Inspection pagination...")
        pager_info = page.evaluate("""() => {
            // Chercher la pagination avec plusieurs sélecteurs courants
            const candidates = [
                '.pager', '.pager--below', 'nav.pager', 'ul.pager',
                '.pagination', 'nav[role="navigation"]',
                '[class*="pager"]', '[class*="pagination"]',
            ];
            let pagerEl = null;
            for (const sel of candidates) {
                pagerEl = document.querySelector(sel);
                if (pagerEl) break;
            }
            // Chercher "suivant" dans tous les liens
            const allLinks = [...document.querySelectorAll('a')];
            const nextLinks = allLinks.filter(a =>
                a.textContent.toLowerCase().includes('suivant') ||
                a.getAttribute('title')?.toLowerCase().includes('suivant') ||
                a.getAttribute('rel') === 'next' ||
                a.textContent.trim() === '>' ||
                a.textContent.trim() === '›' ||
                a.textContent.trim() === '»'
            );
            return {
                pagerFound:    !!pagerEl,
                pagerSelector: candidates.find(sel => document.querySelector(sel)) || null,
                pagerHtml:     pagerEl?.outerHTML?.substring(0, 800) || null,
                nextLinks:     nextLinks.map(a => ({text: a.textContent.trim(), href: a.href, title: a.title || ''})).slice(0, 5),
            };
        }""")
        print(f"  Pager trouvé: {pager_info['pagerFound']} (sélecteur: {pager_info['pagerSelector']})")
        print(f"  Liens 'suivant': {pager_info['nextLinks']}")
        if pager_info["pagerHtml"]:
            print(f"  Pager HTML: {pager_info['pagerHtml']}")

        # ── 7. Cliquer "page suivante" ─────────────────────────────────────────
        if intercepted and intercepted[0]["nb_total"] > 30:
            print(f"\n6. Clic page suivante (nb_total={intercepted[0]['nb_total']} > 30)...")
            click_result = page.evaluate("""() => {
                const selectors = [
                    'li.pager__item--next a', '.pager-next a', '.pager--next a',
                    'a[rel="next"]', 'a[title*="suivant"]', 'a[title*="Suivant"]',
                    '.pagination .next a', 'li.next a',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) { el.click(); return {clicked: true, sel, text: el.textContent.trim(), href: el.href}; }
                }
                // Fallback : texte "›", "»", ">", "suivant"
                for (const a of document.querySelectorAll('a')) {
                    const t = a.textContent.trim().toLowerCase();
                    if (t === '›' || t === '»' || t === '>' || t === 'suivant' || t === 'page suivante') {
                        a.click();
                        return {clicked: true, sel: 'text', text: a.textContent.trim(), href: a.href};
                    }
                }
                return {clicked: false, reason: 'bouton non trouvé'};
            }""")
            print(f"  Clic: {click_result}")
            page.wait_for_timeout(8000)
            page.screenshot(path="diag_p1.png")
            print("  Screenshot page 1 sauvegardé.")
        else:
            reason = "pas assez de résultats" if not intercepted else f"nb_total={intercepted[0]['nb_total']} ≤ 30"
            print(f"\n6. Pas de clic page suivante ({reason})")

        # ── 8. Extraire un échantillon DOM de carte tournoi ───────────────────
        print("\n7. Extraction HTML carte tournoi (structure DOM)...")
        card_info = page.evaluate("""() => {
            // Chercher les cards de résultat
            const candidates = [
                '.views-row', '.card', '.tournoi', '[class*="result"]',
                '.view-content > *', 'article', '.node',
            ];
            for (const sel of candidates) {
                const els = document.querySelectorAll(sel);
                if (els.length > 2) {
                    return {
                        selector: sel,
                        count: els.length,
                        sample: els[0]?.outerHTML?.substring(0, 1000) || '',
                    };
                }
            }
            // Dernier recours: premier enfant du main/article
            const main = document.querySelector('main, #main, .main, #content');
            return {
                selector: 'none found',
                count: 0,
                bodySnippet: main?.innerHTML?.substring(0, 2000) || document.body.innerHTML.substring(0, 2000),
            };
        }""")
        print(f"  Cards: {card_info.get('count')} (sélecteur: {card_info.get('selector')})")
        if card_info.get("sample"):
            print(f"  Sample HTML:\n{card_info['sample'][:600]}")
        elif card_info.get("bodySnippet"):
            print(f"  Body snippet:\n{card_info['bodySnippet'][:800]}")

        browser.close()

    # ── Analyse finale ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ANALYSE FINALE")
    print("=" * 60)
    print(f"Réponses AJAX interceptées : {len(intercepted)}")

    for entry in intercepted:
        print(f"  Page {entry['page_num']}: {entry['count']} items, nb_total={entry['nb_total']}, "
              f"first_id={entry['ids'][0] if entry['ids'] else 'N/A'}")

    if len(intercepted) >= 2:
        set0 = set(intercepted[0]["ids"])
        set1 = set(intercepted[1]["ids"])
        overlap   = len(set0 & set1)
        new_in_p1 = len(set1 - set0)
        pct_new   = new_in_p1 / len(set1) * 100 if set1 else 0

        print(f"\nComparaison page 0 vs page 1 :")
        print(f"  Page 0 : {len(set0)} items")
        print(f"  Page 1 : {len(set1)} items")
        print(f"  Chevauchement : {overlap}")
        print(f"  Nouveaux dans page 1 : {new_in_p1} ({pct_new:.0f}%)")

        if overlap == len(set0) and overlap == len(set1):
            print("\n→ RÉSULTAT : PAGINATION CASSÉE — page 1 == page 0 (mêmes 30 items)")
            print("  La piste 4 DOM ne résout pas le problème fondamental.")
            print("  → Envisager piste 5 (couverture géographique) ou combiner toutes pistes précédentes.")
        elif new_in_p1 > 0:
            print(f"\n→ RÉSULTAT : PAGINATION FONCTIONNE !")
            print(f"  {new_in_p1} nouveaux items en page 1 ({pct_new:.0f}% différents)")
            print("  → Écrire scraper_france_v7.py basé sur Playwright DOM + navigation réelle.")
        else:
            print(f"\n→ RÉSULTAT AMBIGU : à analyser manuellement.")

    elif len(intercepted) == 1:
        e = intercepted[0]
        print(f"\nUne seule page AJAX ({e['count']} items, nb_total={e['nb_total']})")
        if e["nb_total"] <= 30:
            print("  Normal : < 30 résultats pour cette ville/rayon.")
        else:
            print("  Soumission OK mais page suivante non trouvée/cliquée.")
            print("  → Inspecter les screenshots et le pager HTML pour trouver le bon sélecteur.")
    else:
        print("\nAucune réponse AJAX capturée.")
        print("  → La soumission du formulaire a probablement échoué.")
        print("  → Inspecter la section 'Formulaire' et 'Submit' dans les logs ci-dessus.")


if __name__ == "__main__":
    main()
