"""Idées de marathon : enchaîner deux films du même genre dans deux cinémas voisins.

Reprend l'idée du « Ciné marathon » de Paris Ciné Aujourd'hui, en national :
pour chaque grande ville, on cherche des paires de séances du même jour que le
spectateur peut réellement enchaîner à pied, dans DEUX salles différentes
(l'intérêt du jeu : faire découvrir une seconde salle, souvent un indé).

Contraintes d'une paire valide :
  - même jour, deux cinémas distincts, deux films distincts ;
  - au moins un genre en commun (c'est ce qui fait un « marathon » thématique) ;
  - les deux salles à moins de MAX_KM, et l'entracte doit couvrir le trajet
    à pied plus une marge (file d'attente, pause) sans être une demi-journée.

Le tri privilégie les reprises de classiques (le focus éditorial du site),
puis les films les mieux notés sur Letterboxd.

Aucune dépendance externe (stdlib uniquement).
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta

MAX_KM = 3.5              # au-delà, ce n'est plus « deux cinémas rapprochés »
WALK_MIN_PER_KM = 12      # ~5 km/h, allure de marche urbaine
MARGIN_MIN = 10           # marge incompressible (sortie de salle, file d'attente)
SLACK_MAX_MIN = 60        # au-delà, l'attente casse l'enchaînement
HORIZON_DAYS = 7
IDEAS_PER_CITY = 4
MIN_DISTINCT_GENRES = 3   # varier les genres proposés dans une même ville

# Marathon dans UNE seule salle : pas de trajet, juste un entracte le temps de
# souffler. En dessous de PAUSE_MIN on n'a pas le temps de sortir ; au-dessus
# de PAUSE_MAX l'attente casse l'enchaînement (autant rentrer chez soi).
PAUSE_MIN = 5
PAUSE_MAX = 45

# Un « marathon culte » enchaîne DEUX reprises de classiques bien notées : c'est
# le cœur du site (films cultes) et ce qu'un cinéphile vient chercher ici.
CULT_LB_MIN = 3.7         # note Letterboxd /5 minimale de CHAQUE film du duo

# Plafond de gap au-delà duquel la suite de la journée est forcément trop
# tardive pour ce premier film — sert à couper la boucle (les séances sont
# triées par heure). On prend le pire cas des deux formats de marathon.
GAP_BREAK = max(WALK_MIN_PER_KM * MAX_KM + MARGIN_MIN + SLACK_MAX_MIN, PAUSE_MAX)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau entre deux points (km)."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def _genres(movie: dict) -> set:
    """Genres normalisés d'un film (« Drame, Comédie » → {drame, comédie})."""
    return {g.strip().lower() for g in (movie.get("genre") or "").split(",") if g.strip()}


def walk_minutes(distance_km: float) -> int:
    """Temps de marche estimé, plancher à 5 min (traverser une rue prend du temps)."""
    return max(5, round(distance_km * WALK_MIN_PER_KM))


def _pairs_for_day(shows: list, cinemas: dict, movies: dict, is_classic) -> list:
    """Toutes les paires enchaînables parmi les séances d'un même jour.

    Deux formats : « voisin » (deux salles distinctes à moins de MAX_KM, le
    trajet à pied tenant dans l'entracte) et « même salle » (deux films de
    suite au même cinéma, séparés d'une simple pause). Chaque paire est aussi
    marquée `is_cult` quand ses deux films sont des reprises de classiques bien
    notées.
    """
    found = []
    shows.sort(key=lambda s: s["start"])
    for i, first in enumerate(shows):
        m1 = movies[first["movie"]]
        duration = m1.get("duration_min")
        g1 = _genres(m1)
        if not duration or not g1:
            continue  # sans durée ni genre, impossible d'enchaîner sérieusement
        c1 = cinemas[first["cinema"]]
        ends = datetime.fromisoformat(first["start"][:19]) + timedelta(minutes=duration)
        for second in shows[i + 1:]:
            if second["movie"] == first["movie"]:
                continue
            gap = (datetime.fromisoformat(second["start"][:19]) - ends).total_seconds() / 60
            # Séances triées par heure : au-delà du plafond absolu, la suite
            # de la journée est forcément trop tardive pour ce premier film.
            if gap > GAP_BREAK:
                break
            m2 = movies[second["movie"]]
            shared = g1 & _genres(m2)
            if not shared:
                continue
            c2 = cinemas[second["cinema"]]
            if second["cinema"] == first["cinema"]:
                # Même salle : aucun trajet, juste un entracte raisonnable.
                if not PAUSE_MIN <= gap <= PAUSE_MAX:
                    continue
                kind, distance, walk = "meme_salle", 0.0, 0
            else:
                distance = haversine_km(c1["lat"], c1["lon"], c2["lat"], c2["lon"])
                if distance > MAX_KM:
                    continue
                walk = walk_minutes(distance)
                if not walk + MARGIN_MIN <= gap <= walk + MARGIN_MIN + SLACK_MAX_MIN:
                    continue
                kind = "voisin"
            r1, r2 = m1.get("lb_rating") or 0, m2.get("lb_rating") or 0
            found.append({
                "day": first["start"][:10],
                "first": first, "second": second,
                "genres": shared,
                "kind": kind,
                "distance_km": distance,
                "walk_min": walk,
                "gap_min": int(gap),
                "n_classics": int(is_classic(m1)) + int(is_classic(m2)),
                "rating": r1 + r2,
                "is_cult": (is_classic(m1) and is_classic(m2)
                            and r1 >= CULT_LB_MIN and r2 >= CULT_LB_MIN),
                "has_inde": not c1.get("chain") or not c2.get("chain"),
            })
    return found


