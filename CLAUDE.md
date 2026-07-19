# Séancéo

Site national des séances de cinéma en France : **cinémas indépendants + grandes enseignes**,
avec mise en avant des salles Art & Essai. Objectif : trafic monétisable via SEO programmatique
(une page par ville / cinéma / film). Extension nationale du projet Paris Ciné Aujourd'hui.

- **En ligne** : https://keenzzz.github.io/seanceo/ (GitHub Pages, repo `Keenzzz/seanceo`).
- **Dossier local** : `C:\Users\knz92\Projects\cine-indes` (non renommé, sans importance).
- **Domaine** `seanceo.fr` prévu mais pas encore acheté (nom vérifié 100 % libre + sans marque déposée).

## Structure

- `scripts/` — pipeline Python **pur stdlib, aucune dépendance** :
  - `fetch_data.py` — indés via l'API open data du SCARE → `data/{cinemas,movies,showtimes,cities}.json`
  - `fetch_pathe.py` — chaîne Pathé (API pathe.fr) → `data/pathe_*.json`
  - `fetch_webedia.py --chain {cgr,grandecran}` — chaînes sur plateforme Webedia boxofficeapi → `data/<chain>_*.json`
  - `fetch_ugc.py` — chaîne UGC via l'API mobile `backend.ugc.fr` → `data/ugc_*.json`
  - `enrich_tmdb.py` — enrichissement TMDB (titres/notes/affiches/durées) → cache `data/tmdb.json`
  - `sources.py` — **fusionne** toutes les sources + applique TMDB (`load_merged()`)
  - `build_site.py` — génère `site/` (accueil, villes, cinémas, films, carte, sitemap, robots)
- `assets/` — CSS, `map.js`, Leaflet + markercluster **vendorisés** (pas de CDN)
- `data/` — gitignoré SAUF les snapshots de chaînes et `tmdb.json` (voir plus bas)
- `.github/workflows/deploy.yml` — build + deploy, push + cron quotidien 03:30 UTC

## Sources de données

| Source | Licence / accès | Rafraîchissement |
|---|---|---|
| **Indés** (SCARE, `datacinesindes.fr`) | Open data, Licence Ouverte 2.0 (attribution obligatoire) | Auto en CI (chaque jour) |
| **UGC** (`backend.ugc.fr`, API mobile) | API interne ouverte | **Auto en CI** (non bloquée) |
| **Pathé / CGR / Grand Écran** | APIs internes | **Snapshot local** (voir ci-dessous) |

**Attribution obligatoire, ne jamais retirer du footer** : « Data Ciné Indés / SCARE » (Licence Ouverte 2.0)
et la mention TMDB (« ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB »).

## Contraintes à respecter (ne jamais violer)

### Snapshots de chaînes versionnés
- **Pathé, CGR, Grand Écran bloquent les IP datacenter du CI (403).** Leurs séances sont donc
  collectées **en local** et **versionnées** dans `data/<chain>_*.json` (dé-gitignorés). Le CI retente
  ces fetch en `continue-on-error` : un garde-fou (`if not cinemas: return`) évite d'écraser le snapshot.
- **Rafraîchir Pathé/CGR/Grand Écran** = relancer en local `--days 7` **sans limite** puis commit.
- **PIÈGE : `--theaters N` / `--cinemas N` (options de test) ÉCRASENT le snapshot complet.** Après un
  test, TOUJOURS re-collecter en entier (`--days 7` sans `--theaters/--cinemas`) avant de committer.
- UGC s'auto-rafraîchit en CI (son API n'est pas bloquée) — pas besoin de le refaire en local.

### Clé TMDB — SECRET, jamais dans le dépôt
- La clé se lit dans la variable d'env `TMDB_API_KEY`, **jamais écrite dans le code ni un fichier commité**.
- L'enrichissement tourne **en local** ; seul le **cache** `data/tmdb.json` (données publiques de films,
  aucun secret) est versionné. Le CI applique le cache sans avoir besoin de la clé.
- Notes affichées seulement si `votes >= 30` (une note sur 1-2 votes = 10/10 trompeur).

### Sécurité / rendu
- **Tout contenu externe passe par `html.escape()`** (titres, noms de cinémas…) — jamais d'injection HTML.
- Les popups de la carte échappent le texte côté JS (`map.js`, fonction `esc`).

### URL / déploiement
- `BASE_PATH = "/seanceo"` dans `build_site.py` (site servi sous sous-chemin GitHub Pages).
  **Le jour où `seanceo.fr` est branché** : `BASE_PATH = ""`, `BASE_URL = "https://seanceo.fr"`,
  ajouter `static/CNAME` contenant `seanceo.fr`, config DNS, puis re-valider la Search Console.
- Fichier de validation Search Console dans `static/` — **ne jamais le supprimer** (perte de propriété).

## Points de repère

- Distinction indé / chaîne : champ `chain` sur chaque cinéma. `chain_badge()` dans `build_site.py`
  (point rouge « Indé » = signature ; badge gris + nom = chaîne).
- Ajouter une chaîne Webedia = une entrée dans `SITES` de `fetch_webedia.py` (domaine + regex des
  pages `/theaters/` ou `/nos-cinemas/`). Ajouter une chaîne quelconque à la fusion = un préfixe dans
  `CHAIN_PREFIXES` de `sources.py`.
- Dédup des films entre sources = clé `movie_key(titre, réalisateur)` (slugifiée) — `filmid` n'est PAS
  global. TMDB (et le titre le plus « riche ») nettoient les titres en CAPITALES au moment de la fusion.
- **`_dedup_movies()` (sources.py) rattrape les doublons que la clé laisse passer** (~140 fiches) :
  passe 1 = même titre normalisé (accents/ponctuation/casse, « Part. »→« Partie ») + réalisateurs
  compatibles (un nom commun, ou vide/« Collectif ») ; passe 2 = même réalisateur, titre court ⊂ titre
  long quand le surplus n'est que « partie »+chiffres+mots-outils (≥ 4 tokens : jamais « Avatar »/« Avatar 2 »).
  Les homonymes de réalisateurs différents (Macbeth Welles vs Proske) restent séparés — ne pas « simplifier »
  ces garde-fous.
- **Matching TMDB validé par réalisateur** (`enrich_tmdb.py`) : la recherche TMDB trie par popularité,
  jamais prendre `results[0]` sans vérifier les credits. `TITLE_OVERRIDES` corrige les fiches TMDB
  au titre fr erroné. Sans candidat validé → fiche brute (mieux que des données d'un autre film).
- **Classiques & rétrospectives** : page `/classiques/` + badge doré, détection `year ≤ N−20`
  (`CLASSIC_AGE_YEARS` dans `build_site.py`) — dépend de l'année TMDB, donc des films enrichis.
- Piloter l'API GitHub (pas de `gh` CLI installé) : token via `git credential fill` (compte Keenzzz).
- Chaînes NON intégrées (plateformes de billetterie verrouillées auth/CORS/bot) : Mégarama
  (ticketingcine/IMS), MK2, Kinepolis, Cineville. Piste propre à terme = agrégateur payant.
