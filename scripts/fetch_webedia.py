"""Connecteur Webedia (phase 2 — chaînes) pour Séancéo.

Générique pour toute chaîne sur la plateforme Webedia « boxofficeapi » (Gatsby) :
CGR, Grand Écran… (voir SITES). Sélection via --chain. Produit des séances au
MÊME schéma que fetch_data.py (indés). Les données de chaque chaîne vont dans
`data/<chain>_*.json`.

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
from html import unescape
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, movie_key, booking_url

# Chaînes sur la plateforme Webedia « boxofficeapi » (Gatsby). Toutes exposent
# la même API ; seuls le domaine et le chemin des pages cinéma diffèrent.
SITES = {
    "cgr": {
        "name": "CGR", "base": "https://www.cgrcinemas.fr",
        "theater_re": r"https://www\.cgrcinemas\.fr(/theaters/([a-z0-9]{4,6})-[a-z0-9-]+/)",
    },
    "grandecran": {
        "name": "Grand Écran", "base": "https://www.grandecran.fr",
        "theater_re": r"https://www\.grandecran\.fr(/nos-cinemas/([a-z0-9]{4,6})-[a-z0-9-]+/)",
    },
}
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 0.2

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


def webedia_booking(seance: dict) -> str:
    """Lien de réservation d'une séance Webedia, ou "".

    L'API propose DEUX fournisseurs par séance : « default », qui pointe le
    domaine d'achat de la chaîne (achat.cgrcinemas.fr), et « relay », un
    redirecteur tiers (relay.mvtx.us). On prend systématiquement `default` :
    envoyer nos visiteurs à travers un traceur intermédiaire n'apporte rien
    et les expose inutilement. Sans `default`, on préfère ne pas lier."""
    for entree in (seance.get("data") or {}).get("ticketing") or []:
        if entree.get("provider") != "default":
            continue
        for url in entree.get("urls") or []:
            valide = booking_url(url)
            if valide:
                return valide
    return ""


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
            # unescape : le JSON-LD embarqué dans le HTML contient des entités
            # (« Villenave-d&apos;Ornon ») qui saliraient noms ET slugs.
            return {
                "name": unescape(d.get("name", "")).strip(),
                "address": unescape(addr.get("streetAddress", "")).strip(),
                "postcode": str(addr.get("postalCode", "")).zfill(5),
                "city": unescape(addr.get("addressLocality", "")).strip(),
                "lat": geo.get("latitude"),
                "lon": geo.get("longitude"),
            }
    return None


def fetch_movies(api: str, ids: set[str]) -> dict[str, dict]:
    """Fiches films par lots (titre, réalisateur, durée, genre, affiche)."""
    catalog = {}
    ids = list(ids)
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        q = "&".join(f"ids={mid}" for mid in chunk)
        data = get(f"{api}/movies?basic=false&castingLimit=3&{q}")
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
    ap.add_argument("--chain", choices=SITES, default="cgr", help="chaîne Webedia")
    ap.add_argument("--theaters", type=int, default=0, help="nb de cinémas (0 = tous)")
    ap.add_argument("--days", type=int, default=7, help="fenêtre de jours")
    args = ap.parse_args()
    cfg = SITES[args.chain]
    site, chain_name = cfg["base"], cfg["name"]
    api = f"{site}/api/gatsby-source-boxofficeapi"

    today = date.today()
    frm = f"{today.isoformat()}T03:00:00"
    to = f"{(today + timedelta(days=args.days)).isoformat()}T03:00:00"

    print(f"Liste des cinémas {chain_name} (sitemap)…")
    sitemap = get(f"{site}/sitemap-0.xml", as_json=False) or ""
    # Code cinéma → URL exacte de sa page, telle qu'au sitemap
    theater_urls: dict[str, str] = {}
    for m in re.finditer(cfg["theater_re"], sitemap, re.I):
        theater_urls[m.group(2).upper()] = m.group(0)  # URL complète
    all_codes = list(theater_urls)
    if args.theaters:
        all_codes = all_codes[:args.theaters]
    print(f"  {len(all_codes)} cinémas {chain_name} (fenêtre {args.days} j)")

    cinemas: dict[str, dict] = {}
    showtimes: list[dict] = []
    movie_ids: set[str] = set()
    raw_shows: list[tuple] = []  # (cid, movieId, startsAt, tags, booking)

    for i, code in enumerate(all_codes, 1):
        info = theater_info(theater_urls[code])
        if not info or not info["name"]:
            continue
        cid = f"{args.chain}-{code.lower()}"
        cinemas[cid] = {
            "id": cid, "name": info["name"], "address": info["address"],
            "postcode": info["postcode"], "city": info["city"],
            "city_slug": slugify(info["city"]), "lat": info["lat"], "lon": info["lon"],
            "chain": chain_name,
        }
        # Le code cinéma se lit en minuscules dans l'URL de la page
        # (« /theaters/w8010-… ») mais l'API l'exige en MAJUSCULES : en
        # minuscules elle répond HTTP 500 avec un corps « null », sans le
        # moindre message. C'est ce qui a cassé la collecte silencieusement.
        api_code = code.upper()
        params = urllib.parse.urlencode({
            "from": frm, "to": to, "includeAllMovies": "true",
            # JSON compact (sans espaces) : l'API renvoie 500 sinon
            "theaters": json.dumps({"id": api_code, "timeZone": "Europe/Paris"},
                                   separators=(",", ":")),
        })
        sched = get(f"{api}/schedule?{params}") or {}
        by_movie = (sched.get(api_code) or {}).get("schedule", {})
        n = 0
        for mid, by_date in by_movie.items():
            movie_ids.add(str(mid))
            for slots in by_date.values():
                for s in slots:
                    raw_shows.append((cid, str(mid), s["startsAt"],
                                      s.get("tags", []), webedia_booking(s)))
                    n += 1
        print(f"  [{i}/{len(all_codes)}] {info['name']} : {n} séances")

    print(f"Fiches films ({len(movie_ids)})…")
    catalog = fetch_movies(api, movie_ids)

    movies: dict[str, dict] = {}
    for cid, mid, starts, tags, booking in raw_shows:
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
            "id": f"{args.chain}-{mid}-{cid}-{starts}", "movie": mkey, "cinema": cid,
            "start": starts, "end": "", "version": cgr_version(tags), "auditorium": "",
            "booking": booking,
        })
    showtimes.sort(key=lambda s: s["start"])

    if not cinemas:
        print(f"Aucune donnée {chain_name} récupérée (API bloquée ?) — snapshot conservé.")
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
    for kind, payload in {
        "cinemas": cinemas, "movies": movies, "showtimes": showtimes, "cities": cities,
    }.items():
        (DATA_DIR / f"{args.chain}_{kind}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nBilan {chain_name} : {len(cinemas)} cinémas, {len(movies)} films, "
          f"{len(showtimes)} séances, {len(cities)} villes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
