"""Connecteur « salles indépendantes hors SCARE » pour Séancéo.

Certaines salles Art & Essai majeures ne publient PAS leur programmation dans
l'open data du SCARE (elles n'y adhèrent pas, ou n'y poussent pas leurs
séances) : elles sont donc invisibles du site alors qu'elles sont exactement
dans son cœur de cible. Ce connecteur va les chercher une par une, à la
source, et produit des séances au MÊME schéma que `fetch_data.py`.

Ce n'est pas une chaîne : ces salles restent des cinémas INDÉPENDANTS. Aucune
fiche ne porte de champ `chain`, ce qui les fait libeller « cinéma
indépendant » par `sources.cinema_kind()` — les ranger sous une enseigne
serait faux.

Deux plateformes suffisent aujourd'hui pour trois salles :

  - `webedia` — le site de la salle est un Gatsby « boxofficeapi », le même
    produit que CGR et Grand Écran (cf. fetch_webedia.py). Le Louxor et Le
    Brady en sont. On réutilise tel quel le code de fetch_webedia : mêmes
    endpoints `/schedule` et `/movies`, mêmes tags de version, mêmes liens de
    billetterie. Seule la DÉCOUVERTE change : pas de sitemap de cinémas à
    balayer ici, une salle unique dont le code se lit dans la page.

  - `cotecine` — la salle vend ses places sur la billetterie Côté Ciné
    (`*-vad.cotecine.fr`), qui expose un petit JSON en trois temps
    (film → jours → séances). La Filmothèque du Quartier Latin en est. Les
    fiches films viennent alors du CMS de la salle (API REST WordPress
    ouverte), la billetterie ne portant que des titres.

Usage :  python scripts/fetch_salles.py [--days N] [--only louxor brady …]
Aucune dépendance externe (stdlib uniquement).
"""

