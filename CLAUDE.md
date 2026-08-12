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

## Site bilingue (français / anglais)

Le build tourne **deux fois**, une passe par langue (`i18n.LANGS`) : le français
à la racine, l'anglais sous `/en/`. Chaque page anglaise a donc sa propre URL
indexable, et les deux se déclarent l'une l'autre en `hreflang` (`alternates()`).

- **La clé de traduction EST la phrase française** (`scripts/i18n.py`,
  `assets/i18n.js`). Deux conséquences voulues : en français `t()` est
  l'identité, donc **zéro risque de régression sur la version déjà indexée** ;
  et une traduction oubliée affiche du français correct, jamais une clé brute.
  Contrepartie : corriger une faute de frappe dans le texte français casse le
  lien avec sa traduction. La fin de build liste les manques dans
  `i18n-manquantes.txt` ; `python scripts/i18n.py` audite le dictionnaire.
- **Les slugs restent français dans les deux langues** (`/en/film/mon-oncle/`) :
  calculés une seule fois, avant la boucle, depuis les titres français. Deux
  jeux de slugs auraient fait diverger les arbres à chaque changement de titre
  TMDB. Corollaire précieux : la contrepartie d'une page est toujours son
  chemin préfixé, donc le sélecteur de langue ne peut pas pointer dans le vide.
- **Ce qui change de RÈGLE et pas seulement de mots** (tout est dans i18n.py) :
  le « s » du pluriel (`plural()` — le français met 0 au singulier, l'anglais
  au pluriel), le séparateur de milliers (`nombre()`), le format d'heure
  (`heure()` : « 20h30 » vs « 8:30 pm »), le séparateur décimal (`decimal()`).
  En français `{s}` et l'accord du verbe voyagent en variable (`{verbe}`) :
  « est / sont », « passe / passent » n'ont qu'une forme en anglais.
- **`localize_movies()`** promeut les champs `*_en` du cache TMDB (titre,
  synopsis, genres, pays, **affiche**) au moment de la passe anglaise. Toute la
  génération lit ensuite `m["title"]` sans savoir dans quelle langue elle est.
  L'enrichissement anglais est une 2ᵉ passe de `enrich_tmdb.py` (une requête
  `language=en-US` par film déjà matché, `--refresh-en` pour la refaire seule).
- **Assets partagés vs par langue** : `SHARED_PATHS` liste ce qui n'est jamais
  préfixé par `/en` (CSS, JS, icônes, `film-directors.json`,
  `cinematheque-directors.json`). Les index qui portent des titres ou des URLs
  (`recherche`, `watchlist-index`, `agenda-index`) et le **manifeste** existent
  en deux exemplaires. **PIÈGE VÉCU** : `film-directors.json` est partagé mais
  écrit dans la boucle — la passe anglaise l'écrasait avec les seules
  empreintes anglaises (963 clés françaises perdues sur 2 084). Il est
  désormais réservé à la passe française, qui voit les deux titres.
- **Sélecteur de langue** (`lang_switch()`) : ses href sont marqués `RAW` pour
  échapper au préfixage automatique de `_prefix_links()` — ce sont les seuls
  liens du site qui visent volontairement l'autre arbre.
- **Mémoire du choix** (`nav.js`) : elle ne va que **dans un sens**. Page
  française + préférence « anglais » → redirection ; page anglaise + préférence
  « français » → **rien**, car être sur `/en/` c'est déjà l'avoir demandé par
  l'URL (typiquement un résultat Google). Cliquer « FR » **efface** la
  préférence au lieu de stocker « fr ». Ce n'est PAS une redirection selon la
  langue du navigateur : `localStorage` est vide au premier chargement et
  **toujours** vide pour un robot, donc Googlebot ne voit jamais de redirection.
- **404** : GitHub Pages ne sert que le `/404.html` de la racine, quelle que
  soit l'adresse manquante — un `/en/404.html` ne serait jamais affiché. La 404
  est donc en français, avec une ligne anglaise et un lien vers `/en/`.
