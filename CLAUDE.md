# Séancéo

Site national des séances de cinéma en France : **cinémas indépendants + grandes enseignes**,
avec mise en avant des salles Art & Essai. Objectif : trafic monétisable via SEO programmatique
(une page par ville / cinéma / film). Extension nationale du projet Paris Ciné Aujourd'hui.

- **En ligne** : https://seanceo.pages.dev/ (Cloudflare Pages, projet `seanceo`).
  L'ancienne adresse `keenzzz.github.io/seanceo/` sert encore des **redirections** (voir plus bas).
- **Dossier local** : `C:\Users\knz92\Projects\cine-indes` (non renommé, sans importance).
- **Domaine** `seanceo.fr` prévu mais pas encore acheté (nom vérifié 100 % libre + sans marque déposée).

## Structure

- `scripts/` — pipeline Python **pur stdlib, aucune dépendance** :
  - `fetch_data.py` — indés via l'API open data du SCARE → `data/{cinemas,movies,showtimes,cities}.json`
  - `fetch_pathe.py` — chaîne Pathé (API pathe.fr) → `data/pathe_*.json`
  - `fetch_webedia.py --chain {cgr,grandecran}` — chaînes sur plateforme Webedia boxofficeapi → `data/<chain>_*.json`
  - `fetch_ugc.py` — chaîne UGC via l'API mobile `backend.ugc.fr` → `data/ugc_*.json`
  - `fetch_salles.py` — salles indépendantes ABSENTES du SCARE (Le Louxor, Le Brady,
    La Filmothèque du Quartier Latin) → `data/salles_*.json`
  - `enrich_tmdb.py` — enrichissement TMDB (titres/notes/affiches/durées) → cache `data/tmdb.json`
  - `fetch_abonnements.py` — cartes d'abonnement illimité (UGC Illimité, CinéPass Pathé)
    → `data/abonnements.json` (+ `data/abonnements_overrides.json`, tenu à la main)
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
| **Salles indés hors SCARE** (`fetch_salles.py`) | Sites/billetteries des salles | **Snapshot local** + tentative CI |
| **Cartes d'abonnement** (page UGC + PDF Pathé) | Pages publiques | **Auto en CI**, best-effort |

**Attribution obligatoire, ne jamais retirer du footer** : « Data Ciné Indés / SCARE » (Licence Ouverte 2.0)
et la mention TMDB (« ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB »).

## Contraintes à respecter (ne jamais violer)

### Reprise sur erreur du fetch SCARE
- `fetch_data.py` passe par **`lire_page()`**, qui réessaie 4 fois (2/4/8 s) les ruptures de
  transport. Motif : depuis les IP datacenter du CI, l'API du SCARE accepte la connexion puis la
  lâche en cours de transfert — `RemoteDisconnected` ou `IncompleteRead`. Trois runs d'affilée en
  échec le 2026-08-21, alors que la même requête passait en 2 s depuis la machine de dev : ce
  n'est ni l'API ni le code, c'est le trajet. Même famille que les blocages Pathé/CGR, mais sous
  une forme PARTIELLE, qui ressemble à un bug plutôt qu'à un blocage.
- ⚠️ **Une `HTTPError` (4xx/5xx) n'est PAS réessayée**, volontairement : elle signale une requête
  fautive ou un service en panne, insister ne ferait que retarder un échec mérité. Ne pas
  élargir le `except` à toutes les exceptions, ce serait transformer une reprise utile en boucle
  qui masque les vrais problèmes.
- **SCARE n'a PAS de garde-fou best-effort** contrairement aux connecteurs de chaînes, et c'est
  assumé : c'est la source principale (les indés sont la raison d'être du site), déployer sans
  elle n'aurait pas de sens. On insiste, puis on échoue franchement.
- `PAGE_SIZE` reste à 10 000 (~12 Mo par page, 2 requêtes pour ~17 000 séances). **Levier
  disponible si les reprises deviennent fréquentes** : le descendre à 2 000 fait des pages de
  2,4 Mo, bien moins exposées à une coupure, au prix de 5 fois plus d'appels chez la source.
  Le journal du CI dit désormais quand une reprise se déclenche : décider sur cette mesure.

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
- **CSP et en-têtes de sécurité** (`site/_headers`, posé le 2026-08-22). GitHub Pages ne permettait
  aucun en-tête, Cloudflare oui : c'est ce que la migration a débloqué.
  - **Le fichier est GÉNÉRÉ par `csp_headers()`, jamais écrit à la main dans `static/`.** La CSP
    contient l'empreinte SHA-256 des deux scripts EN LIGNE du gabarit (`JS_FLAG`, `T_HELPER`) ;
    un site statique ne peut pas utiliser de `nonce` (il devrait changer à chaque réponse). Le
    hash porte sur les octets exacts : **un espace ajouté dans JS_FLAG ou T_HELPER suffirait à
    faire rejeter le script**, et le site perdrait son JavaScript sans un mot au build. Le dériver
    du code est ce qui rend cette divergence impossible.
  - ⚠️ **`img-src` autorise `https:` en bloc, PAS une liste de domaines.** Les affiches viennent de
    TMDB et du CDN de chaque chaîne (8 domaines observés le 2026-08-22). Cette liste vient des
    DONNÉES : une salle qui change d'hébergeur en ajoute un du jour au lendemain, et une liste
    blanche ferait alors disparaître des affiches en silence. Une image ne s'exécute pas ;
    l'essentiel de la protection est dans `script-src`, qui reste strict. Ne pas « durcir » ce
    point sans prévoir un garde-fou qui signale les hôtes inconnus au build.
  - ⚠️ **`style-src 'unsafe-inline'`** : les jauges de « Salles de patrimoine » portent un
    `style="width:NN%"` dont la valeur vient des données, impossible à mettre en feuille de style
    sans une centaine de classes de largeur. Tout contenu externe passant par `html.escape()`, le
    risque résiduel est faible.
  - `connect-src` autorise `'self'` **et le Worker watchlist** (`WORKER_ORIGIN`) : sans lui, la
    watchlist par pseudo échoue. Cette constante est aussi répétée dans `letterboxd.js` et `sw.js`.
  - **PIÈGE DE TEST** : sur un déploiement de PRÉVERSION, l'appel au Worker échoue en
    « Failed to fetch » — non pas à cause de la CSP mais parce que `ORIGINS_OK` (worker/src/index.js)
    n'autorise pas les hôtes `*.pages.dev` de test. Pour distinguer les deux, refaire l'appel en
    `mode:'no-cors'` : ce mode contourne le CORS mais reste soumis à la CSP.
  - Vérifié sous CSP avant mise en prod : carte Leaflet (55/55 tuiles cartocdn), affiches TMDB,
    scripts en ligne, enregistrement du service worker, fetch de l'index local, et blocage effectif
    d'un domaine tiers.
