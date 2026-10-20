# Radar Emploi

Application Android : collez votre profil, choisissez vos pays, et les offres d'emploi sont classées par score de compatibilité.

- Mes offres : l'appli affiche la liste `data/offres.json` (offres évaluées, mise à jour chaque matin) et notifie les nouvelles.
- Maroc : un onglet dédié affiche `data/maroc.json`, le scan du marché marocain classé par métier.
- Scan automatique : chaque matin, GitHub Actions lance `scripts/scan_maroc.py`, qui lit les pages publiques de ReKrute, Exekutive et Michael Page Africa (dans le respect de leur robots.txt), ajoute les nouvelles offres avec une estimation automatique, retire les offres closes et met à jour `data/maroc.json` et `data/offres.json`. Les offres évaluées à la main gardent leur estimation.
- Sans aucune clé : indiquez un poste et vos pays, l'appli ouvre la recherche sur LinkedIn, Indeed, Google, Bayt, ReKrute, Emploi.ma, Apec et Welcome to the Jungle.
- Mode avancé (facultatif, clé JSearch) : offres affichées dans l'appli avec un score et une alerte quotidienne ; scores IA avec une clé Claude API.
- Aucune clé ni donnée personnelle dans ce dépôt : tout reste sur le téléphone.

L'APK est compilé par GitHub Actions à chaque envoi sur `main` : onglet **Releases** → **Radar Emploi · dernière version** → `RadarEmploi.apk`.