- **Notifications** : un service worker n'a accès ni au DOM ni à `window`. La
  langue lui arrive dans l'URL d'enregistrement (`/sw.js?lang=en`), qu'il relit
  dans `self.location`.

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
  ces garde-fous. **Passe 3 = même `tmdb_id`** : le signal le plus sûr des trois. Elle existe
  parce que `_dedup_movies()` tourne **avant** `_apply_tmdb()` : une caisse écrit « Les Vacances
  de Mr Hulot », une autre « … de monsieur Hulot », les deux titres ne se replient pas pareil
  (passe 1 aveugle), puis TMDB leur donne le même titre propre et le doublon n'apparaissait
  qu'à l'écran. On ne fusionne que sur les fiches `found` (validées par réalisateur) : un match
  TMDB non validé peut désigner un autre film. Gain : 11 doublons, 931 → 918 films.
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
- **Recherche de film** (`assets/search.js`, champ dans le header de toutes les pages) : cherche
  par titre **ou par réalisateur**. L'index des ~918 films est un fichier à part,
  `site/recherche.json` (~77 ko, lignes `[titre, réalisateur, url, année]`), **téléchargé à la
  première interaction seulement** — l'injecter dans chaque page coûterait ce poids à tous les
  visiteurs pour une fonction optionnelle. Le chemin de l'index est passé en `data-index`, avec
  `BASE_PATH` écrit à la main : `page()` ne préfixe que les attributs `href`/`src`.
  **Classement des résultats en 4 paquets** (titre qui commence par la requête, titre au début
  d'un mot, réalisateur, titre au milieu d'un mot). Le dernier paquet n'est pas cosmétique :
  sans lui, « tati » remontait « Il était une fois la **stati**on balnéaire… » et
  « L'invi**tati**on » AVANT les films de Jacques Tati.