- **Tout contenu externe passe par `html.escape()`** (titres, noms de cinémas…) — jamais d'injection HTML.
- Les popups de la carte échappent le texte côté JS (`map.js`, fonction `esc`).

### URL / déploiement
- **Le site est servi à la RACINE de son domaine** : `BASE_PATH = ""`,
  `BASE_URL = "https://seanceo.pages.dev"` dans `build_site.py`. Tout le site en dérive
  (canoniques, hreflang, og:url, sitemap, robots, liens internes) : **le jour de `seanceo.fr`,
  seule la ligne `BASE_URL` change**, plus le domaine perso côté Cloudflare et la Search Console.
- **Le build reste dans GitHub Actions, Cloudflare ne fait que RECEVOIR `site/`**
  (`wrangler pages deploy`). Ne pas basculer sur le build intégré de Cloudflare Pages : lui seul
  ne saurait pas relancer les connecteurs best-effort ni retomber sur les snapshots versionnés,
  et le cron quotidien vient de GitHub. Secrets requis : `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
- **L'ancienne adresse GitHub Pages n'est PAS éteinte** : `scripts/build_redirects.py` y publie un
  site fantôme (une page de redirection par URL du sitemap + un `404.html` qui reporte le chemin).
  GitHub Pages ne permet pas de choisir les en-têtes HTTP, donc **pas de 301 possible** : on
  redirige avec `rel="canonical"` + `meta refresh` à délai nul. **Pas de `noindex`** dessus — la
  consigne risquerait d'être reportée sur la page CIBLE. À garder tant que Google sert encore les
  anciennes URL.
- **Une seule origine à déclarer dans le Worker** : `SITE_ORIGIN` (`worker/src/index.js`) sert au
  CORS, au User-Agent et aux liens du `.ics`. `ORIGINS_OK` garde l'ancienne origine le temps que
  les caches navigateur se vident. `WATCHLIST_INDEX` (`worker/wrangler.toml`) doit suivre.
- Fichier de validation Search Console dans `static/` — **ne jamais le supprimer** (perte de propriété).
- **⚠️ PIÈGE CLOUDFLARE : les URL en `.html` sont réécrites.** Cloudflare Pages retire
  automatiquement l'extension et renvoie un **308** vers la version sans `.html` — GitHub Pages
  servait le fichier tel quel. Google Search Console, lui, exige son fichier de validation
  EXACTEMENT à `/google….html` et ne suit pas la redirection : la validation échouait avec
  « impossible de trouver le fichier de validation à l'emplacement requis » alors que le fichier
  était bien déployé et son contenu correct. Correctif : `static/_redirects` avec une règle en
  **200** (une RÉÉCRITURE, pas une redirection — un 301/302 ne marcherait pas). Vérifié sur un
  déploiement de préversion avant mise en prod. Vaut pour tout fichier devant être servi à une
  URL en `.html` exacte.
- **⚠️ Le site fantôme de l'ancienne adresse doit AUSSI porter le fichier de validation.**
  `build_redirects.py` recopie `static/google*.html` dans `redirect/`. Oublié à sa première
  version : le fichier est tombé en 404 sur `keenzzz.github.io/seanceo/` dès le premier
  déploiement, ce qui aurait fait révoquer l'ancienne propriété — et avec elle l'historique de
  performance et le suivi du transfert d'indexation. L'ancienne propriété doit rester valide
  tant que Google sert encore les anciennes URL.

### Salles indépendantes hors SCARE (`fetch_salles.py`)

L'open data du SCARE ne couvre QUE ses adhérents publiants : des salles Art & Essai
majeures y manquent, alors qu'elles sont au cœur de la cible. `fetch_salles.py` va les
chercher une par une. Trois aujourd'hui, toutes à Paris — **Le Louxor** (75010),
**Le Brady** (75010), **La Filmothèque du Quartier Latin** (75005) — pour ~205 séances.

- **MESURÉ le 2026-08-28 : les trois sources PASSENT depuis le CI**, contrairement à
  Pathé/CGR/Grand Écran. Le snapshot reste versionné par prudence (et parce qu'il fait
  filet en cas de panne d'un petit serveur), mais la collecte se rafraîchit toute seule
  chaque nuit. Ne pas conclure du blocage des chaînes à un blocage ici.

- **Ce ne sont PAS des chaînes.** Aucune fiche ne porte de champ `chain`, ce qui les fait
  libeller « cinéma indépendant » par `cinema_kind()`. Le préfixe `salles` est dans
  `CHAIN_PREFIXES` (sources.py) uniquement parce que c'est le mécanisme de fusion ; ne pas
  en conclure qu'il faut leur inventer une enseigne.

- **Deux plateformes, une par type de salle :**
  - `webedia` — le site de la salle est un Gatsby « boxofficeapi », **le même produit que
    CGR et Grand Écran**. Le connecteur IMPORTE `fetch_webedia.py` au lieu de le recopier
    (mêmes endpoints, mêmes tags, mêmes liens). Le piège du `theaterId` en MAJUSCULES +
    JSON compact vaut ici aussi.
  - `cotecine` — billetterie Côté Ciné (`*-vad.cotecine.fr`), un JSON en trois temps
    (film → jours → séances), plus le CMS de la salle pour les fiches films.

- **⚠️ Le code salle Webedia se lit dans `<meta name="bocms:theater:id">`** — et pas au
  même endroit selon la salle : sur l'ACCUEIL du Louxor (`W7510`), mais **seulement sur une
  page film** au Brady (`C0023`), dont l'accueil est un gabarit générique. D'où les deux
  essais du connecteur (accueil, puis premier film du sitemap). Le code du registre sert de
  repli ET de témoin : un écart est signalé, parce que collecter la mauvaise salle
  produirait des séances valides… et fausses.

- **⚠️ L'API Webedia de chaque site est CLOISONNÉE à ses propres salles.** Demander à
  `cinemalouxor.fr` le planning d'un code CGR répond **500**, et réciproquement. Il n'y a
  donc pas de passerelle universelle à chercher : une salle = son site.

- **⚠️ La billetterie Côté Ciné sert de l'iso-8859-1**, pas de l'UTF-8. Décoder en UTF-8
  donnerait des titres accentués en bouillie, sans erreur.

- **⚠️ La caisse Côté Ciné répond `false`, pas `{}`, quand un film n'a plus de jour ouvert
  à la vente.** Le film reste dans la liste déroulante mais son exploitation est finie.
  C'est une réponse NORMALE, qui arrive toutes les semaines — la traiter comme une panne
  bloquerait le snapshot entier à chaque fin d'exploitation. `lire_dict()` la nomme une
  fois pour toutes ; toute AUTRE forme non-objet (liste, chaîne) lève `SourceIndisponible`,
  parce que là ce serait un vrai changement de format. **Trouvé par le CI le 2026-08-28**
  (`TypeError: 'bool' object is not iterable`, sur « Le Violent » et « Mirage de la vie »),
  pas en local : les deux films avaient encore des jours ouverts au moment du test.

- **Heure des séances : on CROISE l'horodatage et l'heure affichée**, on ne convertit pas.
  Windows n'embarque pas la base IANA, donc `zoneinfo("Europe/Paris")` n'est pas garanti
  sans dépendance. La caisse donne l'epoch UTC ET « 21h20 » : chercher le décalage (+1/+2)
  qui reproduit l'heure murale donne du même coup la bonne DATE — ce que le jour de la
  caisse ne dit pas toujours (une séance de minuit est rangée sous la soirée qui précède).

- **Le formulaire Côté Ciné est en POST : aucun lien ne mène à UNE séance.** Mais film et
  jour se présélectionnent en GET (`?modresa_film=…&modresa_jour=…`) : le visiteur arrive
  sur le bon film au bon jour et ne choisit que l'heure. C'est le meilleur lien disponible,
  et il est honnête. **100 % des 206 séances ont une billetterie cliquable.**

- **Le réalisateur n'est PAS un luxe** : `enrich_tmdb.py` s'en sert pour départager les
  homonymes (« Drive », « Bird », « Possession »…). La caisse ne donne qu'un titre, donc le
  connecteur résout chaque titre sur le CMS de la salle (recherche REST WordPress) puis lit
  `<h3 class="director">` dans la fiche. Trois requêtes de recherche au plus, de la plus
  fidèle à la plus permissive, et **jamais de « premier résultat » pris au hasard** : seule
  une correspondance exacte (empreinte, ou radical sans article ni parenthèse) est acceptée,
  sans quoi « Alien 3 » se retrouverait projeté à la place d'« Alien ».
  - `TITRES_CMS` nomme les cas qu'aucune recherche ne rapproche — « 12 hommes en colère »
    (caisse) contre « Douze Hommes en Colère » (site). Une table de nombres générique
    apparierait aussi « Alien » et « Alien 3 » : on préfère nommer les cas, et le connecteur
    SIGNALE les titres non résolus au lieu d'en inventer la résolution.

- **Affiches : on ne prend que les portraits** (marqueur `-c_<l>_<h>_` avec h > l). La même
  figure du CMS porte parfois un photogramme panoramique, qui ferait une carte écrasée.
  Sans affiche valable on laisse vide — **TMDB la pose ensuite** (après fusion : 0 film sans
  affiche, 0 sans réalisateur sur les 76).

- **GARDE-FOU d'écriture, différent de celui des chaînes.** Une salle en RELÂCHE (0 séance)
  est un état NORMAL — travaux, fermeture annuelle — et ne doit pas bloquer les autres. Une
  salle dont la SOURCE n'a pas répondu est autre chose : le connecteur n'écrit alors RIEN
  et sort en 1, pour ne pas faire rétrécir le snapshot en silence. C'est pour ça que le
  réseau lève `SourceIndisponible` au lieu de renvoyer `None`.

- **Abonnements : les trois salles sont badgées, et deux le sont par override.**
  `salles_cinemas.json` est dans `SNAPSHOTS` (fetch_abonnements.py) avec une enseigne à
  `None`, comme les indés du SCARE. Deux faux négatifs de nom ont dû être corrigés à la
  main dans `abonnements_overrides.json`, chacun vérifié sur la source officielle :
  **Le Louxor** (UGC écrit « LE LOUXOR », nous « Le Louxor - Palais du cinéma ») et
  **Le Brady** (le PDF Pathé écrit « Le Brady Cinéma Théâtre »). On ne raccourcit pas le nom
  d'une salle sur le site pour arranger un appariement.

- **Pour ajouter une salle** : une entrée dans `SALLES` (adresse relevée sur le site de la
  salle — *le siège social de l'exploitant n'est pas l'adresse de la salle*, celui du Louxor
  est rue des Martyrs ; lat/lon via la Base Adresse Nationale) et le nom de sa plateforme.
  La liste UGC Illimité contient **~60 salles absentes de Séancéo**, dont une trentaine à
  Paris (MK2, Luminor, Reflet Médicis, Épée de Bois, Mac-Mahon, Max Linder…) : c'est
  l'inventaire de cibles tout fait.

### Cartes d'abonnement illimité (UGC Illimité / CinéPass Pathé)

`fetch_abonnements.py` produit `data/abonnements.json` (`{cinema_id: {ugc_illimite, cinepass}}`),
que `sources.py` pose sur chaque cinéma sous le champ **`cartes`** (nommé ainsi pour ne pas se
confondre avec l'encadré d'ABONNEMENT AGENDA des pages ville, qui n'a rien à voir). Rendu par
`carte_badges()` / `carte_attr()` et le filtre `cartes_filtre()` + `assets/cartes.js`.
Résultat au 2026-08-24 : **153 salles sur 357** — UGC Illimité 75, CinéPass 89, **11 les deux**.

- **Deux sources, deux requêtes, ~400 Ko** :
  `https://www.ugc.fr/cinemas-acceptant-ui.html` (HTML, 144 salles avec code postal) et
  `https://media.pathe.fr/files/conditions/Reseau%20CinePass-CineCartes.pdf` (137 lignes).
  - ⚠️ **Le PDF Pathé DOIT être pris sur `media.pathe.fr`, jamais `www.pathe.fr`** : la même URL
    en `www` renvoie **403** depuis une IP datacenter (le blocage Pathé habituel), le CDN Akamai
    sert le fichier identique octet pour octet et passe. C'est ce qui rend l'étape CI possible.
  - ⚠️ **La page UGC échappe à la détection de bot d'ugc.fr**, contrairement aux pages de séances
    (cf. `fetch_ugc.py`) : elle se sert entière sans User-Agent de navigateur. Ne pas conclure de
    l'une à l'autre.
  - Le PDF est un **export Excel** : texte en clair, un `Tj` par cellule, extractible en stdlib
    pure (zlib + regex). Fragile par nature — d'où `MIN_UGC`/`MIN_PATHE`, qui font échouer
    bruyamment plutôt que de publier un `abonnements.json` amputé.
  - Fraîcheur : le `CreationDate` du PDF (2026-05-06) est le marqueur à surveiller.