import argparse
import http.cookiejar
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, movie_key, booking_url
# Le connecteur des chaînes Webedia fait déjà tout le travail pour cette
# plateforme : on l'importe au lieu de le recopier. `cgr_version` est nommée
# d'après la première chaîne rencontrée, mais elle traduit les tags de TOUTE
# la plateforme — d'où l'alias, qui dit ce qu'elle fait vraiment.
from fetch_webedia import (
    get as webedia_get,
    cgr_version as webedia_version,
    webedia_booking,
    fetch_movies as webedia_movies,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PREFIX = "salles"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 0.2

# —— Registre des salles ————————————————————————————————————————————————————
#
# Adresses et coordonnées sont TENUES À LA MAIN, et c'est délibéré : aucune de
# ces trois salles ne publie de JSON-LD `MovieTheater` (contrairement aux pages
# cinéma de CGR/Grand Écran, où fetch_webedia les lit). Les extraire du HTML
# serait plus fragile que de les écrire une fois, vérifiées.
#
# Provenance de chaque valeur, pour qu'on puisse la recontrôler dans six mois :
#   - adresse : mentions légales ou page « nous trouver » de la salle elle-même
#     (le siège social de l'exploitant N'EST PAS l'adresse de la salle : celui
#     du Louxor est au 38 rue des Martyrs, la salle est boulevard de Magenta) ;
#   - lat/lon : Base Adresse Nationale (api-adresse.data.gouv.fr), score > 0,96.
#
# `theater` est le code Webedia de la salle. Il est REDÉCOUVERT à chaque
# collecte dans la page (`<meta name="bocms:theater:id">`) ; la valeur écrite
# ici sert de repli et de témoin : si la découverte renvoie autre chose, le
# connecteur le dit au lieu de collecter en silence la mauvaise salle.
SALLES = {
    "louxor": {
        "name": "Le Louxor - Palais du cinéma",
        "address": "170 boulevard de Magenta",
        "postcode": "75010", "city": "Paris",
        "lat": 48.883472, "lon": 2.349866,
        "source": "webedia",
        "site": "https://www.cinemalouxor.fr",
        "theater": "W7510",
    },
    "brady": {
        "name": "Le Brady",
        "address": "39 boulevard de Strasbourg",
        "postcode": "75010", "city": "Paris",
        "lat": 48.871779, "lon": 2.355403,
        "source": "webedia",
        "site": "https://www.lebrady.fr",
        "theater": "C0023",
    },
    "filmotheque": {
        "name": "La Filmothèque du Quartier Latin",
        "address": "9 rue Champollion",
        "postcode": "75005", "city": "Paris",
        "lat": 48.84951, "lon": 2.34279,
        "source": "cotecine",
        # Billetterie Côté Ciné : la programmation à jour, avec les versions.
        "vad": "https://lafilmotheque-vad.cotecine.fr/reserver",
        # CMS de la salle : les fiches films (réalisateur, durée, distribution).
        "cms_kind": "wp",
        "cms": "https://lafilmotheque.fr/wp-json/wp/v2/movies",
    },

    # —— Lyon (ajouté le 2026-08-30) ————————————————————————————————————————
    #
    # L'open data du SCARE ne connaît QUE 4 salles dans tout le Rhône
    # (CinéDuchère, Les Alizés à Bron, le Ciné Toboggan à Décines, le Ciné
    # Mourguet à Sainte-Foy) — vérifié en interrogeant l'API sur `cinecp:69*`.
    # Autrement dit : AUCUNE salle de répertoire du centre de Lyon. Pour un
    # site dont c'est le sujet, c'était le trou le plus voyant de la carte.
    #
    # Les quatre salles ci-dessous le comblent. Elles ne sont pas un ajout de
    # confort : le Lumière Fourmi et le Comœdia programment des reprises toute
    # l'année, et les trois Lumière appartiennent à l'Institut Lumière.
    "comoedia": {
        "name": "Cinéma Comœdia",
        "address": "13 avenue Berthelot",
        "postcode": "69007", "city": "Lyon",
        "lat": 45.747368, "lon": 4.835551,
        "source": "webedia",
        "site": "https://www.cinema-comoedia.com",
        "theater": "P3757",
    },
    # Les trois Cinémas Lumière (ex-CNP Terreaux, CNP Bellecour et La Fourmi,
    # repris par l'Institut Lumière en 2016). Une billetterie Côté Ciné PAR
    # salle, mais un seul site pour les fiches films : d'où `cms` identique et
    # `vad` distinct. Le CMS n'est pas un WordPress — voir `cms_kind`.
    "lumiere-terreaux": {
        "name": "Cinéma Lumière Terreaux",
        "address": "40 rue du Président Édouard Herriot",
        "postcode": "69001", "city": "Lyon",
        "lat": 45.765295, "lon": 4.834225,
        "source": "cotecine",
        "vad": "https://cinema-lumiere-terreaux-vad.cotecine.fr/reserver",
        "cms_kind": "lumiere",
        "cms": "https://www.cinemas-lumiere.com",
    },
    "lumiere-bellecour": {
        "name": "Cinéma Lumière Bellecour",
        "address": "12 rue de la Barre",
        "postcode": "69002", "city": "Lyon",
        "lat": 45.757456, "lon": 4.835596,
        "source": "cotecine",
        "vad": "https://cinema-lumiere-bellecour-vad.cotecine.fr/reserver",
        "cms_kind": "lumiere",
        "cms": "https://www.cinemas-lumiere.com",
    },
    "lumiere-fourmi": {
        "name": "Cinéma Lumière Fourmi",
        "address": "68 rue Pierre Corneille",
        "postcode": "69003", "city": "Lyon",
        "lat": 45.763283, "lon": 4.843833,
        "source": "cotecine",
        "vad": "https://cinema-lumiere-fourmi-vad.cotecine.fr/reserver",
        "cms_kind": "lumiere",
        "cms": "https://www.cinemas-lumiere.com",
    },
    "zola": {
        "name": "Le Zola",
        "address": "117 cours Émile Zola",
        "postcode": "69100", "city": "Villeurbanne",
        "lat": 45.770556, "lon": 4.874404,
        "source": "ticketingcine",
        # `num_cine` est le code de la salle chez TicketingCiné : il se lit dans
        # l'URL de sa billetterie (`index.php?lang=fr&nc=1217`) et dans le
        # `gl_init_app.numcine` de la page. Redécouvert à chaque collecte, comme
        # le code Webedia, pour ne pas collecter une autre salle en silence.
        "site": "https://www.lezola.com",
        "num_cine": "1217",
    },
}

# Titres que la billetterie et le CMS de la salle n'écrivent pas pareil, au
# point qu'aucune recherche ne les rapproche. Un nombre écrit en chiffres d'un
# côté et en toutes lettres de l'autre est le cas type : « 12 hommes en
# colère » (caisse) / « Douze Hommes en Colère » (site). Généraliser
# demanderait une table de nombres qui apparierait aussi « Alien » et
# « Alien 3 » ; on préfère nommer les cas, et laisser le connecteur SIGNALER
# les titres qu'il n'a pas su résoudre plutôt que d'en inventer la résolution.
TITRES_CMS = {
    "12 hommes en colère": "https://lafilmotheque.fr/films/douze-hommes-en-colere/",
}


class SourceIndisponible(RuntimeError):
    """La source d'une salle n'a pas répondu (réseau, 4xx/5xx, JSON illisible).

    À distinguer d'une programmation VIDE, qui est un état légitime (relâche,
    travaux, fermeture annuelle) : voir le garde-fou d'écriture dans main()."""


# —— Accès réseau ————————————————————————————————————————————————————————————

def lire(url: str, encodage: str = "utf-8") -> str:
    """GET texte. Lève `SourceIndisponible` — jamais de None silencieux."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode(encodage, "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        raise SourceIndisponible(f"{url[:80]} : {err}") from err
    finally:
        time.sleep(DELAY)


def lire_json(url: str):
    """GET JSON, mêmes garanties que `lire()`."""
    brut = lire(url)
    try:
        return json.loads(brut)
    except json.JSONDecodeError as err:
        raise SourceIndisponible(f"{url[:80]} : réponse non-JSON ({err})") from err


def lire_dict(url: str) -> dict:
    """GET JSON qui doit rendre un OBJET, avec une tolérance NOMMÉE.

    ⚠️ La caisse Côté Ciné répond littéralement `false` — pas `{}` — quand un
    film n'a plus aucun jour ouvert à la vente. C'est une réponse NORMALE : le
    film a fini son exploitation en cours de semaine, il reste dans la liste
    déroulante mais n'a plus rien à vendre. Repéré par le CI le 2026-08-28
    (« Le Violent », « Mirage de la vie »), qui plantait sur un
    `TypeError: 'bool' object is not iterable`.

    La traiter comme une panne bloquerait tout le snapshot chaque fois qu'un
    film s'arrête — c'est-à-dire toutes les semaines. On la nomme donc ici, une
    fois, plutôt que de la deviner sur chaque appel.

    Toute autre forme (une liste, une chaîne non vide) signalerait un vrai
    changement de format : là on veut échouer bruyamment."""
    valeur = lire_json(url)
    if isinstance(valeur, dict):
        return valeur
    if not valeur:          # false, null, 0, "", [] → « rien à cette adresse »
        return {}
    raise SourceIndisponible(
        f"{url[:80]} : objet attendu, reçu {type(valeur).__name__}")


# —— Plateforme Webedia (Le Louxor, Le Brady) ————————————————————————————————

_META_THEATER = re.compile(
    r'<meta[^>]+name="bocms:theater:id"[^>]+content="([A-Za-z0-9]+)"', re.I)
_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def code_salle(site: str) -> str:
    """Code Webedia de la salle, lu dans `<meta name="bocms:theater:id">`.

    La balise est posée par le CMS de Webedia sur les pages qui décrivent une
    salle. Elle est sur l'ACCUEIL du Louxor, mais PAS sur celui du Brady, dont
    la page d'accueil est un gabarit générique : là, elle n'apparaît que sur
    une page film. D'où les deux essais — l'accueil d'abord (une requête), le
    premier film du sitemap ensuite. Renvoie "" si aucun des deux ne la porte."""
    trouve = _META_THEATER.search(lire(f"{site}/"))
    if trouve:
        return trouve.group(1).upper()
    sitemap = lire(f"{site}/sitemap-0.xml")
    pages = [u for u in _SITEMAP_LOC.findall(sitemap) if "/film" in u]
    if not pages:
        return ""
    trouve = _META_THEATER.search(lire(pages[0]))
    return trouve.group(1).upper() if trouve else ""


def collecte_webedia(cid: str, cfg: dict, jours: int) -> tuple[dict, list]:
    """Séances + fiches films d'une salle sur la plateforme Webedia."""
    site = cfg["site"]
    api = f"{site}/api/gatsby-source-boxofficeapi"

    code = code_salle(site)
    if not code:
        print(f"    ! code salle introuvable sur {site} — repli sur {cfg['theater']}")
        code = cfg["theater"]
    elif code != cfg["theater"]:
        # Ne pas taire l'écart : collecter une AUTRE salle que celle annoncée
        # produirait des séances parfaitement valides… et fausses.
        print(f"    ! code salle inattendu sur {site} : {code} "
              f"(registre : {cfg['theater']}) — vérifier le registre")

    aujourdhui = date.today()
    params = urllib.parse.urlencode({
        "from": f"{aujourdhui.isoformat()}T03:00:00",
        "to": f"{(aujourdhui + timedelta(days=jours)).isoformat()}T03:00:00",
        "includeAllMovies": "true",
        # Le code doit être en MAJUSCULES et le JSON compact : en minuscules ou
        # avec des espaces, l'API répond 500 avec un corps « null », sans le
        # moindre message (le piège qui avait figé CGR en silence).
        "theaters": json.dumps({"id": code, "timeZone": "Europe/Paris"},
                               separators=(",", ":")),
    })
    planning = webedia_get(f"{api}/schedule?{params}")
    if planning is None:
        raise SourceIndisponible(f"{api}/schedule (salle {code})")

    brutes = []          # (id film, début, tags, lien billetterie)
    ids_films = set()
    for mid, par_date in ((planning.get(code) or {}).get("schedule") or {}).items():
        ids_films.add(str(mid))
        for creneaux in par_date.values():
            for s in creneaux:
                brutes.append((str(mid), s["startsAt"], s.get("tags", []),
                               webedia_booking(s)))

    catalogue = webedia_movies(api, ids_films) if ids_films else {}

    films, seances = {}, []
    for mid, debut, tags, billet in brutes:
        fiche = catalogue.get(mid)
        if not fiche or not fiche["title"]:
            continue
        cle = movie_key(fiche["title"], fiche["director"])
        films.setdefault(cle, {
            "key": cle, "title": fiche["title"], "director": fiche["director"],
            "cast": "", "genre": fiche["genre"], "country": "",
            "duration_min": fiche["duration_min"], "poster": fiche["poster"],
            "trailer": "", "storyline": "",
        })
        seances.append({
            "id": f"{cid}-{mid}-{debut}", "movie": cle, "cinema": cid,
            "start": debut, "end": "", "version": webedia_version(tags),
            "auditorium": "", "booking": billet,
        })
    return films, seances


# —— Plateforme Côté Ciné (La Filmothèque du Quartier Latin, Cinémas Lumière) ——

# Versions Côté Ciné à ramener au vocabulaire du site (VF / VO / VOST).
# « VFST » = version française SOUS-TITRÉE EN FRANÇAIS : une séance
# accessible aux spectateurs sourds et malentendants, pas une version
# étrangère. C'est bien du VF pour le filtre langue des pages ville — laissée
# telle quelle, la séance n'était NI dans « VF » ni dans « VO/VOST », donc
# invisible dès qu'un visiteur touchait au filtre. Apparu avec les Cinémas
# Lumière (3 séances au 2026-08-30), jamais servi par La Filmothèque.
VERSIONS_COTECINE = {"VFST": "VF", "VOSTF": "VOST"}


_SELECT_FILM = re.compile(r'<select name="modresa_film">(.*?)</select>', re.S)
_OPTION = re.compile(r'<option value="(\d+)">(.*?)</option>', re.S)
_REALISATEUR = re.compile(r'<h3 class="director">(.*?)</h3>', re.S)
# Affiche : le CMS sert des vignettes recadrées, dont le marqueur
# `-c_<largeur>_<hauteur>_` dit le format. On n'accepte QUE les portraits : la
# même figure porte parfois un photogramme panoramique, qui ferait une carte de
# film écrasée. Sans affiche valable on laisse vide — TMDB la pose ensuite.
_AFFICHE = re.compile(r'(https://[^"\s]+-c_(\d+)_(\d+)_[^"\s]+\.(?:jpg|jpeg|png))')
_HEURE = re.compile(r"\b(\d{1,2})h(\d{2})\b")
_ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "the", "a"}


