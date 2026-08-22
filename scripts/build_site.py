"""Générateur de site statique Séancéo.

Lit les JSON produits par fetch_data.py et écrit le site complet dans `site/` :
accueil, une page par ville, par cinéma et par film, sitemap.xml, robots.txt.

SITE BILINGUE. Le build tourne DEUX FOIS, une par langue (`i18n.LANGS`) : le
français à la racine, l'anglais sous `/en/`. Chaque page anglaise a donc sa
propre URL indexable, et les deux versions se déclarent l'une l'autre en
`hreflang` — c'est la seule forme que Google traite comme deux pages
équivalentes plutôt que comme du contenu dupliqué.

Les SLUGS restent français dans les deux langues (`/en/film/mon-oncle/`) :
ils sont calculés une seule fois, avant la boucle, à partir des titres
français. Deux jeux de slugs auraient fait diverger les deux arbres à chaque
changement de titre TMDB, pour un gain SEO marginal.

Usage :  python scripts/build_site.py
Aucune dépendance externe (stdlib uniquement).
"""

import base64
import hashlib
import html
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime  # dates RFC 822 des flux RSS
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, decalage_paris  # même slugification, même fuseau
from sources import load_merged, _fold_title  # fusion indés + chaînes
from marathon import build_ideas  # doubles programmes par ville
import repertoire  # reprises, cycles, séances uniques, salles de patrimoine
import i18n  # traduction FR/EN ; `i18n.LANG` porte la langue du build en cours
from i18n import (t, tf, plural, nombre, date_label, jour_mois, jour_date, heure,
                  decimal, localize_movies, lang_prefix, cinema_kind_label, LANGS)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
ASSETS = ROOT / "assets"

# Hébergement Cloudflare Pages : le site vit à la RACINE de son sous-domaine,
# d'où BASE_PATH vide (avant, GitHub Pages le servait sous /seanceo).
# Quand le domaine seanceo.fr sera branché : seul BASE_URL change.
BASE_PATH = ""
BASE_URL = f"https://seanceo.pages.dev{BASE_PATH}"
SITE_NAME = "Séancéo"

# Open Graph attend une locale complète (langue_PAYS), pas le code court du
# <html lang>. Table à part pour que l'ajout d'une langue ne se traduise pas
# par une locale inventée à la volée.
OG_LOCALES = {"fr": "fr_FR", "en": "en_US"}

# Site frère dédié à Paris (« Paris Ciné Aujourd'hui ») : plus complet que
# Séancéo pour la capitale au quotidien — il liste TOUT ce qui passe à Paris,
# pas seulement le répertoire. On y renvoie depuis les pages parisiennes
# uniquement (ville de Paris + fiches des cinémas parisiens) : ailleurs en
# France l'encadré n'aurait aucun sens.
PARIS_CINE_URL = "https://paris-cine-pages.pages.dev/"

CITY_WINDOW_DAYS = 7     # séances affichées sur une page ville
CINEMA_WINDOW_DAYS = 14  # séances affichées sur une page cinéma

# Un film sorti il y a au moins N ans et pourtant à l'affiche = une reprise :
# rétrospective, version restaurée, ciné-club. Mise en avant éditoriale du site.
CLASSIC_AGE_YEARS = 20
TODAY = date.today()

# Fiche film : les 10 plus grandes villes de France en accès direct dans le
# sommaire des séances ; les autres passent par la recherche.
BIG_CITY_SLUGS = ("paris", "marseille", "lyon", "toulouse", "nice",
                  "nantes", "montpellier", "strasbourg", "bordeaux", "lille")

# Posé dans le <head> (donc avant le rendu du corps : pas de clignotement).
# Le CSS ne masque les sections ville que si cette classe est présente —
# sans JavaScript la recherche serait inopérante, tout doit rester affiché.
JS_FLAG = '<script>document.documentElement.classList.add("js")</script>'

# Traduction côté navigateur. `T()` est défini EN LIGNE dans le <head> de toutes
# les pages (60 octets) et vaut l'identité tant que `window.I18N` est absent :
# une page française ne télécharge donc aucun dictionnaire, et un script qui
# oublie de traduire une chaîne affiche du français, pas une clé brute.
# Le dictionnaire lui-même n'est chargé que sur les pages anglaises.
#
# `PL(n)` accompagne `T`/`TF` : le « s » du pluriel ne se coupe pas au même
# endroit dans les deux langues (français « 1 film », « 0 film » ; anglais
# « 1 film », « 0 films »). Il lit la langue sur <html lang>, seule source de
# vérité côté navigateur.
T_HELPER = ('<script>window.T=function(s){var d=window.I18N;'
            'return(d&&d[s])||s},window.TF=function(s,v){'
            'return window.T(s).replace(/\\{(\\w+)\\}/g,function(m,k){'
            'return k in v?v[k]:m})},window.PL=function(n){'
            'return document.documentElement.lang==="fr"?(n>1?"s":""):'
            '(n===1?"":"s")}</script>')
I18N_JS = '<script src="/assets/i18n.js" defer></script>'

# Origine du Worker watchlist. Répétée dans assets/letterboxd.js et static/sw.js
# (ni l'un ni l'autre ne passe par le gabarit) ; elle est ici parce que la CSP
# doit l'autoriser en `connect-src`, sans quoi la watchlist par pseudo échoue.
WORKER_ORIGIN = "https://seanceo-watchlist.keenzzz.workers.dev"


def csp_hash(balise: str) -> str:
    """Empreinte CSP d'un `<script>…</script>` écrit en dur dans le gabarit.

    Un site statique ne peut pas utiliser de `nonce` : celui-ci doit changer à
    CHAQUE réponse, or nos pages sont des fichiers servis tels quels. Le hash
    est l'autre mécanisme prévu par la spec, et il convient parfaitement à du
    contenu figé au build.

    ⚠️ Calculé sur le CONTENU RÉEL de la balise, jamais recopié à la main : le
    hash porte sur les octets exacts, donc un espace ajouté dans JS_FLAG ou
    T_HELPER suffirait à faire rejeter le script par le navigateur. Le dériver
    du code garantit qu'ils ne peuvent pas diverger.
    """
    corps = re.search(r"<script>(.*)</script>", balise, re.S).group(1)
    digest = hashlib.sha256(corps.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def csp_headers() -> str:
    """Contenu du fichier `_headers`, lu par Cloudflare Pages au déploiement.

    GitHub Pages ne permettait aucun en-tête ; Cloudflare oui, d'où cette
    politique posée après la migration (2026-08-22).

    Deux assouplissements ASSUMÉS, à ne pas retirer sans lire ces raisons :

    - `style-src 'unsafe-inline'` : les jauges de « Salles de patrimoine »
      portent un `style="width:NN%"`, une valeur qui vient des données et ne
      peut donc pas vivre dans la feuille de style. La seule alternative serait
      une centaine de classes de largeur. Le risque est faible : tout contenu
      externe passe déjà par `html.escape()`, et une injection CSS suppose une
      injection HTML que `script-src` bloquerait de toute façon.

    - `img-src https:` plutôt qu'une liste de domaines : les affiches viennent
      de TMDB ET du CDN de chaque chaîne (8 domaines observés le 2026-08-22 :
      image.tmdb.org, cinemedia.cine.digital, images.monnaie-services.com,
      all.web.img.acsta.net, media.pathe.fr…). Cette liste vient des DONNÉES :
      une salle qui change d'hébergeur d'affiches en ajouterait un du jour au
      lendemain, et une liste blanche ferait alors disparaître des affiches en
      silence, sans que rien ne le signale. On garde donc `https:` (qui interdit
      quand même le `http:` et le contenu mixte). Une image ne s'exécute pas :
      l'essentiel de la protection est dans `script-src`, qui reste strict.

    Le reste est verrouillé : pas de script tiers, `object-src 'none'`, pas
    d'encadrement possible du site (`frame-ancestors`), et `connect-src` limité
    au site plus le Worker watchlist.
    """
    scripts = " ".join(csp_hash(b) for b in (JS_FLAG, T_HELPER))
    csp = "; ".join([
        "default-src 'self'",
        f"script-src 'self' {scripts}",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        f"connect-src 'self' {WORKER_ORIGIN}",
        "font-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "frame-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])
    # `geolocation=(self)` : « Autour de moi » (carte et accueil) en a besoin.
    # Tout le reste est refusé — le site n'a aucune raison de demander la
    # caméra, le micro ou un moyen de paiement.
    return (f"/*\n"
            f"  Content-Security-Policy: {csp}\n"
            f"  X-Frame-Options: DENY\n"
            f"  Permissions-Policy: geolocation=(self), camera=(), microphone=(), payment=()\n")

# Chemins servis À L'IDENTIQUE aux deux langues : ils ne prennent jamais le
# préfixe /en. Dupliquer une feuille de style ou une icône par langue ferait
# tout retélécharger au visiteur qui bascule, pour un fichier au contenu
# rigoureusement identique. Le manifeste, lui, N'EST PAS ici : son `name`, sa
# `description`, son `lang` et son `start_url` changent avec la langue.
SHARED_PATHS = ("/assets/", "/favicon.png", "/apple-touch-icon.png", "/icon-",
                "/sw.js", "/film-directors.json", "/cinematheque-directors.json")

# Marque un href/src DÉJÀ complet (BASE_PATH et langue inclus) : _prefix_links()
# la retire sans rien préfixer. Sert au sélecteur de langue, seul lien du site
# qui pointe volontairement vers l'AUTRE arbre de langue.
RAW = "@@"

# Index de recherche : un fichier à part, chargé à la première frappe et pas
# à chaque page. 931 films injectés dans chaque page pèseraient ~90 ko inutiles.
SEARCH_INDEX = "/recherche.json"

# Combien de cartes une liste triable affiche avant « Afficher plus » (tri.js).
PAGE_SIZE = 40

# Articles ignorés pour le tri alphabétique : « Le Bon, la Brute… » se range
# à B, pas à L — c'est l'usage des catalogues de cinéma et de bibliothèque.
# Comparés à la sortie de _fold_title(), où l'apostrophe est déjà une espace
# (« L'Odyssée » → « l odyssee ») : d'où le « l » seul dans la liste.
LEADING_ARTICLES = ("le", "la", "les", "l", "un", "une", "des", "the", "a", "an")

# Renseignés par main() avant tout appel à movie_card() : servent aux
# attributs data-* sur lesquels tri.js trie et filtre côté client.
MOVIE_VERSIONS: dict[str, set[str]] = {}
MOVIE_VENUES: dict[str, int] = {}

def film_search() -> str:
    """Recherche de film, présente dans le header de toutes les pages.

    `data-index` porte le chemin complet (BASE_PATH ET langue inclus) : page()
    ne préfixe que les attributs href/src, un data-* lui échapperait. L'index
    anglais est un fichier distinct — il porte les titres anglais et des URLs
    en /en/, chercher « Mr. Hulot's Holiday » depuis la version anglaise doit
    marcher.
    """
    return f"""<div class="film-search">
<input id="film-search" type="search" autocomplete="off"
data-index="{BASE_PATH}{lang_prefix()}{SEARCH_INDEX}"
placeholder="{esc(t("Chercher un film ou un réalisateur…"))}"
aria-label="{esc(t("Chercher un film ou un réalisateur"))}">
<ul id="film-suggest" hidden></ul>
</div>
<script src="/assets/search.js" defer></script>"""

# Alertes « préviens-moi quand ce film repasse ». Chargé par head_extra sur les
# seules pages qui s'en servent (fiche film, /mes-alertes/) plutôt que dans
# page() : inutile de le faire télécharger sur les 1 500 autres pages.
# Il lit l'URL du Worker dans window.LB (lb-core), on ne la répète pas ici.
ALERTES_JS = '<script src="/assets/alertes.js" defer></script>'

# --- Navigation ------------------------------------------------------------
# L'ordre EST une priorité : sur mobile la barre défile horizontalement, et les
# deux premières places sont les seules vues sans faire le moindre geste.
# La watchlist y reste donc en tête — c'est la fonction phare du site, celle
# qu'on veut voir sans avoir à faire défiler la barre.
# Libellé raccourci : « Ma watchlist letterboxd » faisait 192 px à lui seul et
# provoquait une ligne orpheline sur mobile. L'anneau vert (.nav-wl) dit déjà
# Letterboxd, le mot était redondant.
# Un emoji par entrée, et surtout UN SEUL SENS PAR EMOJI — même discipline que
# les couleurs : 🎞️ servait à la fois à la cinémathèque et aux rétrospectives,
# il ne distinguait donc rien. La cinémathèque prend 🏛️.
NAV_ITEMS = [
    ("/ma-watchlist/",   "Watchlist",          "nav-wl"),
    ("/derniere-chance/", "⏳ Dernière chance", ""),
    ("/a-l-affiche/",    "🎬 À l'affiche",     ""),
    ("/retrospectives/", "🎞️ Rétrospectives",  ""),
    ("/marathon/",       "🍿 Marathons",       ""),
    ("/cinematheque/",   "🏛️ Ma cinémathèque", ""),
]
# ⚠️ « 🗺️ Carte » a été retiré du menu le 2026-08-21 (demande utilisateur), mais
# **la page `/carte/` existe toujours** et reste dans le sitemap — même choix que
# pour « 🏆 Le classement » avant elle. Différence importante : le classement
# gardait une centaine de liens internes, la carte n'en garde que DEUX
# (`/salles-patrimoine/` et la 404). C'est peu pour rester indexée : ne pas
# retirer ces liens-là sans la supprimer franchement, sinon la page devient
# orpheline et Google finit par la sortir de l'index sans qu'on l'ait décidé.


def site_nav(current: str) -> str:
    """Barre de navigation du header.

    `current` est le chemin de la page en cours de génération : on s'en sert
    pour poser `aria-current="page"` sur l'entrée active. C'est l'attribut
    standard qui dit « vous êtes ici » — double bénéfice, les lecteurs d'écran
    l'annoncent ET on peut le styler via `a[aria-current="page"]`, donc pas
    besoin d'une classe `.active` en plus.

    ⚠️ BASE_PATH : on écrit bien `href="/…` (slash en premier), c'est ce motif
    exact que page() préfixe ensuite. `aria-current` est placé APRÈS le href
    pour ne pas s'intercaler dans ce remplacement.
    """
    liens = []
    for href, label, cls in NAV_ITEMS:
        c = f' class="{cls}"' if cls else ""
        cur = ' aria-current="page"' if current == href else ""
        liens.append(f'<a{c} href="{href}"{cur}>{t(label)}</a>')
    return (f'<nav class="site-nav" aria-label="{esc(t("Sections du site"))}">'
            f'{"".join(liens)}</nav>')


def lang_switch(path: str) -> str:
    """Sélecteur de langue du header : un lien par langue, vers LA MÊME page.

    Les slugs étant communs aux deux arbres, la contrepartie d'une page est
    toujours son chemin préfixé — aucune table de correspondance à tenir, donc
    aucun lien de bascule ne peut pointer vers une page inexistante.

    Les href sont écrits COMPLETS (marqués `RAW`) : ce sont les seuls liens du
    site qui visent délibérément l'autre langue, le préfixage automatique de
    page() les enverrait sinon sur /en/en/.

    `hreflang` sur chaque lien et `aria-current` sur la langue affichée : c'est
    ce couple qui fait comprendre le sélecteur à un lecteur d'écran.
    """
    liens = []
    for lang, court, titre in (("fr", "FR", "Version française"),
                               ("en", "EN", "Version anglaise")):
        cible = f"{RAW}{BASE_PATH}{lang_prefix(lang)}{path}"
        actif = ' aria-current="true"' if lang == i18n.LANG else ""
        liens.append(f'<a href="{cible}" hreflang="{lang}" lang="{lang}"'
                     f' title="{esc(t(titre))}" data-lang="{lang}"{actif}>{court}</a>')
    return (f'<nav class="lang-switch" aria-label="{esc(t("Langue"))}">'
            f'{"".join(liens)}</nav>')


# Les noms de jours et de mois, le format d'heure, le séparateur de milliers et
# le « s » du pluriel vivent dans i18n.py : ils ne changent pas seulement de
# mots d'une langue à l'autre, mais de RÈGLE (« 20h30 » vs « 8:30 pm »,
# « 0 film » vs « 0 films »). Voir date_label(), heure(), nombre(), plural().


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# --- Gabarit commun -------------------------------------------------------

_LINK_RE = re.compile(r'\b(href|src)="(/[^"]*)"')


def _prefix_links(doc: str) -> str:
    """Préfixe les URLs internes absolues : sous-chemin d'hébergement + langue.

    Remplace l'ancien double `.replace('href="/', …)`. Un simple remplacement
    de texte ne suffit plus dès lors que le préfixe dépend de la CIBLE du lien :
    une page part sous `/seanceo/en/`, mais la feuille de style reste sur
    `/seanceo/assets/` (voir SHARED_PATHS).

    Ne touche ni aux liens externes (`https://…`, qui ne commencent pas par
    `/`), ni aux ancres (`#…`), ni au canonical (URL absolue), ni aux `data-*`
    (qui portent déjà leur préfixe à la main). Les href marqués `RAW` sont
    laissés tels quels, débarrassés de leur marque.
    """
    prefixe = f"{BASE_PATH}{lang_prefix()}"

    def sub(m: re.Match) -> str:
        attr, url = m.group(1), m.group(2)
        base = BASE_PATH if url.startswith(SHARED_PATHS) else prefixe
        return f'{attr}="{base}{url}"'

    return _LINK_RE.sub(sub, doc).replace(f'="{RAW}', '="')


def alternates(path: str) -> str:
    """Balises `hreflang` : les deux versions d'une page se déclarent l'une
    l'autre, et `x-default` désigne le français.

    C'est ce qui distingue « deux traductions de la même page » de « deux pages
    au contenu dupliqué » pour un moteur de recherche. La déclaration doit être
    RÉCIPROQUE et porter des URLs absolues, sinon Google l'ignore en silence —
    d'où sa génération en un seul endroit plutôt qu'au cas par cas.
    """
    liens = [f'<link rel="alternate" hreflang="{lang}" '
             f'href="{BASE_URL}{lang_prefix(lang)}{path}">' for lang in LANGS]
    liens.append(f'<link rel="alternate" hreflang="x-default" href="{BASE_URL}{path}">')
    return "\n".join(liens)

def open_graph(title: str, description: str, path: str,
               image: str = "", image_alt: str = "", portrait: bool = False) -> str:
    """Balises de partage (Open Graph + Twitter) : le titre, le texte et
    l'image affichés quand un lien du site est collé dans WhatsApp, Discord,
    Bluesky, Slack ou un forum.

    Sans elles, un lien s'affiche en URL nue — c'est-à-dire que la moitié des
    fonctions du site (la watchlist croisée, une rétrospective composée, une
    séance unique repérée) circulait sans rien dire de ce qu'elle montre.

    `image` : URL ABSOLUE. Les réseaux ne résolvent pas les chemins relatifs,
    et `_prefix_links()` ne touche de toute façon qu'aux attributs href/src,
    pas aux `content` — l'URL doit donc être complète dès ici. Par défaut, la
    carte de marque de `static/` (voir make_icons.py), déclinée par langue.

    `portrait` : l'image est une affiche de film (ratio 2:3). Twitter/X est le
    seul réseau à choisir son cadrage d'après une balise : en
    `summary_large_image` il rogne une affiche en une bande horizontale qui
    coupe têtes et titre. On lui demande alors la vignette `summary`, où
    l'affiche reste entière. Les autres réseaux respectent le ratio réel.
    """
    if not image:
        suffixe = "" if i18n.LANG == "fr" else f"-{i18n.LANG}"
        image = f"{BASE_URL}/og{suffixe}.png"
        image_alt = image_alt or t("Le répertoire en salle, partout en France")
    autres = [l for l in LANGS if l != i18n.LANG]
    balises = [
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(description)}">',
        f'<meta property="og:url" content="{BASE_URL}{lang_prefix()}{path}">',
        f'<meta property="og:image" content="{esc(image)}">',
        f'<meta property="og:locale" content="{esc(OG_LOCALES[i18n.LANG])}">',
    ]
    balises += [f'<meta property="og:locale:alternate" content="{esc(OG_LOCALES[l])}">'
                for l in autres]
    if image_alt:
        balises.append(f'<meta property="og:image:alt" content="{esc(image_alt)}">')
    balises.append('<meta name="twitter:card" content="'
                   + ("summary" if portrait else "summary_large_image") + '">')
    return "\n".join(balises)


def page(title: str, description: str, body: str, path: str,
         jsonld: dict | None = None, h1: str | None = None,
         head_extra: str = "", top_link: bool = False,
         og_image: str = "", og_image_alt: str = "",
         og_portrait: bool = False) -> str:
    """Enveloppe une page : head SEO complet + header/footer communs.
    `head_extra` : balises à ajouter dans le <head> (ex. CSS Leaflet de la carte).
    `top_link` : bouton flottant « retour en haut » pour les gabarits longs.
    `og_image` / `og_portrait` : image de partage propre à la page (l'affiche,
    sur une fiche film) — voir open_graph()."""
    ld = (f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'
          if jsonld else "")
    top = ('\n<a class="top-link" href="#" '
           f'aria-label="{esc(t("Retour en haut de page"))}">{t("↑ Haut")}</a>'
           if top_link else "")
    # Dictionnaire de traduction des scripts : chargé sur les seules pages
    # anglaises. Une page francaise n'en telecharge pas un octet, T() y valant
    # l'identite (voir T_HELPER).
    dico = I18N_JS if i18n.LANG != "fr" else ""
    doc = f"""<!DOCTYPE html>
<html lang="{i18n.LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{BASE_URL}{lang_prefix()}{path}">
{alternates(path)}
{open_graph(h1 if h1 is not None else title, description, path,
            og_image, og_image_alt, og_portrait)}
<link rel="stylesheet" href="/assets/style.css">
<link rel="icon" href="/favicon.png" type="image/png">
<meta name="theme-color" content="#0d1014">
<link rel="manifest" href="/manifest.webmanifest">
<!-- iOS ne lit pas le manifeste pour l'icône d'écran d'accueil : il lui faut
     apple-touch-icon. Sans elle, l'iPhone met une capture de la page. -->
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
{JS_FLAG}
{T_HELPER}
{dico}
<script src="/assets/nav.js" defer></script>
<script id="lb-core" src="/assets/letterboxd.js" data-index="{BASE_PATH}{lang_prefix()}/watchlist-index.json" defer></script>
{head_extra}
{ld}
</head>
<body>
<header class="site-header">
<a class="brand" href="/">🎬 {SITE_NAME}</a>
<p class="tagline">{esc(t("Le répertoire en salle, partout en France"))}</p>
{film_search()}
{site_nav(path)}
{lang_switch(path)}
</header>
<main>
<a class="retour" id="retour" href="#" hidden>{esc(t("← Retour"))}</a>
<h1>{esc(h1 if h1 is not None else title)}</h1>
{body}
</main>{top}
<footer>
<p>{t("Données de programmation :")} <a href="https://datacinesindes.fr" rel="noopener">Data Ciné Indés / SCARE</a>
{t("(Syndicat des Cinémas d'Art, de Répertoire et d'Essai), sous Licence Ouverte 2.0.")}</p>
<p>{tf("{site} réunit les séances des cinémas indépendants et des grandes enseignes, et met en avant les salles Art &amp; Essai.", site=SITE_NAME)}</p>
<p>{t("Fiches films (titres, notes, affiches, synopsis) enrichies via")}
<a href="https://www.themoviedb.org/" rel="noopener">TMDB</a>.
{t("Ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB.")}</p>
</footer>
</body>
</html>"""
    return _prefix_links(doc)


