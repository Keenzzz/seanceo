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

# (fichier indés, fichier chaîne équivalent) — le second est optionnel
INDE = ("cinemas.json", "movies.json", "showtimes.json", "cities.json")
PATHE = ("pathe_cinemas.json", "pathe_movies.json", "pathe_showtimes.json", "pathe_cities.json")


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


def load_merged(data_dir: Path) -> tuple[dict, dict, list, dict]:
    """Renvoie (cinemas, movies, showtimes, cities) fusionnés et prêts à bâtir."""
    ci, mo, sh, ct = (_load(data_dir, n) for n in INDE)
    if ci is None:
        raise FileNotFoundError(
            "Sources indés absentes : lance d'abord `python scripts/fetch_data.py`")
    cinemas, movies, showtimes, cities = ci, mo, sh, dict(ct)

    p_ci, p_mo, p_sh, p_ct = (_load(data_dir, n) for n in PATHE)
    if p_ci:  # source chaîne présente → on fusionne
        cinemas.update(p_ci)              # ids disjoints (numériques vs "pathe-…")
        _merge_movies(movies, p_mo or {})
        showtimes.extend(p_sh or [])
        _merge_cities(cities, p_ct or {})
        showtimes.sort(key=lambda s: s["start"])

    # Recalcule le tri des villes par volume de séances (l'ordre a changé)
    cities = dict(sorted(cities.items(), key=lambda kv: -kv[1]["showtime_count"]))
    return cinemas, movies, showtimes, cities


def cinema_kind(cinema: dict) -> str:
    """Libellé de nature : « cinéma indépendant » ou « cinéma Pathé »."""
    chain = cinema.get("chain")
    return f"cinéma {chain}" if chain else "cinéma indépendant"
