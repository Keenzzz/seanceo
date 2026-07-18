"""Pipeline de données Ciné Indés.

Interroge l'API open data du SCARE (programmation des cinémas indépendants,
Licence Ouverte 2.0), nettoie les données et produit 4 fichiers JSON dans
`data/` : cinemas, films, séances à venir, et index des villes.

Usage :  python scripts/fetch_data.py
Aucune dépendance externe (stdlib uniquement).
"""

import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

API_BASE = "https://datacinesindes.fr/data-fair/api/v1/datasets/programmation-cinemas/lines"
PAGE_SIZE = 10_000
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Champs qu'on demande à l'API (évite de télécharger _rand, _score, etc.)
FIELDS = [
    "showid", "showstart", "showend", "auditoriumnumber",
    "cineid", "cinenom", "cineadresse", "cinecp", "cineville",
    "_coords.lat", "_coords.lon",
    "filmid", "filmtitle", "filmdirector", "filmcast", "filmgenre",
    "filmcountry", "filmduration", "filmversion", "filmposter",
    "filmtrailer", "filmstoryline",
]


def fetch_all_showtimes(since: date) -> list[dict]:
    """Récupère toutes les séances à partir de `since`, en suivant la
    pagination par curseur de l'API data-fair (champ `next`)."""
    params = {
        "size": PAGE_SIZE,
        "select": ",".join(FIELDS),
        # Syntaxe de filtre data-fair : intervalle sur la date de séance
        "qs": f"showstart:[{since.isoformat()} TO *]",
    }
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    rows: list[dict] = []
    while url:
        with urllib.request.urlopen(url, timeout=60) as resp:
            page = json.load(resp)
        rows.extend(page["results"])
        # `next` n'est présent que s'il reste des pages
        url = page.get("next") if page["results"] else None
    return rows


# --- Nettoyage du texte ---------------------------------------------------

_MOJIBAKE_HINT = re.compile(r"Ã[\x80-\xBF‰€šœžŸ¡©ª«¨®°²³´µ¸¹º»¼½¾]|â€|Å“|Ã ")


def fix_mojibake(text: str) -> str:
    """Répare le texte doublement encodé renvoyé par certaines caisses
    (UTF-8 relu comme cp1252 : « Ã©tÃ© » au lieu de « été »).

    On ne tente la réparation que si le texte présente les symptômes, et on
    la garde seulement si elle réussit sans perte."""
    if not text or not _MOJIBAKE_HINT.search(text):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired


def clean(value) -> str:
    """Normalise une valeur de l'API : None / "null" -> chaîne vide."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "null":
        return ""
    return fix_mojibake(text)


_ARRONDISSEMENT = re.compile(r"\s+\d+(er|e|ème|eme)\s+arrondissement$", re.IGNORECASE)


def normalize_city(raw: str) -> str:
    """« Marseille 1er arrondissement » -> « Marseille », espaces propres."""
    city = _ARRONDISSEMENT.sub("", clean(raw))
    city = re.sub(r"\s+", " ", city).strip()
    # Harmonise « La-Roche-Sur-Yon » vs « La Roche-sur-Yon » : on garde la
    # graphie telle quelle mais on génère un slug commun pour le regroupement.
    return city


def slugify(text: str) -> str:
    """« Saint-Étienne » -> « saint-etienne » (pour les URLs et les clés)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower())
    return text.strip("-")


# Les caisses utilisent deux nomenclatures pour la langue de la séance ;
# on les ramène aux libellés usuels du public français.
VERSION_MAP = {
    "VF": "VF",
    "VERSION_LOCAL": "VF",
    "VO": "VO",
    "VERSION_ORIGINAL": "VO",
    "VERSION_ORIGINAL_LOCAL": "VOST",
    "VERSION_MUET": "Muet",
}


def movie_key(title: str, director: str) -> str:
    """Clé de déduplication d'un film.

    `filmid` n'est PAS global : chaque logiciel de caisse a sa propre
    numérotation, donc deux cinémas donnent des ids différents au même film.
    On dédoublonne par (titre, réalisateur) normalisés."""
    return f"{slugify(title)}|{slugify(director)}"


