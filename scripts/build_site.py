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
         jsonld: dict | None = None, h1: str | None = None) -> str:
    """Enveloppe une page : head SEO complet + header/footer communs."""
    ld = (f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'
          if jsonld else "")
    doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{BASE_URL}{path}">
<link rel="stylesheet" href="/assets/style.css">
{ld}
</head>
<body>
<header class="site-header">
<a class="brand" href="/">🎬 {SITE_NAME}</a>
<p class="tagline">Les séances de cinéma, partout en France</p>
</header>
<main>
<h1>{esc(h1 if h1 is not None else title)}</h1>
{body}
</main>
<footer>
<p>Données de programmation : <a href="https://datacinesindes.fr" rel="noopener">Data Ciné Indés / SCARE</a>
(Syndicat des Cinémas d'Art, de Répertoire et d'Essai) — Licence Ouverte 2.0.</p>
<p>{SITE_NAME} réunit les séances des cinémas indépendants et des grandes enseignes, et met en avant les salles Art &amp; Essai.</p>
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


def showtime_pills(shows: list[dict]) -> str:
    pills = []
    for s in sorted(shows, key=lambda x: x["start"]):
        t = s["start"][11:16].replace(":", "h")
        v = f' <span class="v">{esc(s["version"])}</span>' if s["version"] else ""
        pills.append(f'<li>{t}{v}</li>')
    return f'<ul class="showtimes">{"".join(pills)}</ul>'


