"""Connecteur CGR (phase 2 — chaînes) pour Séancéo.

Interroge l'API interne du site cgrcinemas.fr (plateforme Webedia « boxofficeapi »,
Gatsby) et produit des séances au MÊME schéma que fetch_data.py (indés).

Pipeline (3 sources) :
  1. sitemap-0.xml → pages `/theaters/<code>-<slug>/` (liste des 73 cinémas CGR)
  2. page cinéma → JSON-LD MovieTheater (nom, adresse, GPS)
  3. /api/gatsby-source-boxofficeapi/schedule → horaires par cinéma (7 jours)
     /api/gatsby-source-boxofficeapi/movies  → fiches films (titre, durée, affiche)

Comme Pathé : API privée susceptible de changer, IP datacenter probablement
bloquée (→ collecte locale, snapshot versionné). Poli, tolérant aux erreurs.

Usage :  python scripts/fetch_cgr.py [--theaters N] [--days N]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, movie_key

SITE = "https://www.cgrcinemas.fr"
API = f"{SITE}/api/gatsby-source-boxofficeapi"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 0.2

_THEATER_URL = re.compile(r"/theaters/([pbw][0-9]{4})-[a-z0-9-]+/", re.I)
_LDJSON = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)


def get(url: str, as_json: bool = True):
    """GET tolérant : renvoie None en cas d'échec (ne lève pas)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if as_json else raw
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"    ! échec {url[:70]} : {e}")
        return None
    finally:
        time.sleep(DELAY)


def cgr_version(tags: list[str]) -> str:
    """Tags Webedia (« Localization.Language.French/Original ») → VF/VO/VOST."""
    joined = " ".join(tags or [])
    if "Original" in joined:
        return "VOST" if "Subtitl" in joined else "VO"
    return "VF"


def theater_info(url: str) -> dict | None:
    """Extrait le JSON-LD MovieTheater d'une page cinéma (nom, adresse, GPS)."""
    html = get(url, as_json=False)
    if not html:
        return None
    for block in _LDJSON.findall(html):
        try:
            d = json.loads(block)
        except json.JSONDecodeError:
            continue
        if d.get("@type") == "MovieTheater":
            addr = d.get("address") or {}
            geo = d.get("geo") or {}
            return {
                "name": d.get("name", "").strip(),
                "address": addr.get("streetAddress", "").strip(),
                "postcode": str(addr.get("postalCode", "")).zfill(5),
                "city": addr.get("addressLocality", "").strip(),
                "lat": geo.get("latitude"),
                "lon": geo.get("longitude"),
            }
    return None


