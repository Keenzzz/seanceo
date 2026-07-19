"""Fusion des sources de données Ciné Indés.

Combine les séances open data des indés (data/cinemas.json…) et celles des
chaînes (data/pathe_*.json, optionnelles) en un jeu unifié consommé par
build_site.py. La fusion est tolérante : si une source chaîne est absente,
seuls les indés sont utilisés — le site se construit quand même.

Règle de fusion des films : deux sources décrivent souvent le MÊME film sous la
même clé (titre+réalisateur normalisés). On garde alors une seule fiche, en
préférant le titre le plus propre (les indés renvoient souvent des CAPITALES
sans accents) et en complétant chaque champ vide par l'autre source.
"""

import json
from collections import defaultdict
from pathlib import Path

# Quatre fichiers par source, dans l'ordre cinemas/movies/showtimes/cities.
KINDS = ("cinemas", "movies", "showtimes", "cities")
INDE = tuple(f"{k}.json" for k in KINDS)
# Chaînes (phase 2) : snapshots optionnels versionnés, collectés en local.
# Ajouter un préfixe ici suffit à intégrer une nouvelle chaîne à la fusion.
CHAIN_PREFIXES = ("pathe", "cgr", "ugc", "grandecran", "megarama", "mk2", "kinepolis", "cineville")


def _load(data_dir: Path, name: str):
    path = data_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _title_richness(t: str) -> int:
    """Score de « propreté » d'un titre. Les indés arrivent souvent capitalisés
    et dépouillés de leurs accents/apostrophes (« L Odyssee ») ; Pathé fournit
    la graphie soignée (« L'Odyssée »). Apostrophes et accents trahissent la
    bonne version, les CAPITALES la mauvaise."""
    score = 0
    if any(c in t for c in "'’"):
        score += 2
    if any(ord(c) > 127 for c in t):  # lettres accentuées
        score += 2
    if t != t.upper():                # pas entièrement en capitales
        score += 1
    return score


def _cleaner_title(a: str, b: str) -> str:
    """Entre deux graphies du même film, garde la plus riche (à égalité, `a`)."""
    return b if _title_richness(b) > _title_richness(a) else a


def _merge_movies(base: dict, extra: dict) -> None:
    for key, m in extra.items():
        if key not in base:
            base[key] = dict(m)
            continue
        ex = base[key]
        ex["title"] = _cleaner_title(ex["title"], m["title"])
        # Complète chaque champ vide par la valeur de l'autre source
        for field in ("director", "cast", "genre", "country",
                      "duration_min", "poster", "trailer", "storyline"):
            if not ex.get(field) and m.get(field):
                ex[field] = m[field]


def _merge_cities(base: dict, extra: dict) -> None:
    for slug, c in extra.items():
        if slug not in base:
            base[slug] = {**c, "cinemas": list(c["cinemas"])}
            continue
        dst = base[slug]
        # Une ville peut avoir des indés ET des cinémas de chaîne
        dst["cinemas"] = list(dict.fromkeys(dst["cinemas"] + c["cinemas"]))
        dst["showtime_count"] += c["showtime_count"]


def _apply_tmdb(movies: dict, tmdb: dict) -> None:
    """Applique le cache TMDB : titres propres, note, affiche HD, durée, synopsis.
    Chaque film reçoit un champ `rating` (None si non trouvé) et un champ `year`
    (année de sortie, None si inconnue) — `year` sert à repérer les reprises de
    classiques (rétrospectives)."""
    for key, m in movies.items():
        t = tmdb.get(key)
        # Note affichée seulement si assez de votes (une note sur 1-2 votes = 10/10
        # trompeur). Seuil 30 votes pour une moyenne crédible.
        reliable = t and t.get("found") and (t.get("votes") or 0) >= 30
        m["rating"] = t.get("rating") if reliable else None
        year = (t or {}).get("year") or ""
        m["year"] = int(year) if str(year).isdigit() else None
        if not t or not t.get("found"):
            continue
        if t.get("title"):
            m["title"] = t["title"]
        if t.get("poster"):
            m["poster"] = t["poster"]
        if t.get("runtime"):
            m["duration_min"] = t["runtime"]
        if t.get("overview"):
            m["storyline"] = t["overview"]
        if t.get("genres"):
            m["genre"] = t["genres"]


def load_merged(data_dir: Path) -> tuple[dict, dict, list, dict]:
    """Renvoie (cinemas, movies, showtimes, cities) fusionnés et prêts à bâtir."""
    ci, mo, sh, ct = (_load(data_dir, n) for n in INDE)
    if ci is None:
        raise FileNotFoundError(
            "Sources indés absentes : lance d'abord `python scripts/fetch_data.py`")
    cinemas, movies, showtimes, cities = ci, mo, sh, dict(ct)

    merged_any = False
    for prefix in CHAIN_PREFIXES:
        c_ci, c_mo, c_sh, c_ct = (_load(data_dir, f"{prefix}_{k}.json") for k in KINDS)
        if not c_ci:  # snapshot de cette chaîne absent → on saute
            continue
        cinemas.update(c_ci)             # ids disjoints (préfixés par chaîne)
        _merge_movies(movies, c_mo or {})
        showtimes.extend(c_sh or [])
        _merge_cities(cities, c_ct or {})
        merged_any = True
    if merged_any:
        showtimes.sort(key=lambda s: s["start"])

    # Enrichissement TMDB (cache local optionnel : titres propres, notes, affiches)
    tmdb = _load(data_dir, "tmdb.json")
    _apply_tmdb(movies, tmdb or {})

    # Recalcule le tri des villes par volume de séances (l'ordre a changé)
    cities = dict(sorted(cities.items(), key=lambda kv: -kv[1]["showtime_count"]))
    return cinemas, movies, showtimes, cities


def cinema_kind(cinema: dict) -> str:
    """Libellé de nature : « cinéma indépendant » ou « cinéma Pathé »."""
    chain = cinema.get("chain")
    return f"cinéma {chain}" if chain else "cinéma indépendant"
