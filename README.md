# 🎾 Padel Alert

Système d'alertes automatiques par email pour les nouveaux tournois de padel publiés sur Ten'Up (FFT).

## Fonctionnement

Toutes les heures, GitHub Actions :
1. Charge la page Ten'Up et récupère le token de session
2. Lance une recherche de tournois avec les critères configurés
3. Compare les résultats avec les tournois déjà connus
4. Envoie un email si de nouveaux tournois sont détectés
5. Sauvegarde la liste mise à jour

## Critères de recherche actuels

- **Sport** : Padel
- **Zone** : Angers, rayon 80 km
- **Période** : 11/04/2026 → 31/12/2026
- **Catégorie** : Messieurs Sénior
- **Type** : Tournoi P50 / P100

## Configuration

Les secrets suivants doivent être configurés dans GitHub Actions :

| Secret | Description |
|--------|-------------|
| `GMAIL_ADDRESS` | Adresse Gmail pour l'envoi |
| `GMAIL_APP_PASSWORD` | Mot de passe d'application Google |