- **Tri et filtre des listes de films** (`assets/tri.js`, barre `film_tools()`) : sur
  `/classiques/` (défaut = note Letterboxd) et `/a-l-affiche/` (défaut = nombre de cinémas).
  Tri par note, titre, année ou diffusion ; filtre de version **VO/VOST ou VF**. Les critères
  voyagent en `data-*` sur chaque carte (`card_attrs()`), donc une carte sait se classer quelle
  que soit la page. Trois points à ne pas casser : le tri JavaScript est **stable**, donc
  re-trier la liste sur son critère par défaut redonne exactement l'ordre calculé au build ; le
  rang « n° 3 » du classement est masqué (`.hors-classement`) dès qu'on trie sur un AUTRE
  critère, sinon il mentirait (le sens, lui, n'y change rien : à l'envers la liste déroule
  simplement les rangs du dernier au premier) ; et **VOST compte comme de la VO** (le spectateur
  qui filtre « VO » veut la langue d'origine, sous-titrée ou non).
- **Sens de tri réversible** : les tris sont des BOUTONS, pas un `<select>` — un second clic sur
  le tri actif inverse le sens (`data-dir`, marque « ↓ »/« A → Z » dans `.tri-sens`). Les
  comparateurs de `TRIS` sont tous écrits en ordre **croissant**, `appliquer()` inverse le signe :
  un seul comparateur par critère, donc les deux sens ne peuvent pas diverger. **Une fiche sans
  valeur pour le critère courant part toujours en queue, dans les deux sens** (`renseigne()`) —
  sinon « note croissante » ouvrait sur les 49 films SANS note au lieu des moins bien notés.
- **Pagination côté client** : `tri.js` n'affiche que `PAGE_SIZE` (40) cartes à la fois avec un
  bouton « Afficher plus ». Le HTML contient **toutes** les cartes (indexables) ; c'est le même
  contrat que les villes des fiches film — **sans JavaScript, tout doit rester visible**, d'où
  `.movie-card[hidden] { display: none }` posé par le script seul et `html:not(.js) .film-tools
  { display: none }` (une barre d'outils morte serait pire que pas de barre).
- **Liens de billetterie** (champ `booking` sur chaque séance) : un horaire dont la source donne
  un lien de réservation devient cliquable et mène **directement à la réservation de CETTE
  séance**, dans un nouvel onglet (`target="_blank" rel="noopener noreferrer"`, flèche ↗ pour
  annoncer la sortie du site). Rendu par `showtime_pills()`, `seance_row()` (agenda) et les
  jambes d'un marathon. Les pastilles réservables se distinguent des autres (`.reservable`) :
  toutes les rendre cliquables reproduirait l'affordance trompeuse qu'on avait corrigée.
  - **`booking_url()` (fetch_data.py) filtre le schéma — n'accepter que http(s).** Ces URLs
    viennent de sources externes et finissent dans un `href` : `html.escape()` empêche de sortir
    de l'attribut mais PAS d'y glisser un `javascript:`. **Toute nouvelle source doit passer par
    cette fonction**, sans exception.
  - Couverture : **indés 83 %** (champ `showurl` de l'open data SCARE, 42 salles sur 50 —
    les salles sans billetterie en ligne le laissent vide) ; **UGC 100 %** (`urlReservation` +
    `seance_id`, on repart du chemin donné par l'API plutôt que de l'écrire en dur) ;
    **Pathé** (`refCmd`, lien direct par séance) ; **CGR et Grand Écran 100 %**
    (`data.ticketing[]`, voir `webedia_booking()`). Garder le `.get("booking")` partout :
    une séance sans lien doit rester affichable.
  - **Webedia expose DEUX fournisseurs par séance** : `default` = le domaine d'achat de la
    chaîne (`achat.cgrcinemas.fr`), `relay` = un redirecteur tiers (`relay.mvtx.us`).
    `webedia_booking()` ne prend **que `default`** — faire transiter nos visiteurs par un
    traceur intermédiaire n'apporte rien. Sans `default`, on préfère ne pas lier.
- **⚠️ PIÈGE WEBEDIA : le `theaterId` doit être en MAJUSCULES.** Le code se lit en minuscules
  dans l'URL de la page (« /theaters/w8010-… ») mais l'API `schedule` exige « W8010 » ; en
  minuscules elle répond **HTTP 500 avec un corps `null`**, sans le moindre message. C'est ce
  qui avait cassé la collecte CGR/Grand Écran **silencieusement** : le connecteur est
  best-effort, l'échec passait pour un blocage d'IP et le garde-fou conservait un snapshot
  périmé. Diagnostic (2026-07-21) : `/movies` répondait 200 alors que `/schedule` renvoyait 500
  même **sans paramètre** — c'est en observant les appels réseau du site CGR qu'on a vu son
  propre frontend utiliser `W8010`. Après correctif : CGR 11 646 → **23 740 séances**,
  Grand Écran ~1 260 → **2 594**.
  - Corollaire à retenir : **un connecteur best-effort qui échoue ressemble à un connecteur
    bloqué**. Si un snapshot cesse de bouger, vérifier le corps de l'erreur avant de conclure
    au blocage d'IP.
  - `grand-ecran-arcachon-la-teste` n'est plus collecté (14 → 13 salles) : sa page n'expose
    plus de JSON-LD `MovieTheater`. Changement côté source, pas un bug du connecteur.
- **⚠️ HEURES : l'API du SCARE mélange les fuseaux.** Deux tiers des séances indés arrivent en UTC
  (« …T08:00:00Z »), le reste avec un décalage explicite. Or tout le site lit l'heure en découpant
  la chaîne (`start[11:16]`) : les séances en UTC s'affichaient **deux heures trop tôt** l'été.
  `heure_locale()` (fetch_data.py) ramène tout à l'heure locale française **sans suffixe de
  fuseau**, la forme que produisent déjà les connecteurs de chaînes. Diagnostic par la
  distribution horaire : les séances en UTC ne montraient que 17 séances à 20 h sur 8 000, alors
  que 20 h est le créneau le plus chargé ; recalées, les deux distributions se superposent.
  `decalage_paris()` code la règle européenne à la main **exprès** : `zoneinfo` n'a pas de base
  de fuseaux sur la machine Windows de développement alors que le CI (Ubuntu) en a une — le même
  code donnerait deux résultats. Ne pas « simplifier » en important zoneinfo.
- **UNE SEULE ÉCHELLE DE NOTE : Letterboxd, sur 5.** `note_lb()` est le seul endroit qui affiche
  une note. Les notes TMDB (/10) ont été retirées de l'affichage — deux échelles côte à côte
  faisaient lire « 7.9 » comme meilleur que « 4.4 ». TMDB reste utilisé pour tout le reste
  (titre, affiche, année, durée, genres). Couverture : 700 films sur 973 ; les autres n'ont pas
  de note fiable sur Letterboxd (moins de 50 votes) et n'affichent rien.
- **Casting normalisé comme les réalisateurs** (`_canonical_people()`). **Deux registres, à ne pas
  fusionner** : `entiers` indexe la CHAÎNE ENTIÈRE du champ `director` (comportement historique —
  `_fold_person()` trie les mots, donc « Stanton, McKenna » et « McKenna, Stanton » reçoivent la
  même graphie ; découper sur les virgules recouperait les cycles), `unitaires` indexe nom par
  nom pour le casting et est alimenté aussi par les réalisateurs (une même personne réalise et
  joue). Les mentions creuses (`_PLACEHOLDER_PEOPLE` : « acteurs inconnus »…) sont retirées.
- **`ScreeningEvent` sur les pages de rétrospective** (`screening_event()`) : JSON-LD en `@graph`
  = la CollectionPage plus une séance par événement daté, avec `location` (MovieTheater) et
  `offers` (le lien de billetterie). C'est le type que Google attend pour des horaires de cinéma ;
  la CollectionPage seule ne portait aucune date. `startDate` est en heure locale sans fuseau,
  cohérent avec le stockage.
- **Bouton « ← Retour »** (`search.js`) : affiché **uniquement si le référent est du même site**.
  Un visiteur venu de Google n'a pas de « page où il était » chez nous ; lui proposer Retour le
  ferait quitter le site.
- **⚠️ PIÈGE CSS RÉCURRENT : `display:` l'emporte sur l'attribut `hidden`.** Tout élément que le
  JavaScript masque via `.hidden = true` ET qui porte une règle `display:` doit avoir sa règle
  `[hidden] { display: none }`. Déjà rencontré trois fois : `.movie-card` (flex), `.retour`
  (inline-block), `.tri-plus` (block). Sans elle, le masquage est silencieusement sans effet —
  et pour `.retour` ça annulait la protection ci-dessus.
- **Ton des textes d'intro** : pas de tiret cadratin dans la prose (l'utilisateur trouve que ça
  fait « AI generated »), et pas de tournures d'IA : « ce n'est pas X, c'est Y », les chutes
  d'effet (« le grand écran, c'est aussi fait pour ça »), les triades décoratives. Écrire plat
  et factuel. `nombre()` met une espace insécable aux milliers : « 84 640 », pas « 84640 ».