def _plie(texte: str) -> str:
    """Empreinte d'un titre : minuscules, sans accents ni ponctuation."""
    texte = unicodedata.normalize("NFD", unescape(texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texte).split())


def _radical(texte: str) -> str:
    """Empreinte SANS parenthèse ni article de tête : « Les Duellistes » et
    « Duellistes », « Cutter's way (la blessure) » et « CUTTER'S WAY » sont le
    même film — deux écarts observés entre la caisse et le CMS de la salle."""
    mots = _plie(re.sub(r"\([^)]*\)", "", unescape(texte or ""))).split()
    while mots and mots[0] in _ARTICLES:
        mots = mots[1:]
    return " ".join(mots)


def _texte(html: str) -> str:
    """HTML → texte simple (les champs ACF du CMS sont du HTML rédigé)."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html or "")).split())


# —— CMS « Cinémas Lumière » —————————————————————————————————————————————————
#
# Le site des trois salles lyonnaises n'est pas un WordPress : pas d'API REST,
# des pages `/film/<slug>.html`. Mais il publie un CALENDRIER GÉNÉRAL qui liste
# tous les films à l'affiche avec le lien de leur fiche — un index tout fait,
# et bien meilleur qu'une recherche : on n'a pas à deviner le slug d'un titre
# (« Le Château de l'araignée » → `le-chateau-de-l-araignee`), le site le dit.
#
# On le lit UNE FOIS par collecte et on le garde en mémoire : les trois salles
# partagent le même site, le retélécharger trois fois n'apprendrait rien.
# Deux pages, et il en faut deux. Le calendrier général ne liste que la
# programmation RÉGULIÈRE (27 films au 2026-08-30) ; l'accueil en annonce 55,
# séances événement comprises. C'est là que vivaient « Fight Club » (Midnight
# Movie) et « Le Petit monde de Leo », vendus par la caisse mais absents du
# calendrier — deux titres de répertoire qui seraient partis sans réalisateur,
# donc sans appariement TMDB possible.
_PAGES_LUMIERE = ("/calendrier-general.html", "/")
_LIEN_LUMIERE = re.compile(r'href="([^"]*/film/([^"/]+)\.html)"')
# Sur le CALENDRIER seul, le lien est nu dans sa cellule : son texte est le
# titre, propre. Sur l'accueil, le même lien enveloppe toute une carte (titre,
# réalisateur, date, « Voir la fiche ») — inutilisable comme titre.
_TITRE_LUMIERE = re.compile(
    r'<th class="movie-title[^"]*">\s*<a[^>]*>(.*?)</a>', re.S)
# Les fiches Lumière rangent leurs métadonnées dans une liste étiquetée :
# <li><strong>De : </strong>Katsuhiro Otomo</li>. On lit l'étiquette, pas la
# position — l'ordre des lignes change d'un film à l'autre (pas de « Avec »
# sur un documentaire, par exemple).
_DETAIL_LUMIERE = re.compile(
    r"<li>\s*<strong>\s*([^:<]+?)\s*:\s*</strong>(.*?)</li>", re.S)
_SYNOPSIS_LUMIERE = re.compile(
    r'<div class="section synopsis">(.*?)</div>', re.S)
# L'affiche est en `data-src` (chargement paresseux) et non en `src`, qui ne
# porte qu'un GIF transparent en base64. Lire `src` donnerait une carte vide.
_POSTER_LUMIERE = re.compile(
    r'<figure class="poster">.*?data-src="([^"]+)"', re.S)
_DUREE_LUMIERE = re.compile(r"(\d+)\s*h\s*(\d+)")

_index_lumiere: dict[str, dict[str, str]] = {}


def index_lumiere(cms: str) -> dict[str, str]:
    """{empreinte du titre: URL de la fiche} pour tout le site Cinémas Lumière.

    Mémorisé par site : les trois salles Lumière appellent cette fonction, les
    pages ne sont donc lues qu'une fois par collecte. On indexe SOUS DEUX FORMES — empreinte exacte et
    radical sans article — pour rattraper les écarts d'écriture entre la caisse
    et le site, sans jamais accepter un « à peu près » (cf. `fiche_cms`)."""
    if cms in _index_lumiere:
        return _index_lumiere[cms]
    index: dict[str, str] = {}
    for chemin in _PAGES_LUMIERE:
        page = lire(f"{cms}{chemin}")
        # Le titre affiché quand la page en donne un propre (calendrier).
        for titre in _TITRE_LUMIERE.findall(page):
            lien = _LIEN_LUMIERE.search(titre)
            titre = _texte(re.sub(r"<[^>]+>", " ", titre))
            if lien and titre:
                index.setdefault(_plie(titre), lien.group(1))
                index.setdefault(_radical(titre), lien.group(1))
        # Puis le SLUG de chaque fiche liée, d'où qu'elle vienne. Le slug est
        # le titre du site déjà déaccentué et sans ponctuation, c'est-à-dire
        # exactement ce que `_plie()` produit : « /film/le-chateau-de-l-araignee
        # .html » et « Le Château de l'araignée » se rejoignent sans effort.
        # C'est ce qui rattrape les pages où le lien enveloppe une carte
        # entière et où son texte ne vaut rien comme titre.
        for lien, slug in _LIEN_LUMIERE.findall(page):
            titre = slug.replace("-", " ")
            index.setdefault(_plie(titre), lien)
            index.setdefault(_radical(titre), lien)
    if not index:
        raise SourceIndisponible(
            f"{cms} : aucun film trouvé sur {', '.join(_PAGES_LUMIERE)}")
    _index_lumiere[cms] = index
    return index


def fiche_lumiere(titre: str, cms: str) -> dict:
    """Fiche film sur le site des Cinémas Lumière, résolue par son titre.

    Même contrat que `fiche_cms` : {} si le titre n'est pas résolu (la séance
    reste diffusable, simplement moins renseignée), et JAMAIS de « premier
    résultat » approchant — c'est ce qui projetterait « Alien 3 » à la place
    d'« Alien »."""
    index = index_lumiere(cms)
    lien = index.get(_plie(titre)) or index.get(_radical(titre))
    if not lien:
        return {}
    page = lire(lien)
    details = {_plie(etiquette): _texte(valeur)
               for etiquette, valeur in _DETAIL_LUMIERE.findall(page)}
    duree = _DUREE_LUMIERE.search(details.get("duree", ""))
    synopsis = _SYNOPSIS_LUMIERE.search(page)
    affiche = _POSTER_LUMIERE.search(page)
    titre_page = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    return {
        "title": _texte(titre_page.group(1)) if titre_page else unescape(titre).strip(),
        "lien": lien,
        "director": details.get("de", ""),
        "cast": details.get("avec", ""),
        "duration_min": (int(duree.group(1)) * 60 + int(duree.group(2))
                         if duree else None),
        "poster": affiche.group(1) if affiche else "",
        "storyline": _texte(synopsis.group(1)) if synopsis else "",
    }