def lang_dir() -> Path:
    """Racine sur le disque de la langue en cours : `site/` ou `site/en/`."""
    return SITE / lang_prefix().strip("/") if lang_prefix() else SITE


def write(path: str, content: str) -> None:
    """path est le chemin URL (« /ville/tours/ »), SANS le segment de langue :
    écrit site/ville/tours/index.html en français, site/en/ville/tours/index.html
    en anglais. Les appelants n'ont donc pas à savoir dans quelle langue ils
    tournent — un oubli de préfixe est impossible."""
    racine = lang_dir()
    target = racine / path.strip("/") / "index.html" if path != "/" else racine / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def write_raw(path: str, content: str) -> None:
    """Écrit un fichier NON HTML à une URL précise de la langue courante
    (`/ville/tours/repertoire.ics`). `write()` ajouterait un `index.html`.

    ⚠️ ÉCRITURE EN OCTETS, jamais `write_text()`. Sur Windows, celui-ci
    traduit chaque « \\n » en « \\r\\n » : un contenu déjà en CRLF (ce qu'exige
    la RFC 5545 pour un .ics) ressortait en **CR CR LF**, illisible pour les
    agendas — et le build ne donnait pas le même résultat que sur le CI Linux.
    Le contenu porte déjà les fins de ligne voulues, on le pose tel quel.
    """
    cible = lang_dir() / path.strip("/")
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(content.encode("utf-8"))


# --- Abonnements par ville (.ics et RSS) ----------------------------------
#
# Un fichier .ics servi à une URL FIXE et réécrit à chaque build est un vrai
# abonnement : Google Agenda, Apple Calendrier et Outlook re-téléchargent
# périodiquement l'adresse à laquelle on les a abonnés. Le répertoire de sa
# ville arrive donc tout seul dans l'agenda du visiteur, chaque semaine, sans
# qu'il ait à revenir sur le site — et sans le moindre serveur, ce qui serait
# impossible avec un système de comptes ou de notifications.
#
# ⚠️ LE FLUX EXISTE POUR TOUTES LES VILLES, MÊME VIDES. C'est tout l'intérêt :
# une ville sans reprise cette semaine en aura une le mois prochain, et
# l'abonné doit la recevoir. Ne générer que les villes non vides ferait
# disparaître l'URL dès la première semaine creuse, et les agendas qui
# reçoivent un 404 finissent par se désabonner d'eux-mêmes.