- **Passerelle vers le site frère « Paris Ciné Aujourd'hui »** (`paris_cine_bridge()`,
  `PARIS_CINE_URL`) : encadré en bas des **pages parisiennes uniquement** (la page ville de Paris
  et les fiches des cinémas dont `city_slug == "paris"`, soit 31 salles). Paris Ciné est plus
  complet que Séancéo pour la capitale au quotidien (il liste toutes les sorties, pas seulement
  le répertoire) ; on cible par CONTENU parisien, pas par géolocalisation (site statique).
  Lien externe → nouvel onglet + `rel="noopener noreferrer"` + flèche ↗. **Ne pas l'étendre aux
  pages nationales** (accueil, /a-l-affiche/) : un visiteur non parisien y verrait un renvoi
  vers un site 100 % parisien. L'URL cible est le déploiement Cloudflare (`*.pages.dev`), pas le
  miroir GitHub Pages.
- **L'onglet « 🏆 Le classement » a été retiré du header** (demande utilisateur, 2026-07-22) mais
  **la page `/classiques/` existe toujours** — elle porte le classement COMPLET triable/filtrable
  que l'accueil n'a pas. Elle reste reliée par les « voir le classement » des pages ville et par
  la page marathon (≈ 100 liens internes), donc ni orpheline ni désindexée. Ne pas la supprimer.