- **PAS de règle par enseigne, et ce n'est pas de la prudence excessive** :
  - `chain == "Grand Écran"` ne détermine rien : **6 des 14 sont EXCLUS** d'UGC Illimité
    (La Chapelle-sur-Erdre, Montaigu-Vendée, Fontenay-le-Comte, Vichy, Bergerac, Villeneuve-sur-Lot).
  - Badger « CinéPass » les 77 Pathé serait FAUX : la liste compte 77 salles Pathé et nos
    snapshots 77 aussi, **mais ce ne sont pas les mêmes** — `Le Renoir` (Aix) et `Pathé Île Seguin`
    n'y figurent pas, la liste connaît `Le Cézanne` et `Ciné Jaude` que nous n'avons pas. On badge
    ce qui est listé, rien de plus.
  - **CGR : aucune offre illimitée n'existe.** Club CGR = fidélité, La Box = carnet de places.
    Ne pas re-chercher. Et ne pas confondre avec le « CinéPass » de grandecran.fr : **homonyme
    total**, c'est une carte rechargeable sans rapport avec l'abonnement Pathé.

- **Appariement : trois garde-fous, tous nés d'un faux positif observé.** Un badge « accepte ta
  carte » qui se trompe envoie quelqu'un au guichet pour rien : on préfère le silence au faux.
  1. **Les mots d'enseigne ne sont retirés qu'en PRÉFIXE** (`PREFIXES`, jamais `VIDES`). Les
     retirer partout écrasait « L'Écran de Saint-Denis » en « SAINT DENIS », qui s'appariait au
     **Pathé Saint-Denis** — et la vraie salle (L'Écran, indé) perdait son badge.
  2. **`compatibles()`** refuse d'apparier deux noms qui revendiquent des enseignes différentes :
     « MK2 Parnasse » (75006) et « Pathé Parnasse » (75014) se réduisent tous deux à « PARNASSE »
     et se rejoignaient au rattrapage par commune — Paris est une commune, et une grande.
  3. **Le groupe du PDF fait foi** : une ligne « Cinéma indépendant » ne peut pas désigner une de
     nos salles Pathé. C'est le seul discriminant entre « Ciné Massy » (l'indé Cinémassy) et
     Pathé Massy, dont les noms normalisés sont identiques et les villes correctes.
  - **Blocage géographique asymétrique, volontairement** : côté UGC, code postal puis commune en
    rattrapage (UGC range les 3 salles de Limoges en 87100 quand nos snapshots disent 87000).
    Côté Pathé, le PDF ne donne qu'une **agglomération** qui n'est presque jamais la commune
    (Labège sous TOULOUSE, Coquelles sous CALAIS, Quetigny sous DIJON) : on exige la commune pour
    les lignes **indé** — dont les noms (Le Vox, Le Capitole, Les Capucins) sont partagés par toute
    la France — et on s'en remet à l'unicité du nom pour les lignes **Pathé**, que l'exploitant
    nomme sans ambiguïté. Exiger la commune partout perdait 11 salles Pathé.

