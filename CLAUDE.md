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
- **Noms de réalisateurs normalisés** (`_canonical_directors()` dans `sources.py`, appelé AVANT
  `_dedup_movies`) : chaque source a sa graphie (« David Lynch » vs « LYNCH David »). Deux notions
  distinctes, ne pas les confondre : `_fold_person()` = clé de COMPARAISON (casse, accents,
  ponctuation **et ordre des mots** neutralisés — contrairement à `_fold_title()` où l'ordre compte) ;
  `_tidy_person()` = graphie AFFICHÉE (« ANNAUD Jean-Jacques » → « Jean-Jacques Annaud », « Daniel
  ROHER » → « Daniel Roher », listes séparées par virgules traitées nom par nom). Sans cette passe,
  repertoire.py voyait deux réalisateurs et **coupait les cycles en deux** (Tati perdait « Mon oncle »,
  Lynch « Eraserhead »). Résultat : 125 → 2 fiches au nom en capitales, 933 → 931 films (doublons
  rattrapés). Les 2 restantes (« Abrams J.J. ») suivent un motif « nom puis initiales » qu'on ne
  devine volontairement pas — trop peu de cas pour justifier une heuristique de plus.
- **`_dedup_movies()` (sources.py) rattrape les doublons que la clé laisse passer** (~140 fiches) :
  passe 1 = même titre normalisé (accents/ponctuation/casse, « Part. »→« Partie ») + réalisateurs
  compatibles (un nom commun, ou vide/« Collectif ») ; passe 2 = même réalisateur, titre court ⊂ titre
  long quand le surplus n'est que « partie »+chiffres+mots-outils (≥ 4 tokens : jamais « Avatar »/« Avatar 2 »).
  Les homonymes de réalisateurs différents (Macbeth Welles vs Proske) restent séparés — ne pas « simplifier »
  ces garde-fous.
- **Matching TMDB validé par réalisateur** (`enrich_tmdb.py`) : la recherche TMDB trie par popularité,
  jamais prendre `results[0]` sans vérifier les credits. `TITLE_OVERRIDES` corrige les fiches TMDB
  au titre fr erroné. Sans candidat validé → fiche brute (mieux que des données d'un autre film).
- **POSITIONNEMENT : le site est un agenda du RÉPERTOIRE.** L'accueil ne montre plus les sorties
  récentes mais les films anciens qui repassent. `scripts/repertoire.py` porte toute la détection :
  reprise = `year < REPERTOIRE_BEFORE` (2020) ; séance unique = le film ne passe qu'une fois en
  France sur 7 jours (6 films sur 10 !) ; cycle = ≥ 2 films d'un même réalisateur dans une même
  salle, agrégés ensuite au national. **Le seuil 2020 n'est pas arbitraire** : à 20 ans d'âge,
  84 villes sur 257 seulement étaient couvertes ; avant 2020, 154 villes le sont. Ne pas le
  remonter sans re-mesurer la couverture.
- **Pages de rétrospective** : `/retrospectives/` (index) et `/retrospectives/<réalisateur>/` (une par
  cycle), générées depuis `repertoire.cycles(..., limit=None)`. Le programme y est présenté
  **salle par salle** (un cycle est ancré dans une salle), avec horaires. Ces URLs sont
  **volatiles par nature** : un cycle qui s'achève fait disparaître sa page — c'est le même modèle
  que les fiches film, et la 404 de marque l'explique au visiteur. Ne pas chercher à les figer.
- **Salles de patrimoine** (`/salles-patrimoine/`) : classement par **PART** de répertoire dans la
  programmation, jamais par volume — sinon les multiplexes écrasent les salles qui ne font que ça.
  Plancher `VENUE_MIN_SHOWS` séances pour qu'un pourcentage ait un sens.
- **Une couleur = un sens** (`assets/style.css`) : ambre `--accent` = accent du site (lumière du
  projecteur) ; rouge `--indie` = signature « cinéma indépendant » et RIEN d'autre ; vert `--lb` =
  note Letterboxd et rien d'autre. Ne pas réintroduire le rouge comme couleur de chrome.
- **Classiques & rétrospectives** : page `/classiques/` = LE CLASSEMENT par note Letterboxd,
  badge doré, détection `year ≤ N−20` (`CLASSIC_AGE_YEARS`) — plus strict que le répertoire, c'est
  volontaire (la distinction premium). Dépend de l'année TMDB, donc des films enrichis.
- **`/a-l-affiche/`** : l'ancien accueil, devenu un onglet. Il garde l'intention à plus gros volume
  (« quel film voir ce soir ») ; l'accueil et lui se renvoient l'un à l'autre (`.passerelle`) pour
  qu'aucune des deux pages ne soit orpheline.
- **Fiche film : une seule ville affichée à la fois.** Les 234 sections ville sont toutes dans le
  HTML (indexables) mais masquées en CSS ; la recherche ou une pastille en révèle une
  (`showCity()` dans `film.js`). Le masquage est conditionné à la classe `js` posée dans le `<head>`
  (`JS_FLAG`) : **sans JavaScript tout doit rester visible**, sinon la page serait vide pour un
  visiteur sans JS et pour un robot qui n'exécute pas les scripts. Ne pas remettre de `<details>`.
- **Idées de marathon** : page `/marathon/`, module `scripts/marathon.py`. Deux films partageant un
  genre, enchaînables le même jour dans **deux salles distinctes** distantes de moins de `MAX_KM`.
  L'entracte doit couvrir le trajet à pied (`WALK_MIN_PER_KM`) plus `MARGIN_MIN`, sans dépasser
  `SLACK_MAX_MIN` d'attente. Tri : reprises de classiques d'abord, puis note Letterboxd. Les idées
  sont dédoublonnées par paire de films et diversifiées par genre. Un cinéma **sans coordonnées est
  ignoré** (impossible de juger la proximité), un film **sans durée ou sans genre** aussi.
- **Aucune page ne montre de séance passée** : `build_site.py` filtre `showtimes` sur `>= today`
  dès le chargement. Indispensable car les snapshots de chaînes ont souvent un jour de retard.
- Piloter l'API GitHub (pas de `gh` CLI installé) : token via `git credential fill` (compte Keenzzz).
- Chaînes NON intégrées (plateformes de billetterie verrouillées auth/CORS/bot) : Mégarama
  (ticketingcine/IMS), MK2, Kinepolis, Cineville. Piste propre à terme = agrégateur payant.