- **INTERACTIONS LETTERBOXD.** `sources.py` propage `lb_url` (filtré aux URLs
  `letterboxd.com/film/…`) en plus de `lb_rating`. Deux usages :
  - **Lien « Voir sur Letterboxd »** sur chaque fiche film notée (700 films), à côté de la
    bande-annonce, en vert (`.lien-lb`, `var(--lb)`), nouvel onglet.
  - **Import de watchlist** (`/ma-watchlist/`, `assets/watchlist.js`) — fonction phare, mise en
    avant (1er onglet du header `.nav-wl` + encart `.wl-cta` sur l'accueil). Le visiteur dépose
    l'export de sa watchlist Letterboxd (le `watchlist.csv` d'un export de compte) ; **tout se
    passe dans le navigateur, rien n'est envoyé** (FileReader, aucun upload). Croisement avec
    `site/watchlist-index.json` généré au build.
  - **Clé de matching = empreinte du slug Letterboxd** (`lb_slug_key()` en Python, répliqué à
    l'identique dans `watchlist.js` : NFKD → retirer non-ASCII → garder `[a-z0-9]` collés). Le
    CSV donne un lien court `boxd.it` INUTILISABLE (résolution CORS impossible côté client) et
    des titres en anglais international, MAIS son champ « Name » et notre slug Letterboxd
    dérivent du même titre principal → même empreinte. Ainsi « Shoplifters » (CSV) matche notre
    « Une Affaire de famille » : **matching exact et multilingue sans dépendre du titre
    français**. Validé sur une vraie watchlist : rappel 100 %, 0 faux positif. L'index est
    indexé sous l'empreinte complète ET sa base sans l'année finale (Letterboxd désambiguïse par
    « -2016 ») ; le client tente `empreinte+année` puis `empreinte`.
  - **Ne PAS dire « cette semaine »** : l'index inclut toutes les séances à venir (certaines à
    plusieurs semaines). Wording « à l'affiche », date exacte sur chaque carte, tri par
    imminence (prochaine séance croissante).
  - **Une carte de watchlist doit toujours dire OÙ, QUAND et COMMENT RÉSERVER.** Elle se
    construit dans une seule fonction, `LB.card(f, ag, pick)` (`assets/letterboxd.js`), à
    partir de `watchlist-index.json` seul : depuis 2026-07-27 celui-ci porte l'heure ET le lien
    de billetterie de chaque prochaine séance (voir `k` ci-dessous), donc **tous** les films en
    profitent. `agenda-index.json` n'est plus qu'un **repli** pour un index périmé resté en
    cache navigateur (`agSeance()`, jointure par `u` = URL de fiche, jamais par empreinte —
    l'empreinte est dédoublée entre forme complète et forme sans année). `LB.loadAgenda()`
    avale ses propres erreurs et renvoie `null` : il ne doit jamais casser l'affichage.
    - **Pourquoi ce déplacement** : agenda-index ne couvre que le **répertoire sur 5 semaines**
      (289 entrées). Un film récent de la watchlist (constaté sur *Kneecap* au Cinéma Pax du
      Pouliguen) n'avait donc ni heure ni bouton « Réserver », alors que la fiche du cinéma,
      elle, en proposait un : incohérence visible pour le visiteur. Ne pas re-restreindre.
    - Reste sans bouton ce que la SOURCE ne donne pas (`booking` vide) : quelques salles indés
      sans billetterie en ligne publiée (Le Cinématographe à Nantes, Les 3 Robespierre,
      L'Entrepôt…). Aucune page du site n'a de lien pour ces séances — ce n'est pas un bug.
  - **`watchlist-index.json` est NORMALISÉ (tables partagées).** En tête : `_v` =
    `[nom de ville, lat, lon]`, `_s` = `[nom de salle, index de ville, préfixe de billetterie]`.
    Chaque film porte `k` = `[[index de salle, jour, heure, suffixe de billetterie]]` pour sa
    prochaine séance dans chaque salle, **trié par date**, donc `k[0]` est la prochaine séance
    du film. `n`, `c` et `v` ont été supprimés : ils s'en déduisent (`n` = `k.length`). Les
    clés `_v`/`_s` ne peuvent pas entrer en collision avec un film — une empreinte est faite de
    `[a-z0-9]` uniquement, jamais de tiret bas — mais **tout parcours de l'index doit sauter les
    clés commençant par `_`** (déjà oublié une fois dans le compteur `n_wl`).
    - **Les liens de billetterie sont factorisés par salle** : une salle a toujours le même
      domaine d'achat, seul l'identifiant de séance change. Le préfixe commun vit dans `_s[i][2]`,
      la séance ne garde que son suffixe, et le client recompose (`billetterie()`). Sans ça le
      fichier passait de 281 à 661 ko bruts ; avec, il fait **404 ko bruts / 85 ko gzippés**.
    - ⚠️ **Le préfixe est volontairement raccourci d'un caractère** (`_prefixe_billetterie`) pour
      qu'un suffixe stocké ne soit JAMAIS vide. C'est ce qui permet à `""` de vouloir dire « pas
      de billetterie » sans ambiguïté. Sans ce détail, une salle n'ayant qu'une seule séance
      réservable voyait son URL entièrement absorbée par le préfixe et perdait son bouton.
    - `lb-reco.js`, `lb-listes.js` et `cinematheque.js` ne lisent que `p` et `r` de cet index :
      les faire dépendre de `k` les casserait inutilement.
  - **CADRAGE PAR VILLE (le cœur de la page).** « 32 films à l'affiche » sans ville veut dire
    « quelque part en France » et n'est pas actionnable. Le portail demande donc la ville en
    **étape 2**, APRÈS la synchro du pseudo — demander deux choses avant le moindre résultat
    fait abandonner ; là le visiteur a déjà la preuve que ça marche. La ville est stockée par
    son **NOM** (`LB.setCity`), pas par son index dans `_v` : un index numérique ne survivrait
    pas à une reconstruction du fichier. `LB.city()` ne fonctionne qu'**après `loadIndex()`**
    (c'est `_v` qui résout le nom en coordonnées) ; `villeParNom()` neutralise casse et accents
    (« NANCY », « nancy » → Nancy).
    - **Le champ de ville s'affiche d'emblée**, il n'y a plus de lien « Choisir ma ville » à
      cliquer d'abord (`/ma-watchlist/`, encadré `.lb-city-edit` avec l'accent ambre). C'est
      l'action principale de l'écran : la cacher derrière un clic la faisait manquer. Une fois
      la ville cadrée, la barre redevient compacte avec un bouton « Changer de ville ».
    - **Suggestions maison, jamais de `<datalist>`** (`LB.autoVille`, partagé par le portail et
      la page) : un datalist déroule les 257 villes dès le clic dans le champ, ce qui invite à
      PARCOURIR une liste alors que la bonne action est de TAPER. Rien ne s'affiche avant
      **2 lettres**, puis seules les villes correspondantes remontent, celles qui COMMENCENT par
      la saisie d'abord. Le repli passe par `empreinte`, la même fonction que `villeParNom` :
      ce qui est proposé est donc exactement ce qui sera résolu. Cliquer une suggestion vaut
      validation (pas de second clic sur « Continuer »). Même modèle que `film.js`.
  - **Ville sans séance → on désigne la plus proche, on ne renvoie pas au national.**
    `villeProcheAvecFilm()` cherche, parmi les films de la watchlist, la ville la plus proche
    (Haversine, même formule que `map.js`) qui en programme un — « Rien à Albi, le plus proche
    est Toulouse à ~68 km ». **Ces films doivent être retirés de la section « Ailleurs en
    France »**, sinon ils s'affichent deux fois. Les FAVORIS, eux, ne sont jamais filtrés par
    ville : ils sont au maximum 4, et « un de tes films préférés repasse, à 60 km » reste une
    information qu'on veut donner.
  - **⚠️ ORDRE DE LA PAGE : le verdict sur SA ville passe AVANT les favoris.** `render()`
    construit la section des favoris tôt mais ne l'insère que par `ajouteFavoris()`, appelé
    dans chaque branche APRÈS le compte de la watchlist et la section de la ville. Les favoris
    n'étant pas filtrés par ville, les laisser en tête revenait à annoncer une séance à Nantes
    à quelqu'un qui venait de demander Paris, et à ne lui apprendre qu'en dessous qu'il n'y
    avait rien chez lui (signalé par l'utilisateur le 2026-07-27, compte `Kenzz92`). On répond
    d'abord à la question posée, les séances lointaines viennent après. **Ne pas remonter la
    section `.lb-favs`.**
    - Corollaire à ne pas casser : un favori peut passer dans la ville alors que la watchlist
      n'y a rien. Le titre devient alors « Rien **de ta watchlist** à Paris » plus une ligne qui
      renvoie aux favoris juste en dessous, sinon le « Rien à Paris » sec est démenti par la
      section suivante.
  - **⚠️ PIÈGE UTILISATEUR N°1 : nom affiché ≠ identifiant d'URL sur Letterboxd.** « Alex Her »
    à l'écran peut avoir `alexher__` dans son URL, et `alexher` est alors un AUTRE compte, réel
    mais vide. Le visiteur lisait « ta watchlist est vide » sans comprendre (constaté en vrai,
    2026-07-26 : `alexher` → 0 film, `alexher__` → 380). Ce n'est pas rattrapable côté code (les
    deux pseudos existent, tous deux valides). D'où le rappel `.lb-hint` sous les DEUX champs de
    saisie (portail `USER_HINT` + `/ma-watchlist/` dans build_site.py) et la relance dans le
    message « watchlist vide » — c'est là que la question se pose. Ne pas les retirer.
  - **Nommer la source dans les compteurs** : « 32 des 380 films de ta watchlist Letterboxd sont
    à l'affiche », pas « de tes 380 films à voir ». La page affiche aussi les favoris du profil
    juste au-dessus : sans le mot « watchlist », on ne sait pas ce qui a été compté.
- **« Autour de moi » sur la carte** (`assets/map.js`, page `/carte/`) : bouton `#geoloc-btn` →
  `navigator.geolocation` (position lue dans le navigateur, **rien n'est envoyé**), marqueur
  « vous êtes ici » (`.cine-moi`), carte recentrée, et panneau `#map-nearby` listant les 12
  salles les plus proches (distance Haversine, tri croissant) avec leur nombre de séances de
  répertoire. Répond au use case principal « le répertoire près de chez moi ». Nécessite HTTPS
  (prod OK ; localhost aussi). Les points carte portent désormais `rep` = nb de séances de
  répertoire de la salle cette semaine (injecté au build depuis `rep_by_cinema`). Filtre
  `#rep-only` (« salles de répertoire seulement ») : masque les salles à `rep == 0` sur la carte
  ET dans le panneau (fonction `garde()`). Les salles avec répertoire portent la bordure ambre
  (`.near-item.has-rep`) — c'est ce que le visiteur cherche.
- **Marathons : deux formats + mode culte** (`scripts/marathon.py`). `_pairs_for_day()` génère
  les paires « voisin » (deux salles < `MAX_KM`, trajet à pied dans l'entracte) ET « même salle »
  (`kind`, deux films de suite au même cinéma, entracte `PAUSE_MIN`..`PAUSE_MAX`, aucun trajet).
  `is_cult` = les DEUX films sont des reprises de classiques notées ≥ `CULT_LB_MIN` (3,7/5).
  `build_ideas()` renvoie désormais un **tuple** `(idées par ville, sélection culte nationale)` —
  la section « 🏛️ Marathons cultes » en tête de `/marathon/` agrège les meilleures paires cultes
  de toutes les villes (dédup par paire de films). Les cultes passent en tête du tri partout
  (`_select`). Rendu : `marathon_card(idea, show_city=)` choisit le texte selon `kind`
  (🍿 même salle / 🚶 voisin), badge `.badge-cult`, bordure `.marathon-cult`. Un même marathon
  culte peut apparaître dans la section nationale ET dans sa ville — assumé (une + rubrique).
- **Aucune page ne montre de séance passée** : `build_site.py` filtre `showtimes` sur `>= today`
  dès le chargement. Indispensable car les snapshots de chaînes ont souvent un jour de retard.
- Piloter l'API GitHub (pas de `gh` CLI installé) : token via `git credential fill` (compte Keenzzz).
- Chaînes NON intégrées (plateformes de billetterie verrouillées auth/CORS/bot) : Mégarama
  (ticketingcine/IMS), MK2, Kinepolis, Cineville. Piste propre à terme = agrégateur payant.
