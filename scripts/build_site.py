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
from sources import load_merged, cinema_kind  # fusion indés + chaînes

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
{head_extra}
{ld}
</head>
<body>
<header class="site-header">
<a class="brand" href="/">🎬 {SITE_NAME}</a>
<p class="tagline">Les séances de cinéma, partout en France</p>
<nav class="site-nav"><a href="/classiques/">🎞️ Classiques</a> <a href="/carte/">🗺️ Carte des cinémas</a></nav>
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
    pills = []
    for s in sorted(shows, key=lambda x: x["start"]):
        t = s["start"][11:16].replace(":", "h")
        v = f' <span class="v">{esc(s["version"])}</span>' if s["version"] else ""
        pills.append(f'<li>{t}{v}</li>')
    return f'<ul class="showtimes">{"".join(pills)}</ul>'


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
    return f"""<article class="movie-card">
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


# --- Construction ---------------------------------------------------------

def main() -> int:
    today = date.today()
    cinemas, movies, showtimes, cities = load_merged(DATA)
    meta = load("meta.json")

    # Index des séances
    by_cinema = defaultdict(list)
    by_movie = defaultdict(list)
    for s in showtimes:
        by_cinema[s["cinema"]].append(s)
        by_movie[s["movie"]].append(s)

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
            today_iso = today.isoformat()
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
        # Villes repliées par défaut (<details>) : un film très diffusé faisait
        # jusqu'à 96 écrans de scroll toutes villes dépliées. Peu de villes →
        # tout ouvert, le repli n'apporterait rien.
        few_cities = len(city_slugs) <= 3
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
<h3><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h3>
{per_day}</section>""")
            n = len(blocks)
            rows.append(f"""<details class="city-group" id="v-{cslug}"{" open" if few_cities else ""}>
<summary>{esc(city_name(cslug))} <span class="meta">{n} cinéma{"s" if n > 1 else ""}</span></summary>
<p class="meta"><a href="/ville/{cslug}/">Tous les cinémas de {esc(city_name(cslug))} →</a></p>
{"".join(blocks)}</details>""")
        # Sommaire des villes : les plus grandes villes en accès direct,
        # une recherche (datalist native, sans dépendance) pour les autres —
        # 234 pastilles de villes formaient un mur illisible.
        city_jump = ""
        if len(city_slugs) > 6:
            majors = [c for c in BIG_CITY_SLUGS if c in by_city]
            pills = " ".join(f'<a href="#v-{c}">{esc(city_name(c))}</a>' for c in majors)
            cmap = {city_name(c): f"v-{c}" for c in city_slugs}
            # Suggestions maison (pas de <datalist> : elle déroule tout au clic ;
            # ici rien ne s'ouvre avant 2 lettres tapées — voir film.js)
            city_jump = city_search_nav(pills, cmap, len(city_slugs))
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
        body = f"""<div class="film-head">{poster}<div>
<p class="lead">{classic_badge(movie)} {esc(credits)}</p>
<p>{esc(movie["storyline"])}</p>{trailer}</div></div>
<h2>Où voir {esc(movie["title"])} ?</h2>
{city_jump}
{"".join(rows) or "<p>Aucune séance à venir.</p>"}"""
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

    # ----- Accueil -----
    top_movies = sorted(movies.values(),
                        key=lambda m: -len(by_movie[m["key"]]))[:12]
    films_html = "".join(
        movie_card(m, movie_urls,
                   f'<p class="meta">{len({s["cinema"] for s in by_movie[m["key"]]})} cinémas</p>')
        for m in top_movies)
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
    # Mise en avant éditoriale : les reprises de classiques à l'affiche,
    # les mieux notées (Letterboxd) d'abord — cohérent avec le classement
    top_classics = sorted((m for m in movies.values() if is_classic(m)),
                          key=lambda m: (-(m.get("lb_rating") or 0),
                                         -len(by_movie[m["key"]])))[:8]
    classics_html = "".join(
        movie_card(m, movie_urls,
                   f'<p class="meta">{len({s["cinema"] for s in by_movie[m["key"]]})} cinémas</p>')
        for m in top_classics)
    classics_section = (f"""
<h2>🎞️ Classiques &amp; rétrospectives</h2>
<p class="meta">Les films d'hier à revoir en salle : versions restaurées, ciné-clubs, rétrospectives.</p>
<div class="grid">{classics_html}</div>
<p><a class="more" href="/classiques/">Tous les classiques à l'affiche →</a></p>"""
                        if top_classics else "")
    # La ville d'abord : c'est l'action principale promise par le H1 (« Quel
    # film voir ce soir ? » commence par « où »), avant les vitrines de films.
    body = f"""<p class="lead">{inventory}, {len(cities)} villes,
{len(showtimes)} séances à venir. Mis à jour quotidiennement.</p>
<h2>Choisissez votre ville</h2>
{city_finder}
<details class="all-cities"><summary>Toutes les villes ({len(cities)})</summary>
<ul class="cities">{cities_html}</ul></details>
<h2>À l'affiche cette semaine</h2>
<div class="grid">{films_html}</div>{classics_section}"""
    write("/", page(
        f"{SITE_NAME} — Séances de cinéma partout en France",
        f"Les séances et horaires de {len(cinemas)} cinémas en France, indépendants "
        "et grandes enseignes, mis à jour chaque jour. Trouvez votre film, votre ville, votre salle.",
        body, "/", h1="Quel film voir au cinéma ce soir ?"))
    urls.append("/")

    # ----- Page Classiques & rétrospectives -----
    # Classement unique par note Letterboxd (choix éditorial) : du chef-d'œuvre
    # plébiscité au moins aimé ; les films sans note fiable ferment la marche.
    classics = [m for m in movies.values() if is_classic(m) and by_movie[m["key"]]]
    rated = sorted((m for m in classics if m.get("lb_rating")),
                   key=lambda m: (-m["lb_rating"], -len(by_movie[m["key"]])))
    unrated = sorted((m for m in classics if not m.get("lb_rating")),
                     key=lambda m: -len(by_movie[m["key"]]))

    def classic_card(m: dict, rank: int | None = None) -> str:
        n = len({s["cinema"] for s in by_movie[m["key"]]})
        parts = [f"n° {rank}" if rank else "",
                 f"★ {m['lb_rating']}/5 Letterboxd" if m.get("lb_rating") else "",
                 f"{n} cinéma{'s' if n > 1 else ''}"]
        extra = f'<p class="meta">{" · ".join(p for p in parts if p)}</p>'
        # show_classic=False : ici tout est classique, le badge serait du bruit
        return movie_card(m, movie_urls, extra, show_rating=False, show_classic=False)

    # Top du classement déplié, la longue traîne repliée : 313 cartes d'un
    # bloc = 20 écrans desktop, 60 mobile. Un humain n'en scanne pas plus.
    TOP_RANKED = 40
    ranked_html = "".join(classic_card(m, i) for i, m in enumerate(rated[:TOP_RANKED], 1))
    rest = rated[TOP_RANKED:]
    rest_html = (f'<details class="more-films"><summary>Voir la suite du classement '
                 f'(n° {TOP_RANKED + 1} à {len(rated)})</summary><div class="grid">'
                 + "".join(classic_card(m, i) for i, m in enumerate(rest, TOP_RANKED + 1))
                 + "</div></details>" if rest else "")
    unrated_html = "".join(classic_card(m) for m in unrated)
    unrated_section = (f'<details class="more-films"><summary>Sans note Letterboxd fiable '
                       f'({len(unrated)} film{"s" if len(unrated) > 1 else ""})</summary>'
                       f'<div class="grid">{unrated_html}</div></details>' if unrated else "")
    n_classic_cines = len({s["cinema"] for m in classics for s in by_movie[m["key"]]})
    classics_body = f"""<p class="lead">{len(classics)} films d'au moins {CLASSIC_AGE_YEARS} ans
sont à l'affiche en ce moment : rétrospectives, versions restaurées et séances de ciné-club
dans {n_classic_cines} cinémas en France, classés par la note de la communauté
<a href="https://letterboxd.com" rel="noopener">Letterboxd</a>. Le grand écran, c'est aussi fait pour ça.</p>
{city_finder}
<div class="grid">{ranked_html or "<p>Aucune reprise annoncée en ce moment.</p>"}</div>
{rest_html}
{unrated_section}"""
    write("/classiques/", page(
        f"Films classiques et rétrospectives au cinéma — {SITE_NAME}",
        f"Quel film classique revoir en salle ? {len(classics)} reprises, rétrospectives et "
        "versions restaurées à l'affiche en France, classées par note Letterboxd.",
        classics_body, "/classiques/", h1="Classiques & rétrospectives à l'affiche",
        top_link=True))
    urls.append("/classiques/")

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
<p><a class="more" href="/">← Retour à l'accueil</a> &nbsp;
<a class="more" href="/carte/">🗺️ Carte des cinémas</a> &nbsp;
<a class="more" href="/classiques/">🎞️ Classiques</a></p>""",
        "/404.html", h1="Oups, séance introuvable"), encoding="utf-8")

    print(f"Site généré dans {SITE} : {len(urls)} pages "
          f"({len(cinemas)} cinémas, {len(cities)} villes, {len(movies)} films)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
