"""Générateur de site statique Séancéo.

Lit les JSON produits par fetch_data.py et écrit le site complet dans `site/` :
accueil, une page par ville, par cinéma et par film, sitemap.xml, robots.txt.

Usage :  python scripts/build_site.py
Aucune dépendance externe (stdlib uniquement).
"""

import html
import json
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify  # même slugification partout
from sources import load_merged, cinema_kind, _fold_title  # fusion indés + chaînes
from marathon import build_ideas  # doubles programmes par ville
import repertoire  # reprises, cycles, séances uniques, salles de patrimoine

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
ASSETS = ROOT / "assets"

# Hébergement GitHub Pages (projet) : le site vit sous un sous-chemin.
# Quand le domaine seanceo.fr sera branché : BASE_PATH = "" et BASE_URL = "https://seanceo.fr".
BASE_PATH = "/seanceo"
BASE_URL = f"https://keenzzz.github.io{BASE_PATH}"
SITE_NAME = "Séancéo"

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

# Recherche de film, présente dans le header de toutes les pages.
# `data-index` porte le chemin complet (BASE_PATH inclus) : page() ne préfixe
# que les attributs href/src, un data-* lui échapperait.
FILM_SEARCH = f"""<div class="film-search">
<input id="film-search" type="search" autocomplete="off" data-index="{BASE_PATH}{SEARCH_INDEX}"
placeholder="Chercher un film ou un réalisateur…" aria-label="Chercher un film ou un réalisateur">
<ul id="film-suggest" hidden></ul>
</div>
<script src="/assets/search.js" defer></script>"""

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def fr_date(d: date, today: date) -> str:
    if d == today:
        return "Aujourd'hui"
    if d == today + timedelta(days=1):
        return "Demain"
    return f"{JOURS[d.weekday()].capitalize()} {d.day} {MOIS[d.month - 1]}"


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# --- Gabarit commun -------------------------------------------------------

def page(title: str, description: str, body: str, path: str,
         jsonld: dict | None = None, h1: str | None = None,
         head_extra: str = "", top_link: bool = False) -> str:
    """Enveloppe une page : head SEO complet + header/footer communs.
    `head_extra` : balises à ajouter dans le <head> (ex. CSS Leaflet de la carte).
    `top_link` : bouton flottant « retour en haut » pour les gabarits longs."""
    ld = (f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'
          if jsonld else "")
    top = ('\n<a class="top-link" href="#" aria-label="Retour en haut de page">↑ Haut</a>'
           if top_link else "")
    doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{BASE_URL}{path}">
<link rel="stylesheet" href="/assets/style.css">
{JS_FLAG}
{head_extra}
{ld}
</head>
<body>
<header class="site-header">
<a class="brand" href="/">🎬 {SITE_NAME}</a>
<p class="tagline">Le répertoire en salle, partout en France</p>
{FILM_SEARCH}
<nav class="site-nav"><a href="/a-l-affiche/">🎬 À l'affiche</a> <a href="/salles-patrimoine/">🏛️ Salles de patrimoine</a> <a href="/classiques/">🏆 Le classement</a> <a href="/marathon/">🍿 Marathons</a> <a href="/carte/">🗺️ Carte</a></nav>
</header>
<main>
<h1>{esc(h1 if h1 is not None else title)}</h1>
{body}
</main>{top}
<footer>
<p>Données de programmation : <a href="https://datacinesindes.fr" rel="noopener">Data Ciné Indés / SCARE</a>
(Syndicat des Cinémas d'Art, de Répertoire et d'Essai) — Licence Ouverte 2.0.</p>
<p>{SITE_NAME} réunit les séances des cinémas indépendants et des grandes enseignes, et met en avant les salles Art &amp; Essai.</p>
<p>Fiches films (titres, notes, affiches, synopsis) enrichies via
<a href="https://www.themoviedb.org/" rel="noopener">TMDB</a> — ce produit utilise l'API TMDB
mais n'est ni approuvé ni certifié par TMDB.</p>
</footer>
</body>
</html>"""
    if BASE_PATH:
        # Hébergement sous sous-chemin : préfixe les URLs internes absolues.
        # Les liens externes (https://…) et le canonical ne commencent pas
        # par href="/ ou src="/, ils ne sont donc pas touchés.
        doc = doc.replace('href="/', f'href="{BASE_PATH}/').replace('src="/', f'src="{BASE_PATH}/')
    return doc


def write(path: str, content: str) -> None:
    """path est le chemin URL (« /ville/tours/ ») ; écrit site/ville/tours/index.html."""
    target = SITE / path.strip("/") / "index.html" if path != "/" else SITE / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --- Fragments réutilisés -------------------------------------------------

def chain_badge(cinema: dict) -> str:
    """Pastille distinguant un cinéma de chaîne d'un indépendant. Les indés
    (signature du site) portent le point rouge ; les chaînes leur nom."""
    chain = cinema.get("chain")
    if chain:
        return f' <span class="badge badge-chain">{esc(chain)}</span>'
    return ' <span class="badge badge-inde" title="Cinéma indépendant">Indé</span>'


def is_classic(movie: dict) -> bool:
    """Vrai si le film est une reprise : année de sortie connue (via TMDB) et
    vieille d'au moins CLASSIC_AGE_YEARS ans. Sans année fiable, on s'abstient."""
    year = movie.get("year")
    return bool(year) and year <= TODAY.year - CLASSIC_AGE_YEARS


def classic_badge(movie: dict) -> str:
    return (' <span class="badge badge-classic">Classique</span>'
            if is_classic(movie) else "")


def showtime_pills(shows: list[dict]) -> str:
    """Horaires d'un film dans une salle. Une séance dont la source donne un
    lien de billetterie devient cliquable et mène directement à la réservation ;
    les autres restent des chips informatives. Les deux styles se distinguent
    (`.reservable`) : promettre un clic qui n'existe pas est le défaut qu'on
    avait justement corrigé en neutralisant ces pastilles."""
    pills = []
    for s in sorted(shows, key=lambda x: x["start"]):
        t = s["start"][11:16].replace(":", "h")
        v = f' <span class="v">{esc(s["version"])}</span>' if s["version"] else ""
        # .get() : les snapshots de chaînes collectés avant l'ajout du champ
        # n'ont pas de clé « booking » — ils doivent rester affichables.
        url = s.get("booking")
        if url:
            pills.append(
                f'<li class="reservable"><a href="{esc(url)}" target="_blank"'
                f' rel="noopener noreferrer"'
                f' title="Réserver la séance de {t} sur la billetterie du cinéma'
                f' (nouvel onglet)">{t}{v}</a></li>')
        else:
            pills.append(f'<li>{t}{v}</li>')
    return f'<ul class="showtimes">{"".join(pills)}</ul>'


def sort_title(title: str) -> str:
    """Clé de tri alphabétique d'un titre : sans accents ni ponctuation, et
    sans l'article initial (« Le Bon, la Brute… » se range à B). Calculée ici
    plutôt qu'en JavaScript pour que le tri soit identique partout."""
    folded = _fold_title(title)
    head, _, rest = folded.partition(" ")
    return rest if rest and head in LEADING_ARTICLES else folded


