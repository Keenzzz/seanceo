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
        "cms": "https://lafilmotheque.fr/wp-json/wp/v2/movies",
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


# —— Plateforme Côté Ciné (La Filmothèque du Quartier Latin) ————————————————

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


def collecte_cotecine(cid: str, cfg: dict, jours: int) -> tuple[dict, list]:
    """Séances + fiches films d'une salle sur la billetterie Côté Ciné."""
    vad, cms = cfg["vad"], cfg["cms"]
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

        fiche = fiche_cms(titre, cms)
        if fiche:
            complete_fiche(fiche)
        else:
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
                    "start": debut, "end": "", "version": morceaux[1].upper(),
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


COLLECTEURS = {"webedia": collecte_webedia, "cotecine": collecte_cotecine}


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
