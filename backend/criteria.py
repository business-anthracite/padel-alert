"""
Codes Ten'Up pour les critères de recherche de tournois.
À mettre à jour si la FFT modifie ses catégories (cf. §4 CDC).
"""

# Type d'épreuve
MATCH_TYPES = {
    "DM": "Messieurs",
    "DD": "Dames",
    "DX": "Mixte",
}

# Catégorie d'âge — codes extraits du formulaire Ten'Up
AGE_CATEGORIES = {
    "910":  "9/10 ans",
    "1112": "11/12 ans",
    "1314": "13/14 ans",
    "1516": "15/16 ans",
    "1718": "17/18 ans",
    "200":  "Senior",
    "345":  "+45 ans",
    "355":  "+55 ans",
}

# Type de compétition
COMPETITION_TYPES = {
    "P":   "Tournoi",
    "CE":  "Championnat par paires",
    "CEQ": "Championnat par équipes",
}

# Catégorie d'épreuve (niveau)
TOURNAMENT_CATEGORIES = {
    "P25":   "P25",
    "P50":   "P50",
    "P100":  "P100",
    "P250":  "P250",
    "P500":  "P500",
    "P1000": "P1000",
    "P1500": "P1500",
    "P2000": "P2000",
}

# Limites d'alertes par plan
PLAN_ALERT_LIMITS = {
    "essential": 2,
    "pro": None,  # illimité
}

# Tarifs en centimes (pour PayPlug)
PLAN_PRICES = {
    "essential_monthly": 399,
    "essential_annual":  3499,
    "pro_monthly":       599,
    "pro_annual":        4999,
}

# Réduction parrainage en centimes
REFERRAL_CREDIT_MONTHLY = 399   # 1 mois offert = 3,99€
REFERRAL_CREDIT_ANNUAL  = 399   # Déduit sur renouvellement annuel


def build_tenup_criteria(alert: dict) -> dict:
    """
    Convertit les critères d'une alerte (depuis la DB) en paramètres
    pour la requête POST Ten'Up.
    """
    params = {}

    for code in alert.get("match_types", ["DM"]):
        if code in MATCH_TYPES:
            params[f"epreuve[{code}]"] = code

    for code in alert.get("age_categories", ["200"]):
        if code in AGE_CATEGORIES:
            params[f"categorie_age[{code}]"] = code

    for code in alert.get("competition_types", ["P"]):
        if code in COMPETITION_TYPES:
            params[f"type[{code}]"] = code

    for code in alert.get("tournament_categories", ["P50", "P100"]):
        if code in TOURNAMENT_CATEGORIES:
            params[f"categorie_tournoi[{code}]"] = code

    return params
