"""Notes Letterboxd des films (pour le classement des Classiques).

Letterboxd n'a pas d'API publique, mais son catalogue est construit sur TMDB :
`letterboxd.com/tmdb/<id>` redirige vers la fiche du film, laquelle embarque sa
note moyenne en JSON-LD (aggregateRating). Comme notre cache TMDB fournit l'id,
le matching est exact — aucun risque de confondre deux films homonymes.

Zone grise assumée (pas d'API officielle ouverte) : collecte LOCALE, polie
(1 s entre requêtes), snapshot `data/letterboxd.json` versionné — le CI ne
scrape jamais Letterboxd. Rafraîchir de loin en loin : les notes bougent peu.

Usage :  python scripts/fetch_letterboxd.py [--limit N] [--refresh]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "letterboxd.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 1.0  # scraping poli : jamais plus d'une page par seconde

# Le JSON-LD de Letterboxd est enveloppé de commentaires /* <![CDATA[ */ … /* ]]> */
_LDJSON = re.compile(
    r'<script type="application/ld\+json">\s*(?:/\*.*?\*/)?\s*(\{.*?\})\s*(?:/\*.*?\*/)?\s*</script>',
    re.S)


def get(url: str) -> tuple[str | None, str | None]:
    """Renvoie (html, url_finale_après_redirection) ou (None, None)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", "replace"), r.geturl()
    except (urllib.error.URLError, TimeoutError) as e:
        code = getattr(e, "code", None)
        if code != 404:  # 404 = film absent de Letterboxd, cas normal et silencieux
            print(f"    ! {url}: {e}")
        return None, None
    finally:
        time.sleep(DELAY)


def fetch_one(tmdb_id: int) -> dict:
    html, final_url = get(f"https://letterboxd.com/tmdb/{tmdb_id}/")
    if not html:
        return {"found": False}
    m = _LDJSON.search(html)
    if not m:
        return {"found": False}
    try:
        d = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"found": False}
    ar = d.get("aggregateRating") or {}
    if not ar.get("ratingValue"):
        return {"found": False}  # fiche présente mais pas encore de note moyenne
    return {
        "found": True,
        "rating": round(float(ar["ratingValue"]), 2),  # sur 5
        "votes": int(ar.get("ratingCount") or 0),
        "url": final_url or "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="n films max (test)")
    ap.add_argument("--refresh", action="store_true", help="réinterroger même si en cache")
    args = ap.parse_args()

    tmdb = json.loads((DATA / "tmdb.json").read_text(encoding="utf-8"))
    cache = {}
    if CACHE.exists() and not args.refresh:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    todo = [(k, v["tmdb_id"]) for k, v in tmdb.items()
            if v.get("found") and (args.refresh or k not in cache)]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} films à interroger sur Letterboxd "
          f"({len(cache)} déjà en cache)…", flush=True)

    for i, (key, tmdb_id) in enumerate(todo, 1):
        cache[key] = fetch_one(tmdb_id)
        if i % 25 == 0 or i == len(todo):
            # Sauvegarde incrémentale : une interruption ne perd pas la collecte
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            print(f"  [{i}/{len(todo)}]", flush=True)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    found = sum(1 for v in cache.values() if v.get("found"))
    print(f"\nCache Letterboxd : {len(cache)} films, {found} avec note.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