- **`data/abonnements_overrides.json` est tenu à la main et gagne toujours.** Trois entrées
  aujourd'hui, chacune avec sa justification dans le fichier (`_pourquoi`) — c'est ce qui
  distingue une correction vérifiée d'une intuition, six mois plus tard. Y figure aussi la liste
  des **absents volontaires**, pour qu'on ne « corrige » pas un jour ce qui est juste.
  Quand les listes officielles changent, le collecteur affiche les lignes non appariées : c'est
  là que se recrutent les overrides.

- **Le filtre est mémorisé** (`localStorage["seanceo:carte"]`) : une carte d'abonnement, on l'a
  pour l'année, pas pour une visite. Il agit au niveau du **bloc cinéma** (la carte donne accès à
  une salle, tous ses films y compris) via `data-carte-off` et **pas** `style.display`, que
  `ville.js` écraserait au tri suivant. Il masque aussi les liens du sommaire ancré
  (`.city-jump`), sans quoi ils mèneraient à des ancres invisibles. Une carte mémorisée qu'aucune
  salle de la ville n'accepte retombe sur « Peu importe » plutôt que de vider la page.
  ⚠️ Le build ne propose QUE les cartes représentées dans la ville : proposer « CinéPass » à
  Nancy, où aucune salle ne l'accepte, ne rendrait qu'une page vide et l'impression d'un bug.