def fiche_cms(titre: str, cms: str) -> dict:
    """Fiche film du site de la salle, à partir du titre de la billetterie.

    La caisse ne donne qu'un titre ; le réalisateur, lui, est indispensable :
    `enrich_tmdb.py` s'en sert pour DÉPARTAGER les homonymes (des « Drive »,
    des « Bird », des « Possession », TMDB en connaît plusieurs). Sans lui, on
    risquerait d'afficher l'affiche et le résumé d'un autre film.

    Deux requêtes par film : la recherche REST résout le titre en URL de fiche,
    puis la fiche donne le réalisateur (absent de l'API, il n'est rendu que
    dans la page). Renvoie {} si le titre n'est pas résolu — le film reste
    diffusable, il sera simplement moins renseigné."""
    lien = TITRES_CMS.get(unescape(titre))
    if lien:
        return {"title": unescape(titre), "lien": lien,
                "duration_min": None, "cast": "", "storyline": ""}

    # Trois requêtes possibles, de la plus fidèle à la plus permissive. On
    # s'arrête à la première qui donne une correspondance EXACTE (empreinte ou
    # radical) : jamais de « premier résultat » pris au hasard, qui
    # attribuerait joyeusement « Alien 3 » à une séance d'« Alien ».
    essais = [unescape(titre),
              re.sub(r"\([^)]*\)", "", unescape(titre)).strip(),
              _radical(titre)]
    for question in dict.fromkeys(e for e in essais if e):
        url = (f"{cms}?per_page=8&_fields=link,title,acf&"
               + urllib.parse.urlencode({"search": question}))
        resultats = lire_json(url)
        if not isinstance(resultats, list):
            # L'API REST signale ses erreurs par un OBJET ({"code": …}) : itéré
            # tel quel, on parcourrait ses clés en croyant lire des films.
            continue
        trouve = (
            next((r for r in resultats
                  if _plie(r["title"]["rendered"]) == _plie(titre)), None)
            or next((r for r in resultats
                     if _radical(r["title"]["rendered"]) == _radical(titre)), None))
        if trouve:
            acf = trouve.get("acf") or {}
            distribution = _texte(acf.get("mov_casting"))
            return {
                "title": unescape(trouve["title"]["rendered"]).strip(),
                "lien": trouve["link"],
                "duration_min": acf.get("mov_time") or None,
                # Le champ du CMS est rédigé (« Avec Mark Wahlberg, … ») ; les
                # autres sources donnent une liste nue, on s'aligne dessus.
                "cast": distribution.removeprefix("Avec ").strip(),
                "storyline": _texte(acf.get("mov_synopsis")),
            }
    return {}