def _select(ideas: list, limit: int) -> list:
    """Garde les meilleures idées, sans répéter une paire de films ni s'enfermer
    dans un seul genre (trois « marathons drame » ne sont pas trois idées).
    Les marathons cultes passent devant : c'est ce qu'on vient chercher ici."""
    ideas.sort(key=lambda x: (-x["is_cult"], -x["n_classics"], -x["rating"],
                              -x["has_inde"], x["distance_km"], x["day"]))
    kept, seen_pairs, seen_genres = [], set(), set()
    for idea in ideas:
        pair = frozenset((idea["first"]["movie"], idea["second"]["movie"]))
        if pair in seen_pairs:
            continue
        genre = min(idea["genres"])
        if genre in seen_genres and len(seen_genres) < MIN_DISTINCT_GENRES:
            continue
        seen_pairs.add(pair)
        seen_genres.add(genre)
        kept.append(idea)
        if len(kept) == limit:
            break
    return kept


def _raw_by_city(city_slugs, cinemas, movies, showtimes, is_classic, today):
    """Toutes les paires enchaînables par ville, sans sélection ni tri final."""
    wanted = set(city_slugs)
    by_city_day = defaultdict(lambda: defaultdict(list))
    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    today_iso = today.isoformat()
    for s in showtimes:
        cinema = cinemas[s["cinema"]]
        # Sans coordonnées, impossible de juger si deux salles sont voisines.
        if cinema["city_slug"] not in wanted or not cinema.get("lat"):
            continue
        if today_iso <= s["start"][:10] <= horizon:
            by_city_day[cinema["city_slug"]][s["start"][:10]].append(s)

    raw = {}
    for slug, days in by_city_day.items():
        ideas = []
        for shows in days.values():
            ideas.extend(_pairs_for_day(shows, cinemas, movies, is_classic))
        if ideas:
            raw[slug] = ideas
    return raw


def build_ideas(city_slugs, cinemas: dict, movies: dict, showtimes: list,
                is_classic, today: date, limit: int = IDEAS_PER_CITY,
                cult_limit: int = 6) -> tuple[dict, list]:
    """Renvoie (idées par ville, sélection nationale de marathons cultes).

    - `{slug de ville: [idées]}` : les meilleures idées de chaque ville.
    - `[idées cultes]` : les meilleurs marathons de DEUX classiques bien notés,
      toutes villes confondues (avec un champ `city` pour l'afficher). C'est la
      section mise en avant pour les amateurs de films cultes.

    `is_classic` est passé par build_site.py pour garder une seule définition
    de « reprise » dans le projet.
    """
    raw = _raw_by_city(city_slugs, cinemas, movies, showtimes, is_classic, today)

    by_city = {slug: sel for slug, ideas in raw.items()
               if (sel := _select(ideas, limit))}

    # Sélection culte nationale : toutes les paires de deux classiques bien
    # notées, la mieux notée d'abord, sans répéter une même paire de films.
    cults = []
    for slug, ideas in raw.items():
        for idea in ideas:
            if idea["is_cult"]:
                cults.append({**idea, "city": slug})
    cults.sort(key=lambda x: (-x["rating"], x["distance_km"], x["day"]))
    top_cults, seen = [], set()
    for idea in cults:
        pair = frozenset((idea["first"]["movie"], idea["second"]["movie"]))
        if pair in seen:
            continue
        seen.add(pair)
        top_cults.append(idea)
        if len(top_cults) == cult_limit:
            break
    return by_city, top_cults