- **Ne badge que ce qui est accepté, jamais l'inverse.** Sur 357 salles, une trentaine seulement
  portent une information que le visiteur ne devine pas en lisant l'enseigne ; afficher
  « n'accepte pas le CinéPass » partout ailleurs affirmerait ce que nos sources ne disent pas —
  elles listent les partenaires, elles ne certifient pas l'absence.

- **Piste d'élargissement notée au passage** : la liste UGC contient **~60 salles absentes de
  Séancéo**, dont une trentaine à Paris intra-muros (MK2, Luminor, Reflet Médicis, Épée de Bois,
  Mac-Mahon, Max Linder…). C'est un inventaire de cibles tout fait, plus rentable en trafic que
  les badges eux-mêmes.

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
- **404** : l'hébergeur ne sert que le `/404.html` de la racine, quelle que
  soit l'adresse manquante — un `/en/404.html` ne serait jamais affiché (vrai
  sur GitHub Pages hier, sur Cloudflare Pages aujourd'hui). La 404 est donc en
  français, avec une ligne anglaise et un lien vers `/en/`.
- **Notifications** : un service worker n'a accès ni au DOM ni à `window`. La
  langue lui arrive dans l'URL d'enregistrement (`/sw.js?lang=en`), qu'il relit
  dans `self.location`.

## Points de repère

- Distinction indé / chaîne : champ `chain` sur chaque cinéma. `chain_badge()` dans `build_site.py`
  (point rouge « Indé » = signature ; badge gris + nom = chaîne).
- Cartes d'abonnement illimité : champ `cartes` sur chaque cinéma, badge bleu (`carte_badges()`).
  Voir la section dédiée plus haut — **l'enseigne ne détermine pas la carte**, dans les deux sens.
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
  - **`ID_OVERRIDES` force un id TMDB pour une clé de film donnée** (ajouté le 2026-08-28). Il ne
    contourne PAS la validation par réalisateur : celle-ci départage des candidats, elle ne peut
    rien quand la recherche en rend **zéro**. C'est le cas de figure visé — « Le Cadet d'eau
    douce » (Le Brady) ne remonte aucun résultat parce que TMDB titre sa fiche « Cadet d'eau
    douce », sans l'article ; l'id 25768 (Keaton 1928, « Steamboat Bill, Jr. ») est vérifié à la
    main. Un film absent de la table suit **exactement** le chemin d'avant : mesuré en rejouant
    22 films (trouvés, non trouvés, avec et sans réalisateur) sur les deux versions au même
    instant — 22/22 identiques, 0 divergence.
    - ⚠️ **La clé dépend de la GRAPHIE de la source** (`movie_key` = titre|réalisateur slugifiés).
      Une autre caisse écrivant le même film autrement produirait une autre clé, non couverte.
      On corrige un cas constaté, on ne parie pas sur les autres.
    - ⚠️ **Le cache est incrémental** : ajouter une entrée ne suffit pas, le film garde son
      `{found: false}`. Retirer SA clé de `data/tmdb.json` puis relancer le script (ne PAS faire
      `--refresh`, qui réinterroge les 1 879 films). Puis `fetch_letterboxd.py`, qui a besoin de
      l'id TMDB pour trouver la fiche Letterboxd.
    - **Piste NON retenue** : rejouer la recherche sans l'article de tête réglerait cette classe
      de films d'un coup. Écarté pour l'instant — élargir la recherche, c'est augmenter le risque
      de faux positifs sur 1 879 films pour en gagner quelques-uns, alors qu'un override est
      explicite et vérifié. À reconsidérer si le cas devient fréquent.
- **POSITIONNEMENT : le site est un agenda du RÉPERTOIRE.** L'accueil ne montre plus les sorties
  récentes mais les films anciens qui repassent. `scripts/repertoire.py` porte toute la détection :
  reprise = `year < REPERTOIRE_BEFORE` (2020) ; séance unique = le film ne passe qu'une fois en
  France sur 7 jours (6 films sur 10 !) ; cycle = ≥ 2 films d'un même réalisateur dans une même
  salle, agrégés ensuite au national. **Le seuil 2020 n'est pas arbitraire** : à 20 ans d'âge,
  84 villes sur 257 seulement étaient couvertes ; avant 2020, 154 villes le sont. Ne pas le
  remonter sans re-mesurer la couverture.
- **ORDRE DE L'ACCUEIL (modifié le 2026-08-22, demande utilisateur)** : « À ne pas rater », puis
  « Rétrospectives en cours », puis l'encart « Compose ta cinémathèque », puis « Les anniversaires
  de {année} », puis « Salles de patrimoine ». Les rétrospectives sont passées AVANT les
  anniversaires. L'encart cinémathèque a suivi les rétrospectives et n'est pas resté en place :
  il propose de composer SA PROPRE rétrospective, il enchaîne donc sur les cycles existants ;
  coincé derrière les anniversaires il n'était plus rattaché à rien.