# --- Construction des sorties --------------------------------------------

def build(rows: list[dict], today: date) -> dict[str, object]:
    cinemas: dict[str, dict] = {}
    movies: dict[str, dict] = {}
    showtimes: list[dict] = []
    skipped = 0

    for row in rows:
        title = clean(row.get("filmtitle"))
        start = clean(row.get("showstart"))
        cine_id = str(row.get("cineid") or "")
        if not (title and start and cine_id):
            skipped += 1
            continue

        city = normalize_city(row.get("cineville"))
        cinema = cinemas.setdefault(cine_id, {
            "id": cine_id,
            "name": clean(row.get("cinenom")),
            "address": clean(row.get("cineadresse")),
            "postcode": clean(row.get("cinecp")).zfill(5),
            "city": city,
            "city_slug": slugify(city),
            "lat": row.get("_coords.lat"),
            "lon": row.get("_coords.lon"),
        })

        mkey = movie_key(title, clean(row.get("filmdirector")))
        movie = movies.setdefault(mkey, {
            "key": mkey,
            "title": title.title() if title.isupper() else title,
            "director": clean(row.get("filmdirector")),
            "cast": clean(row.get("filmcast")),
            "genre": clean(row.get("filmgenre")),
            "country": clean(row.get("filmcountry")),
            "duration_min": round(row["filmduration"] / 60) if row.get("filmduration") else None,
            "poster": clean(row.get("filmposter")),
            "trailer": clean(row.get("filmtrailer")),
            "storyline": clean(row.get("filmstoryline")),
        })
        # Complète la fiche si un autre cinéma a des infos plus riches
        for field in ("poster", "trailer", "storyline", "genre", "cast"):
            if not movie[field]:
                movie[field] = clean(row.get(f"film{field if field != 'storyline' else 'storyline'}"))

        showtimes.append({
            "id": clean(row.get("showid")),
            "movie": mkey,
            "cinema": cine_id,
            "start": start,
            "end": clean(row.get("showend")),
            "version": VERSION_MAP.get(clean(row.get("filmversion")), ""),
            "auditorium": clean(row.get("auditoriumnumber")),
        })

    showtimes.sort(key=lambda s: s["start"])

    # Index des villes : cinémas et volume de séances par ville
    cities: dict[str, dict] = {}
    shows_by_cinema = defaultdict(int)
    for s in showtimes:
        shows_by_cinema[s["cinema"]] += 1
    for cinema in cinemas.values():
        c = cities.setdefault(cinema["city_slug"], {
            "slug": cinema["city_slug"],
            "name": cinema["city"],
            "cinemas": [],
            "showtime_count": 0,
        })
        c["cinemas"].append(cinema["id"])
        c["showtime_count"] += shows_by_cinema[cinema["id"]]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "since": today.isoformat(),
        "skipped_rows": skipped,
        "cinemas": cinemas,
        "movies": movies,
        "showtimes": showtimes,
        "cities": dict(sorted(cities.items(), key=lambda kv: -kv[1]["showtime_count"])),
    }


def main() -> int:
    today = date.today()
    print(f"Récupération des séances depuis le {today.isoformat()}…")
    rows = fetch_all_showtimes(today)
    print(f"  {len(rows)} lignes reçues de l'API")

    result = build(rows, today)
    DATA_DIR.mkdir(exist_ok=True)
    meta = {k: result[k] for k in ("generated_at", "since", "skipped_rows")}
    outputs = {
        "cinemas.json": result["cinemas"],
        "movies.json": result["movies"],
        "showtimes.json": result["showtimes"],
        "cities.json": result["cities"],
        "meta.json": meta,
    }
    for name, payload in outputs.items():
        path = DATA_DIR / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"  écrit {path.name}")

    print(
        f"\nBilan : {len(result['cinemas'])} cinémas, {len(result['movies'])} films, "
        f"{len(result['showtimes'])} séances à venir, {len(result['cities'])} villes "
        f"({meta['skipped_rows']} lignes ignorées)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