def card_attrs(movie: dict) -> str:
    """Attributs data-* lus par tri.js pour trier et filtrer sans recharger.
    Toujours posés : une carte sait se classer quelle que soit la page qui
    l'affiche. Les valeurs absentes valent 0 (elles finissent en queue de tri).
    `data-v` liste les versions du film (« vf vo ») pour le filtre VF/VO."""
    key = movie["key"]
    versions = " ".join(sorted(MOVIE_VERSIONS.get(key, ())))
    return (f' data-title="{esc(sort_title(movie["title"]))}"'
            f' data-lb="{movie.get("lb_rating") or 0}"'
            f' data-year="{movie.get("year") or 0}"'
            f' data-venues="{MOVIE_VENUES.get(key, 0)}"'
            f' data-v="{esc(versions)}"')


def movie_card(movie: dict, movie_urls: dict, extra: str = "",
               show_rating: bool = True, show_classic: bool = True) -> str:
    """`show_rating=False` masque la note TMDB — utile quand la carte affiche
    déjà une note d'une autre échelle (classement Letterboxd /5).
    `show_classic=False` masque le badge Classique — bruit pur sur une page
    qui ne liste QUE des classiques."""
    url = movie_urls[movie["key"]]
    poster = (f'<img src="{esc(movie["poster"])}" alt="Affiche de {esc(movie["title"])}" loading="lazy">'
              if movie["poster"] else '<div class="noposter">🎞️</div>')
    rating = f'★ {movie["rating"]}' if show_rating and movie.get("rating") else ""
    meta = " · ".join(filter(None, [
        str(movie["year"]) if movie.get("year") else "",
        rating, movie["genre"],
        f"{movie['duration_min']} min" if movie["duration_min"] else "",
    ]))
    return f"""<article class="movie-card"{card_attrs(movie)}>
<a href="{url}">{poster}</a>
<div class="movie-info">
<h3><a href="{url}">{esc(movie["title"])}</a>{classic_badge(movie) if show_classic else ""}</h3>
<p class="meta">{esc(meta)}</p>
{extra}
</div>
</article>"""


def city_search_nav(pills_html: str, cmap: dict, n_cities: int) -> str:
    """Sommaire de villes : pastilles des grandes villes + recherche à la
    frappe (assets/film.js). `cmap` associe un nom de ville affiché à sa
    cible : ancre « v-slug » sur une fiche film, URL absolue ailleurs
    (film.js navigue quand la cible commence par « / »)."""
    return f"""<nav class="city-jump">
{pills_html}
<span class="city-search"><input id="city-search" type="search" autocomplete="off"
placeholder="Chercher votre ville ({n_cities} villes)…" aria-label="Chercher une ville">
<ul id="city-suggest" hidden></ul></span>
<script type="application/json" id="city-map">{json.dumps(cmap, ensure_ascii=False)}</script>
</nav>
<script src="/assets/film.js" defer></script>"""


# Tris proposés au-dessus d'une liste de films. Chaque entrée donne le libellé
# du bouton, le sens appliqué au premier clic, et la marque affichée dans
# chaque sens — un second clic sur le tri actif l'inverse (tri.js).
# Le sens de départ est celui qu'on attend spontanément : les meilleures notes
# d'abord, mais les titres de A à Z. Les flèches sont explicites sur le titre
# (« A → Z ») là où un ↑ ne dirait pas grand-chose.
SORTS = {
    "lb": ("Note Letterboxd", "desc", "↑", "↓"),
    "title": ("Titre", "asc", "A → Z", "Z → A"),
    "year": ("Année", "desc", "↑", "↓"),
    "venues": ("Cinémas", "desc", "↑", "↓"),
}