- **Filtre par ville sur « À ne pas rater »** (`assets/agenda-ville.js`, 2026-08-22) : des BOUTONS
  portant les seules villes DIFFUSATRICES de la sélection, jamais les 255 villes du site —
  proposer une ville sans résultat fait cliquer dans le vide.
  - **Boutons et non un `<select>`, contrairement à « Dernière chance »** : là-bas le menu liste
    une trentaine de villes, ici il y en a deux à quatre. Un menu déroulant pour deux choix
    cache derrière un clic une information qui tient sur une ligne. Même grammaire que les
    boutons de tri (`aria-pressed`, styles partagés) : c'est le même geste pour le visiteur.
  - **La ville active est portée par `aria-pressed`, pas par une variable à part** : l'état lu
    par un lecteur d'écran et l'état interne sont le même, ils ne peuvent pas diverger.
  - Re-cliquer la ville active ne la désélectionne pas : il faut qu'une ville soit toujours
    choisie, sinon plus aucun bouton n'indiquerait ce qui est affiché.
  - ⚠️ **Tous les compteurs sont en SÉANCES**, « Toutes (12) » compris. Le `<select>` d'origine
    mélangeait deux unités (« Toutes les villes (3) » = des villes, « Nantes (7) » = des
    séances), illisible une fois les deux côte à côte. L'accueil appelle donc désormais
  `agenda_par_jour(rep_uniques, data=True)` (c'est `data-city` qui sert ; 12 lignes, surcoût nul).
  - Le script est une version RÉDUITE de `chance.js`, volontairement : la page « Dernière chance »
    filtre aussi par jour, trie par note et exporte un .ics. La réutiliser telle quelle aurait
    chargé tout ça sur l'accueil pour n'en garder qu'un dixième.
  - Portée EXPLICITE `#agenda-uniques` et non le document : rien ne garantit que l'accueil
    n'accueillera pas un second agenda un jour.
  - Styles partagés avec `.chance-tools` (`.agenda-tools` ajoutée aux mêmes sélecteurs) : c'est le
    même geste pour le visiteur, il doit avoir la même forme. `html:not(.js) .agenda-tools` masque
    la barre sans JavaScript, comme `.film-tools`.
  - ⚠️ Dépend des règles `.seance[hidden]` / `.jour[hidden]` déjà présentes (piège CSS récurrent),
    et masque les sections `.jour` devenues vides pour ne pas laisser un titre de jour orphelin.
  - **La sélection est PLAFONNÉE PAR VILLE depuis le 2026-08-22** (`unique_screenings()`,
    repertoire.py) : 2 séances par ville, **3 pour Paris**. Avant ce plafond, les 12 meilleures
    notes de France se groupaient sur 3 villes (Nantes 7, Paris 4, Dunkerque 1) alors que le
    vivier comptait 81 séances notées sur 20 villes ; on affiche désormais **9 villes**, Paris en
    tête. Le filtre est donc passé de 4 à 10 boutons, qui s'enroulent sur deux lignes.
  - ⚠️ **Le quota parisien va dans le sens INVERSE du `PARIS_CAP` des cycles**, et c'est voulu :
    sur les rétrospectives, la Cinémathèque et le Quartier latin saturent le classement, il faut
    brider Paris ; sur les séances uniques, c'est Nantes qui domine et Paris a besoin d'être
    protégé. Chaque réglage corrige la sur-représentation de SA section — ne pas « harmoniser ».
  - Réglages mesurés avant d'être choisis : quota Paris à 3 → 9 villes, à 4 → 8 villes. La note
    moyenne ne bouge quasiment pas (4,29 contre 4,30) : les rangs 13 à 30 du classement se valent,
    diversifier ne coûte rien en qualité.
- **Page « Dernière chance »** (`/derniere-chance/`) : TOUTES les séances uniques de la fenêtre,
  en agenda chronologique, filtrables par ville et par jour, classables par note. Deux fonctions distinctes dans `repertoire.py`,
  ne pas les confondre : `unique_screenings()` = la SÉLECTION de l'accueil (les mieux notées, une
  douzaine) ; `unique_all()` = le catalogue complet, **notes ou pas**. Un film sans note
  Letterboxd reste une séance unique : l'écarter ferait mentir le compte affiché juste à côté.
  `count_unique()` est défini à partir de `unique_all()` pour qu'il n'existe qu'UNE définition de
  la séance unique — le compteur de l'accueil et la page ne peuvent pas diverger.
  - Le filtre de ville est un `<select>` et non la recherche à suggestions du reste du site :
    ici le visiteur ne cherche pas une ville parmi 257, il regarde ce qui existe parmi la
    trentaine qui programme une séance unique. La liste déroulée annonce au passage les villes
    concernées. `chance.js` masque aussi les journées devenues vides (sinon un titre de jour
    reste orphelin), et les règles `.seance[hidden]` / `.jour[hidden]` sont indispensables
    (`display:` l'emporte sur `hidden`, voir le piège récurrent plus bas).
  - **Le filtre de JOUR transporte la DATE ISO, jamais le nom du jour.** La fenêtre déborde sur
    la semaine suivante (8 jours mesurés), donc deux « dimanche » y coexistent : filtrer sur
    « dimanche » en mélangerait deux. Les options sont dans l'ordre de la semaine, jamais
    alphabétique. `i18n.jour_date()` (≠ `date_label()`) nomme TOUJOURS le jour : « Aujourd'hui »
    dans une liste déroulante ne dit pas quel jour on choisit et changerait de sens le lendemain.
  - **Le tri par note DÉPLACE les `<li>` dans une liste plate** (`#chance-note`, vide dans le HTML
    servi) et masque les sections `.jour` : classer par note casse forcément le groupement par
    jour. Retour au tri chronologique = chaque ligne réintègre le `<ul>` de sa journée, via la
    table `accueil` construite au chargement. Vérifié : le round-trip redonne le HTML du build au
    nœud près. Chaque ligne porte donc sa date en dur (`.jour-inline`, écrite par `seance_row()`),
    **masquée en CSS** sauf sous `.par-note` — en tri chronologique l'en-tête de section la dit
    déjà. Un film sans note Letterboxd porte `data-lb="0"` et part en queue, comme `renseigne()`
    dans tri.js ; l'écarter ferait mentir le compte affiché juste au-dessus.
- **`assets/ics.js` est PARTAGÉ** par `/cinematheque/` et `/derniere-chance/` : les deux boutons
  « ajouter à mon agenda » doivent produire exactement le même fichier. Le module est chargé
  **avant** le script de la page qui l'appelle (les deux en `defer`, donc dans l'ordre du
  document) — l'oublier rend le bouton silencieusement mort. Il n'est PAS chargé ailleurs :
  inutile de le mettre dans le `<head>` commun pour deux pages. ⚠️ La description d'un événement
  se construit avec un **vrai saut de ligne** ; c'est `esc()` qui le convertit en `\n` iCalendar.
  L'écrire déjà échappé le fait échapper deux fois et les agendas affichent « \n » en toutes
  lettres (bug d'origine de l'export cinémathèque, corrigé le 2026-08-15).
