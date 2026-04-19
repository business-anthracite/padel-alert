"""
Envoi des emails de notification via l'API Brevo (transactionnel).
Template HTML fidèle à la charte graphique Padel Alert.
"""
import requests
from config import BREVO_API_KEY, FROM_EMAIL, FROM_NAME

BREVO_SMTP_API = "https://api.brevo.com/v3/smtp/email"


def send_alert_email(user_email: str, first_name: str, alert_name: str, tournaments: list[dict]):
    """Envoie un email listant les nouveaux tournois détectés pour une alerte."""
    count      = len(tournaments)
    subject    = f"🎾 {count} nouveau{'x' if count > 1 else ''} tournoi{'s' if count > 1 else ''} {'correspondent' if count > 1 else 'correspond'} à votre alerte"
    html_body  = _build_html(first_name, alert_name, tournaments)

    payload = {
        "sender":      {"name": FROM_NAME, "email": FROM_EMAIL},
        "to":          [{"email": user_email, "name": first_name}],
        "subject":     subject,
        "htmlContent": html_body,
    }

    resp = requests.post(
        BREVO_SMTP_API,
        json=payload,
        headers={
            "api-key":      BREVO_API_KEY,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _build_html(first_name: str, alert_name: str, tournaments: list[dict]) -> str:
    cards = "".join(_tournament_card(t) for t in tournaments)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nouveaux tournois détectés</title>
</head>
<body style="margin:0;padding:0;background:#090D18;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#090D18;padding:32px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- EN-TÊTE -->
      <tr>
        <td style="background:#0C1428;border:1px solid #2A3D5E;border-radius:12px 12px 0 0;padding:24px 32px;border-bottom:none;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <span style="font-family:Impact,'Arial Narrow',Arial,sans-serif;font-size:22px;letter-spacing:4px;color:#FFFFFF;">PADEL</span>
                <span style="font-family:Impact,'Arial Narrow',Arial,sans-serif;font-size:22px;letter-spacing:4px;color:#FFD600;"> ALERT</span>
              </td>
              <td align="right">
                <span style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#6A84A8;">Alerte : {alert_name or 'Ma zone'}</span>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- INTRO -->
      <tr>
        <td style="background:#0C1428;border-left:1px solid #2A3D5E;border-right:1px solid #2A3D5E;padding:28px 32px 8px;">
          <p style="margin:0 0 8px;font-size:15px;color:#C8D6E8;line-height:1.6;">
            Bonjour <strong style="color:#FFFFFF;">{first_name}</strong>,
          </p>
          <p style="margin:0 0 24px;font-size:14px;color:#C8D6E8;line-height:1.6;">
            Nous avons détecté <strong style="color:#FFD600;">{len(tournaments)} nouveau{'x' if len(tournaments) > 1 else ''} tournoi{'s' if len(tournaments) > 1 else ''}</strong>
            correspondant à vos critères. Inscrivez-vous avant qu'ils soient complets !
          </p>
        </td>
      </tr>

      <!-- TOURNOIS -->
      <tr>
        <td style="background:#0C1428;border-left:1px solid #2A3D5E;border-right:1px solid #2A3D5E;padding:0 32px 24px;">
          {cards}
        </td>
      </tr>

      <!-- FOOTER -->
      <tr>
        <td style="background:#090D18;border:1px solid #2A3D5E;border-top:none;border-radius:0 0 12px 12px;padding:20px 32px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="font-size:11px;color:#6A84A8;">
                Envoyé par <strong style="color:#C8D6E8;">Padel Alert</strong> · padel-alert.fr
              </td>
              <td align="right" style="font-size:11px;">
                <a href="https://padel-alert.fr/mon-compte" style="color:#4FC3F7;text-decoration:none;">Gérer mes alertes</a>
                &nbsp;·&nbsp;
                <a href="https://padel-alert.fr/mon-compte?action=unsubscribe" style="color:#6A84A8;text-decoration:none;">Se désabonner</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def _tournament_card(t: dict) -> str:
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
      <tr>
        <td style="background:#111E3A;border:1px solid #2A3D5E;border-left:3px solid #FFD600;border-radius:8px;padding:14px 16px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="vertical-align:top;">
                <p style="margin:0 0 6px;font-size:14px;font-weight:bold;color:#FFFFFF;">{t['nom']}
                  <span style="font-size:11px;font-weight:normal;color:#6A84A8;"> — {t['categories']}</span>
                </p>
                <p style="margin:0 0 3px;font-size:12px;color:#6A84A8;">
                  <span style="color:#4FC3F7;">📅</span> {t['date']}
                </p>
                <p style="margin:0 0 3px;font-size:12px;color:#6A84A8;">
                  <span style="color:#4FC3F7;">🏟</span> {t['club']}
                </p>
                <p style="margin:0;font-size:12px;color:#6A84A8;">
                  <span style="color:#4FC3F7;">📍</span> {t['adresse']}{' · ' + t['distance'] if t.get('distance') else ''}
                </p>
              </td>
              <td style="vertical-align:middle;padding-left:16px;white-space:nowrap;">
                <a href="{t['link']}"
                   style="display:inline-block;font-size:11px;font-weight:bold;padding:8px 14px;
                          background:rgba(255,214,0,0.1);border:1px solid rgba(255,214,0,0.3);
                          color:#FFD600;border-radius:6px;text-decoration:none;">
                  S'inscrire →
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>"""
