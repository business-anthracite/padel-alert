"""
Padel Alert — Backend multi-utilisateurs
Tourne en continu sur Railway, exécute la vérification toutes les heures.
"""
import time
import schedule
import logging
from datetime import datetime

from config import CHECK_INTERVAL_MINUTES
from database import init_pool, close_pool, fetch_active_alerts, fetch_known_tournament_ids, save_known_tournaments, log_notification
from tenup import get_session, make_session, fetch_tournaments_for_alert
from notifications import send_alert_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def run_check():
    log.info("═══ Début de la vérification ═══")
    start = datetime.now()

    alerts = fetch_active_alerts()
    if not alerts:
        log.info("Aucune alerte active.")
        return

    log.info(f"{len(alerts)} alerte(s) active(s) à traiter.")

    # Une seule session Playwright pour tout le cycle
    try:
        log.info("Ouverture de la session Ten'Up...")
        form_build_id, cookies = get_session()
        session = make_session(cookies)
        log.info("Session Ten'Up OK.")
    except Exception as e:
        log.error(f"Impossible d'ouvrir la session Ten'Up : {e}")
        return

    total_new  = 0
    total_sent = 0

    for alert in alerts:
        alert_id   = str(alert["id"])
        alert_name = alert.get("name") or alert["location_value"]
        log.info(f"  Alerte [{alert_id[:8]}] {alert['first_name']} — {alert_name}")

        try:
            tournaments = fetch_tournaments_for_alert(session, alert)
            log.info(f"    → {len(tournaments)} tournoi(s) dans la zone")
        except Exception as e:
            log.error(f"    ✗ Erreur scraping : {e}")
            continue

        known_ids   = fetch_known_tournament_ids(alert_id)
        new_ones    = [t for t in tournaments if t["id"] not in known_ids]

        if new_ones:
            log.info(f"    → {len(new_ones)} NOUVEAU(X) ! Envoi email à {alert['email']}")
            try:
                send_alert_email(
                    user_email=alert["email"],
                    first_name=alert["first_name"],
                    alert_name=alert_name,
                    tournaments=new_ones,
                )
                save_known_tournaments(alert_id, new_ones)
                log_notification(str(alert["user_id"]), alert_id, new_ones)
                total_new  += len(new_ones)
                total_sent += 1
                log.info(f"    ✓ Email envoyé.")
            except Exception as e:
                log.error(f"    ✗ Erreur envoi email : {e}")
        else:
            log.info(f"    → Aucun nouveau tournoi.")
            # Mise à jour de la liste des connus même sans nouveaux (évite les re-détections)
            save_known_tournaments(alert_id, tournaments)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"═══ Fin — {total_new} nouveau(x) tournoi(s), {total_sent} email(s) envoyé(s) en {elapsed:.1f}s ═══")


def main():
    log.info("Padel Alert backend démarré.")
    init_pool()

    # Premier passage immédiat au démarrage
    run_check()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_check)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        log.info("Arrêt demandé.")
    finally:
        close_pool()


if __name__ == "__main__":
    main()