- **Fiches réalisateur** (`/realisateur/<nom>/` + index `/realisateurs/`) : PERMANENTES, contrairement
  aux pages de rétrospective qui disparaissent avec leur cycle. Elles répondent à « films de X au
  cinéma » et ferment un trou de maillage (les 966 fiches film citaient un réalisateur sans jamais
  pouvoir y renvoyer — c'est `credit_realisateurs()` qui pose ce lien).
  - **SEUIL, à ne pas relâcher** : 746 réalisateurs ont un film à l'affiche ; une page pour chacun
    ferait des centaines de pages maigres qui recopient une fiche film. On garde ≥ 2 films à
    l'affiche **ou** un film de répertoire joué au moins 2 fois → **134 pages**. Le cas exclu (un
    film de répertoire à séance unique) est déjà couvert par `/derniere-chance/` et par la fiche film.
  - **Fusion d'alias LOCALE** (`alias_reels`) : certaines caisses créditent « A Demuynck » là où
    d'autres écrivent « Arnaud Demuynck ». On ne fusionne que le cas sûr — prénom réduit à une
    initiale, même nom de famille, **un seul** candidat au prénom complet. Sur 4 cas mesurés, 2 ont
    un jumeau, les 2 autres gardent leur graphie. ⚠️ Cette fusion ne touche PAS
    `_canonical_directors()` : ses garde-fous protègent la déduplication des FILMS, on n'y touche pas
    pour un problème d'affichage. Le nom affiché reste celui du générique, seul le lien pointe vers
    la fiche canonique.
  - L'intro ne répète pas le nom du cinéaste (il est en h1 juste au-dessus) : « de {nom} »
    obligerait à gérer l'élision française (« de Abbas » au lieu de « d'Abbas ») pour rien.
  - L'agenda de la fiche ne liste que les séances de RÉPERTOIRE, plafonnées : un film récent du même
    cinéaste peut passer 200 fois dans la semaine.
- **⚠️ Le badge « Séance unique » de `seance_row()` est CONDITIONNEL** (`uniques_keys`, dérivé de
  `repertoire.unique_all()`). Il était posé sur toutes les lignes, ce qui était juste tant que la
  fonction ne servait qu'à l'accueil et à « Dernière chance » — deux pages qui ne montrent QUE des
  séances uniques. Sur une fiche réalisateur, un film joué à Strasbourg ET à Nancy s'annonçait
  comme une séance unique. Toute nouvelle page qui réutilise `seance_row()` hérite du bon
  comportement, ne pas le re-figer.