def complete_fiche(fiche: dict) -> None:
    """Ajoute le réalisateur et l'affiche, lus dans la page de la fiche film."""
    page = lire(fiche["lien"])
    realisateur = _REALISATEUR.search(page)
    fiche["director"] = _texte(realisateur.group(1)) if realisateur else ""
    fiche["poster"] = next((u for u, largeur, hauteur in _AFFICHE.findall(page)
                            if int(hauteur) > int(largeur)), "")


def debut_local(horodatage: int, jour: str, libelle: str) -> str:
    """Début d'une séance, en heure locale naïve (« 2026-08-31T21:20:00 »).

    La caisse donne les deux : un horodatage epoch (UTC) et l'heure affichée
    (« 21h20 - VO »). On les CROISE plutôt que de convertir : Windows
    n'embarque pas la base de fuseaux IANA, donc `zoneinfo("Europe/Paris")`
    n'est pas garanti sans dépendance — et le dépôt tient à ne dépendre que de
    la stdlib.

    Comme l'heure murale est connue, il suffit de chercher le décalage (+1 en
    hiver, +2 en été) qui la reproduit : il donne du même coup la bonne DATE,
    ce que le jour de la caisse ne dit pas toujours (une séance de minuit est
    rangée sous la soirée qui la précède). Si aucun décalage ne colle, on
    retombe sur le jour annoncé plutôt que d'écarter la séance.

    Renvoie "" si le libellé ne porte pas d'heure — la séance est alors ignorée
    plutôt que datée au hasard."""
    trouve = _HEURE.search(libelle)
    if not trouve:
        return ""
    h, m = int(trouve.group(1)), int(trouve.group(2))
    utc = datetime.fromtimestamp(horodatage, timezone.utc).replace(tzinfo=None)
    for decalage in (1, 2):
        local = utc + timedelta(hours=decalage)
        if (local.hour, local.minute) == (h, m):
            return local.isoformat(timespec="seconds")
    return f"{jour}T{h:02d}:{m:02d}:00"