def film_tools(list_id: str, default: str, total: int) -> str:
    """Barre de tri et de filtre au-dessus d'une liste de films (tri.js).
    Elle ne sert à rien sans JavaScript : le CSS la masque alors, et la liste
    reste affichée en entier dans l'ordre calculé au build.
    `default` : tri appliqué à l'arrivée, celui que la page assume
    éditorialement (le classement Letterboxd sur /classiques/…)."""
    order = [default] + [k for k in SORTS if k != default]
    options = "".join(
        f'<button type="button" data-sort="{k}" data-dir="{SORTS[k][1]}"'
        f' data-asc="{esc(SORTS[k][2])}" data-desc="{esc(SORTS[k][3])}"'
        f' aria-pressed="{"true" if k == default else "false"}">'
        f'<span class="tri-nom">{esc(SORTS[k][0])}</span>'
        f'<span class="tri-sens"></span></button>'
        for k in order)
    # « Toutes » est actif à l'arrivée : aucun film n'est masqué par défaut.
    versions = "".join(
        f'<button type="button" data-v="{v}" aria-pressed="{pressed}">{lbl}</button>'
        for v, lbl, pressed in (("", "Toutes", "true"), ("vo", "VO / VOST", "false"),
                                ("vf", "VF", "false")))
    return f"""<div class="film-tools" data-list="{list_id}" data-page="{PAGE_SIZE}">
<span class="tri-tri" role="group" aria-label="Trier les films">
<span class="tri-label">Trier par</span>{options}</span>
<span class="tri-versions" role="group" aria-label="Filtrer par version">{versions}</span>
<p class="tri-compte" id="tri-compte" role="status">{total} films</p>
</div>
<script src="/assets/tri.js" defer></script>"""


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
            sections.append(f'<section><h2>{fr_date(d, today)}</h2>{films_html}</section>')
        body = f"""<p class="lead">{esc(cinema["address"])}, {esc(cinema["postcode"])} {esc(cinema["city"])} —
{esc(cinema_kind(cinema))}. <a href="/ville/{cinema["city_slug"]}/">Tous les cinémas de {esc(cinema["city"])}</a></p>
{"".join(sections) or "<p>Aucune séance annoncée pour les deux prochaines semaines.</p>"}"""
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
            f"{cinema['name']} ({cinema['city']}) : séances et programme — {SITE_NAME}",
            f"Programme et horaires des séances du cinéma {cinema['name']} à {cinema['city']} "
            f"sur les 15 prochains jours. {cinema_kind(cinema).capitalize()}.",
            body, path, jsonld, h1=f"{cinema['name']} — {cinema['city']}"))
        urls.append(path)

    # ----- Pages ville -----
    for slug, city in cities.items():
        path = f"/ville/{slug}/"
        horizon = (today + timedelta(days=CITY_WINDOW_DAYS)).isoformat()
        blocks = []
        city_movie_keys: set[str] = set()
        sorted_cids = sorted(city["cinemas"], key=lambda c: cinemas[c]["name"])
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
                                                  showtime_pills(todays)))
                else:
                    films_later.append(movie_card(
                        movies[mk], movie_urls,
                        f'<p class="meta">prochaine séance : {fr_date(date.fromisoformat(ss[0]["start"][:10]), today)}</p>'))
            today_html = f'<div class="films">{"".join(films_today)}</div>' if films_today else ""
            later_html = ""
            if films_later:
                if films_today:
                    later_html = (f'<details class="more-films"><summary>+ {len(films_later)} '
                                  f'autre{"s" if len(films_later) > 1 else ""} film{"s" if len(films_later) > 1 else ""} '
                                  f'plus tard cette semaine</summary>'
                                  f'<div class="films">{"".join(films_later)}</div></details>')
                else:
                    # Rien aujourd'hui : ne pas cacher tout le programme du cinéma
                    today_html = '<p class="meta">Pas de séance aujourd\'hui — prochaines dates :</p>'
                    later_html = f'<div class="films">{"".join(films_later)}</div>'
            blocks.append(f"""<section class="cinema-block" id="c-{cid}">
<h2><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h2>
<p class="meta">{esc(cinema["address"])} — <a href="{cinema_urls[cid]}">programme complet</a></p>
{(today_html + later_html) or "<p>Aucune séance cette semaine.</p>"}</section>""")
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
            parts.append(f'{n_inde} cinéma{"s" if n_inde > 1 else ""} indépendant{"s" if n_inde > 1 else ""}')
        if n_chain:
            parts.append(f'{n_chain} cinéma{"s" if n_chain > 1 else ""} de chaîne')
        n_classics = sum(1 for mk in city_movie_keys if is_classic(movies[mk]))
        classics_bit = (f' 🎞️ {n_classics} classique{"s" if n_classics > 1 else ""} au badge doré — '
                        f'<a href="/classiques/">tous les classiques à l\'affiche</a>.'
                        if n_classics else "")
        body = f"""<p class="lead">{" et ".join(parts)} à {esc(city["name"])} —
séances du jour et de la semaine.{classics_bit}</p>{toc}{"".join(blocks)}"""
        write(path, page(
            f"Cinéma à {city['name']} : séances et horaires — {SITE_NAME}",
            f"Quel film voir à {city['name']} ? Séances et horaires des {n_cine} cinéma(s) "
            f"de la ville : programme du jour et de la semaine.",
            body, path, h1=f"Cinémas à {city['name']}", top_link=True))
        urls.append(path)

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
                    f'<span class="day">{fr_date(date.fromisoformat(d), today)}</span>{showtime_pills(v)}'
                    for d, v in sorted(days.items()))
                blocks.append(f"""<section class="cinema-block">
<h4><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h4>
{per_day}</section>""")
            n = len(blocks)
            rows.append(f"""<section class="city-group" id="v-{cslug}">
<h3>{esc(city_name(cslug))} <span class="meta">{n} cinéma{"s" if n > 1 else ""}</span></h3>
<p class="meta"><a href="/ville/{cslug}/">Tous les cinémas de {esc(city_name(cslug))} →</a></p>
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
            prompt = (f'<p class="city-prompt" id="city-prompt">À l\'affiche dans '
                      f'{n_cine_total} cinéma{"s" if n_cine_total > 1 else ""} de '
                      f'{len(city_slugs)} villes — choisissez la vôtre pour voir les horaires.</p>')
        credits = " · ".join(filter(None, [
            movie.get("year") and str(movie["year"]),
            movie.get("rating") and f"★ {movie['rating']}/10",
            movie["director"] and f"De {movie['director']}",
            movie["cast"] and f"Avec {movie['cast']}",
            movie["genre"], movie["duration_min"] and f"{movie['duration_min']} min"]))
        poster = (f'<img class="poster" src="{esc(movie["poster"])}" alt="Affiche de {esc(movie["title"])}">'
                  if movie["poster"] else "")
        trailer = (f'<p><a href="{esc(movie["trailer"])}" rel="noopener">▶ Bande-annonce</a></p>'
                   if movie["trailer"] else "")
        # `filtered` : les sections ville sont masquées en CSS tant que le
        # visiteur n'en a pas choisi une. Le masquage est conditionné à la
        # classe `js` posée dans le <head> — sans JavaScript, la recherche ne
        # marcherait pas et tout doit rester visible (et lisible par un robot).
        city_list = (f'<div class="city-list{" filtered" if filtered else ""}" id="city-list">'
                     f'{"".join(rows)}</div>' if rows else "<p>Aucune séance à venir.</p>")
        body = f"""<div class="film-head">{poster}<div>
<p class="lead">{classic_badge(movie)} {esc(credits)}</p>
<p>{esc(movie["storyline"])}</p>{trailer}</div></div>
<h2>Où voir {esc(movie["title"])} ?</h2>
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
        write(path, page(
            f"{movie['title']} : séances près de chez vous — {SITE_NAME}",
            (f"Où voir {movie['title']}"
             + (f" de {movie['director']}" if movie["director"] else "")
             + f" ? Séances et horaires ville par ville, dans {len({s['cinema'] for s in shows})}"
               f" cinéma(s) en France." if shows else
             f"Où voir {movie['title']} ? Séances et horaires ville par ville en France."),
            body, path, jsonld, h1=movie["title"], top_link=True))
        urls.append(path)

    # ----- Index de recherche (titre + réalisateur) -----
    # Fichier à part, chargé par search.js à la première frappe : l'injecter
    # dans chaque page coûterait ~90 ko à chaque visite pour une fonction que
    # la plupart des visiteurs n'utiliseront pas. Tableaux plutôt qu'objets
    # (pas de noms de clés répétés 931 fois) : [titre, réalisateur, url, année].
    index = sorted(
        ([m["title"], m["director"], f"{BASE_PATH}{movie_urls[k]}", m.get("year") or 0]
         for k, m in movies.items()),
        key=lambda row: sort_title(row[0]))
    (SITE / "recherche.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ----- Répertoire : le moteur éditorial du site -----
    rep_window = repertoire.window(showtimes, today)
    rep_shows = repertoire.repertoire_shows(rep_window, movies)
    rep_uniques = repertoire.unique_screenings(rep_shows, movies)
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
    # Catalogue complet de « À l'affiche », le plus diffusé d'abord : c'est le
    # classement qui répond à « qu'est-ce qui passe partout cette semaine ».
    # Le visiteur qui cherche autre chose le retrie (titre, année, note) ou le
    # filtre par version sans quitter la page — tri.js n'en montre que
    # PAGE_SIZE à la fois pour ne pas dérouler 931 cartes d'un coup.
    catalogue = sorted((m for m in movies.values() if by_movie[m["key"]]),
                       key=lambda m: (-MOVIE_VENUES[m["key"]], sort_title(m["title"])))
    films_html = "".join(
        movie_card(m, movie_urls,
                   f'<p class="meta">{MOVIE_VENUES[m["key"]]} '
                   f'cinéma{"s" if MOVIE_VENUES[m["key"]] > 1 else ""}</p>')
        for m in catalogue)
    # Liste complète repliée + tri alphabétique : 257 villes en vrac formaient
    # un mur de 57 % de la page (le « mur de pastilles » déjà refusé, en liste).
    cities_html = "".join(
        f'<li><a href="/ville/{slug}/">{esc(c["name"])}</a> '
        f'<span class="meta">{len(c["cinemas"])} ciné{"s" if len(c["cinemas"]) > 1 else ""}</span></li>'
        for slug, c in sorted(cities.items(), key=lambda kv: kv[1]["name"]))
    majors = [s for s in BIG_CITY_SLUGS if s in cities]
    city_pills = " ".join(f'<a href="/ville/{s}/">{esc(cities[s]["name"])}</a>' for s in majors)
    # Cibles = URLs (avec BASE_PATH : le JSON échappe au préfixage automatique
    # de page(), qui ne touche que les attributs href/src)
    city_cmap = {c["name"]: f"{BASE_PATH}/ville/{slug}/" for slug, c in cities.items()}
    city_finder = city_search_nav(city_pills, city_cmap, len(cities))
    n_chain = sum(1 for c in cinemas.values() if c.get("chain"))
    n_inde = len(cinemas) - n_chain
    inventory = f"{n_inde} cinémas indépendants"
    if n_chain:
        inventory += f" et {n_chain} cinémas de chaîne"
    # ----- Page « À l'affiche » (l'ancien accueil, devenu un onglet) -----
    # Elle garde l'intention à plus gros volume (« quel film voir ce soir »)
    # pendant que l'accueil se recentre sur le répertoire.
    affiche_body = f"""<p class="lead">{inventory}, {len(cities)} villes,
{len(showtimes)} séances à venir. Mis à jour quotidiennement.</p>
<h2>Choisissez votre ville</h2>
{city_finder}
<details class="all-cities"><summary>Toutes les villes ({len(cities)})</summary>
<ul class="cities">{cities_html}</ul></details>
<h2>Tous les films à l'affiche</h2>
{film_tools("film-list", "venues", len(catalogue))}
<div class="grid" id="film-list">{films_html}</div>
<div class="passerelle">
<p><span class="titre">{n_rep_films} classiques sont aussi à l'affiche</span>
<span class="meta">Rétrospectives, copies restaurées et ciné-clubs, partout en France.</span></p>
<a class="bouton" href="/">Voir le répertoire</a>
</div>"""
    write("/a-l-affiche/", page(
        f"Films à l'affiche cette semaine : séances et horaires — {SITE_NAME}",
        f"Quel film voir au cinéma cette semaine ? Séances et horaires de {len(cinemas)} cinémas "
        f"dans {len(cities)} villes en France, indépendants et grandes enseignes. Mis à jour chaque jour.",
        affiche_body, "/a-l-affiche/", h1="Quel film voir au cinéma cette semaine ?",
        top_link=True))
    urls.append("/a-l-affiche/")

    # ----- Accueil : l'agenda du répertoire -----
    def seance_row(s: dict) -> str:
        """Une ligne d'agenda : l'heure d'abord, comme sur un programme."""
        m, cin = movies[s["movie"]], cinemas[s["cinema"]]
        img = (f'<img src="{esc(m["poster"])}" alt="Affiche de {esc(m["title"])}" loading="lazy">'
               if m["poster"] else '<span class="noposter">🎞️</span>')
        credits = " · ".join(filter(None, [
            m["director"], m["genre"],
            f'{m["duration_min"]} min' if m["duration_min"] else "", s["version"]]))
        note = (f'<span class="note-lb" title="Note moyenne Letterboxd">{m["lb_rating"]}'
                f'<span class="sur">/5</span></span>' if m.get("lb_rating") else "")
        # L'heure est le point d'entrée naturel vers la réservation : c'est la
        # séance précise que le visiteur vise dans un agenda.
        heure = s["start"][11:16].replace(":", "h")
        if s.get("booking"):
            heure = (f'<a href="{esc(s["booking"])}" target="_blank"'
                     f' rel="noopener noreferrer"'
                     f' title="Réserver cette séance (nouvel onglet)">{heure}</a>')
        return f"""<li class="seance">
<time class="heure{' reservable' if s.get("booking") else ''}" datetime="{s["start"][:16]}">{heure}</time>
<div class="vignette"><a href="{movie_urls[s["movie"]]}">{img}</a></div>
<div class="corps">
<h3 class="film"><a href="{movie_urls[s["movie"]]}">{esc(m["title"])}</a>
<span class="annee">{m["year"]}</span></h3>
<p class="meta">{esc(credits)}</p>
<p class="meta lieu"><strong><a href="{cinema_urls[s["cinema"]]}">{esc(cin["name"])}</a></strong>,
{esc(cin["city"])}{chain_badge(cin)}</p>
</div>
<div class="flags">{note}<span class="unique">Séance unique</span></div>
</li>"""

    agenda_html = ""
    par_jour: dict[str, list] = defaultdict(list)
    for s in rep_uniques:
        par_jour[s["start"][:10]].append(s)
    for iso in sorted(par_jour):
        d = date.fromisoformat(iso)
        rows = "".join(seance_row(s) for s in sorted(par_jour[iso],
                                                     key=lambda x: x["start"]))
        # « Aujourd'hui »/« Demain » ne disent pas la date : on la précise.
        # Les autres jours sont déjà datés — l'ajouter ferait un doublon.
        libelle = fr_date(d, today)
        precision = (f'<span class="jour-date">{JOURS[d.weekday()]} {d.day} {MOIS[d.month-1]}</span>'
                     if libelle in ("Aujourd'hui", "Demain") else "")
        agenda_html += (f'<section class="jour"><h3 class="jour-titre">'
                        f'<span>{libelle}</span>{precision}'
                        f'</h3><ul class="seances">{rows}</ul></section>')

    cycles_html = ""
    for c in rep_cycles[:4]:
        bande = "".join(
            f'<a href="{movie_urls[k]}"><img src="{esc(movies[k]["poster"])}" '
            f'alt="Affiche de {esc(movies[k]["title"])}" loading="lazy"></a>'
            for k in c["movies"][:6] if movies[k]["poster"])
        salles_liens = ", ".join(
            f'<a href="{cinema_urls[cid]}">{esc(cinemas[cid]["name"])}</a>'
            for cid in c["cinemas"][:3])
        reste = len(c["cinemas"]) - 3
        if reste > 0:
            salles_liens += f' et {reste} autre{"s" if reste > 1 else ""} salle{"s" if reste > 1 else ""}'
        villes_txt = (f'{len(c["cities"])} villes' if len(c["cities"]) > 1
                      else esc(c["cities"][0]))
        cycles_html += f"""<article class="cycle">
<p class="eyebrow">Rétrospective</p>
<h3 class="cycle-nom"><a href="{cycle_urls[c["key"]]}">{esc(c["director"])}</a></h3>
<div class="bande">{bande}</div>
<p class="meta"><strong>{len(c["movies"])} films</strong> · {c["n_shows"]} séances · {villes_txt}</p>
<p class="meta">{salles_liens}</p>
<p class="meta"><a class="more" href="{cycle_urls[c["key"]]}">Voir le cycle →</a></p>
</article>"""

    salles_html = "".join(f"""<li class="salle">
<span class="rang">{i}</span>
<div class="salle-corps">
<h3 class="salle-nom"><a href="{cinema_urls[v["cinema"]]}">{esc(cinemas[v["cinema"]]["name"])}</a>
{chain_badge(cinemas[v["cinema"]])}</h3>
<p class="meta">{esc(cinemas[v["cinema"]]["city"])}</p>
</div>
<div class="jauge" role="img" aria-label="{v["share"]} % de séances de répertoire">
<div class="jauge-piste"><div class="jauge-part" style="width:{v["share"]}%"></div></div>
<p class="jauge-txt"><strong>{v["share"]} %</strong> de répertoire · {v["n_rep"]} séances sur {v["n_total"]}</p>
</div></li>""" for i, v in enumerate(rep_venues[:8], 1))

    # Villes classées par nombre de films de répertoire (pas par démographie :
    # Tours programme plus de reprises que Lyon).
    top_rep_cities = sorted(rep_cities.items(),
                            key=lambda kv: (-kv[1]["films"], -kv[1]["seances"]))[:12]
    villes_html = "".join(
        f'<a class="ville" href="/ville/{slug}/">'
        f'<span>{esc(cities[slug]["name"] if slug in cities else slug)}</span>'
        f'<span class="ville-n">{st["films"]} films</span></a>'
        for slug, st in top_rep_cities)
    raccourcis = ", ".join(
        f'<a href="/ville/{slug}/">{esc(cities[slug]["name"] if slug in cities else slug)} '
        f'<span class="racc-n">({st["seances"]} séances)</span></a>'
        for slug, st in top_rep_cities[:6])
    # Accueil : pas de pastilles de grandes villes. Elles listeraient Lyon ou
    # Nice, pauvres en reprises, alors que la ligne « villes les plus fournies »
    # ci-dessous donne les bonnes (Tours, Le Mans…). Ici, la recherche seule.
    home_finder = city_search_nav("", city_cmap, len(cities))

    n_rep_cines = len({s["cinema"] for s in rep_shows})
    n_rep_villes = len(rep_cities)
    body = f"""<p class="lead">{SITE_NAME} recense les reprises, rétrospectives et copies
restaurées à l'affiche dans toute la France. <strong>{n_rep_uniques} de ces séances ne
repasseront pas cette semaine alors n'attendez pas.</strong></p>

<div class="compteurs">
<div class="compteur"><b>{n_rep_films}</b><span>films de répertoire</span></div>
<div class="compteur"><b>{len(rep_shows)}</b><span>séances cette semaine</span></div>
<div class="compteur"><b>{n_rep_cines}</b><span>cinémas</span></div>
<div class="compteur"><b>{n_rep_villes}</b><span>villes</span></div>
<div class="compteur compteur-fort"><b>{n_rep_uniques}</b><span>séances uniques</span></div>
</div>

<h2>Choisissez votre ville</h2>
{home_finder}
<p class="meta">Les villes les plus fournies : {raccourcis}.</p>

<h2>À ne pas rater</h2>
<p class="meta">Des séances qui ne repassent nulle part ailleurs en France cette semaine.</p>
<p class="legende"><span class="puce">4.4<span class="sur">/5</span></span>
Note moyenne de la communauté <a href="https://letterboxd.com" rel="noopener">Letterboxd</a> —
les séances ci-dessous sont les mieux notées de la semaine.</p>
{agenda_html or "<p>Aucune séance unique repérée cette semaine.</p>"}

<h2>Rétrospectives en cours</h2>
<p class="meta">Les cycles programmés en ce moment, salle par salle.
<a class="more" href="/retrospectives/">Toutes les rétrospectives →</a></p>
<div class="cycles">{cycles_html or "<p>Aucun cycle en cours.</p>"}</div>

<h2>Salles de patrimoine</h2>
<p class="meta">Les cinémas dont la programmation fait la plus grande place au répertoire.
<a class="more" href="/salles-patrimoine/">Le classement complet →</a></p>
<ul class="salles">{salles_html}</ul>

<h2>Où voir du répertoire</h2>
<p class="meta">{n_rep_villes} villes sur {len(cities)} programment au moins une reprise cette semaine.</p>
<div class="villes">{villes_html}</div>

<div class="passerelle">
<p><span class="titre">Vous cherchez une sortie récente ?</span>
<span class="meta">{len(movies)} films à l'affiche cette semaine dans {len(cinemas)} cinémas,
indépendants et grandes enseignes.</span></p>
<a class="bouton" href="/a-l-affiche/">Voir ce qui est à l'affiche</a>
</div>"""
    write("/", page(
        f"Reprises et rétrospectives au cinéma en France — {SITE_NAME}",
        f"Quel classique voir en salle ? {n_rep_films} reprises, versions restaurées et "
        f"rétrospectives à l'affiche cette semaine dans {n_rep_cines} cinémas en France. "
        "Cherchez votre ville.",
        body, "/", h1="Ce soir, un classique passe près de chez vous",
        top_link=True))
    urls.append("/")

    # ----- Page Salles de patrimoine -----
    salles_full = "".join(f"""<li class="salle">
<span class="rang">{i}</span>
<div class="salle-corps">
<h3 class="salle-nom"><a href="{cinema_urls[v["cinema"]]}">{esc(cinemas[v["cinema"]]["name"])}</a>
{chain_badge(cinemas[v["cinema"]])}</h3>
<p class="meta"><a href="/ville/{cinemas[v["cinema"]]["city_slug"]}/">{esc(cinemas[v["cinema"]]["city"])}</a></p>
</div>
<div class="jauge" role="img" aria-label="{v["share"]} % de séances de répertoire">
<div class="jauge-piste"><div class="jauge-part" style="width:{v["share"]}%"></div></div>
<p class="jauge-txt"><strong>{v["share"]} %</strong> de répertoire · {v["n_rep"]} séances sur {v["n_total"]}</p>
</div></li>""" for i, v in enumerate(rep_venues, 1))
    venues_body = f"""<p class="lead">Certaines salles consacrent l'essentiel de leur
programmation aux films du passé : ce sont les cinémathèques de fait, souvent des cinémas
indépendants — mais pas seulement. Ce classement mesure la <strong>part</strong> de répertoire
dans la programmation de la semaine, pas le volume : une salle qui ne fait que ça devance un
multiplexe qui en propose davantage en valeur absolue. Seules les salles annonçant au moins
{repertoire.VENUE_MIN_SHOWS} séances sur la semaine sont classées.</p>
<ul class="salles">{salles_full}</ul>
<p class="meta"><a class="more" href="/carte/">Retrouver ces salles sur la carte →</a></p>"""
    write("/salles-patrimoine/", page(
        f"Les salles de patrimoine en France : où voir du répertoire — {SITE_NAME}",
        "Quels cinémas programment le plus de films de répertoire en France ? Classement des "
        "salles par part de reprises, rétrospectives et copies restaurées dans leur programmation.",
        venues_body, "/salles-patrimoine/", h1="Salles de patrimoine", top_link=True))
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
        rang = f'<span class="rang-lb">n° {rank}</span> · ' if rank else ""
        parts = [f"★ {m['lb_rating']}/5 Letterboxd" if m.get("lb_rating") else "",
                 f"{n} cinéma{'s' if n > 1 else ''}"]
        extra = f'<p class="meta">{rang}{" · ".join(p for p in parts if p)}</p>'
        # show_classic=False : ici tout est classique, le badge serait du bruit
        return movie_card(m, movie_urls, extra, show_rating=False, show_classic=False)

    # Une seule liste, triable et filtrable : les films notés dans l'ordre du
    # classement, puis ceux qu'on ne sait pas noter. tri.js n'en affiche que
    # PAGE_SIZE à la fois (313 cartes d'un bloc = 20 écrans desktop, 60 mobile)
    # et ajoute un « Afficher plus » ; sans JavaScript, tout reste visible.
    classics_html = ("".join(classic_card(m, i) for i, m in enumerate(rated, 1))
                     + "".join(classic_card(m) for m in unrated))
    n_classic_cines = len({s["cinema"] for m in classics for s in by_movie[m["key"]]})
    classics_body = f"""<p class="lead">{len(classics)} films d'au moins {CLASSIC_AGE_YEARS} ans
sont à l'affiche en ce moment : rétrospectives, versions restaurées et séances de ciné-club
dans {n_classic_cines} cinémas en France, classés par la note de la communauté
<a href="https://letterboxd.com" rel="noopener">Letterboxd</a>. Le grand écran, c'est aussi fait pour ça.</p>
{city_finder}
{film_tools("film-list", "lb", len(classics))}
<div class="grid" id="film-list">{classics_html or "<p>Aucune reprise annoncée en ce moment.</p>"}</div>"""
    write("/classiques/", page(
        f"Films classiques et rétrospectives au cinéma — {SITE_NAME}",
        f"Quel film classique revoir en salle ? {len(classics)} reprises, rétrospectives et "
        "versions restaurées à l'affiche en France, classées par note Letterboxd.",
        classics_body, "/classiques/", h1="Classiques & rétrospectives à l'affiche",
        top_link=True))
    urls.append("/classiques/")

    # ----- Pages de rétrospective (une par cycle) -----
    # Un cycle est ancré dans une salle : on présente donc le programme salle
    # par salle, avec les horaires. C'est ce qu'un spectateur vient chercher.
    for c in rep_cycles:
        path = cycle_urls[c["key"]]
        films_du_cycle = set(c["movies"])
        blocs = []
        for cid in c["cinemas"]:
            cinema = cinemas[cid]
            par_film = defaultdict(list)
            for s in rep_by_cinema[cid]:
                if s["movie"] in films_du_cycle:
                    par_film[s["movie"]].append(s)
            if not par_film:
                continue
            cartes = []
            for mk, ss in sorted(par_film.items(),
                                 key=lambda kv: sorted(kv[1], key=lambda s: s["start"])[0]["start"]):
                jours = defaultdict(list)
                for s in sorted(ss, key=lambda x: x["start"])[:8]:
                    jours[s["start"][:10]].append(s)
                horaires = " ".join(
                    f'<span class="day">{fr_date(date.fromisoformat(d), today)}</span>{showtime_pills(v)}'
                    for d, v in sorted(jours.items()))
                cartes.append(movie_card(movies[mk], movie_urls, horaires,
                                         show_classic=False))
            blocs.append(f"""<section class="cinema-block">
<h2><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h2>
<p class="meta"><a href="/ville/{cinema["city_slug"]}/">{esc(cinema["city"])}</a> —
{len(par_film)} film{"s" if len(par_film) > 1 else ""} du cycle</p>
<div class="films">{"".join(cartes)}</div></section>""")

        affiches = "".join(
            f'<a href="{movie_urls[k]}"><img src="{esc(movies[k]["poster"])}" '
            f'alt="Affiche de {esc(movies[k]["title"])}" loading="lazy"></a>'
            for k in c["movies"] if movies[k]["poster"])
        titres = ", ".join(movies[k]["title"] for k in c["movies"])
        tronque = len(c["cities"]) > 6
        villes_txt = ", ".join(c["cities"][:6]) + ("…" if tronque else "")
        # Pas de point final après « … » : « Montreuil…. » est disgracieux.
        fin = "" if tronque else "."
        n_films, n_salles = len(c["movies"]), len(c["cinemas"])
        body = f"""<p class="lead"><strong>{n_films} films</strong> de {esc(c["director"])}
sont à l'affiche cette semaine, en {c["n_shows"]} séances, dans {n_salles}
salle{"s" if n_salles > 1 else ""} — {esc(villes_txt)}{fin}</p>
<div class="bande">{affiches}</div>
<p class="meta">Au programme : {esc(titres)}.</p>
{"".join(blocs)}
<p class="meta"><a class="more" href="/retrospectives/">← Toutes les rétrospectives en cours</a></p>"""
        jsonld = {"@context": "https://schema.org", "@type": "CollectionPage",
                  "name": f"Rétrospective {c['director']}",
                  "about": {"@type": "Person", "name": c["director"]}}
        write(path, page(
            f"Rétrospective {c['director']} : où voir ses films en salle — {SITE_NAME}",
            f"Où voir les films de {c['director']} au cinéma ? {n_films} films à l'affiche "
            f"cette semaine en {c['n_shows']} séances, dans {n_salles} salle(s) : {villes_txt}.",
            body, path, jsonld, h1=f"Rétrospective {c['director']}", top_link=True))
        urls.append(path)

    # ----- Index des rétrospectives -----
    if rep_cycles:
        index_cartes = "".join(f"""<article class="cycle">
<p class="eyebrow">Rétrospective</p>
<h3 class="cycle-nom"><a href="{cycle_urls[c["key"]]}">{esc(c["director"])}</a></h3>
<div class="bande">{"".join(
    f'<img src="{esc(movies[k]["poster"])}" alt="Affiche de {esc(movies[k]["title"])}" loading="lazy">'
    for k in c["movies"][:6] if movies[k]["poster"])}</div>
<p class="meta"><strong>{len(c["movies"])} films</strong> · {c["n_shows"]} séances ·
{len(c["cities"])} ville{"s" if len(c["cities"]) > 1 else ""}</p>
<p class="meta">{esc(", ".join(c["cities"][:4]))}{"…" if len(c["cities"]) > 4 else ""}</p>
</article>""" for c in rep_cycles)
        n_cyc_films = len({k for c in rep_cycles for k in c["movies"]})
        index_body = f"""<p class="lead">Une rétrospective, ce n'est pas un vieux film isolé :
c'est une salle qui consacre sa programmation à une œuvre. {SITE_NAME} en repère
<strong>{len(rep_cycles)}</strong> en ce moment en France — {n_cyc_films} films au total.
Un cycle est détecté dès qu'une même salle programme au moins deux films d'un même cinéaste
dans la semaine.</p>
<div class="cycles">{index_cartes}</div>
<p class="meta"><a class="more" href="/">← L'agenda du répertoire</a></p>"""
        write("/retrospectives/", page(
            f"Rétrospectives et cycles au cinéma en France — {SITE_NAME}",
            f"Quelles rétrospectives voir en salle ? {len(rep_cycles)} cycles de cinéastes "
            f"programmés cette semaine en France, salle par salle : {n_cyc_films} films à l'affiche.",
            index_body, "/retrospectives/", h1="Rétrospectives en cours", top_link=True))
        urls.append("/retrospectives/")

    # ----- Idées de marathon -----
    # Deux films du même genre enchaînables dans deux salles voisines, dans les
    # dix plus grandes villes. Angle éditorial : les reprises d'abord, et une
    # bonne raison de pousser la porte d'une seconde salle (souvent un indé).
    ideas_by_city = build_ideas(BIG_CITY_SLUGS, cinemas, movies, showtimes,
                                is_classic, today)
    marathon_cities = [s for s in BIG_CITY_SLUGS if s in ideas_by_city]

    def marathon_card(idea: dict) -> str:
        first, second = idea["first"], idea["second"]

        def leg(show: dict) -> str:
            cinema = cinemas[show["cinema"]]
            hour = show["start"][11:16].replace(":", "h")
            # Une idée de marathon désigne DEUX séances précises : si elles
            # sont réservables, c'est ici que le visiteur veut cliquer.
            if show.get("booking"):
                hour = (f'<a href="{esc(show["booking"])}" target="_blank"'
                        f' rel="noopener noreferrer"'
                        f' title="Réserver cette séance (nouvel onglet)">{hour}</a>')
            version = f' <span class="v">{esc(show["version"])}</span>' if show["version"] else ""
            extra = (f'<p class="meta"><strong>{hour}</strong>{version} — '
                     f'<a href="{cinema_urls[show["cinema"]]}">{esc(cinema["name"])}</a>'
                     f'{chain_badge(cinema)}</p>')
            return movie_card(movies[show["movie"]], movie_urls, extra)

        genre = min(idea["genres"]).capitalize()
        day = fr_date(date.fromisoformat(idea["day"]), today)
        km_txt = f'{idea["distance_km"]:.1f}'.replace(".", ",")
        return f"""<article class="marathon">
<h3>{esc(day)} · marathon {esc(genre)}</h3>
<div class="grid marathon-films">{leg(first)}{leg(second)}</div>
<p class="marathon-transfer">🚶 {km_txt} km entre les deux salles, soit ~{idea["walk_min"]} min
à pied — vous avez {idea["gap_min"]} min d'entracte à la fin du premier film.</p>
</article>"""

    if marathon_cities:
        jump = " ".join(f'<a href="#m-{s}">{esc(cities[s]["name"])}</a>'
                        for s in marathon_cities)
        sections = "".join(
            f'<section id="m-{s}"><h2>{esc(cities[s]["name"])}</h2>'
            f'<p class="meta"><a href="/ville/{s}/">Toutes les séances à '
            f'{esc(cities[s]["name"])} →</a></p>'
            + "".join(marathon_card(i) for i in ideas_by_city[s]) + "</section>"
            for s in marathon_cities)
        n_ideas = sum(len(v) for v in ideas_by_city.values())
        marathon_body = f"""<p class="lead">Une séance, c'est bien. Deux à la suite, c'est une
soirée. Pour les {len(marathon_cities)} plus grandes villes de France, {SITE_NAME} compose des
doubles programmes du même genre dans <strong>deux salles voisines</strong> : le temps de trajet
à pied est calculé, l'entracte vérifié. Les reprises de
<a href="/classiques/">classiques</a> sont privilégiées — l'occasion de découvrir une seconde
salle en chemin.</p>
<nav class="city-jump">{jump}</nav>
{sections}"""
        write("/marathon/", page(
            f"Idées de marathon cinéma : deux films à la suite — {SITE_NAME}",
            f"{n_ideas} idées de marathon dans les grandes villes de France : deux films du même "
            "genre enchaînés dans deux cinémas voisins, trajet à pied et entracte calculés.",
            marathon_body, "/marathon/", h1="Idées de marathon", top_link=True))
        urls.append("/marathon/")

    # ----- Carte des cinémas -----
    # Données injectées dans la page (pas de fetch) : nom, ville, coords, chaîne, URL.
    map_points = [
        {"name": c["name"], "city": c["city"], "lat": c["lat"], "lon": c["lon"],
         "chain": c.get("chain", ""), "url": f"{BASE_PATH}{cinema_urls[cid]}"}
        for cid, c in cinemas.items() if c["lat"] and c["lon"]
    ]
    n_inde_map = sum(1 for p in map_points if not p["chain"])
    leaflet_css = (
        '<link rel="stylesheet" href="/assets/vendor/leaflet/leaflet.css">'
        '<link rel="stylesheet" href="/assets/vendor/leaflet.markercluster/MarkerCluster.css">'
        '<link rel="stylesheet" href="/assets/vendor/leaflet.markercluster/MarkerCluster.Default.css">'
    )
    map_body = f"""<p class="lead">{len(map_points)} cinémas géolocalisés en France —
{n_inde_map} indépendants et {len(map_points) - n_inde_map} de grandes enseignes.
Cliquez un point pour accéder au programme de la salle.</p>
<div id="map-legend">
<span class="legend-item"><span class="legend-dot dot-indep"></span>Cinéma indépendant</span>
<span class="legend-item"><span class="legend-dot dot-chain"></span>Grande enseigne</span>
</div>
<div id="cine-map"></div>
<script type="application/json" id="cinemas-data">{json.dumps(map_points, ensure_ascii=False)}</script>
<script src="/assets/vendor/leaflet/leaflet.js"></script>
<script src="/assets/vendor/leaflet.markercluster/leaflet.markercluster.js"></script>
<script src="/assets/map.js"></script>"""
    write("/carte/", page(
        f"Carte des cinémas en France — {SITE_NAME}",
        f"Carte interactive de {len(map_points)} cinémas en France, indépendants et "
        "grandes enseignes. Trouvez une salle près de chez vous et accédez à son programme.",
        map_body, "/carte/", h1="Carte des cinémas", head_extra=leaflet_css))
    urls.append("/carte/")

    # ----- sitemap & robots -----
    lastmod = meta["generated_at"][:10]
    entries = "".join(
        f"<url><loc>{BASE_URL}{u}</loc><lastmod>{lastmod}</lastmod></url>" for u in sorted(urls))
    (SITE / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>',
        encoding="utf-8")
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")

    # ----- 404 de marque (GitHub Pages sert /404.html) -----
    # La 404 brute de GitHub éjectait le visiteur du site (page blanche, sans
    # lien de retour). Hors sitemap, volontairement.
    (SITE / "404.html").write_text(page(
        f"Page introuvable — {SITE_NAME}",
        "Cette page n'existe pas ou plus.",
        """<p class="lead">Cette adresse ne mène à aucune page. Le programme change chaque jour :
les fiches des films sortis de l'affiche disparaissent avec leurs séances.</p>
<p><a class="more" href="/">← Le répertoire</a> &nbsp;
<a class="more" href="/a-l-affiche/">🎬 À l'affiche</a> &nbsp;
<a class="more" href="/salles-patrimoine/">🏛️ Salles de patrimoine</a> &nbsp;
<a class="more" href="/carte/">🗺️ Carte</a></p>""",
        "/404.html", h1="Oups, séance introuvable"), encoding="utf-8")

    print(f"Site généré dans {SITE} : {len(urls)} pages "
          f"({len(cinemas)} cinémas, {len(cities)} villes, {len(movies)} films)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