- **Abonnement au répertoire par ville** : un `.ics` et un flux RSS par ville, à URL fixe
  (`/ville/<slug>/repertoire.ics` et `.xml`), réécrits à chaque build. Un agenda abonné à une URL la
  re-télécharge tout seul : le répertoire de sa ville arrive chaque semaine chez le visiteur **sans
  serveur, sans compte et sans e-mail**. C'est la seule forme d'abonnement possible pour un site
  statique. Encadré `.abo` en bas de chaque page ville (webcal / .ics / RSS) + `<link rel="alternate">`
  pour la découverte automatique.
  - ⚠️ **LES FLUX EXISTENT POUR LES 257 VILLES, MÊME VIDES.** Une ville sans reprise cette semaine
    en aura une le mois prochain, et l'abonné doit la recevoir. Ne générer que les villes non vides
    ferait disparaître l'URL à la première semaine creuse, et un agenda qui reçoit un 404 finit par
    se désabonner. 1 028 fichiers, 1,2 Mo au total.
  - **UID stable** (`salle-film-début@seanceo`) : sans lui, chaque build effacerait puis recréerait
    tous les événements de l'abonné, qui perdrait ses rappels. Un item RSS **par film et non par
    séance** (dix séances du même film ne font pas dix lignes), avec un `guid` qui inclut la date de
    la première séance — le même film reprogrammé plus tard redevient une nouveauté.
  - ⚠️ **`write_raw()` écrit des OCTETS, jamais `write_text()`.** Sous Windows, `write_text()`
    traduit « \n » en « \r\n » : un contenu déjà en CRLF (ce qu'exige la RFC 5545) ressortait en
    **CR CR LF**, illisible pour les agendas, et le build ne donnait pas le même résultat que sur le
    CI Linux. Le repliage à 75 octets (`ics_fold`) s'applique à TOUTES les lignes au moment de
    l'assemblage, pas champ par champ : un en-tête traduit y échappait.
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
  et pour `.retour` ça annulait la protection ci-dessus. Cinquième et sixième cas : `.seance`
  (grid) et `.jour` (block), masqués par les filtres de « Dernière chance » (`.chance-vide` a sa
  règle par avance, elle n'a pas encore de `display:`).
- **Cartes de partage (Open Graph)** : `open_graph()` est appelée par `page()`, donc TOUTES les
  pages en portent. Trois règles à ne pas défaire :
  - **`og:title` = le `h1`, pas le `<title>`.** Le titre SEO d'une fiche film (« Titre : séances
    près de chez vous — Séancéo ») fait un mauvais titre de partage ; le nom du site est déjà
    porté par `og:site_name`.
  - **Une fiche film partage SON AFFICHE** (URL TMDB déjà absolue, rien à générer) avec
    `og_portrait=True`, ce qui bascule la carte Twitter en `summary`. X est le seul réseau à
    cadrer d'après une balise : en `summary_large_image` il rogne une affiche 2:3 en bandeau
    horizontal qui coupe le titre. Les autres réseaux respectent le ratio réel.
  - **L'image par défaut existe en DEUX langues** (`static/og.png`, `og-en.png`), sinon un lien
    vers `/en/` s'annonce avec une accroche française sous un titre anglais. Elles sont
    produites par `make_icons.py` (hors pipeline, Pillow autorisé, sorties versionnées) et
    servies depuis la racine, jamais préfixées.
  - ⚠️ Les URLs d'`og:` vivent dans des attributs `content`, que `_prefix_links()` ne touche
    PAS (il ne voit que `href`/`src`) : elles doivent être **absolues dès l'écriture**.
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
- **L'onglet « Carte » a été retiré du header** (demande utilisateur, 2026-08-21), **mais la
  page `/carte/` existe toujours**, avec Leaflet, « Autour de moi » et le filtre répertoire, et
  elle reste dans le sitemap. ⚠️ Différence critique avec `/classiques/` ci-dessus : le classement
  gardait ~100 liens internes, la carte n'en garde que **DEUX** (`/salles-patrimoine/` et la 404).
  C'est le minimum vital pour rester indexée — **ne pas retirer ces deux liens** sans décider
  franchement de supprimer la page, sinon elle devient orpheline et sort de l'index toute seule.
  Si la suppression est un jour décidée : Cloudflare Pages sait faire une vraie 301 (fichier
  `_redirects`), ce que GitHub Pages ne permettait pas.
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
  - **⚠️ LES 4 FAVORIS NE SONT PLUS ALIMENTÉS DEPUIS LE 2026-08-16 : Letterboxd 403 la page de
    profil `letterboxd.com/<pseudo>/` depuis les IP datacenter de Cloudflare.** Le Worker ne va
    donc plus la chercher (voir la note en tête de `buildWatchlist` dans `worker/src/index.js`,
    qui porte le diagnostic complet et les chemins encore ouverts). Le front, lui, garde son code
    de rendu : `if (!favHits.length) return;` fait que la section `.lb-favs` n'est simplement pas
    rendue, sans bloc vide. **Les deux points ci-dessous décrivent donc du comportement DORMANT** ;
    ils restent écrits parce qu'ils redeviendraient vrais si la source rouvrait, et parce que la
    règle d'ordre de page vaut pour toute section non filtrée par ville qu'on ajouterait demain.
    Ne pas re-brancher la page de profil sans relire la note du Worker (ne PAS maquiller l'UA :
    le blocage est indépendant de l'UA).
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
  - **QUAND le portail d'accueil s'ouvre** (`letterboxd.js`, revu le 2026-08-22). Trois règles :
    visiteur **connecté** (`user`) → jamais, il n'y a plus rien à demander ; **refus horodaté**
    (`seen` + `seenAt`) → pas avant `REFUS_MS` (60 jours) ; sinon → on l'ouvre.
    - ⚠️ **Le clic à CÔTÉ de la carte ferme SANS marquer de refus** — c'est le seul des quatre
      gestes de fermeture qui peut être accidentel (viser un lien de la page et toucher le fond).
      La croix, « continuer sans compte » et Échap sont délibérés et marquent, eux. Avant cette
      révision un clic malheureux éteignait le portail **à vie**, et c'est exactement comme ça
      que l'utilisateur l'avait perdu sans s'en rendre compte.
    - ⚠️ **Un refus n'est plus définitif.** Il l'était jusqu'ici, alors que la programmation change
      chaque semaine : quelqu'un qui refuse un jour de presse ne revoyait plus jamais l'offre.
      60 jours = assez long pour ne pas harceler, assez court pour qu'un visiteur fidèle retombe
      dessus. Ne pas descendre ce seuil sans y penser à deux fois : un modal qui revient trop vite
      après un « non » est pire que pas de modal.
    - Un `seen` **sans** `seenAt` vient d'avant cette révision : on ne peut pas savoir quand il a
      été posé, et le tenir pour éternel reconduirait le défaut corrigé. Il est donc traité comme
      expiré (le portail se représente une fois, puis le refus est correctement daté).
    - Diagnostic à connaître : « la popup ne s'ouvre plus » n'est presque jamais un bug. Regarder
      `localStorage["seanceo.lb"]` AVANT de chercher ailleurs.
  - **⚠️ PIÈGE UTILISATEUR N°1 : nom affiché ≠ identifiant d'URL sur Letterboxd.** « Alex Her »
    à l'écran peut avoir `alexher__` dans son URL, et `alexher` est alors un AUTRE compte, réel
    mais vide. Le visiteur lisait « ta watchlist est vide » sans comprendre (constaté en vrai,
    2026-07-26 : `alexher` → 0 film, `alexher__` → 380). Ce n'est pas rattrapable côté code (les
    deux pseudos existent, tous deux valides). D'où le rappel `.lb-hint` sous les DEUX champs de
    saisie (portail `USER_HINT` + `/ma-watchlist/` dans build_site.py) et la relance dans le
    message « watchlist vide » — c'est là que la question se pose. Ne pas les retirer.
  - **Nommer la source dans les compteurs** : « 32 des 380 films de ta watchlist Letterboxd sont
    à l'affiche », pas « de tes 380 films à voir ». La page affichait aussi les favoris du profil
    juste au-dessus (dormant depuis le 2026-08-16, voir plus haut) : sans le mot « watchlist », on
    ne sait pas ce qui a été compté.
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