def _dans_fenetre(jour: str, limite: date) -> bool:
    try:
        return date.fromisoformat(jour) <= limite
    except ValueError:
        return False


# Les deux CMS de salles rencontrés derrière une billetterie Côté Ciné. La
# CAISSE est la même (mêmes `modresa_*`, même iso-8859-1) ; c'est le site qui
# porte les fiches films qui change. Séparer les deux ici évite d'écrire un
# second connecteur Côté Ciné entier pour une différence de deux fonctions.
FICHES_CMS = {"wp": fiche_cms, "lumiere": fiche_lumiere}


def collecte_cotecine(cid: str, cfg: dict, jours: int) -> tuple[dict, list]:
    """Séances + fiches films d'une salle sur la billetterie Côté Ciné."""
    vad, cms = cfg["vad"], cfg["cms"]
    fiche_de = FICHES_CMS[cfg.get("cms_kind", "wp")]
    page = lire(f"{vad}/", encodage="latin-1")   # la caisse sert de l'iso-8859-1
    bloc = _SELECT_FILM.search(page)
    if not bloc:
        raise SourceIndisponible(f"{vad}/ : liste des films introuvable")
    catalogue = _OPTION.findall(bloc.group(1))
    if not catalogue:
        raise SourceIndisponible(f"{vad}/ : liste des films vide")

    limite = date.today() + timedelta(days=jours)
    films, seances, non_resolus = {}, [], []

    for fid, titre_brut in catalogue:
        titre = unescape(titre_brut).strip()
        # La caisse ouvre aussi la vente de séances très lointaines
        # (rétrospectives annoncées, séances événement) : on garde la même
        # fenêtre que les autres connecteurs pour ne pas remplir le site de
        # dates hors sujet.
        dates = [j for j in lire_dict(f"{vad}/ajax/?modresa_film={fid}")
                 if _dans_fenetre(j, limite)]
        if not dates:
            continue

        fiche = fiche_de(titre, cms)
        # Le CMS Lumière rend déjà réalisateur et affiche dans la MÊME page que
        # le reste : seul le WordPress de la Filmothèque exige une requête de
        # plus pour aller les lire (ils sont absents de son API REST).
        if fiche and "director" not in fiche:
            complete_fiche(fiche)
        if not fiche:
            non_resolus.append(titre)
            fiche = {"title": titre, "director": "", "poster": "",
                     "duration_min": None, "cast": "", "storyline": ""}

        cle = movie_key(fiche["title"], fiche["director"])
        films.setdefault(cle, {
            "key": cle, "title": fiche["title"], "director": fiche["director"],
            "cast": fiche["cast"], "genre": "", "country": "",
            "duration_min": fiche["duration_min"], "poster": fiche["poster"],
            "trailer": "", "storyline": fiche["storyline"],
        })

        for jour in dates:
            creneaux = lire_dict(f"{vad}/ajax/?modresa_film={fid}&modresa_jour={jour}")
            # Clé d'une séance : « <horodatage>/<version>/<salle> ».
            for reference, libelle in creneaux.items():
                morceaux = reference.split("/")
                if len(morceaux) < 2 or not morceaux[0].isdigit():
                    continue
                debut = debut_local(int(morceaux[0]), jour, libelle)
                if not debut:
                    continue
                seances.append({
                    "id": f"{cid}-{fid}-{reference}", "movie": cle, "cinema": cid,
                    "start": debut, "end": "",
                    "version": VERSIONS_COTECINE.get(morceaux[1].upper(),
                                                     morceaux[1].upper()),
                    "auditorium": "",
                    # Le formulaire de la caisse est en POST : aucune URL ne
                    # mène à UNE séance précise. Mais film et jour se
                    # présélectionnent en GET — le visiteur arrive sur le bon
                    # film au bon jour et n'a plus qu'à choisir l'heure. Mieux
                    # que la page d'accueil de la billetterie, et honnête.
                    "booking": booking_url(
                        f"{vad}/?" + urllib.parse.urlencode(
                            {"modresa_film": fid, "modresa_jour": jour})),
                })

    if non_resolus:
        print(f"    ! {len(non_resolus)} titre(s) sans fiche sur le site de la salle "
              f"(séances gardées, réalisateur manquant) : {', '.join(non_resolus)}")
    return films, seances


# —— Plateforme TicketingCiné (Le Zola) —————————————————————————————————————
#
# `ticketingcine.fr` (éditeur Monnaie-Services) est la caisse de ~500 salles
# indépendantes françaises. Le site est une application JavaScript : la page
# n'affiche AUCUNE séance dans son HTML, tout arrive par des appels POST que le
# connecteur refait à l'identique.
#
#   ajax/get_movies_cine.php         → catalogue de la salle (titre, réalisateur,
#                                      durée, genre, affiche, synopsis)
#   ajax/get_movie_sessions_cine.php → pour un film : ses jours ouverts, puis
#                                      les horaires d'un jour donné
#
# ⚠️ CES APPELS EXIGENT LE COOKIE DE SESSION. Sans lui, ils répondent 200 avec
# un corps VIDE — zéro octet, pas une erreur, pas un JSON d'erreur : rien. Le
# choix de la salle (`?nc=1217`) vit dans la session PHP et non dans le POST,
# même si `num_cine` y est répété. Il faut donc charger la page de la salle
# d'abord, uniquement pour poser le cookie.
#
# ⚠️ `dates_sessions` et `sessions` sont DEUX choses différentes : la première
# liste les jours où le film passe, la seconde ne rend les horaires QUE du jour
# demandé. Interroger un seul jour et conclure « ce film ne passe pas » serait
# faux — d'où la boucle sur les jours annoncés.
_TC_ORIGINE = "https://www.ticketingcine.fr"
_TC_NUMCINE = re.compile(r'"numcine"\s*:\s*"(\d+)"')


