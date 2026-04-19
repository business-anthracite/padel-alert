import os

# Base de données PostgreSQL (Railway fournit cette variable automatiquement)
DATABASE_URL = os.environ["DATABASE_URL"]

# Brevo — API transactionnelle
BREVO_API_KEY = os.environ["BREVO_API_KEY"]
FROM_EMAIL    = os.environ.get("FROM_EMAIL", "alertes@padel-alert.fr")
FROM_NAME     = os.environ.get("FROM_NAME", "Padel Alert")

# Intervalle de vérification en minutes
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "60"))

# Horizon de recherche des tournois (jours dans le futur)
SEARCH_DATE_HORIZON_DAYS = int(os.environ.get("SEARCH_DATE_HORIZON_DAYS", "365"))
