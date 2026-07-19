# Séancéo

Site national des séances de cinéma en France : cinémas indépendants (open data SCARE)
et grandes enseignes (connecteur Pathé), avec mise en avant des salles Art & Essai.
En ligne : https://keenzzz.github.io/seanceo/ (domaine seanceo.fr à venir).
Extension du projet [Paris Ciné Aujourd'hui](https://github.com/Keenzzz/paris-cine-aujourdhui) à l'échelle nationale.

## Source de données

[API open data du SCARE](https://www.data.gouv.fr/dataservices/programmation-des-cinemas-independants)
(Syndicat des Cinémas d'Art, de Répertoire et d'Essai) — programmation d'environ
150 cinémas indépendants, alimentée quotidiennement par leurs logiciels de caisse.

- Endpoint : `https://datacinesindes.fr/data-fair/api/v1/datasets/programmation-cinemas/lines`
  (⚠ utiliser ce domaine ; `data-cines-indes.koumoul.com` a une chaîne de certificats incomplète)
- Licence : [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence) — réutilisation
  commerciale autorisée avec attribution. **Créditer le SCARE / Data Ciné Indés sur le site.**

## Pipeline de données

```
python scripts/fetch_data.py
```

Aucune dépendance (stdlib Python ≥ 3.10). Le script :

1. télécharge toutes les séances à venir (pagination par curseur data-fair) ;
2. répare le texte doublement encodé de certaines caisses (mojibake cp1252/UTF-8) ;
3. dédoublonne les films par (titre, réalisateur) — `filmid` n'est **pas** global,
   chaque logiciel de caisse a sa propre numérotation ;
4. normalise les villes (fusion des arrondissements, slugs pour les URLs) ;
5. écrit dans `data/` (gitignoré, régénérable) :
   - `cinemas.json` — cinémas avec adresse et coordonnées GPS
   - `movies.json` — fiches films (synopsis, affiche, bande-annonce…)
   - `showtimes.json` — séances triées par horaire
   - `cities.json` — index des villes, triées par volume de séances
   - `meta.json` — horodatage de génération

## Étapes suivantes (prévu)

- Générateur de pages statiques (une page par ville / cinéma / film) pour le SEO
- Réutilisation de la carte Leaflet et du CSS responsive de Paris Ciné
- Déploiement Cloudflare Pages + régénération quotidienne (GitHub Actions cron)