def ics_escape(texte: str) -> str:
    """Échappement iCalendar (RFC 5545) : la virgule et le point-virgule y
    séparent des champs. Même règle que `esc()` dans assets/ics.js."""
    return (str(texte).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def ics_fold(ligne: str) -> str:
    """Replie une ligne à 75 octets, comme l'exige la RFC : les lignes
    suivantes commencent par une espace. Un titre long non replié fait rejeter
    l'événement par certains clients."""
    brut = ligne.encode("utf-8")
    if len(brut) <= 75:
        return ligne
    morceaux, courant = [], b""
    for ch in ligne:
        octets = ch.encode("utf-8")
        # 74 : on garde la place de l'espace de continuation.
        if len(courant) + len(octets) > (75 if not morceaux else 74):
            morceaux.append(courant.decode("utf-8"))
            courant = b""
        courant += octets
    morceaux.append(courant.decode("utf-8"))
    return "\r\n ".join(morceaux)


def abonnement_bloc(slug: str, ville: str) -> str:
    """Encadré d'abonnement en bas d'une page ville.

    Trois portes pour un même contenu : `webcal://` (abonnement qui se met à
    jour tout seul), le `.ics` en téléchargement (instantané figé, pour qui
    préfère), et le flux RSS. Le lien webcal est écrit en ABSOLU et sans `/`
    initial, donc `_prefix_links()` ne le touche pas ; les deux autres sont
    des chemins internes normaux, préfixés automatiquement.
    """
    hote = BASE_URL.split("://", 1)[1]
    webcal = f"webcal://{hote}{lang_prefix()}/ville/{slug}/repertoire.ics"
    return f"""<div class="abo">
<p class="abo-titre">{tf("📅 Recevoir le répertoire de {ville}", ville=esc(ville))}</p>
<p class="meta">{tf("Les reprises et rétrospectives programmées à {ville} arrivent dans "
                    "votre agenda, et s'y mettent à jour toutes seules chaque nuit. Pas "
                    "de compte à créer, pas d'adresse e-mail à donner.", ville=esc(ville))}</p>
<p class="abo-liens">
<a class="bouton" href="{webcal}">{t("S'abonner dans mon agenda")}</a>
<a href="/ville/{slug}/repertoire.ics">{t("Télécharger le .ics")}</a>
<a href="/ville/{slug}/repertoire.xml">{t("Flux RSS")}</a>
</p>
</div>"""


def write_data(name: str, payload) -> None:
    """Écrit un index JSON dans la racine de la langue courante (recherche,
    watchlist, agenda) : il porte des titres et des URLs, il est donc propre à
    une langue. Les index qui ne portent que des noms de personnes restent à la
    racine du site, partagés (voir SHARED_PATHS)."""
    cible = lang_dir() / name
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")


# --- Fragments réutilisés -------------------------------------------------

def chain_badge(cinema: dict) -> str:
    """Pastille distinguant un cinéma de chaîne d'un indépendant. Les indés
    (signature du site) portent le point rouge ; les chaînes leur nom."""
    chain = cinema.get("chain")
    if chain:
        return f' <span class="badge badge-chain">{esc(chain)}</span>'
    return (f' <span class="badge badge-inde" title="{esc(t("Cinéma indépendant"))}">'
            f'{t("Indé")}</span>')


def is_classic(movie: dict) -> bool:
    """Vrai si le film est une reprise : année de sortie connue (via TMDB) et
    vieille d'au moins CLASSIC_AGE_YEARS ans. Sans année fiable, on s'abstient."""
    year = movie.get("year")
    return bool(year) and year <= TODAY.year - CLASSIC_AGE_YEARS


def classic_badge(movie: dict) -> str:
    return (f' <span class="badge badge-classic">{t("Classique")}</span>'
            if is_classic(movie) else "")


# Un film « fête ses N ans » quand son âge tombe sur un cap rond : multiple de
# 10 (au moins 20 ans, sinon ce n'est pas un anniversaire de patrimoine) ou un
# quart de siècle marquant (25, 75). Calé sur l'année TMDB, comme is_classic.
ANNIV_MIN_AGE = 20


def anniversaire_age(movie: dict) -> int | None:
    """Âge du film cette année s'il tombe sur un cap rond, sinon None."""
    year = movie.get("year")
    if not year:
        return None
    age = TODAY.year - year
    if age >= ANNIV_MIN_AGE and (age % 10 == 0 or age in (25, 75)):
        return age
    return None


def anniversaire_texte(age: int) -> str:
    """Formulation d'un anniversaire ; le centenaire a droit à sa tournure
    (« fête son siècle » / « turns one hundred »), les autres à un gabarit."""
    return t("fête son siècle") if age == 100 else tf("fête ses {age} ans", age=age)


def anniversaire_badge(movie: dict) -> str:
    """Pastille « 🎂 N ans » posée à côté du badge Classique. Le titre complet
    (année de sortie → anniversaire) est dans l'attribut `title`, la pastille
    reste courte pour ne pas encombrer la carte."""
    age = anniversaire_age(movie)
    if not age:
        return ""
    libelle = t("100 ans") if age == 100 else tf("{age} ans", age=age)
    titre = tf("Sorti en {annee}, {celebration} en {cette_annee}",
               annee=movie["year"], celebration=anniversaire_texte(age),
               cette_annee=TODAY.year)
    return (f' <span class="badge badge-anniv" title="{esc(titre)}">'
            f'🎂 {esc(libelle)}</span>')


def version_label(version: str) -> str:
    """Version de projection affichée sur une pastille d'horaire.

    « VF », « VO », « VOST » sont des sigles que tout spectateur français lit
    d'un coup d'œil et qu'un anglophone ne peut pas deviner — or c'est
    exactement l'information dont il a le plus besoin ici : savoir si le film
    est doublé en français ou projeté en version originale. On les développe
    donc en anglais, en restant assez court pour une pastille.
    """
    return t(version) if version else ""


def showtime_pills(shows: list[dict]) -> str:
    """Horaires d'un film dans une salle. Une séance dont la source donne un
    lien de billetterie devient cliquable et mène directement à la réservation ;
    les autres restent des chips informatives. Les deux styles se distinguent
    (`.reservable`) : promettre un clic qui n'existe pas est le défaut qu'on
    avait justement corrigé en neutralisant ces pastilles."""
    pills = []
    for s in sorted(shows, key=lambda x: x["start"]):
        # `hh` et pas `t` : `t` est la fonction de traduction importée depuis
        # i18n, une variable locale du même nom la masquerait dans toute la
        # boucle — et le titre de la pastille ci-dessous en a justement besoin.
        hh = heure(s["start"])
        v = f' <span class="v">{esc(version_label(s["version"]))}</span>' if s["version"] else ""
        # .get() : les snapshots de chaînes collectés avant l'ajout du champ
        # n'ont pas de clé « booking » — ils doivent rester affichables.
        url = s.get("booking")
        if url:
            titre = tf("Réserver la séance de {heure} sur la billetterie du cinéma"
                       " (nouvel onglet)", heure=hh)
            pills.append(
                f'<li class="reservable"><a href="{esc(url)}" target="_blank"'
                f' rel="noopener noreferrer"'
                f' title="{esc(titre)}">{hh}{v}</a></li>')
        else:
            pills.append(f'<li>{hh}{v}</li>')
    return f'<ul class="showtimes">{"".join(pills)}</ul>'


def lb_slug_key(slug_or_title: str) -> str:
    """Empreinte comparable d'un slug/titre Letterboxd : minuscules, sans
    accents, caractères non alphanumériques SUPPRIMÉS (collés).

    C'est la clé de croisement avec la watchlist. Le slug Letterboxd et le
    « Name » du CSV d'export viennent tous deux du même titre principal
    Letterboxd (souvent l'anglais international) : « Shoplifters » et son slug
    « shoplifters » retombent donc sur la même empreinte, alors même que NOTRE
    titre est « Une Affaire de famille ». Le matching traverse ainsi les langues.
    watchlist.js applique EXACTEMENT la même normalisation côté client."""
    import unicodedata as _u
    s = _u.normalize("NFKD", slug_or_title or "").encode("ascii", "ignore").decode("ascii")
    return "".join(c for c in s.lower() if c.isalnum())


def sort_title(title: str) -> str:
    """Clé de tri alphabétique d'un titre : sans accents ni ponctuation, et
    sans l'article initial (« Le Bon, la Brute… » se range à B). Calculée ici
    plutôt qu'en JavaScript pour que le tri soit identique partout."""
    folded = _fold_title(title)
    head, _, rest = folded.partition(" ")
    return rest if rest and head in LEADING_ARTICLES else folded


def genre_parts(movie: dict) -> list[str]:
    """Genres INDIVIDUELS d'un film, dans leur graphie d'origine.
    Le champ `genre` est une liste jointe (« Comédie, Drame ») ; le filtre par
    genre travaille sur chaque genre séparément, pas sur la combinaison."""
    return [p.strip() for p in (movie.get("genre") or "").split(",") if p.strip()]


def genre_slug(name: str) -> str:
    """Slug d'un genre pour l'attribut data-* et la valeur d'option (« Science-
    Fiction » -> « sciencefiction »). Même normalisation que les clés LB."""
    return lb_slug_key(name)


def card_attrs(movie: dict, versions: set | None = None) -> str:
    """Attributs data-* lus par tri.js pour trier et filtrer sans recharger.
    Toujours posés : une carte sait se classer quelle que soit la page qui
    l'affiche. Les valeurs absentes valent 0 (elles finissent en queue de tri).
    `data-v` liste les versions du film (« vf vo ») pour le filtre VF/VO ;
    `data-genres` liste les genres slugifiés ; `data-country` (vide tant que le
    cache TMDB ne porte pas le pays) sert au filtre pays une fois enrichi.
    `versions` : ensemble de versions à poser sur `data-v` À LA PLACE des
    versions nationales — la page ville s'en sert pour que le filtre langue
    reflète les séances DE CETTE VILLE, pas de la France entière."""
    key = movie["key"]
    vers = versions if versions is not None else MOVIE_VERSIONS.get(key, ())
    versions = " ".join(sorted(vers))
    genres = " ".join(genre_slug(g) for g in genre_parts(movie))
    return (f' data-title="{esc(sort_title(movie["title"]))}"'
            f' data-lb="{movie.get("lb_rating") or 0}"'
            f' data-year="{movie.get("year") or 0}"'
            f' data-venues="{MOVIE_VENUES.get(key, 0)}"'
            f' data-v="{esc(versions)}"'
            f' data-genres="{esc(genres)}"'
            f' data-country="{esc(genre_slug(movie.get("country_tmdb") or ""))}"')


def paris_cine_bridge() -> str:
    """Passerelle vers le site frère « Paris Ciné Aujourd'hui ».
    Lien EXTERNE : nouvel onglet (garde Séancéo ouvert) + rel de sécurité, et
    flèche ↗ pour annoncer la sortie du site, comme les liens de billetterie.
    Placée en bas des pages parisiennes : le visiteur a d'abord vu ce que
    Séancéo propose, on lui signale ensuite l'outil plus complet pour Paris."""
    return f"""<div class="passerelle">
<p><span class="titre">{t("Vous êtes à Paris ?")}</span>
<span class="meta">{t("Pour la capitale, Paris Ciné Aujourd'hui recense tout plus "
                      "efficacement. C'est un hub dédié à Paris : films à l'affiche, "
                      "rétrospectives, séances de plein air de cet été, carte des cinémas "
                      "et idées de marathon. Uniquement pour Paris.")}</span></p>
<a class="bouton" href="{PARIS_CINE_URL}" target="_blank" rel="noopener noreferrer">{t("Ouvrir Paris Ciné ↗")}</a>
</div>"""


def affiche_alt(movie: dict) -> str:
    """Texte alternatif d'une affiche. Il n'existe QUE pour les lecteurs
    d'écran et les images cassées : il doit donc être dans la langue de la
    page, comme le reste, et pas figé en français."""
    return tf("Affiche de {titre}", titre=movie["title"])


def note_lb(movie: dict) -> str:
    """Note Letterboxd d'un film, en vert — la couleur qui lui est réservée.

    UNE SEULE ÉCHELLE SUR TOUT LE SITE : /5, celle de Letterboxd. Les notes
    TMDB (/10) ont été retirées de l'affichage — deux échelles côte à côte
    faisaient lire « 7.9 » et « 4.4 » comme si la première était meilleure.
    TMDB reste utilisé pour tout le reste (titres, affiches, année, durée)."""
    note = movie.get("lb_rating")
    if not note:
        return ""
    return (f'<span class="note-lb" title="{esc(t("Note moyenne Letterboxd"))}">{note}'
            f'<span class="sur">/5</span></span>')


def movie_card(movie: dict, movie_urls: dict, extra: str = "",
               show_rating: bool = True, show_classic: bool = True,
               versions: set | None = None) -> str:
    """`show_rating=False` masque la note — utile quand la carte l'affiche
    déjà ailleurs (le classement de /classiques/ la met dans son propre rang).
    `show_classic=False` masque le badge Classique — bruit pur sur une page
    qui ne liste QUE des classiques.
    `versions` : versions locales à poser sur `data-v` (voir card_attrs) —
    utilisé par la page ville pour un filtre langue propre à la ville."""
    url = movie_urls[movie["key"]]
    poster = (f'<img src="{esc(movie["poster"])}" alt="{esc(affiche_alt(movie))}" loading="lazy">'
              if movie["poster"] else '<div class="noposter">🎞️</div>')
    meta = " · ".join(filter(None, [
        str(movie["year"]) if movie.get("year") else "",
        movie["genre"],
        tf("{n} min", n=movie["duration_min"]) if movie["duration_min"] else "",
    ]))
    # La note est du HTML (elle porte sa couleur), le reste du texte échappé.
    ligne = " · ".join(filter(None, [note_lb(movie) if show_rating else "",
                                     esc(meta)]))
    return f"""<article class="movie-card"{card_attrs(movie, versions)}>
<a href="{url}">{poster}</a>
<div class="movie-info">
<h3><a href="{url}">{esc(movie["title"])}</a>{classic_badge(movie) if show_classic else ""}{anniversaire_badge(movie)}</h3>
<p class="meta">{ligne}</p>
{extra}
</div>
</article>"""


def screening_event(show: dict, movie: dict, cinema: dict) -> dict:
    """Une séance décrite en schema.org ScreeningEvent (résultats enrichis).

    C'est le type que Google attend pour des horaires de cinéma : il porte la
    DATE et le LIEU, ce qu'un simple CollectionPage ne disait pas. `startDate`
    est en heure locale sans fuseau — c'est la forme que livrent nos sources,
    et annoncer un fuseau qu'on n'a pas vérifié serait pire que de l'omettre.
    Le lien de billetterie devient une Offer quand on en a un."""
    event = {
        "@type": "ScreeningEvent",
        "name": f"{movie['title']} — {cinema['name']}",
        "startDate": show["start"],
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "workPresented": {
            "@type": "Movie",
            "name": movie["title"],
            **({"image": movie["poster"]} if movie["poster"] else {}),
            **({"director": {"@type": "Person", "name": movie["director"]}}
               if movie["director"] else {}),
        },
        "location": {
            "@type": "MovieTheater",
            "name": cinema["name"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": cinema["address"],
                "postalCode": cinema["postcode"],
                "addressLocality": cinema["city"],
                "addressCountry": "FR",
            },
        },
    }
    # VF = doublé en français ; VOST = version originale sous-titrée français.
    # « VO » (sans sous-titres) ne dit rien de la langue parlée, qu'on ne
    # connaît pas de façon fiable : on préfère ne rien déclarer.
    if show.get("version") == "VF":
        event["inLanguage"] = "fr"
    elif show.get("version") == "VOST":
        event["subtitleLanguage"] = "fr"
    if show.get("booking"):
        event["offers"] = {
            "@type": "Offer",
            "url": show["booking"],
            "availability": "https://schema.org/InStock",
        }
    return event


def poster_strip(keys: list[str], movies: dict, movie_urls: dict,
                 limit: int | None = None) -> str:
    """Bande d'affiches d'un cycle. Le titre apparaît au survol et au focus
    clavier : une affiche seule ne dit pas de quel film il s'agit, et c'est
    précisément le fonds de répertoire — des films qu'on ne reconnaît pas
    forcément à leur jaquette — que ces bandes présentent.
    Le titre reste dans le HTML (donc lisible par un lecteur d'écran et
    indexable) ; seule son opacité change."""
    items = []
    for k in (keys[:limit] if limit else keys):
        m = movies[k]
        if not m["poster"]:
            continue
        items.append(
            f'<a class="affiche" href="{movie_urls[k]}">'
            f'<img src="{esc(m["poster"])}" alt="{esc(affiche_alt(m))}" loading="lazy">'
            f'<span class="affiche-nom">{esc(m["title"])}</span></a>')
    return f'<div class="bande">{"".join(items)}</div>'


def city_search_nav(pills_html: str, cmap: dict, n_cities: int) -> str:
    """Sommaire de villes : pastilles des grandes villes + recherche à la
    frappe (assets/film.js). `cmap` associe un nom de ville affiché à sa
    cible : ancre « v-slug » sur une fiche film, URL absolue ailleurs
    (film.js navigue quand la cible commence par « / »)."""
    return f"""<nav class="city-jump">
{pills_html}
<span class="city-search"><input id="city-search" type="search" autocomplete="off"
placeholder="{esc(tf("Chercher votre ville ({n} villes)…", n=n_cities))}"
aria-label="{esc(t("Chercher une ville"))}">
<ul id="city-suggest" hidden></ul></span>
<script type="application/json" id="city-map">{json.dumps(cmap, ensure_ascii=False)}</script>
</nav>
<script src="/assets/film.js" defer></script>"""


# Tris proposés au-dessus d'une liste de films. Chaque entrée donne le libellé
# du bouton, le sens appliqué au premier clic, et la marque affichée dans
# chaque sens — un second clic sur le tri actif l'inverse (tri.js).
# Le sens de départ est celui qu'on attend spontanément : les meilleures notes
# d'abord, mais les titres de A à Z. Les flèches sont explicites sur le titre
# (« A → Z ») là où un ↑ ne dirait pas grand-chose. Les libellés passent par
# t() au moment du rendu ; « A → Z » se lit pareil dans les deux langues.
SORTS = {
    "lb": ("Note Letterboxd", "desc", "↑", "↓"),
    "title": ("Titre", "asc", "A → Z", "Z → A"),
    "year": ("Année", "desc", "↑", "↓"),
    "venues": ("Cinémas", "desc", "↑", "↓"),
}

# Nombre max de genres proposés dans le filtre (les plus représentés) : au-delà,
# le menu déroulant devient un mur de genres à un ou deux films.
GENRE_FILTER_MAX = 10


def _select(cls: str, label: str, all_label: str, options: list[tuple[str, str]]) -> str:
    """Un menu déroulant de filtre (décennie, genre, pays). La 1re option
    (valeur vide) ne filtre rien. `options` = liste (valeur, libellé) déjà
    triée et DÉJÀ DANS LA BONNE LANGUE — les genres et les pays viennent de
    TMDB, pas du dictionnaire : c'est l'appelant qui sait dans quelle langue
    il les a lus."""
    opts = f'<option value="">{esc(t(all_label))}</option>' + "".join(
        # `lbl` et pas `t` : `t` est la fonction de traduction importée, une
        # variable de boucle du même nom la masquerait dans la compréhension.
        f'<option value="{esc(v)}">{esc(lbl)}</option>' for v, lbl in options)
    return (f'<label class="tri-filtre"><span class="tri-filtre-nom">{esc(t(label))}</span>'
            f'<select class="{cls}">{opts}</select></label>')


def film_tools(list_id: str, default: str, movies_list: list[dict]) -> str:
    """Barre de tri et de filtre au-dessus d'une liste de films (tri.js).
    Elle ne sert à rien sans JavaScript : le CSS la masque alors, et la liste
    reste affichée en entier dans l'ordre calculé au build.
    `default` : tri appliqué à l'arrivée, celui que la page assume
    éditorialement (le classement Letterboxd sur /classiques/…).
    Les menus décennie/genre/pays sont construits à partir des VRAIS films de la
    liste : on ne propose que des valeurs qui existent (pas de filtre vide)."""
    order = [default] + [k for k in SORTS if k != default]
    options = "".join(
        f'<button type="button" data-sort="{k}" data-dir="{SORTS[k][1]}"'
        f' data-asc="{esc(t(SORTS[k][2]))}" data-desc="{esc(t(SORTS[k][3]))}"'
        f' aria-pressed="{"true" if k == default else "false"}">'
        f'<span class="tri-nom">{esc(t(SORTS[k][0]))}</span>'
        f'<span class="tri-sens"></span></button>'
        for k in order)
    # « Toutes » est actif à l'arrivée : aucun film n'est masqué par défaut.
    versions = "".join(
        f'<button type="button" data-v="{v}" aria-pressed="{pressed}">{esc(t(lbl))}</button>'
        for v, lbl, pressed in (("", "Toutes", "true"), ("vo", "VO / VOST", "false"),
                                ("vf", "VF", "false")))

    # Décennies présentes, de la plus récente à la plus ancienne.
    decades = sorted({(int(m["year"]) // 10) * 10 for m in movies_list if m.get("year")},
                     reverse=True)
    dec_sel = _select("tri-decennie", "Décennie", "Toutes",
                      [(str(d), tf("Années {d}", d=d)) for d in decades]) if decades else ""

    # Genres : on n'en propose que les PLUS PERTINENTS (les plus représentés
    # dans la liste), plafonnés à GENRE_FILTER_MAX, sinon le menu déroule une
    # vingtaine d'entrées dont beaucoup n'ont qu'un ou deux films. Comptage sur
    # les genres individuels, sélection par fréquence, réaffichage alphabétique.
    #
    # Les libellés viennent du champ `genre` du film, donc DÉJÀ dans la langue
    # du build (localize_movies a promu `genre_en`) : rien à traduire ici. Le
    # slug, lui, dérive du libellé — « Comédie » et « Comedy » ne produisent
    # donc pas la même valeur d'option. Sans conséquence : le filtre compare le
    # slug de la carte à celui de l'option, et les deux sont calculés dans la
    # même langue au sein d'une même page.
    genre_labels: dict[str, str] = {}
    genre_count: dict[str, int] = {}
    for m in movies_list:
        for g in genre_parts(m):
            sl = genre_slug(g)
            genre_labels.setdefault(sl, g)
            genre_count[sl] = genre_count.get(sl, 0) + 1
    top_genres = sorted(genre_count, key=lambda sl: -genre_count[sl])[:GENRE_FILTER_MAX]
    genres_opts = sorted(((sl, genre_labels[sl]) for sl in top_genres),
                         key=lambda pair: pair[1].lower())
    genre_sel = _select("tri-genre", "Genre", "Tous", genres_opts) if genres_opts else ""

    # Pays : même logique que les genres — `country_tmdb` porte déjà le nom
    # dans la langue du build (table COUNTRY_FR côté français, nom TMDB brut
    # côté anglais, voir enrich_tmdb.py).
    country_labels: dict[str, str] = {}
    for m in movies_list:
        c = (m.get("country_tmdb") or "").strip()
        if c:
            country_labels.setdefault(genre_slug(c), c)
    country_opts = sorted(country_labels.items(), key=lambda pair: pair[1].lower())
    country_sel = _select("tri-pays", "Pays", "Tous", country_opts) if country_opts else ""

    filtres = dec_sel + genre_sel + country_sel
    filtres_html = (f'<span class="tri-filtres" role="group" '
                    f'aria-label="{esc(t("Filtrer les films"))}">'
                    f'{filtres}</span>' if filtres else "")

    return f"""<div class="film-tools" data-list="{list_id}" data-page="{PAGE_SIZE}">
<span class="tri-tri" role="group" aria-label="{esc(t("Trier les films"))}">
<span class="tri-label">{t("Trier par")}</span>{options}</span>
<span class="tri-versions" role="group" aria-label="{esc(t("Filtrer par version"))}">{versions}</span>
{filtres_html}
<p class="tri-compte" id="tri-compte" role="status">{tf("{n} films", n=len(movies_list))}</p>
</div>
<script src="/assets/tri.js" defer></script>"""


def ville_tools() -> str:
    """Barre de la page ville : trier les films par note Letterboxd et filtrer
    par langue (VO/VOST ou VF). `ville.js` l'applique SUR PLACE, cinéma par
    cinéma (la page reste groupée par salle). Sans JavaScript, le CSS la masque
    et le programme reste affiché en entier, dans l'ordre du jour."""
    langues = "".join(
        f'<button type="button" data-v="{v}" aria-pressed="{p}">{esc(t(lbl))}</button>'
        for v, lbl, p in (("", "Toutes", "true"), ("vo", "VO / VOST", "false"),
                          ("vf", "VF", "false")))
    return f"""<div class="film-tools ville-tools" role="group" aria-label="{esc(t("Trier et filtrer les films"))}">
<span class="tri-tri" role="group" aria-label="{esc(t("Trier les films"))}">
<span class="tri-label">{t("Trier par")}</span>
<button type="button" class="ville-sort" data-sort="imminence" aria-pressed="true"><span class="tri-nom">{t("Prochaine séance")}</span></button>
<button type="button" class="ville-sort" data-sort="lb" aria-pressed="false"><span class="tri-nom">{t("Note Letterboxd")}</span></button>
</span>
<span class="tri-versions" role="group" aria-label="{esc(t("Filtrer par langue"))}">{langues}</span>
<p class="tri-compte ville-compte" role="status"></p>
</div>
<script src="/assets/ville.js" defer></script>"""


# --- Construction ---------------------------------------------------------

def main() -> int:
    today = date.today()
    cinemas, movies, showtimes, cities = load_merged(DATA)
    meta = load("meta.json")

    # Les snapshots de chaînes sont collectés en local et peuvent avoir un jour
    # de retard : sans ce filtre, une fiche film affiche « Dimanche 19 juillet »
    # alors qu'on est le 20. Aucune page ne doit proposer une séance passée.
    today_iso = today.isoformat()
    showtimes = [s for s in showtimes if s["start"][:10] >= today_iso]

    # Index des séances
    by_cinema = defaultdict(list)
    by_movie = defaultdict(list)
    for s in showtimes:
        by_cinema[s["cinema"]].append(s)
        by_movie[s["movie"]].append(s)

    # Versions et nombre de salles par film : lus par card_attrs() pour poser
    # les attributs data-* que tri.js exploite. VOST compte comme de la VO —
    # le spectateur qui filtre « VO » veut la langue d'origine, sous-titrée ou
    # non ; les séances sans version connue (ou muettes) ne comptent ni l'un
    # ni l'autre plutôt que d'être rangées à tort.
    MOVIE_VERSIONS.clear()
    MOVIE_VENUES.clear()
    for key, shows in by_movie.items():
        tags = set()
        for s in shows:
            if s["version"] == "VF":
                tags.add("vf")
            elif s["version"] in ("VO", "VOST"):
                tags.add("vo")
        MOVIE_VERSIONS[key] = tags
        MOVIE_VENUES[key] = len({s["cinema"] for s in shows})

    # URLs uniques : collision de slug -> suffixe ville / réalisateur
    cinema_urls: dict[str, str] = {}
    taken: dict[str, str] = {}
    for cid, c in cinemas.items():
        slug = slugify(c["name"]) or f"cinema-{cid}"
        if slug in taken:
            slug = f"{slug}-{c['city_slug']}"
        taken[slug] = cid
        cinema_urls[cid] = f"/cinema/{slug}/"
    movie_urls: dict[str, str] = {}
    taken = {}
    for key, m in movies.items():
        # Slug borné à 60 caractères : les listes de réalisateurs à rallonge
        # produisaient des chemins dépassant la limite Windows (260 car.).
        slug = slugify(m["title"])[:60].strip("-") or "film"
        if slug in taken:
            alt = f"{slug}-{slugify(m['director'])}"[:60].strip("-")
            slug = alt if alt not in taken else f"{slug}-{len(taken)}"
        taken[slug] = key
        movie_urls[key] = f"/film/{slug}/"

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    shutil.copytree(ASSETS, SITE / "assets")
    # Fichiers servis tels quels à la racine (ex. validation Search Console)
    static_dir = ROOT / "static"
    if static_dir.exists():
        for f in static_dir.iterdir():
            shutil.copy(f, SITE / f.name)

    # ----- Une passe de génération complète par langue -----
    # Tout ce qui précède (fusion, index de séances, slugs) est calculé UNE
    # fois : ces données ne dépendent pas de la langue, et recalculer la fusion
    # pour l'anglais aurait surtout risqué de faire diverger les deux arbres.
    # Ce qui suit est refait intégralement pour chaque langue.
    urls_par_langue: dict[str, list[str]] = {}
    for lang in LANGS:
        i18n.set_lang(lang)
        urls_par_langue[lang] = build_lang(
            today, today_iso, cinemas, localize_movies(movies), showtimes,
            cities, by_cinema, by_movie, cinema_urls, movie_urls)

    # ----- sitemap & robots -----
    # UN SEUL sitemap, qui liste les deux langues : le lien entre une page et
    # sa traduction est porté par les balises `hreflang` du <head> (voir
    # alternates()), pas ici — les répéter en `xhtml:link` doublerait le poids
    # du fichier pour une information que Google a déjà lue sur la page.
    lastmod = meta["generated_at"][:10]
    entries = "".join(
        f"<url><loc>{BASE_URL}{lang_prefix(lang)}{u}</loc>"
        f"<lastmod>{lastmod}</lastmod></url>"
        for lang in LANGS for u in sorted(urls_par_langue[lang]))
    (SITE / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>',
        encoding="utf-8")
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")

    # ----- En-têtes de sécurité (Cloudflare Pages) -----
    # GÉNÉRÉ, jamais écrit à la main dans static/ : la CSP contient l'empreinte
    # des deux scripts en ligne du gabarit, qui doit suivre le code au caractère
    # près (voir csp_headers). Un fichier figé se désynchroniserait au premier
    # espace ajouté dans JS_FLAG ou T_HELPER, et le site perdrait son JavaScript
    # sans le moindre avertissement au build.
    (SITE / "_headers").write_text(csp_headers(), encoding="utf-8")

    # ----- 404 de marque (GitHub Pages sert /404.html) -----
    # La 404 brute de GitHub éjectait le visiteur du site (page blanche, sans
    # lien de retour). Hors sitemap, volontairement.
    #
    # UNE SEULE 404, en français, et c'est une contrainte d'hébergement, pas un
    # choix : GitHub Pages sert TOUJOURS le /404.html de la racine, quelle que
    # soit l'adresse manquante. Un /en/404.html ne serait jamais affiché. D'où
    # la ligne anglaise ajoutée sous le texte français : c'est le seul endroit
    # du site où un anglophone peut atterrir sans avoir de version traduite.
    i18n.set_lang("fr")
    (SITE / "404.html").write_text(page(
        f"Page introuvable — {SITE_NAME}",
        "Cette page n'existe pas ou plus.",
        """<p class="lead">Cette adresse ne mène à aucune page. Le programme change tous les
jours, et la fiche d'un film disparaît quand il quitte l'affiche.</p>
<p><a class="more" href="/">← Le répertoire</a> &nbsp;
<a class="more" href="/a-l-affiche/">🎬 À l'affiche</a> &nbsp;
<a class="more" href="/retrospectives/">🎞️ Rétrospectives</a> &nbsp;
<a class="more" href="/carte/">🗺️ Carte</a></p>
<p class="meta" lang="en">This page does not exist, or no longer does. The programme
changes every day, and a film's page disappears when it stops showing.
<a class="more" href="/en/">← English home</a></p>""",
        "/404.html", h1="Oups, séance introuvable"), encoding="utf-8")

    # Messages de fin en ASCII PUR, sans accent ni symbole. La console Windows
    # tourne en cp1252 et lève UnicodeEncodeError sur « ⚠ » comme sur « é » :
    # un build parfaitement réussi se terminait par une trace d'erreur.
    total = sum(len(v) for v in urls_par_langue.values())
    detail = " + ".join(f"{len(v)} {k}" for k, v in urls_par_langue.items())
    print(f"Site genere dans {SITE} : {total} pages ({detail}) - "
          f"{len(cinemas)} cinemas, {len(cities)} villes, {len(movies)} films")
    # La liste des manques part dans un FICHIER (UTF-8) : ce sont des phrases
    # françaises, la console ne saurait pas les afficher, et on veut pouvoir
    # les relire après coup pour compléter le dictionnaire.
    manquantes = i18n.report_missing()
    if manquantes:
        rapport = ROOT / "i18n-manquantes.txt"
        rapport.write_text("\n".join(manquantes) + "\n", encoding="utf-8")
        print(f"ATTENTION : {len(manquantes)} chaines sans traduction anglaise "
              f"(affichees en francais sur /en/).")
        print(f"            Liste complete : {rapport}")
    else:
        print("Traduction anglaise complete : aucune chaine sans equivalent.")
    return 0


def build_lang(today, today_iso, cinemas, movies, showtimes, cities,
               by_cinema, by_movie, cinema_urls, movie_urls) -> list[str]:
    """Génère le site entier dans la langue courante (`i18n.LANG`).

    `movies` arrive DÉJÀ localisé (titres, synopsis, genres, pays) : voir
    `localize_movies()`. `cinema_urls` et `movie_urls` sont au contraire
    communs aux deux langues — ce sont des chemins sans segment de langue, que
    `write()` et `page()` préfixent chacun de leur côté.

    Renvoie la liste des chemins écrits, pour le sitemap.
    """
    urls: list[str] = []

    # ----- Pages cinéma -----
    for cid, cinema in cinemas.items():
        path = cinema_urls[cid]
        horizon = (today + timedelta(days=CINEMA_WINDOW_DAYS)).isoformat()
        shows = [s for s in by_cinema[cid] if s["start"][:10] <= horizon]
        by_day = defaultdict(lambda: defaultdict(list))
        for s in shows:
            by_day[s["start"][:10]][s["movie"]].append(s)
        sections = []
        for day in sorted(by_day):
            d = date.fromisoformat(day)
            films_html = "".join(
                movie_card(movies[mk], movie_urls, showtime_pills(ss))
                for mk, ss in sorted(by_day[day].items(),
                                     key=lambda kv: kv[1][0]["start"])
            )
            sections.append(f'<section><h2>{date_label(d, today)}</h2>{films_html}</section>')
        # Passerelle vers le site frère, sur les fiches des cinémas parisiens.
        bridge = paris_cine_bridge() if cinema["city_slug"] == "paris" else ""
        nature = cinema_kind_label(cinema.get("chain"))
        voir_ville = tf("Voir tous les cinémas de {ville}", ville=esc(cinema["city"]))
        vide = f'<p>{t("Aucune séance annoncée pour les deux prochaines semaines.")}</p>'
        body = f"""<p class="lead">{esc(cinema["address"])}, {esc(cinema["postcode"])} {esc(cinema["city"])}.
{esc(nature).capitalize()}. <a href="/ville/{cinema["city_slug"]}/">{voir_ville}</a>.</p>
{"".join(sections) or vide}{bridge}"""
        jsonld = {
            "@context": "https://schema.org", "@type": "MovieTheater",
            "name": cinema["name"],
            "address": {"@type": "PostalAddress", "streetAddress": cinema["address"],
                        "postalCode": cinema["postcode"], "addressLocality": cinema["city"],
                        "addressCountry": "FR"},
        }
        if cinema["lat"]:
            jsonld["geo"] = {"@type": "GeoCoordinates",
                             "latitude": cinema["lat"], "longitude": cinema["lon"]}
        write(path, page(
            tf("{cinema} ({ville}) : séances et programme — {site}",
               cinema=cinema["name"], ville=cinema["city"], site=SITE_NAME),
            tf("Programme et horaires des séances du cinéma {cinema} à {ville} "
               "sur les 15 prochains jours. {nature}.",
               cinema=cinema["name"], ville=cinema["city"],
               nature=nature.capitalize()),
            body, path, jsonld, h1=f"{cinema['name']} — {cinema['city']}"))
        urls.append(path)

    # ----- Pages ville -----
    for slug, city in cities.items():
        path = f"/ville/{slug}/"
        horizon = (today + timedelta(days=CITY_WINDOW_DAYS)).isoformat()
        blocks = []
        city_movie_keys: set[str] = set()
        sorted_cids = sorted(city["cinemas"], key=lambda c: cinemas[c]["name"])
        # Versions disponibles DANS CETTE VILLE par film : le filtre langue de la
        # page ville doit refléter les séances locales, pas la moyenne nationale
        # (un film en VF ici peut être en VO ailleurs).
        city_versions: dict[str, set] = defaultdict(set)
        for cid in sorted_cids:
            for s in by_cinema[cid]:
                if s["start"][:10] <= horizon:
                    if s["version"] == "VF":
                        city_versions[s["movie"]].add("vf")
                    elif s["version"] in ("VO", "VOST"):
                        city_versions[s["movie"]].add("vo")
        for cid in sorted_cids:
            cinema = cinemas[cid]
            shows = [s for s in by_cinema[cid] if s["start"][:10] <= horizon]
            films = defaultdict(list)
            for s in shows:
                films[s["movie"]].append(s)
            # Le visiteur type cherche une séance CE SOIR : les films du jour
            # d'abord, ceux qui ne repassent que plus tard repliés en dessous.
            films_today, films_later = [], []
            for mk, ss in sorted(films.items(), key=lambda kv: kv[1][0]["start"]):
                city_movie_keys.add(mk)
                todays = [s for s in ss if s["start"][:10] == today_iso]
                if todays:
                    films_today.append(movie_card(movies[mk], movie_urls,
                                                  showtime_pills(todays),
                                                  versions=city_versions[mk]))
                else:
                    films_later.append(movie_card(
                        movies[mk], movie_urls,
                        f'<p class="meta">{tf("prochaine séance : {jour}", jour=date_label(date.fromisoformat(ss[0]["start"][:10]), today))}</p>',
                        versions=city_versions[mk]))
            today_html = f'<div class="films">{"".join(films_today)}</div>' if films_today else ""
            later_html = ""
            if films_later:
                if films_today:
                    n_later = len(films_later)
                    resume = tf("+ {n} autre{s} film{s2} plus tard cette semaine",
                                n=n_later, s=plural(n_later), s2=plural(n_later))
                    later_html = (f'<details class="more-films"><summary>{esc(resume)}'
                                  f'</summary>'
                                  f'<div class="films">{"".join(films_later)}</div></details>')
                else:
                    # Rien aujourd'hui : ne pas cacher tout le programme du cinéma
                    today_html = (f'<p class="meta">'
                                  f'{t("Pas de séance aujourd\'hui. Prochaines dates :")}</p>')
                    later_html = f'<div class="films">{"".join(films_later)}</div>'
            blocks.append(f"""<section class="cinema-block" id="c-{cid}">
<h2><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h2>
<p class="meta">{esc(cinema["address"])}. <a href="{cinema_urls[cid]}">{t("Programme complet")}</a></p>
{(today_html + later_html) or f'<p>{t("Aucune séance cette semaine.")}</p>'}</section>""")
        # Sommaire ancré : au-delà de 2 cinémas, l'accès direct évite de
        # scroller toute la page pour atteindre SA salle (Lyon = 17 écrans).
        toc = ""
        if len(sorted_cids) > 2:
            toc_links = " ".join(f'<a href="#c-{cid}">{esc(cinemas[cid]["name"])}</a>'
                                 for cid in sorted_cids)
            toc = f'<nav class="city-jump">{toc_links}</nav>'
        n_cine = len(city["cinemas"])
        n_chain = sum(1 for cid in city["cinemas"] if cinemas[cid].get("chain"))
        n_inde = n_cine - n_chain
        parts = []
        if n_inde:
            parts.append(tf("{n} cinéma{s} indépendant{s}", n=n_inde, s=plural(n_inde)))
        if n_chain:
            parts.append(tf("{n} cinéma{s} de chaîne", n=n_chain, s=plural(n_chain)))
        n_classics = sum(1 for mk in city_movie_keys if is_classic(movies[mk]))
        classics_bit = (tf(" Dont {n} film{s} de plus de {age} ans : ",
                           n=n_classics, s=plural(n_classics), age=CLASSIC_AGE_YEARS)
                        + f'<a href="/classiques/">{t("voir le classement")}</a>.'
                        if n_classics else "")
        # Passerelle vers le site frère, EN HAUT de la seule page ville de
        # Paris (page d'aiguillage : l'encadré doit sauter aux yeux, pas
        # dormir sous la liste des 31 cinémas).
        bridge = paris_cine_bridge() if slug == "paris" else ""
        # Barre tri/langue seulement s'il y a assez de films pour que trier ou
        # filtrer ait un sens (sinon elle encombre pour rien).
        tools = ville_tools() if len(city_movie_keys) >= 5 else ""
        # « X et Y » / « X and Y » : le connecteur lui-même change de langue.
        inventaire = tf("{inventaire} à {ville}.",
                        inventaire=f' {t("et")} '.join(parts), ville=esc(city["name"]))
        body = f"""<p class="lead">{inventaire}
{t("Les séances d'aujourd'hui d'abord, puis celles des jours suivants.")}{classics_bit}</p>{bridge}{toc}{tools}{"".join(blocks)}
{abonnement_bloc(slug, city["name"])}"""
        write(path, page(
            tf("Cinéma à {ville} : séances et horaires — {site}",
               ville=city["name"], site=SITE_NAME),
            tf("Quel film voir à {ville} ? Séances et horaires des {n} cinéma(s) "
               "de la ville : programme du jour et de la semaine.",
               ville=city["name"], n=n_cine),
            body, path, h1=tf("Cinémas à {ville}", ville=city["name"]), top_link=True,
            # Découverte standard d'un flux : c'est ce que lisent les lecteurs
            # RSS et les extensions de navigateur pour proposer l'abonnement.
            # href écrit SANS préfixe : _prefix_links() s'en charge, comme pour
            # tous les href/src du site (l'écrire à la main donnait
            # « /seanceo/seanceo/… »).
            head_extra=f'<link rel="alternate" type="application/rss+xml" '
                       f'title="{esc(tf("Répertoire à {ville}", ville=city["name"]))}" '
                       f'href="/ville/{slug}/repertoire.xml">'))
        urls.append(path)

    # ----- Réalisateurs : qui mérite une fiche -----
    # Calculé ICI, avant les pages film, parce que celles-ci doivent pouvoir
    # lier le nom du réalisateur vers sa fiche : c'est le seul maillage interne
    # qui mène à ces pages depuis les 967 fiches film.
    #
    # `rep_shows` est aussi calculé ici (le bloc « Répertoire » plus bas le
    # reprend) : le seuil d'éligibilité en dépend.
    rep_window = repertoire.window(showtimes, today)
    rep_shows = repertoire.repertoire_shows(rep_window, movies)
    rep_keys = {s["movie"] for s in rep_shows}

    # Un film peut créditer plusieurs réalisateurs (« Stanton, McKenna ») : on
    # indexe NOM PAR NOM, comme le registre `unitaires` de sources.py. Les
    # graphies sont déjà normalisées en amont (_canonical_directors), donc
    # « LYNCH David » et « David Lynch » sont ici le même nom.
    real_films: dict[str, set] = defaultdict(set)
    for k, m_ in movies.items():
        if not by_movie[k]:
            continue  # film sans séance : rien à programmer, donc pas de fiche
        for nom in (m_.get("director") or "").split(","):
            nom = nom.strip()
            if nom and _fold_title(nom) not in ("collectif", "divers"):
                real_films[nom].add(k)

    # Certaines caisses créditent « A Demuynck » là où d'autres écrivent
    # « Arnaud Demuynck » : sans rien faire, la même personne obtient deux
    # fiches. On ne fusionne que le cas SÛR — prénom réduit à une initiale,
    # même nom de famille, et UN SEUL candidat au prénom complet commençant
    # par cette initiale. Deux des quatre cas mesurés n'ont pas de jumeau
    # (« B Botella ») : ils gardent leur graphie, c'est tout ce que la source
    # donne. Le motif inverse (« Abrams J.J. ») reste volontairement non
    # traité, voir la note de sources.py.
    #
    # Cette fusion est LOCALE à ces pages : elle ne touche pas
    # `_canonical_directors()`, dont les garde-fous protègent la déduplication
    # des films.
    alias_reels: dict[str, str] = {}
    noms_credites = set(real_films)
    for nom in noms_credites:
        mots = nom.split()
        if len(mots) < 2 or len(mots[0].strip(".")) != 1:
            continue
        initiale, famille = _fold_title(mots[0])[:1], _fold_title(" ".join(mots[1:]))
        candidats = [o for o in noms_credites
                     if o != nom and len(o.split()[0]) > 1
                     and _fold_title(" ".join(o.split()[1:])) == famille
                     and _fold_title(o)[:1] == initiale]
        if len(candidats) == 1:
            alias_reels[nom] = candidats[0]
    for alias, complet in alias_reels.items():
        real_films[complet] |= real_films.pop(alias)

    # SEUIL. 746 réalisateurs ont un film à l'affiche ; leur faire à tous une
    # page produirait des centaines de pages maigres, qui se résumeraient à
    # recopier une fiche film. On garde ceux qui ont de quoi remplir une page :
    # soit au moins deux films à l'affiche (une mini-rétrospective), soit un
    # film de RÉPERTOIRE joué au moins deux fois (le sujet du site, avec un
    # vrai agenda). Le cas exclu — un film de répertoire à séance unique — est
    # déjà couvert par /derniere-chance/ et par la fiche du film.
    def _real_eligible(films: set) -> bool:
        return len(films) >= 2 or any(len(by_movie[k]) >= 2 for k in films & rep_keys)

    realisateurs = sorted((nom for nom, f in real_films.items() if _real_eligible(f)),
                          key=lambda n: (_fold_title(n), n))
    realisateur_urls: dict[str, str] = {}
    _pris: set[str] = set()
    for nom in realisateurs:
        slug = slugify(nom)[:60].strip("-") or "realisateur"
        if slug in _pris:  # homonymes après slugification
            slug = f"{slug}-{len(_pris)}"
        _pris.add(slug)
        realisateur_urls[nom] = f"/realisateur/{slug}/"

    def credit_realisateurs(noms: str) -> str:
        """Le champ `director` en HTML, chaque nom connu devenant un lien vers
        sa fiche. Renvoie du HTML DÉJÀ ÉCHAPPÉ (les noms viennent de sources
        externes) : ne pas le repasser dans esc()."""
        sortie = []
        for nom in noms.split(","):
            nom = nom.strip()
            if not nom:
                continue
            # Le nom AFFICHÉ reste celui du générique ; seul le lien pointe
            # vers la fiche canonique (voir alias_reels). Réécrire le crédit
            # serait un mensonge sur ce que la source dit.
            url = realisateur_urls.get(alias_reels.get(nom, nom))
            sortie.append(f'<a href="{url}">{esc(nom)}</a>' if url else esc(nom))
        return ", ".join(sortie)

    # ----- Pages film -----
    for key, movie in movies.items():
        path = movie_urls[key]
        shows = by_movie[key]
        # Séances groupées par ville puis par cinéma : le lecteur cherche
        # d'abord SA ville, pas une liste plate de toute la France.
        by_city = defaultdict(lambda: defaultdict(list))
        for s in shows:
            by_city[cinemas[s["cinema"]]["city_slug"]][s["cinema"]].append(s)

        def city_name(cslug: str) -> str:
            if cslug in cities:
                return cities[cslug]["name"]
            any_cid = next(iter(by_city[cslug]))
            return cinemas[any_cid]["city"]

        city_slugs = sorted(by_city, key=lambda c: city_name(c))
        # Au-delà de quelques villes, la page n'affiche AUCUNE ville tant que le
        # visiteur n'a pas choisi la sienne (recherche ou pastille) : même
        # repliée, la liste des 234 villes rallongeait la page pour rien.
        # Les sections restent dans le HTML (indexables) mais masquées en CSS.
        filtered = len(city_slugs) > 6
        rows = []
        for cslug in city_slugs:
            blocks = []
            for cid, ss in sorted(by_city[cslug].items(),
                                  key=lambda kv: cinemas[kv[0]]["name"]):
                cinema = cinemas[cid]
                nxt = sorted(ss, key=lambda s: s["start"])[:8]
                days = defaultdict(list)
                for s in nxt:
                    days[s["start"][:10]].append(s)
                per_day = " ".join(
                    f'<span class="day">{date_label(date.fromisoformat(d), today)}</span>{showtime_pills(v)}'
                    for d, v in sorted(days.items()))
                blocks.append(f"""<section class="cinema-block">
<h4><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h4>
{per_day}</section>""")
            n = len(blocks)
            rows.append(f"""<section class="city-group" id="v-{cslug}">
<h3>{esc(city_name(cslug))} <span class="meta">{tf("{n} cinéma{s}", n=n, s=plural(n))}</span></h3>
<p class="meta"><a href="/ville/{cslug}/">{tf("Tous les cinémas de {ville} →", ville=esc(city_name(cslug)))}</a></p>
{"".join(blocks)}</section>""")
        # Sommaire des villes : les plus grandes villes en accès direct,
        # une recherche (suggestions maison, sans dépendance) pour les autres —
        # 234 pastilles de villes formaient un mur illisible.
        city_jump = prompt = ""
        if filtered:
            majors = [c for c in BIG_CITY_SLUGS if c in by_city]
            pills = " ".join(f'<a href="#v-{c}">{esc(city_name(c))}</a>' for c in majors)
            cmap = {city_name(c): f"v-{c}" for c in city_slugs}
            # Suggestions maison (pas de <datalist> : elle déroule tout au clic ;
            # ici rien ne s'ouvre avant 2 lettres tapées — voir film.js)
            city_jump = city_search_nav(pills, cmap, len(city_slugs))
            n_cine_total = len({s["cinema"] for s in shows})
            prompt = (f'<p class="city-prompt" id="city-prompt">'
                      + tf("À l'affiche dans {n} cinéma{s} de {v} villes. "
                           "Choisissez la vôtre pour voir les horaires.",
                           n=n_cine_total, s=plural(n_cine_total), v=len(city_slugs))
                      + '</p>')
        # Crédits assemblés en HTML DÉJÀ ÉCHAPPÉ (et non en texte brut échappé
        # à l'insertion) : le nom du réalisateur doit pouvoir devenir un lien
        # vers sa fiche. Tout le reste passe par esc() ici même.
        credits = " · ".join(filter(None, [
            esc(movie["year"]) if movie.get("year") else "",
            (tf("De {realisateur}", realisateur=credit_realisateurs(movie["director"]))
             if movie["director"] else ""),
            esc(tf("Avec {acteurs}", acteurs=movie["cast"])) if movie["cast"] else "",
            esc(movie["genre"]) if movie["genre"] else "",
            esc(tf("{n} min", n=movie["duration_min"])) if movie["duration_min"] else ""]))
        poster = (f'<img class="poster" src="{esc(movie["poster"])}" alt="{esc(affiche_alt(movie))}">'
                  if movie["poster"] else "")
        # Ligne d'actions sous le synopsis : bande-annonce + fiche Letterboxd.
        # Le lien Letterboxd porte le vert réservé à Letterboxd sur le site,
        # et ouvre dans un nouvel onglet (on quitte Séancéo pour leur fiche).
        actions = []
        if movie["trailer"]:
            actions.append(f'<a href="{esc(movie["trailer"])}" target="_blank" '
                           f'rel="noopener noreferrer">{t("▶ Bande-annonce")}</a>')
        if movie.get("lb_url"):
            actions.append(f'<a class="lien-lb" href="{esc(movie["lb_url"])}" target="_blank" '
                           f'rel="noopener noreferrer">{t("Voir sur Letterboxd ↗")}</a>')
        trailer = f'<p class="film-actions">{"".join(actions)}</p>' if actions else ""
        # Bloc « préviens-moi quand il repasse » : conteneur vide, rempli par
        # assets/alertes.js. Conditionné à `lb_url` parce que l'empreinte du
        # slug Letterboxd EST la clé de watchlist-index.json : sans elle, le
        # balayage nocturne du Worker ne saurait pas quel film surveiller.
        # Rien ne s'affiche sans JavaScript, et c'est voulu — une alerte est
        # une fonction dynamique, un bouton mort serait pire que pas de bouton.
        alerte_bloc = ""
        if movie.get("lb_url"):
            emp = lb_slug_key(movie["lb_url"].rstrip("/").split("/film/")[-1])
            # `data-url` porte BASE_PATH à la main : page() ne préfixe que les
            # attributs href et src, jamais les data-*.
            alerte_bloc = (
                f'<div class="film-alerte" id="film-alerte" data-film="{esc(emp)}" '
                f'data-titre="{esc(movie["title"])}" '
                f'data-url="{esc(BASE_PATH + lang_prefix() + path)}" '
                f'data-lang="{i18n.LANG}"></div>{ALERTES_JS}')
        # `filtered` : les sections ville sont masquées en CSS tant que le
        # visiteur n'en a pas choisi une. Le masquage est conditionné à la
        # classe `js` posée dans le <head> — sans JavaScript, la recherche ne
        # marcherait pas et tout doit rester visible (et lisible par un robot).
        city_list = (f'<div class="city-list{" filtered" if filtered else ""}" id="city-list">'
                     f'{"".join(rows)}</div>' if rows else f'<p>{t("Aucune séance à venir.")}</p>')
        # Ligne anniversaire sous le synopsis : mise en avant éditoriale d'un
        # film qui fête un cap rond cette année (calculé depuis l'année TMDB).
        age_anniv = anniversaire_age(movie)
        anniv_note = (f'<p class="anniv-note">'
                      + tf("🎂 Ce film {celebration} en {annee}.",
                           celebration=anniversaire_texte(age_anniv), annee=TODAY.year)
                      + '</p>' if age_anniv else "")
        body = f"""<div class="film-head">{poster}<div>
<p class="lead">{classic_badge(movie)}{anniversaire_badge(movie)} {note_lb(movie)} {credits}</p>
<p>{esc(movie["storyline"])}</p>{anniv_note}{trailer}{alerte_bloc}</div></div>
<h2>{tf("Où voir {titre} ?", titre=esc(movie["title"]))}</h2>
{city_jump}
{prompt}
{city_list}"""
        jsonld = {"@context": "https://schema.org", "@type": "Movie", "name": movie["title"]}
        if movie.get("year"):
            jsonld["datePublished"] = str(movie["year"])
        if movie["director"]:
            jsonld["director"] = {"@type": "Person", "name": movie["director"]}
        if movie["poster"]:
            jsonld["image"] = movie["poster"]
        # « de Jacques Tati » se place avant le point d'interrogation en
        # français comme en anglais, mais la préposition change : le fragment
        # est donc traduit à part, puis inséré dans la phrase.
        du_real = (tf(" de {realisateur}", realisateur=movie["director"])
                   if movie["director"] else "")
        if shows:
            desc = tf("Où voir {titre}{de_realisateur} ? Séances et horaires ville "
                      "par ville, dans {n} cinéma(s) en France.",
                      titre=movie["title"], de_realisateur=du_real,
                      n=len({s["cinema"] for s in shows}))
        else:
            desc = tf("Où voir {titre} ? Séances et horaires ville par ville en France.",
                      titre=movie["title"])
        write(path, page(
            tf("{titre} : séances près de chez vous — {site}",
               titre=movie["title"], site=SITE_NAME),
            desc, body, path, jsonld, h1=movie["title"], top_link=True,
            # L'affiche TMDB est déjà une URL absolue : la fiche partagée
            # s'annonce avec le film lui-même, pas avec la carte de marque.
            # `og_portrait` parce que c'est une affiche (ratio 2:3) — voir
            # open_graph(). Sans affiche, on retombe sur la carte par défaut.
            og_image=movie["poster"] or "",
            og_image_alt=affiche_alt(movie) if movie["poster"] else "",
            og_portrait=bool(movie["poster"])))
        urls.append(path)

    # ----- Index de recherche (titre + réalisateur) -----
    # Fichier à part, chargé par search.js à la première frappe : l'injecter
    # dans chaque page coûterait ~90 ko à chaque visite pour une fonction que
    # la plupart des visiteurs n'utiliseront pas. Tableaux plutôt qu'objets
    # (pas de noms de clés répétés 931 fois) : [titre, réalisateur, url, année].
    #
    # UN INDEX PAR LANGUE : il porte des titres (traduits) et des URLs (avec le
    # segment de langue). Chercher « Mr. Hulot's Holiday » depuis /en/ doit
    # marcher, et le résultat doit mener à la fiche anglaise, pas à la française.
    index = sorted(
        ([m["title"], m["director"],
          f"{BASE_PATH}{lang_prefix()}{movie_urls[k]}", m.get("year") or 0]
         for k, m in movies.items()),
        key=lambda row: sort_title(row[0]))
    write_data("recherche.json", index)

    # ----- Index de la watchlist (croisement Letterboxd) -----
    # Chargé par watchlist.js quand le visiteur dépose son export Letterboxd.
    # Clé = empreinte du slug Letterboxd (lb_slug_key) ; le CSV donne le titre
    # principal Letterboxd, qui produit la même empreinte → matching exact et
    # multilingue, sans jamais rien envoyer (tout se passe dans le navigateur).
    # On n'indexe que les films À L'AFFICHE (au moins une séance) : la watchlist
    # sert à savoir « lesquels de mes films passent », pas à parcourir un catalogue.
    #
    # Chaque film porte `k` = la liste de SES salles, `[index de salle, date de
    # la prochaine séance dans cette salle]`, triée par date. C'est ce qui permet
    # au visiteur de cadrer sa watchlist sur SA ville : sans elle, on ne savait
    # dire que « ce film repasse quelque part en France », ce qui est inutile
    # quand on habite Nancy et que la séance est à Dunkerque.
    #
    # Salles et villes sont sorties dans DEUX TABLES PARTAGÉES en tête de
    # fichier (`_s`, `_v`) et référencées par leur index. Répéter « Cinéma
    # Le Champo » et « Paris » dans les 5 349 paires (film, salle) triplerait le
    # poids du fichier pour rien. Les clés `_s`/`_v` ne peuvent pas entrer en
    # collision avec un film : une empreinte est faite de `[a-z0-9]` uniquement,
    # elle ne contient jamais de tiret bas.
    #
    # `_v` porte les coordonnées de chaque ville (celles de sa première salle) :
    # c'est ce qui permet, quand aucun film ne passe dans la ville du visiteur,
    # de lui désigner la ville la plus proche où il y en a un.
    #
    # `_s` porte en 3e position le PRÉFIXE COMMUN des liens de billetterie de la
    # salle (voir `_prefixe_billetterie` plus bas) : une salle utilise toujours
    # le même domaine d'achat, répéter « https://lepouliguencinemapax.cine.
    # boutique/media/ » sur chacune de ses séances pesait 250 ko pour rien.
    villes: list[list] = []
    ville_idx: dict[str, int] = {}
    salles: list[list] = []
    salle_idx: dict[str, int] = {}

    def ref_salle(cinema_id: str) -> int:
        """Index de la salle dans `_s`, en créant sa ville dans `_v` au besoin."""
        if cinema_id in salle_idx:
            return salle_idx[cinema_id]
        c = cinemas[cinema_id]
        ville = c.get("city") or ""
        if ville not in ville_idx:
            ville_idx[ville] = len(villes)
            lat, lon = c.get("lat"), c.get("lon")
            villes.append([
                ville,
                round(lat, 4) if lat is not None else None,
                round(lon, 4) if lon is not None else None,
            ])
        salle_idx[cinema_id] = len(salles)
        salles.append([c["name"], ville_idx[ville], ""])
        return salle_idx[cinema_id]

    def _prefixe_billetterie(urls: list[str]) -> str:
        """Plus long préfixe commun à tous les liens d'une salle, TOUJOURS plus
        court que le plus court d'entre eux.

        Ce raccourcissement d'un caractère n'est pas cosmétique : il garantit
        qu'un suffixe stocké n'est jamais vide, et donc que côté client `""`
        veut toujours dire « pas de billetterie », jamais « le préfixe tout
        seul ». Sans lui, une salle qui n'a qu'une séance réservable verrait son
        unique URL entièrement absorbée par le préfixe, et son bouton
        « Réserver » disparaîtrait.
        """
        court, long = min(urls), max(urls)  # ordre lexicographique : les extrêmes suffisent
        i = 0
        while i < len(court) and i < len(long) and court[i] == long[i]:
            i += 1
        return court[: min(i, len(court) - 1)]

    wl_index: dict[str, dict] = {"_v": villes, "_s": salles}
    liens_salle: dict[int, list[str]] = {}
    for key, m in movies.items():
        shows = by_movie.get(key)
        if not shows or not m.get("lb_url"):
            continue
        slug = m["lb_url"].rstrip("/").split("/film/")[-1]
        empreinte = lb_slug_key(slug)
        # Prochaine séance par salle (une salle peut en programmer plusieurs) :
        # on garde la séance ELLE-MÊME, pas seulement son jour, pour porter son
        # heure et son lien de billetterie jusqu'à la carte.
        par_salle: dict[int, dict] = {}
        for s in shows:
            i = ref_salle(s["cinema"])
            if i not in par_salle or s["start"] < par_salle[i]["start"]:
                par_salle[i] = s
        # Trié par date : `k[0]` est donc la prochaine séance du film, toutes
        # salles confondues. `n`, `d`, `c` et `v` s'en déduisent, on ne les
        # stocke plus — ils étaient redondants avec cette liste.
        #
        # Chaque entrée = [salle, jour, heure, billetterie]. L'heure et le lien
        # étaient auparavant lus dans agenda-index, qui ne couvre QUE le
        # répertoire : une reprise avait son bouton « Réserver », un film récent
        # de la watchlist n'en avait pas, alors que la fiche du cinéma, elle, le
        # proposait. Les porter ici les rend disponibles pour TOUS les films.
        # `""` quand la source ne donne pas de billetterie — le champ reste
        # présent pour que la forme des entrées ne varie pas. Le lien est écrit
        # ENTIER ici puis raccourci de son préfixe de salle en fin de boucle.
        k = sorted(
            (
                [i, s["start"][:10], s["start"][11:16], s.get("booking") or ""]
                for i, s in par_salle.items()
            ),
            key=lambda p: (p[1], p[2], p[0]),
        )
        for p in k:
            if p[3]:
                liens_salle.setdefault(p[0], []).append(p[3])
        entry = {
            "t": m["title"],
            "u": f"{BASE_PATH}{lang_prefix()}{movie_urls[key]}",
            "p": m["poster"] or "",
            "r": m.get("lb_rating") or 0,
            "y": m.get("year") or 0,
            "d": k[0][1],
            "k": k,
        }
        # Séance unique : le film ne passe QU'UNE fois dans toute la France sur
        # la fenêtre — même définition que `repertoire.count_unique()`, mais
        # appliquée ici à tout le catalogue et pas au seul répertoire. C'est
        # l'information la plus actionnable qu'on puisse donner à quelqu'un qui
        # a le film dans sa watchlist : elle transforme « il passe » en « c'est
        # maintenant ou jamais ». Se compte sur `shows` (toutes les séances du
        # film) et surtout PAS sur `k`, qui n'en garde qu'une par salle : un
        # film joué cinq fois dans la même salle a bien `len(k) == 1` sans être
        # une séance unique. Champ absent quand le film repasse : inutile de
        # peser sur l'index pour dire « non ».
        if len(shows) == 1:
            entry["x"] = 1
        # Indexé sous l'empreinte complète ET sous sa base sans l'année finale
        # (Letterboxd désambiguïse par « -2016 ») : le client tente les deux.
        wl_index.setdefault(empreinte, entry)
        base = re.sub(r"(19|20)\d\d$", "", empreinte)
        if base != empreinte:
            wl_index.setdefault(base, entry)

    # Factorisation des liens de billetterie : le préfixe commun part dans `_s`,
    # chaque séance ne garde que ce qui la distingue (l'identifiant de séance).
    # Une passe séparée, car le préfixe d'une salle n'est connu qu'une fois tous
    # ses films parcourus. Les entrées étant partagées entre l'empreinte
    # complète et sa base (même objet), on dédoublonne par identité — sinon on
    # raccourcirait deux fois les mêmes liens.
    for i, liens in liens_salle.items():
        salles[i][2] = _prefixe_billetterie(liens)
    vues: set[int] = set()
    for cle, entry in wl_index.items():
        if cle.startswith("_") or id(entry) in vues:
            continue
        vues.add(id(entry))
        for p in entry["k"]:
            if p[3]:
                p[3] = p[3][len(salles[p[0]][2]):]
    write_data("watchlist-index.json", wl_index)

    # ----- Index agenda (détail des séances, pour le calendrier .ics) -----
    # Même clé d'empreinte que la watchlist, mais la valeur porte le DÉTAIL de
    # chaque séance à venir (heure, cinéma, ville, coords, billetterie). Le
    # Worker `/calendar/<pseudo>.ics` croise la watchlist du membre avec ce
    # fichier et émet un événement de calendrier par séance. Séance compacte =
    # [start "YYYY-MM-DDTHH:MM", cinéma, ville, lat, lon, billetterie].
    #
    # Scope VOLONTAIREMENT restreint au RÉPERTOIRE (film sorti avant
    # REPERTOIRE_BEFORE) sur un horizon de 5 semaines : le calendrier sert à ne
    # pas rater une reprise rare, pas à recevoir 3 000 rappels pour un
    # blockbuster à 263 salles. Ça garde aussi le fichier assez léger pour être
    # parsé dans un Worker.
    AG_HORIZON = (today + timedelta(days=35)).isoformat()
    ag_index: dict[str, dict] = {}
    for key, m in movies.items():
        shows = by_movie.get(key)
        year = m.get("year")
        if not shows or not m.get("lb_url") or not year or year >= repertoire.REPERTOIRE_BEFORE:
            continue
        slug = m["lb_url"].rstrip("/").split("/film/")[-1]
        empreinte = lb_slug_key(slug)
        seances = []
        for s in sorted(shows, key=lambda s: s["start"]):
            if s["start"][:10] > AG_HORIZON:
                continue
            cin = cinemas[s["cinema"]]
            lat = cin.get("lat")
            lon = cin.get("lon")
            seances.append([
                s["start"][:16],
                cin["name"],
                cin.get("city") or "",
                round(lat, 4) if lat is not None else None,
                round(lon, 4) if lon is not None else None,
                s.get("booking") or "",
            ])
        if not seances:
            continue
        # Réalisateur(s) : `dk` = empreintes (une par réalisateur) pour le
        # matching côté /pour-moi/ (reco par affinité de réalisateur), `dn` = nom
        # affiché. Champ ignoré par le calendrier .ics et l'import de listes.
        directors = [d.strip() for d in (m.get("director") or "").split(",") if d.strip()]
        entry = {"t": m["title"], "u": f"{BASE_PATH}{lang_prefix()}{movie_urls[key]}", "s": seances,
                 "dk": [lb_slug_key(d) for d in directors], "dn": m.get("director") or ""}
        ag_index.setdefault(empreinte, entry)
        base = re.sub(r"(19|20)\d\d$", "", empreinte)
        if base != empreinte:
            ag_index.setdefault(base, entry)
    write_data("agenda-index.json", ag_index)

    # ----- Réalisateurs éligibles à « Ta cinémathèque » (page /cinematheque/) -----
    # Vivier du sélecteur : les réalisateurs qui ont AU MOINS 2 films de
    # répertoire à l'affiche (sinon il n'y a pas de rétrospective à composer).
    # Dérivé de agenda-index pour garantir la cohérence : chaque réalisateur
    # listé a bien des entrées dans l'index que cinematheque.js va lire. `dk` et
    # `dn` sont alignés (mêmes réalisateurs, dans le même ordre) par construction.
    cine_seen_u: set[str] = set()
    cine_dir_films: dict[str, set] = defaultdict(set)
    cine_dir_name: dict[str, str] = {}
    for entry in ag_index.values():
        if entry["u"] in cine_seen_u:
            continue
        cine_seen_u.add(entry["u"])
        names = [d.strip() for d in (entry.get("dn") or "").split(",") if d.strip()]
        for i, k in enumerate(entry.get("dk", [])):
            if i < len(names):
                cine_dir_name[k] = names[i]
                cine_dir_films[k].add(entry["u"])
    cine_dirs = sorted(
        ({"name": cine_dir_name[k], "key": k, "n": len(us)}
         for k, us in cine_dir_films.items() if len(us) >= 2),
        key=lambda x: (-x["n"], x["name"].lower()))
    # PARTAGÉ entre les deux langues (voir SHARED_PATHS) : ne contient que des
    # noms de réalisateurs, qui ne se traduisent pas. Écrit par la SEULE passe
    # française — voir la note sur film-directors.json plus bas, qui explique
    # pourquoi laisser la passe anglaise réécrire ces fichiers est un piège.
    if i18n.LANG == "fr":
        (SITE / "cinematheque-directors.json").write_text(
            json.dumps(cine_dirs, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    # ----- Index film -> réalisateur (pour la reco /pour-moi/) -----
    # La reco déduit les réalisateurs préférés du visiteur à partir de sa
    # watchlist + ses 4 favoris (lisibles depuis le Worker), en identifiant le
    # réalisateur de CHACUN de ces films VIA NOTRE catalogue — aucun fetch de
    # page film (celles-ci sont bloquées aux IP datacenter). Indexé par empreinte
    # de slug Letterboxd (+ replis titre), comme watchlist-index, pour matcher
    # les films renvoyés par le Worker. Couvre TOUT le catalogue (pas seulement
    # les films à l'affiche) : un film aimé mais non programmé compte quand même
    # pour l'affinité. Valeur = nom du réalisateur affiché.
    dir_index: dict[str, str] = {}
    for key, m in movies.items():
        director = m.get("director")
        if not director:
            continue
        keys = []
        if m.get("lb_url"):
            slug = m["lb_url"].rstrip("/").split("/film/")[-1]
            emp = lb_slug_key(slug)
            keys.append(emp)
            base = re.sub(r"(19|20)\d\d$", "", emp)
            if base != emp:
                keys.append(base)
        # Replis par titre (le Worker renvoie aussi le nom du film). On
        # indexe le titre FRANÇAIS **et** l'anglais quand ils diffèrent : le
        # Worker lit Letterboxd, dont le titre principal est le plus souvent
        # l'anglais international — sans ce second repli, la reco par
        # réalisateur ratait les films au titre français très éloigné.
        titres = {m["title"]}
        if m.get("title_en"):
            titres.add(m["title_en"])
        for titre in titres:
            title_emp = lb_slug_key(titre)
            if m.get("year"):
                keys.append(title_emp + str(m["year"]))
            keys.append(title_emp)
        for k in keys:
            dir_index.setdefault(k, director)
    # ⚠ ÉCRIT PAR LA SEULE PASSE FRANÇAISE, et ce n'est pas un détail.
    #
    # Ce fichier est partagé par les deux langues (SHARED_PATHS) : la dernière
    # passe qui l'écrit gagne. Or la passe anglaise reçoit un catalogue où
    # `title` porte DÉJÀ le titre anglais — la boucle ci-dessus y calculait donc
    # deux fois la même empreinte et n'indexait plus que l'anglais. Résultat
    # mesuré avant correction : 963 clés françaises perdues sur 2 084, et la
    # reco par réalisateur qui cessait de reconnaître les films dont Letterboxd
    # renvoie le titre français.
    #
    # La passe française, elle, voit `title` (français) ET `title_en` : elle
    # seule peut produire l'index bilingue complet.
    if i18n.LANG == "fr":
        (SITE / "film-directors.json").write_text(
            json.dumps(dir_index, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    # ----- Répertoire : le moteur éditorial du site -----
    # `rep_window` et `rep_shows` sont calculés plus haut (le seuil des fiches
    # réalisateur en dépend) : une seule définition, pas deux.
    # `cinemas` est désormais nécessaire : la sélection est plafonnée par ville
    # (et Paris y a un quota supérieur). Voir unique_screenings().
    rep_uniques = repertoire.unique_screenings(rep_shows, movies, cinemas)
    # Films qui ne passent qu'UNE fois en France sur la fenêtre. Dérivé de
    # unique_all() et pas d'un Counter local : une seule définition de la
    # séance unique dans tout le projet. Sert au badge de `seance_row()`, qui
    # apparaît sur trois pages aux contenus différents — sur une fiche
    # réalisateur, un film joué à Strasbourg ET à Nancy ne doit pas s'annoncer
    # comme une séance unique.
    uniques_keys = {s["movie"] for s in repertoire.unique_all(rep_shows)}
    # Tous les cycles (pas seulement ceux de l'accueil) : chacun a sa page.
    rep_cycles = repertoire.cycles(rep_shows, movies, cinemas, _fold_title, limit=None)
    cycle_urls: dict[str, str] = {}
    taken_cycles: dict[str, str] = {}
    for c in rep_cycles:
        slug = slugify(c["director"])[:60].strip("-") or "cycle"
        if slug in taken_cycles:
            slug = f"{slug}-{len(taken_cycles)}"
        taken_cycles[slug] = c["key"]
        cycle_urls[c["key"]] = f"/retrospectives/{slug}/"
    # Séances du répertoire indexées par salle : sert aux pages de cycle.
    rep_by_cinema = defaultdict(list)
    for s in rep_shows:
        rep_by_cinema[s["cinema"]].append(s)
    rep_venues = repertoire.heritage_venues(rep_window, rep_shows, cinemas)
    rep_cities = repertoire.city_stats(rep_shows, cinemas)
    n_rep_films = len({s["movie"] for s in rep_shows})
    n_rep_uniques = repertoire.count_unique(rep_shows)

    # ----- Accueil -----
    # Catalogue complet de « À l'affiche », classé par note Letterboxd d'abord :
    # le visiteur arrive sur les films les mieux notés parmi ce qui passe cette
    # semaine (à note égale, le plus diffusé passe devant, et les films sans note
    # fiable ferment la marche). Il peut retrier (titre, année, cinémas) ou
    # filtrer par version sans quitter la page — tri.js n'en montre que
    # PAGE_SIZE à la fois pour ne pas dérouler 931 cartes d'un coup. L'ordre du
    # HTML doit refléter le tri par défaut, pour les robots et les visiteurs
    # sans JavaScript (tri.js re-trie sur ce même critère, de façon stable).
    catalogue = sorted((m for m in movies.values() if by_movie[m["key"]]),
                       key=lambda m: (-(m.get("lb_rating") or 0),
                                      -MOVIE_VENUES[m["key"]], sort_title(m["title"])))
    films_html = "".join(
        movie_card(m, movie_urls,
                   f'<p class="meta">'
                   + tf("{n} cinéma{s}", n=MOVIE_VENUES[m["key"]],
                        s=plural(MOVIE_VENUES[m["key"]]))
                   + '</p>')
        for m in catalogue)
    # Liste complète repliée + tri alphabétique : 257 villes en vrac formaient
    # un mur de 57 % de la page (le « mur de pastilles » déjà refusé, en liste).
    cities_html = "".join(
        f'<li><a href="/ville/{slug}/">{esc(c["name"])}</a> '
        f'<span class="meta">'
        + tf("{n} ciné{s}", n=len(c["cinemas"]), s=plural(len(c["cinemas"])))
        + '</span></li>'
        for slug, c in sorted(cities.items(), key=lambda kv: kv[1]["name"]))
    majors = [s for s in BIG_CITY_SLUGS if s in cities]
    city_pills = " ".join(f'<a href="/ville/{s}/">{esc(cities[s]["name"])}</a>' for s in majors)
    # Cibles = URLs (avec BASE_PATH : le JSON échappe au préfixage automatique
    # de page(), qui ne touche que les attributs href/src)
    city_cmap = {c["name"]: f"{BASE_PATH}{lang_prefix()}/ville/{slug}/"
                 for slug, c in cities.items()}
    city_finder = city_search_nav(city_pills, city_cmap, len(cities))
    n_chain = sum(1 for c in cinemas.values() if c.get("chain"))
    n_inde = len(cinemas) - n_chain
    inventory = tf("{n} cinémas indépendants", n=n_inde)
    if n_chain:
        inventory += tf(" et {n} cinémas de chaîne", n=n_chain)
    # ----- Page « À l'affiche » (l'ancien accueil, devenu un onglet) -----
    # Elle garde l'intention à plus gros volume (« quel film voir ce soir »)
    # pendant que l'accueil se recentre sur le répertoire.
    affiche_body = f"""<p class="lead">{tf("{inventaire} répartis dans {v} villes, et "
                                            "{s} séances annoncées. La liste est refaite chaque nuit.",
                                            inventaire=inventory, v=len(cities),
                                            s=nombre(len(showtimes)))}</p>
<h2>{t("Choisissez votre ville")}</h2>
{city_finder}
<details class="all-cities"><summary>{tf("Toutes les villes ({n})", n=len(cities))}</summary>
<ul class="cities">{cities_html}</ul></details>
<h2>{t("Tous les films à l'affiche")}</h2>
{film_tools("film-list", "lb", catalogue)}
<div class="grid" id="film-list">{films_html}</div>
<div class="passerelle">
<p><span class="titre">{tf("{n} classiques sont aussi à l'affiche", n=n_rep_films)}</span>
<span class="meta">{t("Rétrospectives, copies restaurées et ciné-clubs, partout en France.")}</span></p>
<a class="bouton" href="/">{t("Voir le répertoire")}</a>
</div>"""
    write("/a-l-affiche/", page(
        tf("Films à l'affiche cette semaine : séances et horaires — {site}", site=SITE_NAME),
        tf("Quel film voir au cinéma cette semaine ? Séances et horaires de {c} cinémas "
           "dans {v} villes en France, indépendants et grandes enseignes. Mis à jour chaque jour.",
           c=len(cinemas), v=len(cities)),
        affiche_body, "/a-l-affiche/", h1=t("Quel film voir au cinéma cette semaine ?"),
        top_link=True))
    urls.append("/a-l-affiche/")

    # ----- Accueil : l'agenda du répertoire -----
    def seance_row(s: dict, data: bool = False, jour: str = "") -> str:
        """Une ligne d'agenda : l'heure d'abord, comme sur un programme.

        `data` ajoute sur le <li> les attributs dont « Dernière chance » a
        besoin pour filtrer par ville et par jour, trier par note et fabriquer
        un .ics sans re-télécharger d'index (chance.js lit la page qu'il a sous
        les yeux). L'accueil, lui, n'en a pas l'usage : autant ne pas alourdir
        son HTML.

        `jour` est le libellé de la journée, écrit dans la ligne elle-même et
        masqué en CSS. Il ne sert QUE au tri par note, qui casse le groupement
        par jour : sans lui, une liste classée par note n'annoncerait plus
        aucune date. En tri chronologique c'est l'en-tête de section qui la
        porte, et le libellé de la ligne resterait un doublon.
        """
        m, cin = movies[s["movie"]], cinemas[s["cinema"]]
        img = (f'<img src="{esc(m["poster"])}" alt="{esc(affiche_alt(m))}" loading="lazy">'
               if m["poster"] else '<span class="noposter">🎞️</span>')
        credits = " · ".join(filter(None, [
            m["director"], m["genre"],
            tf("{n} min", n=m["duration_min"]) if m["duration_min"] else "",
            version_label(s["version"])]))
        note = (f'<span class="note-lb" title="{esc(t("Note moyenne Letterboxd"))}">'
                f'{m["lb_rating"]}<span class="sur">/5</span></span>'
                if m.get("lb_rating") else "")
        # L'heure est le point d'entrée naturel vers la réservation : c'est la
        # séance précise que le visiteur vise dans un agenda. `hh` et pas
        # `heure` : ce dernier est la fonction de formatage importée d'i18n.
        hh = heure(s["start"])
        if s.get("booking"):
            hh = (f'<a href="{esc(s["booking"])}" target="_blank"'
                  f' rel="noopener noreferrer"'
                  f' title="{esc(t("Réserver cette séance (nouvel onglet)"))}">{hh}</a>')
        # URL de fiche SANS BASE_PATH ni langue : elle passe par _prefix_links()
        # comme les href, puisqu'elle est écrite dans un attribut… data-url, que
        # _prefix_links ne touche PAS. On la préfixe donc à la main ici.
        # `data-lb` vaut 0 pour un film sans note : le tri par note l'envoie
        # alors en queue, comme le fait renseigne() dans tri.js. L'écarter de
        # la liste ferait mentir le compte affiché juste au-dessus.
        attrs = (f' data-start="{s["start"][:16]}" data-city="{esc(cin["city"])}"'
                 f' data-title="{esc(m["title"])}"'
                 f' data-lb="{m.get("lb_rating") or 0}"'
                 f' data-lieu="{esc(cin["name"] + ", " + cin["city"])}"'
                 f' data-url="{BASE_PATH}{lang_prefix()}{movie_urls[s["movie"]]}"'
                 f' data-booking="{esc(s.get("booking") or "")}"' if data else "")
        jour_chip = (f'<span class="jour-inline">{esc(jour)}</span>'
                     if data and jour else "")
        return f"""<li class="seance"{attrs}>
<time class="heure{' reservable' if s.get("booking") else ''}" datetime="{s["start"][:16]}">{hh}</time>
<div class="vignette"><a href="{movie_urls[s["movie"]]}">{img}</a></div>
<div class="corps">
<h3 class="film"><a href="{movie_urls[s["movie"]]}">{esc(m["title"])}</a>
<span class="annee">{m["year"]}</span></h3>
<p class="meta">{esc(credits)}</p>
<p class="meta lieu"><strong><a href="{cinema_urls[s["cinema"]]}">{esc(cin["name"])}</a></strong>,
{esc(cin["city"])}{chain_badge(cin)}</p>
</div>
<div class="flags">{jour_chip}{note}{f'<span class="unique">{t("Séance unique")}</span>'
                                   if s["movie"] in uniques_keys else ""}</div>
</li>"""

    def agenda_par_jour(seances: list, data: bool = False) -> str:
        """Un agenda groupé par journée. Sert à l'accueil (une sélection) et à
        « Dernière chance » (tout), qui doivent se lire exactement pareil."""
        html_jours = ""
        par_jour: dict[str, list] = defaultdict(list)
        for s in seances:
            par_jour[s["start"][:10]].append(s)
        for iso in sorted(par_jour):
            d = date.fromisoformat(iso)
            rows = "".join(seance_row(s, data, jour_date(d))
                           for s in sorted(par_jour[iso], key=lambda x: x["start"]))
            # « Aujourd'hui »/« Demain » ne disent pas la date : on la précise.
            # Les autres jours sont déjà datés — l'ajouter ferait un doublon.
            libelle = date_label(d, today)
            precision = (f'<span class="jour-date">{jour_mois(d)}</span>'
                         if i18n.is_today_label(libelle) else "")
            html_jours += (f'<section class="jour"><h3 class="jour-titre">'
                           f'<span>{libelle}</span>{precision}'
                           f'</h3><ul class="seances">{rows}</ul></section>')
        return html_jours

    # `data=True` : l'accueil filtre désormais par ville, il a donc besoin des
    # mêmes attributs que « Dernière chance » (c'est `data-city` qui sert ici).
    # Douze lignes seulement : le surcoût de HTML est négligeable.
    agenda_html = agenda_par_jour(rep_uniques, data=True)

    # Villes DIFFUSATRICES de la sélection : uniquement celles qui programment
    # vraiment une de ces séances, jamais les 255 villes du site. Une liste qui
    # propose des villes sans résultat fait cliquer dans le vide.
    # ⚠️ Compté sur `rep_uniques`, c'est-à-dire exactement ce qui est affiché
    # au-dessus — si un jour la sélection change, la liste suit toute seule.
    home_villes = Counter(cinemas[s["cinema"]]["city"] for s in rep_uniques)
    # BOUTONS et non un <select>, contrairement à « Dernière chance » : là-bas le
    # menu liste une trentaine de villes, ici il y en a deux à quatre. Un menu
    # déroulant pour deux choix cache l'information derrière un clic, alors que
    # des boutons annoncent d'emblée les villes concernées. Même grammaire que
    # les boutons de tri (`aria-pressed`), c'est le même geste pour le visiteur.
    #
    # ⚠️ Les compteurs sont TOUS en séances, y compris « Toutes » : le <select>
    # mélangeait deux unités (« Toutes les villes (3) » = des villes, « Nantes
    # (7) » = des séances), ce qui se lisait mal une fois côte à côte.
    home_ville_btns = "".join(
        f'<button type="button" data-city="{esc(v)}" aria-pressed="false">'
        f'{esc(v)} ({n})</button>'
        for v, n in sorted(home_villes.items(), key=lambda kv: _fold_title(kv[0])))
    # Une seule ville dans la sélection : aucun choix réel à offrir.
    home_ville_tools = (f"""<div class="agenda-tools">
<span class="tri-filtre-nom">{t("Ville")}</span>
<span class="agenda-villes" role="group" aria-label="{esc(t("Filtrer par ville"))}">
<button type="button" data-city="" aria-pressed="true">{tf(
    "Toutes ({n})", n=len(rep_uniques))}</button>
{home_ville_btns}</span>
<p class="tri-compte" id="agenda-compte" role="status">{tf(
    "{n} séance{s} en France", n=len(rep_uniques), s=plural(len(rep_uniques)))}</p>
</div>""" if len(home_villes) > 1 else "")

    # Rétrospectives mises en avant sur l'accueil : jusqu'à 9, les plus
    # fournies d'abord (rep_cycles est déjà trié par nb de films puis séances).
    # On plafonne les cycles EXCLUSIVEMENT parisiens pour ne pas afficher « que
    # Paris » : la Cinémathèque et les salles du Quartier latin saturent sinon
    # le haut du classement. Un cycle qui tourne dans plusieurs villes (Paris
    # incluse) n'est pas concerné, c'est justement de la diversité.
    HOME_CYCLES, PARIS_CAP = 9, 3

    def _paris_only(c: dict) -> bool:
        return all(v == "Paris" for v in c["cities"])

    home_cycles: list[dict] = []
    n_paris = 0
    for c in rep_cycles:
        if len(home_cycles) >= HOME_CYCLES:
            break
        if _paris_only(c):
            if n_paris >= PARIS_CAP:
                continue
            n_paris += 1
        home_cycles.append(c)
    # Trop peu de cycles hors Paris pour atteindre 9 ? On complète avec les
    # parisiens écartés — mieux vaut des cartes remplies que des trous, sans
    # jamais dépasser ce que rep_cycles contient réellement.
    if len(home_cycles) < HOME_CYCLES:
        deja = {c["key"] for c in home_cycles}
        for c in rep_cycles:
            if len(home_cycles) >= HOME_CYCLES:
                break
            if c["key"] not in deja:
                home_cycles.append(c)

    cycles_html = ""
    for c in home_cycles:
        bande = poster_strip(c["movies"], movies, movie_urls, limit=6)
        salles_liens = ", ".join(
            f'<a href="{cinema_urls[cid]}">{esc(cinemas[cid]["name"])}</a>'
            for cid in c["cinemas"][:3])
        reste = len(c["cinemas"]) - 3
        if reste > 0:
            salles_liens += tf(" et {n} autre{s} salle{s2}",
                               n=reste, s=plural(reste), s2=plural(reste))
        villes_txt = (tf("{n} villes", n=len(c["cities"])) if len(c["cities"]) > 1
                      else esc(c["cities"][0]))
        cycles_html += f"""<article class="cycle">
<p class="eyebrow">{t("Rétrospective")}</p>
<h3 class="cycle-nom"><a href="{cycle_urls[c["key"]]}">{esc(c["director"])}</a></h3>
{bande}
<p class="meta">{tf("<strong>{n} films</strong> · {seances} séances · {villes}",
                    n=len(c["movies"]), seances=c["n_shows"], villes=villes_txt)}</p>
<p class="meta">{salles_liens}</p>
<p class="meta"><a class="more" href="{cycle_urls[c["key"]]}">{t("Voir le cycle →")}</a></p>
</article>"""

    salles_html = "".join(f"""<li class="salle">
<span class="rang">{i}</span>
<div class="salle-corps">
<h3 class="salle-nom"><a href="{cinema_urls[v["cinema"]]}">{esc(cinemas[v["cinema"]]["name"])}</a>
{chain_badge(cinemas[v["cinema"]])}</h3>
<p class="meta">{esc(cinemas[v["cinema"]]["city"])}</p>
</div>
<div class="jauge" role="img" aria-label="{esc(tf("{part} % de séances de répertoire", part=v["share"]))}">
<div class="jauge-piste"><div class="jauge-part" style="width:{v["share"]}%"></div></div>
<p class="jauge-txt">{tf("<strong>{part} %</strong> de répertoire · {rep} séances sur {total}",
                         part=v["share"], rep=v["n_rep"], total=v["n_total"])}</p>
</div></li>""" for i, v in enumerate(rep_venues[:8], 1))

    # Villes classées par nombre de films de répertoire (pas par démographie :
    # Tours programme plus de reprises que Lyon).
    top_rep_cities = sorted(rep_cities.items(),
                            key=lambda kv: (-kv[1]["films"], -kv[1]["seances"]))[:12]
    villes_html = "".join(
        f'<a class="ville" href="/ville/{slug}/">'
        f'<span>{esc(cities[slug]["name"] if slug in cities else slug)}</span>'
        f'<span class="ville-n">{tf("{n} films", n=st["films"])}</span></a>'
        for slug, st in top_rep_cities)
    raccourcis = ", ".join(
        f'<a href="/ville/{slug}/">{esc(cities[slug]["name"] if slug in cities else slug)} '
        f'<span class="racc-n">({tf("{n} séances", n=st["seances"])})</span></a>'
        for slug, st in top_rep_cities[:6])
    # Accueil : pas de pastilles de grandes villes. Elles listeraient Lyon ou
    # Nice, pauvres en reprises, alors que la ligne « villes les plus fournies »
    # ci-dessous donne les bonnes (Tours, Le Mans…). Ici, la recherche seule,
    # complétée par un bouton « Autour de moi ».
    #
    # Coordonnées représentatives par ville = moyenne des coords de ses cinémas.
    # proximite.js s'en sert pour classer les villes par distance après une
    # géolocalisation (faite DANS le navigateur, rien n'est envoyé). `r` = nb de
    # films de répertoire de la ville cette semaine, pour mettre en avant celles
    # qui en programment — c'est le cœur du site.
    villes_geo = []
    for slug, c in sorted(cities.items(), key=lambda kv: kv[1]["name"]):
        pts = [(cinemas[cid]["lat"], cinemas[cid]["lon"]) for cid in c["cinemas"]
               if cinemas[cid]["lat"] and cinemas[cid]["lon"]]
        if not pts:
            continue
        villes_geo.append({
            "n": c["name"],
            "u": f"{BASE_PATH}{lang_prefix()}/ville/{slug}/",
            "lat": round(sum(p[0] for p in pts) / len(pts), 4),
            "lon": round(sum(p[1] for p in pts) / len(pts), 4),
            "r": rep_cities.get(slug, {}).get("films", 0),
        })
    # Barre de recherche de ville + bouton « Autour de moi » côte à côte. On
    # reprend le gabarit de city_search_nav (recherche pilotée par film.js) et
    # on y ajoute le bouton, le statut, le conteneur de résultats et les
    # données de géolocalisation. Sans JavaScript, le bouton est masqué par le
    # CSS (une géolocalisation morte n'aurait aucun sens) ; la recherche, elle,
    # reste utilisable via ses suggestions.
    home_finder = f"""<nav class="city-jump home-finder">
<button type="button" id="proximite-btn" class="proximite-btn">{t("📍 Autour de moi")}</button>
<span class="city-search"><input id="city-search" type="search" autocomplete="off"
placeholder="{esc(tf("Chercher votre ville ({n} villes)…", n=len(cities)))}"
aria-label="{esc(t("Chercher une ville"))}">
<ul id="city-suggest" hidden></ul></span>
<script type="application/json" id="city-map">{json.dumps(city_cmap, ensure_ascii=False)}</script>
</nav>
<p id="proximite-status" class="map-status" role="status" hidden></p>
<div id="proximite" hidden></div>
<script type="application/json" id="villes-geo">{json.dumps(villes_geo, ensure_ascii=False)}</script>
<script src="/assets/film.js" defer></script>
<script src="/assets/proximite.js" defer></script>"""

    # Anniversaires de l'année : films de patrimoine qui fêtent un cap rond ET
    # repassent en salle (ils ont des séances à venir). Filon éditorial mis en
    # avant sur l'accueil. Le cap le plus ancien d'abord (le plus marquant),
    # puis les mieux notés.
    anniv_films = sorted(
        ((age, m) for k, m in movies.items()
         if by_movie.get(k) and (age := anniversaire_age(m))),
        key=lambda t: (-t[0], -(t[1].get("lb_rating") or 0)))
    HOME_ANNIV = 12
    anniv_cards = "".join(movie_card(m, movie_urls, show_classic=False)
                          for _, m in anniv_films[:HOME_ANNIV])
    reste_anniv = len(anniv_films) - HOME_ANNIV
    anniv_more = (f'<p class="meta">'
                  + tf("Et {n} autre{s} film{s2} fêtent un cap cette année.",
                       n=reste_anniv, s=plural(reste_anniv), s2=plural(reste_anniv))
                  + f' <a class="more" href="/classiques/">'
                    f'{t("Parcourir les classiques →")}</a></p>'
                  if reste_anniv > 0 else "")
    anniv_section = (f"""<h2>{tf("🎂 Les anniversaires de {annee}", annee=TODAY.year)}</h2>
<p class="meta">{tf("{n} films de patrimoine fêtent un anniversaire rond cette année "
                    "(un demi-siècle, un centenaire…) et repassent en salle. "
                    "L'occasion de les revoir sur grand écran.", n=len(anniv_films))}</p>
<div class="grid">{anniv_cards}</div>
{anniv_more}""" if anniv_films else "")

    n_rep_cines = len({s["cinema"] for s in rep_shows})
    n_rep_villes = len(rep_cities)
    body = f"""<p class="lead">{t("Les films anciens qui repassent en salle cette semaine, "
                                  "partout en France : reprises, copies restaurées, séances "
                                  "de ciné-club.")}
{tf("<strong>{n} de ces séances n'ont pas de deuxième date.</strong>", n=n_rep_uniques)}</p>

<div class="compteurs">
<div class="compteur"><b>{n_rep_films}</b><span>{t("films de répertoire")}</span></div>
<div class="compteur"><b>{nombre(len(rep_shows))}</b><span>{t("séances cette semaine")}</span></div>
<div class="compteur"><b>{n_rep_cines}</b><span>{t("cinémas")}</span></div>
<div class="compteur"><b>{n_rep_villes}</b><span>{t("villes")}</span></div>
<div class="compteur compteur-fort"><b>{n_rep_uniques}</b><span>{t("séances uniques")}</span></div>
</div>

<h2>{t("Choisissez votre ville")}</h2>
{home_finder}
<p class="meta">{tf("Les villes les plus fournies : {liste}.", liste=raccourcis)}</p>

<div class="passerelle wl-cta">
<p><span class="titre">{t("Vous êtes sur Letterboxd ?")}</span>
<span class="meta">{tf("Entrez votre pseudo : {site} vous dit lesquels de vos films à voir "
                       "sont à l'affiche <strong>et vous recommande des reprises selon vos "
                       "réalisateurs préférés</strong>. Tout se passe dans votre navigateur.",
                       site=SITE_NAME)}</span></p>
<button type="button" class="bouton bouton-lb" data-lb-open>{t("Entrer mon pseudo")}</button>
<a class="bouton" href="/ma-watchlist/">{t("Ma watchlist en détail →")}</a>
</div>

<!-- Recommandations par réalisateur, injectées par lb-reco.js quand le visiteur
     s'est connecté (portail Letterboxd). Absent du HTML pour un visiteur non
     connecté et pour les robots : purement personnel. -->
<div id="reco-home" data-agenda="{BASE_PATH}{lang_prefix()}/agenda-index.json" data-wl="{BASE_PATH}{lang_prefix()}/watchlist-index.json" data-directors="{BASE_PATH}/film-directors.json" hidden></div>
<script src="/assets/lb-reco.js" defer></script>

<h2>{t("À ne pas rater")}</h2>
<p class="meta">{t("Des séances qui ne repassent nulle part ailleurs en France cette semaine.")}</p>
<p class="legende"><span class="puce">4.4<span class="sur">/5</span></span>
{t("Note moyenne donnée par les spectateurs de")}
<a href="https://letterboxd.com" rel="noopener">Letterboxd</a>.
{t("Les séances ci-dessous sont les mieux notées de la semaine.")}</p>
<div id="agenda-uniques">
{home_ville_tools}
{agenda_html or f'<p>{t("Aucune séance unique repérée cette semaine.")}</p>'}
<p class="agenda-vide" id="agenda-vide" hidden>{t(
    "Aucune de ces séances n'est dans cette ville.")}</p>
</div>
<p class="meta"><a class="more" href="/derniere-chance/">{tf(
    "Les {n} séances sans deuxième date, ville par ville →", n=n_rep_uniques)}</a></p>
<script src="/assets/agenda-ville.js" defer></script>

<h2>{t("Rétrospectives en cours")}</h2>
<p class="meta">{t("Les cycles programmés en ce moment, salle par salle.")}
<a class="more" href="/retrospectives/">{t("Toutes les rétrospectives →")}</a></p>
<div class="cycles">{cycles_html or f'<p>{t("Aucun cycle en cours.")}</p>'}</div>

<div class="passerelle cine-cta">
<p><span class="titre">{t("🎞️ Compose ta cinémathèque")}</span>
<span class="meta">{tf("Choisis un réalisateur : {site} réunit toutes ses séances de "
                       "répertoire de France en une rétrospective à toi, à mettre dans ton "
                       "agenda. Ne subis plus la séance unique à 400 km, programme-la.",
                       site=SITE_NAME)}</span></p>
<a class="bouton" href="/cinematheque/">{t("Composer ma cinémathèque →")}</a>
</div>

{anniv_section}
<h2>{t("Salles de patrimoine")}</h2>
<p class="meta">{t("Les cinémas qui consacrent la plus grande part de leurs séances de la "
                   "semaine au répertoire, ces films ressortis en salle plutôt qu'aux "
                   "nouveautés. Un pourcentage, pas un volume : une petite salle qui ne "
                   "programme que des reprises devance un multiplexe.")}
<a class="more" href="/salles-patrimoine/">{t("Le classement complet →")}</a></p>
<ul class="salles">{salles_html}</ul>

<h2>{t("Où voir du répertoire")}</h2>
<p class="meta">{tf("{n} villes sur {total} programment au moins une reprise cette semaine.",
                    n=n_rep_villes, total=len(cities))}</p>
<div class="villes">{villes_html}</div>

<div class="passerelle">
<p><span class="titre">{t("Vous cherchez une sortie récente ?")}</span>
<span class="meta">{tf("{n} films à l'affiche cette semaine dans {c} cinémas, "
                       "indépendants et grandes enseignes.",
                       n=len(movies), c=len(cinemas))}</span></p>
<a class="bouton" href="/a-l-affiche/">{t("Voir ce qui est à l'affiche")}</a>
</div>"""
    write("/", page(
        tf("Reprises et rétrospectives au cinéma en France — {site}", site=SITE_NAME),
        tf("Quel classique voir en salle ? {n} reprises, versions restaurées et "
           "rétrospectives à l'affiche cette semaine dans {c} cinémas en France. "
           "Cherchez votre ville.", n=n_rep_films, c=n_rep_cines),
        body, "/", h1=t("Ce soir, un classique passe près de chez vous"),
        top_link=True))
    urls.append("/")

    # ----- Page « Dernière chance » : toutes les séances uniques -----
    # L'accueil n'en montre qu'une douzaine, les mieux notées : c'est une
    # sélection éditoriale. Ici on donne le catalogue entier, notes ou pas,
    # parce que c'est la promesse chiffrée du site (« N séances n'ont pas de
    # deuxième date ») et qu'un visiteur de Quimper doit pouvoir vérifier ce
    # que ce nombre contient POUR LUI.
    #
    # Le filtre ville est un <select>, pas une recherche : ici le visiteur ne
    # cherche pas une ville précise dans les 257 du pays, il regarde ce qui
    # existe parmi la petite centaine qui programme une séance unique. Une
    # liste qu'on déroule est le bon geste, et elle annonce au passage les
    # villes concernées.
    #
    # Le filtre de JOUR suit la même logique, avec une nuance : ses options
    # sont dans l'ordre de la semaine, jamais alphabétique. « Jeudi » avant
    # « Lundi » dans un agenda n'aurait aucun sens, et la valeur transportée
    # est la DATE ISO, pas le nom du jour : la fenêtre peut déborder sur la
    # semaine suivante et deux « lundi » ne seraient plus distinguables.
    chance_shows = repertoire.unique_all(rep_shows)
    chance_villes = Counter(cinemas[s["cinema"]]["city"] for s in chance_shows)
    chance_opts = "".join(
        f'<option value="{esc(v)}">{esc(v)} ({n})</option>'
        for v, n in sorted(chance_villes.items(), key=lambda kv: _fold_title(kv[0])))
    n_chance_villes = len(chance_villes)
    chance_jours = Counter(s["start"][:10] for s in chance_shows)
    # `data-label` porte le libellé SANS son compte : c'est lui que chance.js
    # recopie dans le compteur (« 12 séances · Jeudi 21 août »), où répéter le
    # nombre entre parenthèses ferait doublon avec le nombre juste à gauche.
    chance_jours_opts = "".join(
        f'<option value="{iso}" data-label="{esc(jour_date(date.fromisoformat(iso)))}">'
        f'{esc(jour_date(date.fromisoformat(iso)))} ({n})</option>'
        for iso, n in sorted(chance_jours.items()))
    chance_body = f"""<p class="lead">{tf(
        "Ces <strong>{n} films de répertoire</strong> ne passent qu'une seule fois en "
        "France cette semaine, dans {v} villes et sur {j} jours. Pas de deuxième date, "
        "pas de reprise le lendemain dans la salle d'à côté. Choisissez votre ville et "
        "votre jour, et classez-les par note si vous cherchez d'abord le meilleur film.",
        n=len(chance_shows), v=n_chance_villes, j=len(chance_jours))}</p>

<div class="chance-tools">
<label class="tri-filtre"><span class="tri-filtre-nom">{t("Ville")}</span>
<select id="chance-ville">
<option value="">{tf("Toutes les villes ({n})", n=n_chance_villes)}</option>
{chance_opts}</select></label>
<label class="tri-filtre"><span class="tri-filtre-nom">{t("Jour")}</span>
<select id="chance-jour">
<option value="">{tf("Tous les jours ({n})", n=len(chance_jours))}</option>
{chance_jours_opts}</select></label>
<label class="tri-filtre"><span class="tri-filtre-nom">{t("Ordre")}</span>
<select id="chance-tri">
<option value="date">{t("Par date")}</option>
<option value="note">{t("Par note Letterboxd")}</option>
</select></label>
<p class="tri-compte" id="chance-compte" role="status">{tf(
    "{n} séance{s} en France", n=len(chance_shows), s=plural(len(chance_shows)))}</p>
</div>

{agenda_par_jour(chance_shows, data=True) or f'<p>{t("Aucune séance unique repérée cette semaine.")}</p>'}
<ul class="seances par-note" id="chance-note"></ul>
<p class="chance-vide" id="chance-vide" hidden>{t(
    "Aucune séance unique ne correspond. Élargissez le jour ou la ville.")}</p>

<div class="chance-export">
<button type="button" id="chance-ics" class="bouton">{t("＋ Ajouter ces séances à mon agenda")}</button>
<p class="meta">{t("Un fichier .ics à ouvrir dans Google Agenda, Apple Calendrier ou "
                   "Outlook. Les filtres s'appliquent : choisissez votre ville et votre "
                   "jour avant d'exporter et vous n'emportez que ce qui vous concerne.")}</p>
</div>
<script src="/assets/ics.js" defer></script>
<script src="/assets/chance.js" defer></script>"""
    write("/derniere-chance/", page(
        tf("Dernière chance : les séances uniques de la semaine — {site}", site=SITE_NAME),
        tf("{n} films de répertoire ne passent qu'une seule fois en France cette semaine. "
           "Toutes les séances sans deuxième date, ville par ville, avec la réservation.",
           n=len(chance_shows)),
        chance_body, "/derniere-chance/", h1=t("Dernière chance"), top_link=True))
    urls.append("/derniere-chance/")

    # ----- Abonnements par ville : un .ics et un RSS par ville -----
    # Voir la note au-dessus de ics_escape() : ces fichiers sont générés pour
    # TOUTES les villes, y compris celles qui n'ont rien cette semaine. Une URL
    # d'abonnement qui disparaît est une URL à laquelle plus personne ne se
    # réabonne.
    rep_par_ville: dict[str, list] = defaultdict(list)
    for s in rep_shows:
        rep_par_ville[cinemas[s["cinema"]]["city_slug"]].append(s)

    horodatage = datetime.now(timezone.utc)
    stamp_ics = horodatage.strftime("%Y%m%dT%H%M%SZ")

    def en_utc(local_iso: str) -> datetime:
        """Une heure locale française sans fuseau → un instant UTC.
        On applique la règle européenne de fetch_data (jamais zoneinfo : voir
        la note de decalage_paris, la machine de dev n'a pas de base de
        fuseaux et le CI si)."""
        naif = datetime.fromisoformat(local_iso[:16])
        approx = naif.replace(tzinfo=timezone.utc)
        return (naif - decalage_paris(approx)).replace(tzinfo=timezone.utc)

    caldesc = t("Les films de répertoire à l'affiche, mis à jour chaque nuit.")

    def ics_ville(ville: str, seances: list) -> str:
        lignes = [
            "BEGIN:VCALENDAR", "VERSION:2.0",
            "PRODID:-//Seanceo//Repertoire//FR", "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{ics_escape(tf('Répertoire à {ville}', ville=ville))}",
            f"X-WR-CALDESC:{ics_escape(caldesc)}",
            "X-WR-TIMEZONE:Europe/Paris",
            # Les agendas qui respectent cette extension espacent leurs
            # rafraîchissements : inutile de re-télécharger plus souvent que le
            # build, qui tourne une fois par nuit.
            "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
        ]
        for s in sorted(seances, key=lambda x: x["start"]):
            m, cin = movies[s["movie"]], cinemas[s["cinema"]]
            debut = s["start"][:16].replace("-", "").replace(":", "") + "00"
            fin_dt = datetime.fromisoformat(s["start"][:16]) + timedelta(
                minutes=m.get("duration_min") or 120)
            desc = []
            if m.get("director"):
                desc.append(tf("De {realisateur}", realisateur=m["director"]))
            if s.get("booking"):
                desc.append(t("Réserver :") + " " + s["booking"])
            desc.append(t("Fiche :") + " " + BASE_URL + lang_prefix() + movie_urls[s["movie"]])
            # UID STABLE : même séance = même identifiant d'un build à l'autre,
            # sinon chaque nuit l'agenda de l'abonné effacerait puis recréerait
            # tous ses événements (et perdrait ses rappels).
            uid = f"{s['cinema']}-{s['movie']}-{debut}@seanceo"
            lignes += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp_ics}",
                f"DTSTART:{debut}",
                f"DTEND:{fin_dt.strftime('%Y%m%dT%H%M00')}",
                f"SUMMARY:{ics_escape('🎬 ' + m['title'])}",
                f"LOCATION:{ics_escape(cin['name'] + ', ' + cin['city'])}",
                f"DESCRIPTION:{ics_escape(chr(10).join(desc))}",
                f"URL:{s.get('booking') or BASE_URL + lang_prefix() + movie_urls[s['movie']]}",
                "END:VEVENT",
            ]
        lignes.append("END:VCALENDAR")
        # Le repliage à 75 octets s'applique à TOUTES les lignes, ici et pas au
        # cas par cas : un en-tête traduit ou un nom de salle inhabituellement
        # long échapperait sinon à la règle (constaté sur X-WR-CALDESC).
        return "\r\n".join(ics_fold(l) for l in lignes) + "\r\n"

    def rss_ville(slug: str, ville: str, seances: list) -> str:
        page_url = f"{BASE_URL}{lang_prefix()}/ville/{slug}/"
        # UN ITEM PAR FILM, pas par séance : un lecteur RSS n'a pas à recevoir
        # dix lignes pour le même film qui passe dix fois. La date affichée est
        # celle de sa PROCHAINE séance dans la ville.
        par_film: dict[str, list] = defaultdict(list)
        for s in seances:
            par_film[s["movie"]].append(s)
        items = []
        for mk, ss in sorted(par_film.items(), key=lambda kv: min(x["start"] for x in kv[1])):
            m = movies[mk]
            ss = sorted(ss, key=lambda x: x["start"])
            salles = sorted({cinemas[x["cinema"]]["name"] for x in ss})
            corps = tf("{titre} ({annee}) repasse à {ville} : {n} séance(s), à partir du "
                       "{date} à {heure}, {salles}.",
                       titre=m["title"], annee=m.get("year") or "", ville=ville,
                       n=len(ss), date=jour_mois(date.fromisoformat(ss[0]["start"][:10])),
                       heure=heure(ss[0]["start"]), salles=", ".join(salles))
            lien = f"{BASE_URL}{lang_prefix()}{movie_urls[mk]}"
            # GUID = film + date de sa première séance : le même film reprogrammé
            # plus tard redevient une nouveauté dans le lecteur, alors qu'un
            # simple rafraîchissement du site ne republie rien.
            items.append(f"""<item>
<title>{esc(m["title"])}</title>
<link>{esc(lien)}</link>
<guid isPermaLink="false">{esc(lien)}#{ss[0]["start"][:10]}</guid>
<pubDate>{format_datetime(en_utc(ss[0]["start"]))}</pubDate>
<description>{esc(corps)}</description>
</item>""")
        return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{esc(tf("Répertoire à {ville} — {site}", ville=ville, site=SITE_NAME))}</title>
<link>{esc(page_url)}</link>
<atom:link href="{esc(page_url)}repertoire.xml" rel="self" type="application/rss+xml"/>
<description>{esc(tf("Les films de répertoire à l'affiche à {ville} : reprises, copies "
                     "restaurées et séances de ciné-club.", ville=ville))}</description>
<language>{i18n.LANG}</language>
<lastBuildDate>{format_datetime(horodatage)}</lastBuildDate>
<ttl>720</ttl>
{"".join(items)}
</channel>
</rss>
"""

    for slug, city in cities.items():
        seances = rep_par_ville.get(slug, [])
        write_raw(f"/ville/{slug}/repertoire.ics", ics_ville(city["name"], seances))
        write_raw(f"/ville/{slug}/repertoire.xml", rss_ville(slug, city["name"], seances))

    # ----- Page Salles de patrimoine -----
    salles_full = "".join(f"""<li class="salle">
<span class="rang">{i}</span>
<div class="salle-corps">
<h3 class="salle-nom"><a href="{cinema_urls[v["cinema"]]}">{esc(cinemas[v["cinema"]]["name"])}</a>
{chain_badge(cinemas[v["cinema"]])}</h3>
<p class="meta"><a href="/ville/{cinemas[v["cinema"]]["city_slug"]}/">{esc(cinemas[v["cinema"]]["city"])}</a></p>
</div>
<div class="jauge" role="img" aria-label="{esc(tf("{part} % de séances de répertoire", part=v["share"]))}">
<div class="jauge-piste"><div class="jauge-part" style="width:{v["share"]}%"></div></div>
<p class="jauge-txt">{tf("<strong>{part} %</strong> de répertoire · {rep} séances sur {total}",
                         part=v["share"], rep=v["n_rep"], total=v["n_total"])}</p>
</div></li>""" for i, v in enumerate(rep_venues, 1))
    venues_body = f"""<p class="lead">{tf(
        "Une salle de patrimoine, ici, désigne un cinéma dont une grande part de la "
        "programmation est du répertoire : des films ressortis en salle (versions "
        "restaurées, reprises, séances de ciné-club), par opposition aux sorties "
        "récentes. Le classement mesure la <strong>part</strong> de ces séances de "
        "répertoire dans le total des séances de la salle sur la semaine. C'est donc "
        "un pourcentage, pas un décompte de rétrospectives ni le nombre de films à "
        "l'affiche : compter en volume mettrait les multiplexes en tête, puisqu'ils "
        "programment plus de tout. Il faut au moins {min} séances dans la semaine "
        "pour y figurer.", min=repertoire.VENUE_MIN_SHOWS)}</p>
<ul class="salles">{salles_full}</ul>
<p class="meta"><a class="more" href="/carte/">{t("Retrouver ces salles sur la carte →")}</a></p>"""
    write("/salles-patrimoine/", page(
        tf("Les salles de patrimoine en France : où voir du répertoire — {site}", site=SITE_NAME),
        t("Quels cinémas programment le plus de films de répertoire en France ? Classement "
          "des salles par part de reprises, rétrospectives et copies restaurées dans leur "
          "programmation."),
        venues_body, "/salles-patrimoine/", h1=t("Salles de patrimoine"), top_link=True))
    urls.append("/salles-patrimoine/")

    # ----- Page Classiques & rétrospectives -----
    # Classement unique par note Letterboxd (choix éditorial) : du chef-d'œuvre
    # plébiscité au moins aimé ; les films sans note fiable ferment la marche.
    classics = [m for m in movies.values() if is_classic(m) and by_movie[m["key"]]]
    rated = sorted((m for m in classics if m.get("lb_rating")),
                   key=lambda m: (-m["lb_rating"], -len(by_movie[m["key"]])))
    unrated = sorted((m for m in classics if not m.get("lb_rating")),
                     key=lambda m: -len(by_movie[m["key"]]))

    def classic_card(m: dict, rank: int | None = None) -> str:
        n = MOVIE_VENUES.get(m["key"], 0)
        # Le rang est isolé dans son propre <span> : dès que le visiteur trie
        # autrement (titre, année…), tri.js le masque — un « n° 3 » affiché
        # en quatrième position serait un mensonge.
        rang = (f'<span class="rang-lb">{tf("n° {rang}", rang=rank)}</span> · '
                if rank else "")
        extra = f'<p class="meta">{rang}{tf("{n} cinéma{s}", n=n, s=plural(n))}</p>'
        # show_classic=False : ici tout est classique, le badge serait du bruit.
        # La note vient de movie_card() comme partout ailleurs — la répéter ici
        # la faisait apparaître deux fois sur la même carte.
        return movie_card(m, movie_urls, extra, show_classic=False)

    # Une seule liste, triable et filtrable : les films notés dans l'ordre du
    # classement, puis ceux qu'on ne sait pas noter. tri.js n'en affiche que
    # PAGE_SIZE à la fois (313 cartes d'un bloc = 20 écrans desktop, 60 mobile)
    # et ajoute un « Afficher plus » ; sans JavaScript, tout reste visible.
    classics_html = ("".join(classic_card(m, i) for i, m in enumerate(rated, 1))
                     + "".join(classic_card(m) for m in unrated))
    n_classic_cines = len({s["cinema"] for m in classics for s in by_movie[m["key"]]})
    classics_body = f"""<p class="lead">{tf(
        "{n} films de plus de {age} ans repassent en ce moment dans {c} cinémas en "
        "France. Ils sont classés par la note que leur donnent les spectateurs de",
        n=len(classics), age=CLASSIC_AGE_YEARS, c=n_classic_cines)}
<a href="https://letterboxd.com" rel="noopener">Letterboxd</a>.</p>
{city_finder}
{film_tools("film-list", "lb", classics)}
<div class="grid" id="film-list">{classics_html or f'<p>{t("Aucune reprise annoncée en ce moment.")}</p>'}</div>"""
    write("/classiques/", page(
        tf("Films classiques et rétrospectives au cinéma — {site}", site=SITE_NAME),
        tf("Quel film classique revoir en salle ? {n} reprises, rétrospectives et "
           "versions restaurées à l'affiche en France, classées par note Letterboxd.",
           n=len(classics)),
        classics_body, "/classiques/", h1=t("Classiques & rétrospectives à l'affiche"),
        top_link=True))
    urls.append("/classiques/")

    # ----- Pages de rétrospective (une par cycle) -----
    # Un cycle est ancré dans une salle : on présente donc le programme salle
    # par salle, avec les horaires. C'est ce qu'un spectateur vient chercher.
    for c in rep_cycles:
        path = cycle_urls[c["key"]]
        films_du_cycle = set(c["movies"])
        blocs = []
        evenements = []  # ScreeningEvent : une séance = un événement daté
        for cid in c["cinemas"]:
            cinema = cinemas[cid]
            par_film = defaultdict(list)
            for s in rep_by_cinema[cid]:
                if s["movie"] in films_du_cycle:
                    par_film[s["movie"]].append(s)
            if not par_film:
                continue
            for mk, ss in par_film.items():
                for s in ss:
                    evenements.append(screening_event(s, movies[mk], cinema))
            cartes = []
            for mk, ss in sorted(par_film.items(),
                                 key=lambda kv: sorted(kv[1], key=lambda s: s["start"])[0]["start"]):
                jours = defaultdict(list)
                for s in sorted(ss, key=lambda x: x["start"])[:8]:
                    jours[s["start"][:10]].append(s)
                horaires = " ".join(
                    f'<span class="day">{date_label(date.fromisoformat(d), today)}</span>{showtime_pills(v)}'
                    for d, v in sorted(jours.items()))
                cartes.append(movie_card(movies[mk], movie_urls, horaires,
                                         show_classic=False))
            blocs.append(f"""<section class="cinema-block">
<h2><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h2>
<p class="meta"><a href="/ville/{cinema["city_slug"]}/">{esc(cinema["city"])}</a>,
{tf("{n} film{s} du cycle", n=len(par_film), s=plural(len(par_film)))}</p>
<div class="films">{"".join(cartes)}</div></section>""")

        affiches = poster_strip(c["movies"], movies, movie_urls)
        titres = ", ".join(movies[k]["title"] for k in c["movies"])
        tronque = len(c["cities"]) > 6
        villes_txt = ", ".join(c["cities"][:6]) + ("…" if tronque else "")
        # Pas de point final après « … » : « Montreuil…. » est disgracieux.
        fin = "" if tronque else "."
        n_films, n_salles = len(c["movies"]), len(c["cinemas"])
        body = f"""<p class="lead">{tf(
        "<strong>{n} films</strong> de {realisateur} passent cette semaine dans "
        "{salles} salle{s} ({villes}){fin} Soit {seances} séances en tout.",
        n=n_films, realisateur=esc(c["director"]), salles=n_salles,
        s=plural(n_salles), villes=esc(villes_txt), fin=fin, seances=c["n_shows"])}</p>
{affiches}
<p class="meta">{tf("Au programme : {titres}.", titres=esc(titres))}</p>
<p class="cine-extend"><a class="bouton" href="/cinematheque/?d={quote(c["director"])}">{tf("🎞️ Compose ta rétrospective {realisateur} →", realisateur=esc(c["director"]))}</a></p>
{"".join(blocs)}
<p class="meta"><a class="more" href="/retrospectives/">{t("← Toutes les rétrospectives en cours")}</a></p>"""
        # @graph : la page de collection ET chacune de ses séances. Le
        # ScreeningEvent est le type que Google attend pour les horaires de
        # cinéma — le CollectionPage seul ne décrivait aucune date, donc rien
        # d'exploitable en résultat enrichi.
        titre_cycle = tf("Rétrospective {realisateur}", realisateur=c["director"])
        jsonld = {"@context": "https://schema.org", "@graph": [
            {"@type": "CollectionPage",
             "name": titre_cycle,
             "url": f"{BASE_URL}{lang_prefix()}{path}",
             "about": {"@type": "Person", "name": c["director"]}},
            *evenements,
        ]}
        write(path, page(
            tf("Rétrospective {realisateur} : où voir ses films en salle — {site}",
               realisateur=c["director"], site=SITE_NAME),
            tf("Où voir les films de {realisateur} au cinéma ? {n} films à l'affiche "
               "cette semaine en {seances} séances, dans {salles} salle(s) : {villes}.",
               realisateur=c["director"], n=n_films, seances=c["n_shows"],
               salles=n_salles, villes=villes_txt),
            body, path, jsonld, h1=titre_cycle, top_link=True))
        urls.append(path)

    # ----- Index des rétrospectives -----
    if rep_cycles:
        index_cartes = "".join(f"""<article class="cycle">
<p class="eyebrow">{t("Rétrospective")}</p>
<h3 class="cycle-nom"><a href="{cycle_urls[c["key"]]}">{esc(c["director"])}</a></h3>
{poster_strip(c["movies"], movies, movie_urls, limit=6)}
<p class="meta">{tf("<strong>{n} films</strong> · {seances} séances · {villes}",
                    n=len(c["movies"]), seances=c["n_shows"],
                    villes=tf("{n} ville{s}", n=len(c["cities"]),
                              s=plural(len(c["cities"]))))}</p>
<p class="meta">{esc(", ".join(c["cities"][:4]))}{"…" if len(c["cities"]) > 4 else ""}</p>
</article>""" for c in rep_cycles)
        n_cyc_films = len({k for c in rep_cycles for k in c["movies"]})
        index_body = f"""<p class="lead">{tf(
            "<strong>{n} cinéastes</strong> font l'objet d'un cycle en ce moment, soit "
            "{films} films au total. On compte un cycle dès qu'une même salle passe au "
            "moins deux films du même réalisateur dans la semaine.",
            n=len(rep_cycles), films=n_cyc_films)}</p>
<div class="cycles">{index_cartes}</div>
<p class="meta"><a class="more" href="/">{t("← L'agenda du répertoire")}</a></p>"""
        write("/retrospectives/", page(
            tf("Rétrospectives et cycles au cinéma en France — {site}", site=SITE_NAME),
            tf("Quelles rétrospectives voir en salle ? {n} cycles de cinéastes programmés "
               "cette semaine en France, salle par salle : {films} films à l'affiche.",
               n=len(rep_cycles), films=n_cyc_films),
            index_body, "/retrospectives/", h1=t("Rétrospectives en cours"), top_link=True))
        urls.append("/retrospectives/")

    # ----- Fiches réalisateur (une par cinéaste éligible) -----
    # Une page de rétrospective (/retrospectives/<nom>/) est VOLATILE : elle
    # n'existe que tant qu'une salle enchaîne deux films du cinéaste. Ces
    # fiches-ci, elles, tiennent tant que le réalisateur a quelque chose à
    # l'affiche, et répondent à la requête permanente « films de X au cinéma ».
    # Elles ferment aussi un trou de maillage : les 967 fiches film citaient un
    # réalisateur sans jamais pouvoir renvoyer vers lui.
    real_cycles = {c["key"]: c for c in rep_cycles}
    rep_by_movie: dict[str, list] = defaultdict(list)
    for s in rep_shows:
        rep_by_movie[s["movie"]].append(s)

    REAL_AGENDA = 12  # séances de répertoire listées avant de renvoyer aux fiches

    for nom in realisateurs:
        path = realisateur_urls[nom]
        films = real_films[nom]
        # Répertoire d'abord, puis les mieux notés : la page ouvre sur ce que
        # le site est venu montrer.
        classes = sorted(films, key=lambda k: (k not in rep_keys,
                                               -(movies[k].get("lb_rating") or 0),
                                               sort_title(movies[k]["title"])))
        n_rep = len(films & rep_keys)
        salles = {s["cinema"] for k in films for s in by_movie[k]}
        villes = {cinemas[s["cinema"]]["city"] for k in films for s in by_movie[k]}
        n_seances = sum(len(by_movie[k]) for k in films)

        cartes = "".join(
            movie_card(movies[k], movie_urls,
                       f'<p class="meta">'
                       + tf("{n} cinéma{s}", n=MOVIE_VENUES[k], s=plural(MOVIE_VENUES[k]))
                       + '</p>')
            for k in classes)

        # Agenda des séances de RÉPERTOIRE uniquement : un film récent du même
        # cinéaste peut passer 200 fois dans la semaine, et une liste de 200
        # lignes n'aide personne. Les fiches film portent le détail complet.
        agenda_seances = sorted((s for k in films & rep_keys for s in rep_by_movie[k]),
                                key=lambda s: s["start"])
        agenda_bloc = ""
        if agenda_seances:
            reste = len(agenda_seances) - REAL_AGENDA
            suite = (f'<p class="meta">'
                     + tf("Et {n} autre{s} séance{s2} de répertoire : "
                          "elles sont sur les fiches des films ci-dessus.",
                          n=reste, s=plural(reste), s2=plural(reste))
                     + '</p>') if reste > 0 else ""
            agenda_bloc = (f'<h2>{t("Prochaines séances de répertoire")}</h2>'
                           + agenda_par_jour(agenda_seances[:REAL_AGENDA]) + suite)

        # Cycle en cours pour ce cinéaste : la page de rétrospective en dit
        # plus (le programme salle par salle), on y renvoie explicitement.
        cle_cycle = _fold_title(nom)
        cycle_bloc = ""
        if cle_cycle in real_cycles:
            c = real_cycles[cle_cycle]
            cycle_bloc = f"""<div class="passerelle cine-cta">
<p><span class="titre">{t("🎞️ Une rétrospective est en cours")}</span>
<span class="meta">{tf("{n} de ses films sont programmés ensemble, dans {v}. Le programme "
                       "est détaillé salle par salle.",
                       n=len(c["movies"]),
                       v=(tf("{n} villes", n=len(c["cities"])) if len(c["cities"]) > 1
                          else esc(c["cities"][0])))}</span></p>
<a class="bouton" href="{cycle_urls[c["key"]]}">{t("Voir le cycle →")}</a>
</div>"""

        # La cinémathèque exige DEUX films de répertoire (c'est sa définition) :
        # ne proposer le bouton que dans ce cas, sinon il mène à un message
        # d'erreur.
        cine_bloc = ""
        if n_rep >= 2:
            cine_bloc = f"""<div class="passerelle">
<p><span class="titre">{tf("🏛️ Compose ta rétrospective {realisateur}", realisateur=esc(nom))}</span>
<span class="meta">{t("Toutes ses séances de répertoire du pays réunies en un parcours "
                      "chronologique, à mettre dans ton agenda.")}</span></p>
<a class="bouton" href="/cinematheque/?d={quote(nom)}">{t("Composer ma cinémathèque →")}</a>
</div>"""

        # La phrase ne reprend PAS le nom du réalisateur : il est en h1 juste
        # au-dessus, et « de {nom} » obligerait à gérer l'élision française
        # (« de Abbas » au lieu de « d'Abbas ») pour rien.
        intro = tf("<strong>{n} film{s}</strong> à l'affiche en France cette semaine, en "
                   "{seances} séances, dans {salles} salle{s2} de {villes} ville{s3}.",
                   n=len(films), s=plural(len(films)),
                   seances=nombre(n_seances), salles=len(salles), s2=plural(len(salles)),
                   villes=len(villes), s3=plural(len(villes)))
        # Quatre variantes plutôt qu'un verbe en variable : le sujet ET le
        # verbe changent ensemble, et un `{verbe}` isolé produisait « Tous est
        # des reprises ». Le répertoire n'est mentionné que s'il y en a, sinon
        # on annoncerait « dont 0 reprise ».
        if n_rep and n_rep == len(films):
            intro += " " + (t("C'est une reprise : un film ressorti en salle, en copie "
                              "restaurée ou en séance de ciné-club.") if n_rep == 1 else
                            t("Tous sont des reprises : des films ressortis en salle, en "
                              "copies restaurées ou en séances de ciné-club."))
        elif n_rep:
            intro += " " + (t("L'un d'eux est une reprise : un film ressorti en salle, en "
                              "copie restaurée ou en séance de ciné-club.") if n_rep == 1
                            else tf("{n} d'entre eux sont des reprises : des films "
                                    "ressortis en salle, en copies restaurées ou en "
                                    "séances de ciné-club.", n=n_rep))

        jsonld = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": tf("Films de {realisateur} à l'affiche", realisateur=nom),
            "url": f"{BASE_URL}{lang_prefix()}{path}",
            "about": {"@type": "Person", "name": nom},
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(classes),
                "itemListElement": [
                    {"@type": "ListItem", "position": i,
                     "url": f"{BASE_URL}{lang_prefix()}{movie_urls[k]}",
                     "name": movies[k]["title"]}
                    for i, k in enumerate(classes, 1)],
            },
        }
        real_body = f"""<p class="lead">{intro}</p>
{cycle_bloc}
<h2>{t("Ses films à l'affiche")}</h2>
<div class="grid">{cartes}</div>
{agenda_bloc}
{cine_bloc}
<p class="meta"><a class="more" href="/realisateurs/">{t("Tous les réalisateurs à l'affiche →")}</a></p>"""
        write(path, page(
            tf("{realisateur} : ses films à l'affiche en France — {site}",
               realisateur=nom, site=SITE_NAME),
            tf("Où voir les films de {realisateur} au cinéma ? {n} film(s) à l'affiche "
               "cette semaine dans {salles} salle(s) en France, avec les horaires et la "
               "réservation.", realisateur=nom, n=len(films), salles=len(salles)),
            real_body, path, jsonld, h1=nom, top_link=True))
        urls.append(path)

    # ----- Index des réalisateurs -----
    # Sans lui, les fiches ci-dessus seraient orphelines : elles ne seraient
    # atteignables que depuis les fiches film qui citent le cinéaste.
    if realisateurs:
        # Ordre alphabétique, et rien d'autre : c'est un répertoire de noms
        # qu'on parcourt, pas un classement.
        real_items = "".join(
            f'<li><a href="{realisateur_urls[nom]}">{esc(nom)}</a> '
            f'<span class="meta">'
            + tf("{n} film{s}", n=len(real_films[nom]), s=plural(len(real_films[nom])))
            + (" · " + tf("{n} de répertoire", n=len(real_films[nom] & rep_keys))
               if (real_films[nom] & rep_keys) else "")
            + '</span></li>'
            for nom in realisateurs)
        n_real_rep = sum(1 for nom in realisateurs if real_films[nom] & rep_keys)
        real_index_body = f"""<p class="lead">{tf(
            "Les <strong>{n} cinéastes</strong> dont au moins un film passe en salle cette "
            "semaine et qui ont de quoi remplir une page : deux films à l'affiche, ou une "
            "reprise jouée plusieurs fois. {r} d'entre eux ont au moins un film de "
            "répertoire à l'affiche.", n=len(realisateurs), r=n_real_rep)}</p>
<ul class="cities realisateurs">{real_items}</ul>
<p class="meta"><a class="more" href="/cinematheque/">{t("Composer une rétrospective →")}</a></p>"""
        write("/realisateurs/", page(
            tf("Les réalisateurs à l'affiche en France — {site}", site=SITE_NAME),
            tf("Quels cinéastes sont à l'affiche cette semaine ? {n} réalisateurs dont les "
               "films passent en salle en France, avec leurs séances et leurs reprises.",
               n=len(realisateurs)),
            real_index_body, "/realisateurs/", h1=t("Les réalisateurs à l'affiche"),
            top_link=True))
        urls.append("/realisateurs/")

    # ----- Idées de marathon -----
    # Deux films du même genre enchaînables dans deux salles voisines, dans les
    # dix plus grandes villes. Angle éditorial : les reprises d'abord, et une
    # bonne raison de pousser la porte d'une seconde salle (souvent un indé).
    ideas_by_city, cult_ideas = build_ideas(BIG_CITY_SLUGS, cinemas, movies, showtimes,
                                             is_classic, today)
    marathon_cities = [s for s in BIG_CITY_SLUGS if s in ideas_by_city]

    def marathon_card(idea: dict, show_city: bool = False) -> str:
        first, second = idea["first"], idea["second"]

        def leg(show: dict) -> str:
            cinema = cinemas[show["cinema"]]
            hour = heure(show["start"])
            # Une idée de marathon désigne DEUX séances précises : si elles
            # sont réservables, c'est ici que le visiteur veut cliquer.
            if show.get("booking"):
                hour = (f'<a href="{esc(show["booking"])}" target="_blank"'
                        f' rel="noopener noreferrer"'
                        f' title="{esc(t("Réserver cette séance (nouvel onglet)"))}">{hour}</a>')
            version = (f' <span class="v">{esc(version_label(show["version"]))}</span>'
                       if show["version"] else "")
            extra = (f'<p class="meta"><strong>{hour}</strong>{version} · '
                     f'<a href="{cinema_urls[show["cinema"]]}">{esc(cinema["name"])}</a>'
                     f'{chain_badge(cinema)}</p>')
            return movie_card(movies[show["movie"]], movie_urls, extra)

        genre = min(idea["genres"]).capitalize()
        day = date_label(date.fromisoformat(idea["day"]), today)
        # Un marathon qui a lieu aujourd'hui : on fait ressortir « Aujourd'hui »
        # en ambre (couleur d'accent du site) pour l'œil qui scanne la liste.
        day_html = (f'<span class="marathon-today">{esc(day)}</span>'
                    if idea["day"] == today_iso else esc(day))
        # Sur la section culte nationale, on rappelle la ville (les cartes par
        # ville sont déjà sous un titre de ville, inutile de la répéter).
        lieu = ""
        if show_city and idea.get("city"):
            nom = cities[idea["city"]]["name"] if idea["city"] in cities else idea["city"]
            lieu = f' · {esc(nom)}'
        cult = (f' <span class="badge badge-cult">{t("🏛️ Culte")}</span>'
                if idea["is_cult"] else "")
        if idea["kind"] == "meme_salle":
            cine = cinemas[first["cinema"]]
            lien_salle = (f'<a href="{cinema_urls[first["cinema"]]}">'
                          f'{esc(cine["name"])}</a>')
            transfer = tf("🍿 Les deux films dans la même salle, {salle} : "
                          "{gap} min d'entracte, sans bouger.",
                          salle=lien_salle, gap=idea["gap_min"])
        else:
            transfer = tf("🚶 {km} km entre les deux salles, soit ~{marche} min à pied. "
                          "Il vous reste {gap} min d'entracte à la fin du premier film.",
                          km=decimal(idea["distance_km"]), marche=idea["walk_min"],
                          gap=idea["gap_min"])
        cls = " marathon-cult" if idea["is_cult"] else ""
        return f"""<article class="marathon{cls}">
<h3>{tf("{jour}{lieu} · marathon {genre}", jour=day_html, lieu=lieu, genre=esc(genre))}{cult}</h3>
<div class="grid marathon-films">{leg(first)}{leg(second)}</div>
<p class="marathon-transfer">{transfer}</p>
</article>"""

    if marathon_cities:
        cult_section = ""
        if cult_ideas:
            cult_section = f"""<section class="marathon-cults" id="m-cultes">
<h2>{t("🏛️ Marathons cultes")}</h2>
<p class="meta">{t("Deux classiques très bien notés sur Letterboxd à enchaîner le même "
                   "jour, dans la même salle ou à deux pas. Le meilleur du répertoire, "
                   "d'affilée.")}</p>
{"".join(marathon_card(i, show_city=True) for i in sorted(cult_ideas, key=lambda i: i["day"]))}
</section>"""
        jump = (f'<a href="#m-cultes">{t("🏛️ Cultes")}</a> ' if cult_ideas else "") + " ".join(
            f'<a href="#m-{s}">{esc(cities[s]["name"])}</a>' for s in marathon_cities)
        sections = "".join(
            f'<section id="m-{s}"><h2>{esc(cities[s]["name"])}</h2>'
            f'<p class="meta"><a href="/ville/{s}/">'
            + tf("Toutes les séances à {ville} →", ville=esc(cities[s]["name"]))
            + '</a></p>'
            + "".join(marathon_card(i) for i in sorted(ideas_by_city[s], key=lambda i: i["day"]))
            + "</section>"
            for s in marathon_cities)
        n_ideas = sum(len(v) for v in ideas_by_city.values())
        lien_cultes = f'<a href="/classiques/">{t("marathons de films cultes")}</a>'
        marathon_body = f"""<p class="lead">{tf(
            "Deux films du même genre à enchaîner le même jour : soit dans <strong>deux "
            "salles voisines</strong> (le trajet à pied tient dans l'entracte), soit "
            "<strong>à la suite dans la même salle</strong>, sans bouger. Horaires et "
            "entracte calculés sur les séances réelles. Les {lien_cultes} passent en "
            "tête. Pour les {n} plus grandes villes de France.",
            lien_cultes=lien_cultes, n=len(marathon_cities))}</p>
<nav class="city-jump">{jump}</nav>
{cult_section}
{sections}"""
        write("/marathon/", page(
            tf("Idées de marathon cinéma : deux films à la suite — {site}", site=SITE_NAME),
            tf("{n} idées de marathon dans les grandes villes de France : deux films du "
               "même genre à la suite, dans la même salle ou deux salles voisines. "
               "Marathons cultes mis en avant.", n=n_ideas),
            marathon_body, "/marathon/", h1=t("Idées de marathon"), top_link=True))
        urls.append("/marathon/")

    # ----- Ma watchlist Letterboxd (croisement local) -----
    # Le visiteur dépose l'export de sa watchlist Letterboxd ; watchlist.js le
    # lit DANS LE NAVIGATEUR (rien n'est envoyé), croise chaque film avec
    # l'index par empreinte de slug, et affiche ceux qui passent cette semaine.
    # `_v`/`_s` sont les tables partagées de l'index, pas des films : on les saute.
    n_wl = len({v["t"] for k, v in wl_index.items() if not k.startswith("_")})
    watchlist_body = f"""<div class="wl-tabs" role="tablist" aria-label="{esc(t("Mode de connexion"))}">
<button type="button" class="wl-tab is-active" role="tab" aria-selected="true" data-panel="wl-pane-pseudo">{t("Par pseudo")}</button>
<button type="button" class="wl-tab" role="tab" aria-selected="false" data-panel="wl-pane-liste">{t("Depuis une liste")}</button>
</div>

<section id="wl-pane-pseudo" class="wl-pane">
<p class="lead">{t("Tu as une liste de films à voir sur")}
<a href="https://letterboxd.com" target="_blank" rel="noopener noreferrer">Letterboxd</a>
{tf("? Donne ton <strong>pseudo</strong> : {site} te dit <strong>lesquels de tes films "
    "à voir sont à l'affiche, et dans quels cinémas près de chez toi</strong>. On croise "
    "ta watchlist avec {n} films actuellement programmés en France.",
    site=SITE_NAME, n=n_wl)}</p>

<form class="lb-connect" id="lb-form">
<label for="lb-user">{t("Ton pseudo Letterboxd")}</label>
<div class="lb-field">
<input class="lb-input" id="lb-user" type="text" autocomplete="off" autocapitalize="none"
spellcheck="false" placeholder="{esc(t("pseudo Letterboxd"))}"
aria-label="{esc(t("Ton pseudo Letterboxd"))}">
<button class="bouton bouton-lb" type="submit">{t("Synchroniser")}</button>
</div>
</form>
<p class="lb-hint">{t("C'est l'identifiant de l'<strong>URL</strong> du profil, pas le nom "
                      "affiché : pour <code>letterboxd.com/<b>cinephile_92</b>/</code>, tape "
                      "<code>cinephile_92</code>. Les deux diffèrent souvent (à l'écran "
                      "« Marie Dupont », dans l'URL <code>mariedupont__</code>). En cas de "
                      "doute, ouvre le profil sur Letterboxd et recopie ce qui suit le "
                      "slash.")}</p>
<p class="lb-connect-note">{t("On lit seulement ta watchlist <strong>publique</strong>. "
                              "Rien n'est stocké côté serveur : la liste ne sert qu'à "
                              "l'afficher sur ton appareil.")}</p>

<div id="lb-status" aria-live="polite"></div>
<div id="lb-city" hidden></div>
<div id="wl-results" aria-live="polite"></div>
<div id="lb-calendar" hidden></div>

<details class="wl-alt">
<summary>{t("Watchlist privée, ou tu préfères un fichier ? Importer l'export")}</summary>
<p class="wl-drop-help">{t("Dépose le <code>watchlist.csv</code> de ton export Letterboxd : "
                           "tout se passe dans le navigateur, rien n'est envoyé.")}</p>
<div class="wl-drop" id="wl-drop" data-index="{BASE_PATH}{lang_prefix()}/watchlist-index.json" data-agenda="{BASE_PATH}{lang_prefix()}/agenda-index.json">
<input type="file" id="wl-file" accept=".csv,text/csv" hidden>
<p class="wl-drop-main"><button type="button" id="wl-pick" class="bouton">{t("Choisir mon fichier watchlist.csv")}</button></p>
<p class="wl-drop-alt">{t("ou glissez-le dans ce cadre")}</p>
</div>
<ol class="wl-steps">
<li>{t("Sur")} <a href="https://letterboxd.com/settings/data/" target="_blank" rel="noopener noreferrer">letterboxd.com</a>,
{t("ouvre les réglages, onglet <strong>Data</strong> (ou « Import &amp; Export »).")}</li>
<li>{t("Clique sur <strong>Export your data</strong>. Un fichier <code>.zip</code> se télécharge.")}</li>
<li>{t("Décompresse-le et dépose le fichier <code>watchlist.csv</code> ci-dessus.")}</li>
</ol>
</details>
</section>

<section id="wl-pane-liste" class="wl-pane" hidden>
<p class="lead">{tf("Une <strong>liste</strong> Letterboxd publique (« 1001 films à voir », "
                    "Palme d'or, tes classiques…) ? Colle son URL : {site} te montre "
                    "<strong>lesquels de ces films de patrimoine repassent en salle</strong>, "
                    "ville par ville, avec la séance et la réservation.", site=SITE_NAME)}</p>

<form class="lb-connect" id="list-form" data-agenda="{BASE_PATH}{lang_prefix()}/agenda-index.json" data-wl="{BASE_PATH}{lang_prefix()}/watchlist-index.json">
<label for="list-url">{t("URL de la liste Letterboxd")}</label>
<div class="lb-field">
<input class="lb-input" id="list-url" type="url" autocomplete="off" autocapitalize="none"
spellcheck="false" placeholder="https://letterboxd.com/pseudo/list/ma-liste/"
aria-label="{esc(t("URL de la liste Letterboxd"))}">
<button class="bouton bouton-lb" type="submit">{t("Chercher les séances")}</button>
</div>
</form>
<p class="lb-connect-note">{t("On lit seulement une liste <strong>publique</strong>. Rien "
                              "n'est stocké côté serveur, et ta géolocalisation (pour trier "
                              "par proximité) reste sur ton appareil.")}</p>

<div id="list-status" aria-live="polite"></div>
<div id="list-controls" class="list-controls" hidden></div>
<div id="list-results" aria-live="polite"></div>
</section>
<script src="/assets/watchlist.js" defer></script>
<script src="/assets/lb-watchlist.js" defer></script>
<script src="/assets/lb-listes.js" defer></script>"""
    write("/ma-watchlist/", page(
        tf("Ma watchlist Letterboxd au cinéma — {site}", site=SITE_NAME),
        tf("Donne ton pseudo Letterboxd : {site} te montre lesquels de tes films à voir "
           "sont à l'affiche, et dans quels cinémas près de chez toi.", site=SITE_NAME),
        watchlist_body, "/ma-watchlist/", h1=t("Votre watchlist au cinéma"),
        top_link=True))
    urls.append("/ma-watchlist/")

    # ----- Page « Ta cinémathèque » : rétrospective personnelle -----
    # Le visiteur choisit un réalisateur ; cinematheque.js rassemble TOUTES ses
    # séances de répertoire à venir en France (depuis agenda-index) en un
    # parcours chronologique, avec insight (films/villes, week-end groupable) et
    # export .ics généré côté client. La page servie est légère et indexable ;
    # le parcours se construit en JS après le choix.
    # Le menu déroulant du champ liste les réalisateurs par ORDRE ALPHABÉTIQUE :
    # c'est une liste qu'on PARCOURT pour retrouver un nom, pas un classement.
    # `cine_dirs` est trié par nombre de films (l'ordre des pastilles « les plus
    # programmés » juste en dessous) ; le reprendre ici donnait un déroulé sans
    # logique visible dès qu'on cliquait dans le champ. Clé de tri = _fold_title
    # (accents et ponctuation neutralisés), sinon « Éric Rohmer » se rangeait
    # après « Zhang Yimou ».
    cine_dl = "".join(
        f'<option value="{esc(d["name"])}">'
        for d in sorted(cine_dirs, key=lambda d: _fold_title(d["name"])))
    cine_chips = "".join(
        f'<button type="button" class="cine-chip" data-dir="{esc(d["name"])}">'
        f'{esc(d["name"])} <span>{d["n"]}</span></button>'
        for d in cine_dirs[:6])
    cine_body = f"""<p class="lead">{tf(
        "6 films de répertoire sur 10 ne passent qu'une seule fois en France sur une "
        "semaine. Au lieu de subir cet éparpillement, compose-le : choisis un "
        "réalisateur, {site} réunit <strong>toutes ses séances du pays</strong> en une "
        "rétrospective à toi, à mettre dans ton agenda.", site=SITE_NAME)}</p>

<form class="lb-connect" id="cine-form" data-agenda="{BASE_PATH}{lang_prefix()}/agenda-index.json" data-wl="{BASE_PATH}{lang_prefix()}/watchlist-index.json" data-directors="{BASE_PATH}/cinematheque-directors.json">
<label for="cine-search">{tf("Choisis un réalisateur ({n} ont au moins deux films à l'affiche)", n=len(cine_dirs))}</label>
<div class="lb-field">
<input class="lb-input" id="cine-search" list="cine-dl" type="text" autocomplete="off"
spellcheck="false" placeholder="{esc(t("ex. Akira Kurosawa"))}"
aria-label="{esc(t("Choisis un réalisateur"))}">
<button class="bouton" type="submit">{t("Assembler")}</button>
</div>
<datalist id="cine-dl">{cine_dl}</datalist>
</form>
<p class="cine-chips-label">{t("Les plus programmés en ce moment")}</p>
<div class="cine-chips">{cine_chips}</div>

<div id="cine-status" aria-live="polite"></div>
<div id="cine-result" aria-live="polite"></div>
<!-- ics.js AVANT cinematheque.js : le second appelle ICS.telecharger(). Les
     deux sont `defer`, donc exécutés dans l'ordre du document. -->
<script src="/assets/ics.js" defer></script>
<script src="/assets/cinematheque.js" defer></script>"""
    write("/cinematheque/", page(
        tf("Ta cinémathèque : compose ta rétrospective — {site}", site=SITE_NAME),
        tf("Choisis un réalisateur : {site} réunit toutes ses séances de répertoire à "
           "l'affiche en France en une rétrospective personnelle, à ajouter à ton agenda.",
           site=SITE_NAME),
        cine_body, "/cinematheque/", h1=t("Ta cinémathèque"), top_link=True))
    urls.append("/cinematheque/")

    # ----- Mes alertes -----
    # Page de gestion : ce que le visiteur suit, et de quoi le retirer. Elle
    # n'est pas dans le menu (elle ne concerne que ceux qui ont déjà marqué un
    # film) mais reste atteignable depuis la fiche film et /ma-watchlist/.
    alertes_body = f"""<p class="lead">{t(
        "Sur la fiche d'un film, le bouton « Préviens-moi quand il repasse » te prévient "
        "dès qu'une séance est programmée dans ta ville. Les reprises ne s'annoncent "
        "pas : 6 films de répertoire sur 10 ne passent qu'une seule fois en France sur "
        "une semaine.")}</p>
<div id="mes-alertes" aria-live="polite"></div>
<p class="meta">{t("Rien n'est envoyé à personne : ton navigateur reçoit la notification "
                   "directement, et tu peux retirer une alerte à tout moment.")}</p>
{ALERTES_JS}"""
    write("/mes-alertes/", page(
        tf("Mes alertes — {site}", site=SITE_NAME),
        tf("Les films que tu suis : {site} te prévient quand ils repassent dans ta ville.",
           site=SITE_NAME),
        alertes_body, "/mes-alertes/", h1=t("Mes alertes")))
    # Volontairement ABSENTE du sitemap : son contenu n'existe que dans le
    # navigateur de celui qui a marqué des films, il n'y a rien à indexer.
    # On y arrive par le lien posé sous la confirmation d'une alerte.

    # ----- Carte des cinémas -----
    # Données injectées dans la page (pas de fetch) : nom, ville, coords, chaîne,
    # URL, et `rep` = nb de séances de répertoire cette semaine (le « Autour de
    # moi » et le filtre s'en servent pour mettre en avant les salles qui en
    # programment — c'est le cœur du site).
    map_points = [
        {"name": c["name"], "city": c["city"], "lat": c["lat"], "lon": c["lon"],
         "chain": c.get("chain", ""),
         "url": f"{BASE_PATH}{lang_prefix()}{cinema_urls[cid]}",
         "rep": len(rep_by_cinema.get(cid, []))}
        for cid, c in cinemas.items() if c["lat"] and c["lon"]
    ]
    n_inde_map = sum(1 for p in map_points if not p["chain"])
    n_rep_map = sum(1 for p in map_points if p["rep"])
    leaflet_css = (
        '<link rel="stylesheet" href="/assets/vendor/leaflet/leaflet.css">'
        '<link rel="stylesheet" href="/assets/vendor/leaflet.markercluster/MarkerCluster.css">'
        '<link rel="stylesheet" href="/assets/vendor/leaflet.markercluster/MarkerCluster.Default.css">'
    )
    map_body = f"""<p class="lead">{tf(
        "{n} cinémas situés sur la carte, dont {r} programment du répertoire cette "
        "semaine. Trouvez une salle près de chez vous et ouvrez son programme.",
        n=len(map_points), r=n_rep_map)}</p>
<div class="map-tools">
<button type="button" id="geoloc-btn" class="bouton">{t("📍 Autour de moi")}</button>
<label class="map-filter"><input type="checkbox" id="rep-only"> {t("Salles de répertoire seulement")}</label>
</div>
<p id="geoloc-status" class="map-status" role="status" hidden></p>
<div id="map-legend">
<span class="legend-item"><span class="legend-dot dot-indep"></span>{t("Cinéma indépendant")}</span>
<span class="legend-item"><span class="legend-dot dot-chain"></span>{t("Grande enseigne")}</span>
</div>
<div id="cine-map"></div>
<div id="map-nearby" hidden></div>
<script type="application/json" id="cinemas-data">{json.dumps(map_points, ensure_ascii=False)}</script>
<script src="/assets/vendor/leaflet/leaflet.js"></script>
<script src="/assets/vendor/leaflet.markercluster/leaflet.markercluster.js"></script>
<script src="/assets/map.js"></script>"""
    write("/carte/", page(
        tf("Carte des cinémas en France — {site}", site=SITE_NAME),
        tf("Carte interactive de {n} cinémas en France. « Autour de moi » vous montre les "
           "salles les plus proches et lesquelles programment du répertoire cette semaine.",
           n=len(map_points)),
        map_body, "/carte/", h1=t("Carte des cinémas"), head_extra=leaflet_css))
    urls.append("/carte/")

    # ----- Manifeste (installation sur l'écran d'accueil) -----
    # GÉNÉRÉ, pas posé dans static/ : `start_url` et `scope` contiennent
    # BASE_PATH, qui deviendra "" le jour de seanceo.fr. Un fichier figé
    # pointerait alors vers /seanceo/ sur le nouveau domaine.
    #
    # Il sert d'abord aux ALERTES : sur iPhone, le push n'existe que si le site
    # a été ajouté à l'écran d'accueil, ce qui exige un manifeste et des icônes.
    # `display: standalone` fait ouvrir le site sans la barre d'adresse, comme
    # une application. Les icônes sont générées par scripts/make_icons.py.
    #
    # UN MANIFESTE PAR LANGUE : `name`, `description` et `lang` sont du texte
    # affiché (écran d'accueil, sélecteur d'applications), et `scope` doit
    # cadrer l'arbre de la langue — sinon une application installée depuis
    # /en/ retomberait sur des pages françaises.
    (lang_dir() / "manifest.webmanifest").write_text(json.dumps({
        "name": tf("{site}, le répertoire en salle", site=SITE_NAME),
        "short_name": SITE_NAME,
        "description": t("Les reprises, classiques et rétrospectives à l'affiche "
                         "partout en France."),
        "start_url": f"{BASE_PATH}{lang_prefix()}/",
        "scope": f"{BASE_PATH}{lang_prefix()}/",
        "display": "standalone",
        "lang": i18n.LANG,
        "background_color": "#0d1014",
        "theme_color": "#0d1014",
        "icons": [
            {"src": f"{BASE_PATH}/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"{BASE_PATH}/icon-512.png", "sizes": "512x512", "type": "image/png"},
            # « maskable » : Android rogne l'icône selon la forme du lanceur
            # (cercle, goutte…). Cette variante a le motif plus au centre et le
            # fond à bord perdu, sinon le clap serait amputé sur certains
            # téléphones.
            {"src": f"{BASE_PATH}/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    return urls


if __name__ == "__main__":
    sys.exit(main())
