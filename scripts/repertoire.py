"""Détection du répertoire : reprises, cycles, séances uniques, salles de patrimoine.

C'est le moteur éditorial de Séancéo depuis son repositionnement : le site ne
met plus en avant les sorties récentes mais les films anciens qui REPASSENT en
salle (versions restaurées, rétrospectives, ciné-clubs).

Trois notions, mesurées sur les données réelles :

- **Reprise** : film sorti avant `REPERTOIRE_BEFORE`. Seuil volontairement
  généreux — à 20 ans d'âge, seules 84 villes sur 257 étaient couvertes ;
  avant 2020, on en couvre 154, soit 60 % du pays.
- **Séance unique** : le film ne passe QU'UNE fois en France sur la fenêtre.
  C'est le cas de 6 films sur 10 — le répertoire est un agenda d'événements,
  pas un catalogue qu'on consulte à loisir. D'où la mise en avant.
- **Cycle** : au moins `CYCLE_MIN_FILMS` films d'un même réalisateur dans une
  même salle. C'est l'unité que le public reconnaît (« rétrospective Tati »).

Aucune dépendance externe (stdlib uniquement).
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

REPERTOIRE_BEFORE = 2020   # « sorti avant 2020 » = reprise
HORIZON_DAYS = 7
CYCLE_MIN_FILMS = 2        # en dessous, ce n'est pas un cycle mais une coïncidence
VENUE_MIN_SHOWS = 8        # sous ce volume, un pourcentage n'a pas de sens

# Crédits génériques : pas un vrai réalisateur, donc pas un cycle.
_PLACEHOLDER = {"collectif", "divers", ""}


def is_repertoire(movie: dict) -> bool:
    """Vrai si le film est une reprise. Sans année TMDB, on s'abstient :
    mieux vaut rater une reprise que d'annoncer une sortie récente comme un
    classique."""
    year = movie.get("year")
    return bool(year) and year < REPERTOIRE_BEFORE


def window(showtimes: list, today: date, days: int = HORIZON_DAYS) -> list:
    """Séances comprises entre aujourd'hui et l'horizon (bornes incluses)."""
    horizon = (today + timedelta(days=days)).isoformat()
    return [s for s in showtimes if today.isoformat() <= s["start"][:10] <= horizon]


def repertoire_shows(showtimes: list, movies: dict) -> list:
    return [s for s in showtimes if is_repertoire(movies[s["movie"]])]


def unique_screenings(rep_shows: list, movies: dict, limit: int = 12) -> list:
    """Séances de films qui ne passent qu'une fois en France, les MIEUX NOTÉES
    sur Letterboxd d'abord, puis remises dans l'ordre chronologique pour
    l'affichage en agenda."""
    par_film = Counter(s["movie"] for s in rep_shows)
    seules = [s for s in rep_shows if par_film[s["movie"]] == 1]
    notees = sorted((s for s in seules if movies[s["movie"]].get("lb_rating")),
                    key=lambda s: -movies[s["movie"]]["lb_rating"])[:limit]
    notees.sort(key=lambda s: s["start"])
    return notees


def count_unique(rep_shows: list) -> int:
    """Nombre de films à séance unique (l'argument chiffré de l'accueil)."""
    par_film = Counter(s["movie"] for s in rep_shows)
    return sum(1 for n in par_film.values() if n == 1)


def _director_key(movie: dict, fold) -> str:
    d = fold(movie.get("director") or "")
    return "" if d in _PLACEHOLDER else d


def cycles(rep_shows: list, movies: dict, cinemas: dict, fold,
           limit: int = 6) -> list:
    """Rétrospectives en cours, agrégées au niveau national.

    Un cycle est repéré SALLE PAR SALLE (≥ CYCLE_MIN_FILMS films d'un même
    réalisateur dans la même salle), puis les salles qui programment le même
    réalisateur sont regroupées : la rétrospective Tati tourne dans une dizaine
    de villes, c'est une opération nationale, pas dix coïncidences.

    `fold` est la normalisation de texte de sources.py (accents, casse) —
    passée en paramètre pour ne pas dupliquer la règle.
    """
    par_salle = defaultdict(set)
    for s in rep_shows:
        d = _director_key(movies[s["movie"]], fold)
        if d:
            par_salle[(s["cinema"], d)].add(s["movie"])

    par_real = defaultdict(lambda: {"films": set(), "cinemas": set()})
    for (cid, d), films in par_salle.items():
        if len(films) >= CYCLE_MIN_FILMS:
            par_real[d]["films"] |= films
            par_real[d]["cinemas"].add(cid)

    out = []
    for d, info in par_real.items():
        shows = [s for s in rep_shows if s["movie"] in info["films"]
                 and s["cinema"] in info["cinemas"]]
        villes = sorted({cinemas[c]["city"] for c in info["cinemas"]})
        # Nom affiché : on reprend la graphie d'origine plutôt que la version
        # normalisée (« jacques tati » → « Jacques Tati »).
        graphie = next((movies[k]["director"] for k in info["films"]
                        if movies[k].get("director")), d.title())
        out.append({
            "director": graphie,
            "key": d,
            "movies": sorted(info["films"],
                             key=lambda k: -(movies[k].get("lb_rating") or 0)),
            "cinemas": sorted(info["cinemas"], key=lambda c: cinemas[c]["name"]),
            "cities": villes,
            "n_shows": len(shows),
        })
    out.sort(key=lambda c: (-len(c["movies"]), -c["n_shows"]))
    return out[:limit]


def heritage_venues(all_shows: list, rep_shows: list, cinemas: dict,
                    limit: int = 20) -> list:
    """Salles de patrimoine : celles dont la programmation fait la plus grande
    place au répertoire. Le classement est une PART, pas un volume — sinon les
    multiplexes écraseraient les salles qui ne font que ça."""
    total = Counter(s["cinema"] for s in all_shows)
    vieux = Counter(s["cinema"] for s in rep_shows)
    out = []
    for cid, n in vieux.items():
        if total[cid] >= VENUE_MIN_SHOWS:
            out.append({"cinema": cid, "n_rep": n, "n_total": total[cid],
                        "share": round(100 * n / total[cid])})
    out.sort(key=lambda v: (-v["share"], -v["n_rep"], cinemas[v["cinema"]]["name"]))
    return out[:limit]


def city_stats(rep_shows: list, cinemas: dict) -> dict:
    """{slug de ville: {films, seances}} — sert au classement des villes et au
    repli « aucune reprise ici » des pages ville."""
    films = defaultdict(set)
    seances = Counter()
    for s in rep_shows:
        slug = cinemas[s["cinema"]]["city_slug"]
        films[slug].add(s["movie"])
        seances[slug] += 1
    return {slug: {"films": len(f), "seances": seances[slug]}
            for slug, f in films.items()}
