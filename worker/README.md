# Worker « watchlist par pseudo »

Micro-service Cloudflare qui lit la **watchlist publique** d'un membre Letterboxd
et la renvoie en JSON, pour que Séancéo croise cette liste avec les séances du
répertoire **sans demander au visiteur d'exporter un fichier**.

C'est l'alternative à l'API officielle Letterboxd (accès sur candidature, délai
de plusieurs mois, non garanti). Ici : rien à attendre, ça marche aujourd'hui.

## Ce qu'il fait / ne fait pas

- ✅ Lit une watchlist **publique** par pseudo, renvoie `[{ slug, name, year }]`.
- ✅ Contourne le blocage CORS (le navigateur ne peut pas appeler Letterboxd
  directement ; un serveur, si).
- ✅ Cache 12 h par pseudo → poli envers Letterboxd, instantané au retour.
- ❌ **Aucune écriture** (ajouter à sa watchlist = API officielle uniquement).
- ❌ Ne lit pas les watchlists **privées** (impossible sans compte) → l'UI
  retombe alors sur l'import CSV existant.

## API

```
GET /watchlist/<pseudo>
```

Réponses :

```jsonc
// Succès
{
  "ok": true,
  "user": "dave",
  "count": 601,
  "total": 601,
  "truncated": false,        // true si la watchlist dépasse le plafond (40 pages)
  "favorites": [             // les 4 films préférés du profil (peut être vide)
    { "slug": "high-and-low", "name": "High and Low", "year": "1963" }
  ],
  "generatedAt": "2026-07-23T02:15:00.000Z",
  "films": [
    { "slug": "tuner", "name": "Tuner", "year": "2025" },
    { "slug": "the-entertainment-system-is-down", "name": "The Entertainment System Is Down", "year": null }
  ]
}

// Watchlist vide ou privée (les favoris restent souvent lisibles)
{ "ok": true, "user": "x", "count": 0, "total": 0, "empty": true, "private": true, "favorites": [ ... ], "films": [] }

// Pseudo introuvable         -> 404  { "error": "not_found" }
// Pseudo mal formé           -> 400  { "error": "invalid_username" }
// Letterboxd en erreur       -> 502  { "error": "upstream_error" }
```

**Favoris** : lus sur la page de profil (`letterboxd.com/<user>/`, section `#favourites`,
mêmes posters `LazyPoster` que la watchlist), récupérés en parallèle de la page 1.
Le site les croise avec l'index et met en avant ceux qui repassent (« à revoir »).

**`private`** : détection best-effort par marqueur texte (à affiner avec un vrai
compte privé). Sans marqueur, une liste sans film est traitée comme simplement vide.

En-tête `X-Seanceo-Cache: HIT | MISS | BYPASS` pour savoir si la réponse vient
du cache. `?fresh=1` force un rafraîchissement (debug).

## Le lien avec le croisement existant

Le champ **`slug`** est directement la clé de matching du site : `lb_slug_key()`
en Python (et sa réplique dans `assets/watchlist.js`) applique la même empreinte
`NFKD → non-ASCII retiré → [a-z0-9]` au slug Letterboxd. Le front n'a donc qu'à
faire `empreinte(slug)` et chercher dans `watchlist-index.json` — même moteur
que l'import CSV, en plus fiable (on tient le slug canonique, pas un titre à
re-déduire). `name`/`year` restent là comme filet (`empreinte(name)+year`).

## Déploiement

Prérequis : un compte Cloudflare (gratuit) et Node installé.

```bash
cd worker
npx wrangler login      # une fois, ouvre le navigateur
npx wrangler deploy     # publie -> https://seanceo-watchlist.<sous-domaine>.workers.dev
```

Développement local :

```bash
cd worker
npx wrangler dev        # http://localhost:8787/watchlist/dave
```

Rien à configurer d'autre : pas de secret, pas de variable d'environnement.

## À câbler côté site (étape suivante, pas encore faite)

1. Renseigner l'URL du Worker déployé dans le front (constante `WORKER_URL`).
2. Sur `/ma-watchlist/`, ajouter un champ « pseudo Letterboxd » à côté de
   l'import CSV ; appeler `GET <WORKER_URL>/watchlist/<pseudo>`, puis réutiliser
   l'affichage de résultats actuel.
3. Ajouter l'origine de prod dans `ORIGINS_OK` (déjà fait pour
   `keenzzz.github.io` et `seanceo.fr`).

## Point d'attention

Lecture de pages publiques sans API = **zone grise CGU**, même posture que
`scripts/fetch_letterboxd.py`. Neutralisée par : UA transparent, cache agressif,
plafond de pages, faible concurrence. Si Letterboxd durcit un jour le filtrage
des IP datacenter (celles de Cloudflare), prévoir le repli sur l'import CSV.
