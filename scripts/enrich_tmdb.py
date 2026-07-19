"""Enrichissement des fiches films via l'API TMDB (The Movie Database).

Les sources de séances renvoient des titres sales (CAPITALES sans accents),
des durées farfelues et pas de note. TMDB fournit des titres propres, la vraie
durée, une note, une affiche HD et un synopsis. Ce script construit un CACHE
`data/tmdb.json` (clé film → données TMDB) que sources.py applique à la fusion.

⚠ SÉCURITÉ : la clé API TMDB se lit dans la variable d'environnement
TMDB_API_KEY — elle n'est JAMAIS écrite dans le code ni dans le cache. Le cache
ne contient que des données publiques de films, il peut donc être versionné.

Le cache est incrémental : on ne réinterroge TMDB que pour les films absents du
cache. Rafraîchir en local :  TMDB_API_KEY=... python scripts/enrich_tmdb.py

Usage :  TMDB_API_KEY=xxxx python scripts/enrich_tmdb.py [--limit N] [--refresh]
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA_DIR / "tmdb.json"
KEY = os.environ.get("TMDB_API_KEY", "").strip()
DELAY = 0.06  # TMDB tolère un fort débit ; on reste poli


def get(path: str, **params):
    params["api_key"] = KEY
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"    ! {path}: {e}")
        return None
    finally:
        time.sleep(DELAY)


def enrich_one(title: str) -> dict:
    """Cherche un film sur TMDB et renvoie ses données propres, ou {found: False}."""
    data = get("search/movie", query=title, language="fr-FR", include_adult="false")
    results = (data or {}).get("results") or []
    if not results:
        return {"found": False}
    m = results[0]  # TMDB trie par pertinence/popularité
    det = get(f"movie/{m['id']}", language="fr-FR") or {}
    return {
        "found": True,
        "tmdb_id": m["id"],
        "title": (m.get("title") or title).strip(),
        "rating": round(m["vote_average"], 1) if m.get("vote_average") else None,
        "votes": m.get("vote_count") or 0,  # sert à filtrer les notes non fiables
        "poster": IMG + m["poster_path"] if m.get("poster_path") else "",
        "overview": (det.get("overview") or m.get("overview") or "").strip(),
        "runtime": det.get("runtime") or None,
        "genres": ", ".join(g["name"] for g in (det.get("genres") or [])[:2]),
        "year": (m.get("release_date") or "")[:4],
    }


def load_all_movies() -> dict[str, str]:
    """Union des films de toutes les sources : {clé film → titre à chercher}."""
    titles: dict[str, str] = {}
    for path in DATA_DIR.glob("*movies.json"):
        try:
            movies = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for key, m in movies.items():
            titles.setdefault(key, m.get("title", ""))
    return titles


def main() -> int:
    if not KEY:
        print("ERREUR : variable TMDB_API_KEY absente. "
              "Lancer :  TMDB_API_KEY=xxxx python scripts/enrich_tmdb.py")
        return 1

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="n films max (test)")
    ap.add_argument("--refresh", action="store_true", help="réinterroger même si en cache")
    args = ap.parse_args()

    cache = {}
    if CACHE.exists() and not args.refresh:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    titles = load_all_movies()
    todo = [(k, t) for k, t in titles.items() if t and (args.refresh or k not in cache)]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(titles)} films au total, {len(todo)} à enrichir "
          f"({len(cache)} déjà en cache)…")

    for i, (key, title) in enumerate(todo, 1):
        cache[key] = enrich_one(title)
        if i % 50 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}]")

    DATA_DIR.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    found = sum(1 for v in cache.values() if v.get("found"))
    print(f"\nCache TMDB : {len(cache)} films ({found} trouvés, "
          f"{len(cache) - found} sans correspondance).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