def fetch_movies(ids: set[str]) -> dict[str, dict]:
    """Fiches films par lots (titre, réalisateur, durée, genre, affiche)."""
    catalog = {}
    ids = list(ids)
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        q = "&".join(f"ids={mid}" for mid in chunk)
        data = get(f"{API}/movies?basic=false&castingLimit=3&{q}")
        for m in (data or []):
            images = m.get("images") or []
            poster = images[0]["url"] if images and isinstance(images[0], dict) else ""
            direction = m.get("direction") or []
            genres = m.get("genres") or ""
            catalog[str(m["id"])] = {
                "title": (m.get("title") or "").strip(),
                "director": direction[0] if direction else "",
                "genre": genres.split(",")[0].strip() if genres else "",
                "duration_min": round(m["runtime"] / 60) if m.get("runtime") else None,
                "poster": poster,
            }
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theaters", type=int, default=0, help="nb de cinémas (0 = tous)")
    ap.add_argument("--days", type=int, default=7, help="fenêtre de jours")
    args = ap.parse_args()

    today = date.today()
    frm = f"{today.isoformat()}T03:00:00"
    to = f"{(today + timedelta(days=args.days)).isoformat()}T03:00:00"

    print("Liste des cinémas CGR (sitemap)…")
    sitemap = get(f"{SITE}/sitemap-0.xml", as_json=False) or ""
    # Code (P0867) → URL exacte de la page cinéma, tels qu'ils apparaissent au sitemap
    theater_urls: dict[str, str] = {}
    for m in re.finditer(r"(https://www\.cgrcinemas\.fr/theaters/([pbw][0-9]{4})-[a-z0-9-]+/)",
                         sitemap, re.I):
        theater_urls[m.group(2).upper()] = m.group(1)
    all_codes = list(theater_urls)
    if args.theaters:
        all_codes = all_codes[:args.theaters]
    print(f"  {len(all_codes)} cinémas CGR (fenêtre {args.days} j)")

    cinemas: dict[str, dict] = {}
    showtimes: list[dict] = []
    movie_ids: set[str] = set()
    raw_shows: list[tuple] = []  # (code, movieId, startsAt, tags)

    for i, code in enumerate(all_codes, 1):
        info = theater_info(theater_urls[code])
        if not info or not info["name"]:
            continue
        cid = f"cgr-{code.lower()}"
        cinemas[cid] = {
            "id": cid, "name": info["name"], "address": info["address"],
            "postcode": info["postcode"], "city": info["city"],
            "city_slug": slugify(info["city"]), "lat": info["lat"], "lon": info["lon"],
            "chain": "CGR",
        }
        params = urllib.parse.urlencode({
            "from": frm, "to": to, "includeAllMovies": "true",
            # JSON compact (sans espaces) : l'API renvoie 500 sinon
            "theaters": json.dumps({"id": code, "timeZone": "Europe/Paris"},
                                   separators=(",", ":")),
        })
        sched = get(f"{API}/schedule?{params}") or {}
        by_movie = (sched.get(code) or {}).get("schedule", {})
        n = 0
        for mid, by_date in by_movie.items():
            movie_ids.add(str(mid))
            for slots in by_date.values():
                for s in slots:
                    raw_shows.append((cid, str(mid), s["startsAt"], s.get("tags", [])))
                    n += 1
        print(f"  [{i}/{len(all_codes)}] {info['name']} : {n} séances")

    print(f"Fiches films ({len(movie_ids)})…")
    catalog = fetch_movies(movie_ids)

    movies: dict[str, dict] = {}
    for cid, mid, starts, tags in raw_shows:
        film = catalog.get(mid)
        if not film or not film["title"]:
            continue
        mkey = movie_key(film["title"], film["director"])
        movies.setdefault(mkey, {
            "key": mkey, "title": film["title"], "director": film["director"],
            "cast": "", "genre": film["genre"], "country": "",
            "duration_min": film["duration_min"], "poster": film["poster"],
            "trailer": "", "storyline": "",
        })
        showtimes.append({
            "id": f"cgr-{mid}-{cid}-{starts}", "movie": mkey, "cinema": cid,
            "start": starts, "end": "", "version": cgr_version(tags), "auditorium": "",
        })
    showtimes.sort(key=lambda s: s["start"])

    if not cinemas:
        print("Aucune donnée CGR récupérée (API bloquée ?) — snapshot conservé.")
        return 0

    shows_by_cinema = defaultdict(int)
    for s in showtimes:
        shows_by_cinema[s["cinema"]] += 1
    cities: dict[str, dict] = {}
    for c in cinemas.values():
        city = cities.setdefault(c["city_slug"], {
            "slug": c["city_slug"], "name": c["city"], "cinemas": [], "showtime_count": 0})
        city["cinemas"].append(c["id"])
        city["showtime_count"] += shows_by_cinema[c["id"]]

    DATA_DIR.mkdir(exist_ok=True)
    for name, payload in {
        "cgr_cinemas.json": cinemas, "cgr_movies.json": movies,
        "cgr_showtimes.json": showtimes, "cgr_cities.json": cities,
    }.items():
        (DATA_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nBilan CGR : {len(cinemas)} cinémas, {len(movies)} films, "
          f"{len(showtimes)} séances, {len(cities)} villes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