def _tc_session(num_cine: str):
    """Ouvre une session TicketingCiné positionnée sur UNE salle.

    Renvoie un opener porteur du cookie, et VÉRIFIE au passage que la caisse
    sert bien la salle du registre : la page publie son propre `numcine` dans
    `gl_init_app`. Collecter la mauvaise salle produirait des séances
    parfaitement valides… et fausses — le même piège que le code Webedia."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("User-Agent", UA)]
    url = f"{_TC_ORIGINE}/index.php?lang=fr&nc={num_cine}"
    try:
        with opener.open(url, timeout=30) as resp:
            page = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        raise SourceIndisponible(f"{url} : {err}") from err
    finally:
        time.sleep(DELAY)
    servie = _TC_NUMCINE.search(page)
    if not servie:
        raise SourceIndisponible(f"{url} : salle non identifiée dans la page")
    if servie.group(1) != num_cine:
        raise SourceIndisponible(
            f"{url} : la caisse sert la salle {servie.group(1)}, "
            f"pas {num_cine} (registre à vérifier)")
    return opener


def _tc_post(opener, chemin: str, champs: dict):
    """POST vers un `ajax/*.php` de TicketingCiné, réponse JSON.

    Un corps VIDE veut dire « session perdue », pas « rien à dire » : on le
    signale au lieu de rendre un catalogue vide, qui ferait passer la salle
    pour en relâche et laisserait le snapshot rétrécir sans un mot."""
    url = f"{_TC_ORIGINE}/{chemin}"
    requete = urllib.request.Request(
        url, data=urllib.parse.urlencode(champs).encode(),
        headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener.open(requete, timeout=30) as resp:
            brut = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        raise SourceIndisponible(f"{url} : {err}") from err
    finally:
        time.sleep(DELAY)
    if not brut.strip():
        raise SourceIndisponible(f"{url} : réponse vide (session perdue ?)")
    try:
        return json.loads(brut)
    except json.JSONDecodeError as err:
        raise SourceIndisponible(f"{url} : réponse non-JSON ({err})") from err


def tc_version(features: list) -> str:
    """Version d'une séance, d'après les étiquettes de la caisse.

    Les trois mêmes valeurs que partout ailleurs sur le site (VF / VOST / VO),
    pour que le filtre langue des pages ville ne connaisse qu'un vocabulaire.
    « vo » + « subtitle » = VOST, ce que la salle affiche « VOSTF »."""
    tags = {str(f).lower() for f in features or []}
    if "vf" in tags:
        return "VF"
    if "vo" in tags:
        return "VOST" if "subtitle" in tags else "VO"
    return ""


def _tc_dans_fenetre(jour: str, limite: date) -> bool:
    """« 20260831 » est-il dans la fenêtre ? (format compact de la caisse)"""
    try:
        return datetime.strptime(str(jour), "%Y%m%d").date() <= limite
    except (ValueError, TypeError):
        return False


def _tc_debut(seance: dict) -> str:
    """Début d'une séance en heure locale naïve, depuis `date_hour`.

    Aucune conversion de fuseau ici, contrairement à Côté Ciné : la caisse ne
    donne QUE l'heure murale (« 202608312030 »), qui est déjà celle affichée en
    salle et celle qu'attend le reste du pipeline. Rien à croiser, donc rien à
    deviner. Renvoie "" si le champ est absent ou malformé — la séance est
    alors ignorée plutôt que datée au hasard."""
    brut = str(seance.get("date_hour") or "")
    try:
        return datetime.strptime(brut, "%Y%m%d%H%M").isoformat(timespec="seconds")
    except ValueError:
        return ""


def collecte_ticketingcine(cid: str, cfg: dict, jours: int) -> tuple[dict, list]:
    """Séances + fiches films d'une salle sur la billetterie TicketingCiné."""
    num_cine = cfg["num_cine"]
    opener = _tc_session(num_cine)

    catalogue = _tc_post(opener, "ajax/get_movies_cine.php",
                         {"num_cine": num_cine, "langue": "fr"})
    if not isinstance(catalogue, dict) or "movies" not in catalogue:
        raise SourceIndisponible(
            "get_movies_cine.php : format inattendu (pas de clé « movies »)")

    limite = date.today() + timedelta(days=jours)
    films, seances = {}, []

    for film in catalogue.get("movies") or []:
        titre = unescape(film.get("title") or "").strip()
        identifiant = film.get("id")
        if not titre or not identifiant:
            continue

        # Premier appel : le jour demandé importe peu, on vient chercher
        # `dates_sessions` — la liste des jours où ce film passe.
        planning = _tc_post(opener, "ajax/get_movie_sessions_cine.php",
                            {"num_cine": num_cine, "langue": "fr",
                             "id_unique_MS": identifiant,
                             "date_session": date.today().strftime("%Y%m%d")})
        jours_ouverts = [j for j in (planning.get("dates_sessions") or [])
                         if _tc_dans_fenetre(j, limite)]
        if not jours_ouverts:
            continue

        realisateur = unescape(film.get("director") or "").strip()
        cle = movie_key(titre, realisateur)
        films.setdefault(cle, {
            "key": cle, "title": titre, "director": realisateur,
            "cast": unescape(film.get("actors") or "").strip(),
            "genre": unescape(film.get("genres") or "").strip(),
            "country": "",
            # Déjà en minutes, contrairement au « 02h04 » des Cinémas Lumière.
            "duration_min": film.get("duration") or None,
            "poster": film.get("bill_url") or "",
            "trailer": film.get("trailer_url") or "",
            # La caisse échappe l'apostrophe à la mode SQL, en la DOUBLANT
            # (« l''ours brun ») : laissée telle quelle, elle s'afficherait
            # ainsi sur la fiche film.
            "storyline": unescape(film.get("synopsis") or "").replace("''", "'").strip(),
        })

        for jour in jours_ouverts:
            creneaux = _tc_post(opener, "ajax/get_movie_sessions_cine.php",
                                {"num_cine": num_cine, "langue": "fr",
                                 "id_unique_MS": identifiant,
                                 "date_session": jour})
            for seance in creneaux.get("sessions") or []:
                debut = _tc_debut(seance)
                if not debut:
                    continue
                lien = str(seance.get("booking_url") or "").lstrip("/")
                seances.append({
                    "id": f"{cid}-{seance.get('id')}", "movie": cle, "cinema": cid,
                    "start": debut, "end": "",
                    "version": tc_version(seance.get("features")),
                    "auditorium": str(seance.get("hall") or ""),
                    # `booking_url` est relatif à la racine de la caisse et mène
                    # à LA séance (`&ids=8946`) : le meilleur lien possible, le
                    # visiteur n'a plus qu'à choisir sa place.
                    "booking": booking_url(f"{_TC_ORIGINE}/{lien}" if lien else ""),
                })

    return films, seances


