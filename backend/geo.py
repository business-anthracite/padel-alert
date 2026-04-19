"""
Géocodage des villes françaises via l'API gouvernementale (sans clé API).
Utilisé lors de la création d'une alerte pour construire le label Ten'Up.
"""
import requests


GEO_API = "https://geo.api.gouv.fr/communes"


def lookup_city(city_name: str, limit: int = 5) -> list[dict]:
    """
    Recherche une ville française et retourne les correspondances.
    Chaque résultat contient les champs nécessaires pour construire
    la requête Ten'Up.
    """
    resp = requests.get(GEO_API, params={
        "nom": city_name,
        "boost": "population",
        "fields": "nom,codesPostaux,codeDepartement,nomDepartement,codeRegion,nomRegion,centre",
        "limit": limit,
    }, timeout=10)
    resp.raise_for_status()

    results = []
    for c in resp.json():
        cp = c.get("codesPostaux", [""])[0]
        lat = c.get("centre", {}).get("coordinates", [None, None])[1]
        lng = c.get("centre", {}).get("coordinates", [None, None])[0]
        results.append({
            "display":          f"{c['nom']} ({cp})",
            "location_value":   f"{c['nom']}, {cp}",
            "location_label":   f"{c['nom']}, {c['codeDepartement']}, {c['nomDepartement']}, {c['nomRegion']}",
            "lat":              lat,
            "lng":              lng,
        })
    return results


def city_to_tenup_params(alert: dict) -> dict:
    """
    Convertit les champs de localisation d'une alerte en paramètres
    pour la requête AJAX Ten'Up.
    """
    return {
        "recherche_type": alert["location_type"],
        "ville[autocomplete][country]": "fr",
        "ville[autocomplete][textfield]": "",
        "ville[autocomplete][value_container][value_field]": alert["location_value"],
        "ville[autocomplete][value_container][label_field]": alert["location_label"],
        "ville[autocomplete][value_container][lat_field]":   str(alert["lat"]),
        "ville[autocomplete][value_container][lng_field]":   str(alert["lng"]),
        "ville[distance][value_field]": str(alert["radius_km"]),
        "club[autocomplete][textfield]": "",
        "club[autocomplete][value_container][value_field]": "",
        "club[autocomplete][value_container][label_field]": "",
        "pratique": "PADEL",
    }