def movie_card(movie: dict, movie_urls: dict, extra: str = "") -> str:
    url = movie_urls[movie["key"]]
    poster = (f'<img src="{esc(movie["poster"])}" alt="Affiche de {esc(movie["title"])}" loading="lazy">'
              if movie["poster"] else '<div class="noposter">🎞️</div>')
    meta = " · ".join(filter(None, [
        movie["genre"], f"{movie['duration_min']} min" if movie["duration_min"] else "",
    ]))
    return f"""<article class="movie-card">
<a href="{url}">{poster}</a>
<div class="movie-info">
<h3><a href="{url}">{esc(movie["title"])}</a></h3>
<p class="meta">{esc(meta)}</p>
{extra}
</div>
</article>"""


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
        for cid in sorted(city["cinemas"], key=lambda c: cinemas[c]["name"]):
            cinema = cinemas[cid]
            shows = [s for s in by_cinema[cid] if s["start"][:10] <= horizon]
            films = defaultdict(list)
            for s in shows:
                films[s["movie"]].append(s)
            today_iso = today.isoformat()
            films_html = []
            for mk, ss in sorted(films.items(), key=lambda kv: kv[1][0]["start"]):
                todays = [s for s in ss if s["start"][:10] == today_iso]
                label = showtime_pills(todays) if todays else \
                    f'<p class="meta">prochaine séance : {fr_date(date.fromisoformat(ss[0]["start"][:10]), today)}</p>'
                films_html.append(movie_card(movies[mk], movie_urls, label))
            blocks.append(f"""<section class="cinema-block">
<h2><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a>{chain_badge(cinema)}</h2>
<p class="meta">{esc(cinema["address"])} — <a href="{cinema_urls[cid]}">programme complet</a></p>
{"".join(films_html) or "<p>Aucune séance cette semaine.</p>"}</section>""")
        n_cine = len(city["cinemas"])
        n_chain = sum(1 for cid in city["cinemas"] if cinemas[cid].get("chain"))
        n_inde = n_cine - n_chain
        parts = []
        if n_inde:
            parts.append(f'{n_inde} cinéma{"s" if n_inde > 1 else ""} indépendant{"s" if n_inde > 1 else ""}')
        if n_chain:
            parts.append(f'{n_chain} cinéma{"s" if n_chain > 1 else ""} de chaîne')
        body = f"""<p class="lead">{" et ".join(parts)} à {esc(city["name"])} —
séances du jour et de la semaine.</p>{"".join(blocks)}"""
        write(path, page(
            f"Cinéma à {city['name']} : séances et horaires — {SITE_NAME}",
            f"Quel film voir à {city['name']} ? Séances et horaires des {n_cine} cinéma(s) "
            f"de la ville : programme du jour et de la semaine.",
            body, path, h1=f"Cinémas à {city['name']}"))
        urls.append(path)

    # ----- Pages film -----
    for key, movie in movies.items():
        path = movie_urls[key]
        shows = by_movie[key]
        by_cine = defaultdict(list)
        for s in shows:
            by_cine[s["cinema"]].append(s)
        rows = []
        for cid, ss in sorted(by_cine.items(),
                              key=lambda kv: (cinemas[kv[0]]["city"], cinemas[kv[0]]["name"])):
            cinema = cinemas[cid]
            nxt = sorted(ss, key=lambda s: s["start"])[:8]
            days = defaultdict(list)
            for s in nxt:
                days[s["start"][:10]].append(s)
            per_day = " ".join(
                f'<span class="day">{fr_date(date.fromisoformat(d), today)}</span>{showtime_pills(v)}'
                for d, v in sorted(days.items()))
            rows.append(f"""<section class="cinema-block">
<h3><a href="{cinema_urls[cid]}">{esc(cinema["name"])}</a> — {esc(cinema["city"])}</h3>
{per_day}</section>""")
        credits = " · ".join(filter(None, [
            movie["director"] and f"De {movie['director']}",
            movie["cast"] and f"Avec {movie['cast']}",
            movie["genre"], movie["duration_min"] and f"{movie['duration_min']} min"]))
        poster = (f'<img class="poster" src="{esc(movie["poster"])}" alt="Affiche de {esc(movie["title"])}">'
                  if movie["poster"] else "")
        trailer = (f'<p><a href="{esc(movie["trailer"])}" rel="noopener">▶ Bande-annonce</a></p>'
                   if movie["trailer"] else "")
        body = f"""<div class="film-head">{poster}<div>
<p class="lead">{esc(credits)}</p>
<p>{esc(movie["storyline"])}</p>{trailer}</div></div>
<h2>Où voir {esc(movie["title"])} ?</h2>
{"".join(rows) or "<p>Aucune séance à venir.</p>"}"""
        jsonld = {"@context": "https://schema.org", "@type": "Movie", "name": movie["title"]}
        if movie["director"]:
            jsonld["director"] = {"@type": "Person", "name": movie["director"]}
        if movie["poster"]:
            jsonld["image"] = movie["poster"]
        write(path, page(
            f"{movie['title']} : séances près de chez vous — {SITE_NAME}",
            (f"Où voir {movie['title']}"
             + (f" de {movie['director']}" if movie["director"] else "")
             + " ? Toutes les séances dans les cinémas indépendants en France."),
            body, path, jsonld, h1=movie["title"]))
        urls.append(path)

    # ----- Accueil -----
    top_movies = sorted(movies.values(),
                        key=lambda m: -len(by_movie[m["key"]]))[:12]
    films_html = "".join(
        movie_card(m, movie_urls,
                   f'<p class="meta">{len({s["cinema"] for s in by_movie[m["key"]]})} cinémas</p>')
        for m in top_movies)
    cities_html = "".join(
        f'<li><a href="/ville/{slug}/">{esc(c["name"])}</a> '
        f'<span class="meta">{len(c["cinemas"])} ciné{"s" if len(c["cinemas"]) > 1 else ""}</span></li>'
        for slug, c in cities.items())
    n_chain = sum(1 for c in cinemas.values() if c.get("chain"))
    n_inde = len(cinemas) - n_chain
    inventory = f"{n_inde} cinémas indépendants"
    if n_chain:
        inventory += f" et {n_chain} cinémas de chaîne"
    body = f"""<p class="lead">{inventory}, {len(cities)} villes,
{len(showtimes)} séances à venir. Mis à jour quotidiennement.</p>
<h2>À l'affiche cette semaine</h2>
<div class="grid">{films_html}</div>
<h2>Choisissez votre ville</h2>
<ul class="cities">{cities_html}</ul>"""
    write("/", page(
        f"{SITE_NAME} — Séances de cinéma partout en France",
        f"Les séances et horaires de {len(cinemas)} cinémas en France, indépendants "
        "et grandes enseignes, mis à jour chaque jour. Trouvez votre film, votre ville, votre salle.",
        body, "/", h1="Quel film voir au cinéma ce soir ?"))
    urls.append("/")

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

    print(f"Site généré dans {SITE} : {len(urls)} pages "
          f"({len(cinemas)} cinémas, {len(cities)} villes, {len(movies)} films)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