COLLECTEURS = {"webedia": collecte_webedia, "cotecine": collecte_cotecine,
               "ticketingcine": collecte_ticketingcine}


# —— Assemblage ——————————————————————————————————————————————————————————————

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Collecte les salles indépendantes absentes de l'open data SCARE.")
    ap.add_argument("--days", type=int, default=7, help="fenêtre de jours")
    ap.add_argument("--only", nargs="+", choices=list(SALLES),
                    help="ne collecter que ces salles")
    args = ap.parse_args()

    voulues = args.only or list(SALLES)
    print(f"Salles indépendantes hors SCARE : {', '.join(voulues)} "
          f"(fenêtre {args.days} j)")

    cinemas: dict[str, dict] = {}
    films: dict[str, dict] = {}
    seances: list[dict] = []
    echecs: list[str] = []

    for slug in voulues:
        cfg = SALLES[slug]
        cid = f"{PREFIX}-{slug}"
        print(f"  {cfg['name']} ({cfg['source']})…")
        try:
            nouveaux, creneaux = COLLECTEURS[cfg["source"]](cid, cfg, args.days)
        except SourceIndisponible as err:
            print(f"    x source indisponible : {err}")
            echecs.append(slug)
            continue
        for cle, fiche in nouveaux.items():
            films.setdefault(cle, fiche)
        seances.extend(creneaux)
        cinemas[cid] = {
            "id": cid, "name": cfg["name"], "address": cfg["address"],
            "postcode": cfg["postcode"], "city": cfg["city"],
            "city_slug": slugify(cfg["city"]), "lat": cfg["lat"], "lon": cfg["lon"],
            # Pas de `chain` : ce sont des cinémas INDÉPENDANTS (cf. en-tête).
        }
        print(f"    ok {len(creneaux)} séances, {len(nouveaux)} films")

    # GARDE-FOU. Une salle en RELÂCHE (0 séance) est un état normal — travaux,
    # fermeture annuelle, semaine sans programmation — et ne doit pas empêcher
    # de rafraîchir les autres. Une salle dont la SOURCE n'a pas répondu est
    # autre chose : réécrire le snapshot sans elle le ferait rétrécir en
    # silence, exactement ce que les snapshots versionnés servent à éviter.
    # On préfère garder la photo d'hier et sortir en erreur.
    if echecs:
        print(f"\nÉchec sur {len(echecs)} salle(s) ({', '.join(echecs)}) — "
              f"snapshot précédent CONSERVÉ, rien n'est écrit.")
        return 1

    par_cinema: dict[str, int] = defaultdict(int)
    for s in seances:
        par_cinema[s["cinema"]] += 1
    villes: dict[str, dict] = {}
    for c in cinemas.values():
        ville = villes.setdefault(c["city_slug"], {
            "slug": c["city_slug"], "name": c["city"], "cinemas": [],
            "showtime_count": 0})
        ville["cinemas"].append(c["id"])
        ville["showtime_count"] += par_cinema[c["id"]]

    seances.sort(key=lambda s: s["start"])
    DATA_DIR.mkdir(exist_ok=True)
    for genre, contenu in {"cinemas": cinemas, "movies": films,
                           "showtimes": seances, "cities": villes}.items():
        (DATA_DIR / f"{PREFIX}_{genre}.json").write_text(
            json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nBilan : {len(cinemas)} salles, {len(films)} films, "
          f"{len(seances)} séances.")
    for cid, n in sorted(par_cinema.items(), key=lambda kv: -kv[1]):
        print(f"  {cinemas[cid]['name']} : {n} séances")
    return 0


if __name__ == "__main__":
    sys.exit(main())
