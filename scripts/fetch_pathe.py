"""Connecteur Pathé (phase 2 — chaînes) pour Ciné Indés.

Interroge l'API interne du site pathe.fr et produit des séances au MÊME schéma
que fetch_data.py (indés), pour permettre une fusion ultérieure. Contrairement
à l'API open data du SCARE, il s'agit ici de l'API privée qui alimente le site
public de Pathé : pas de licence explicite, structure susceptible de changer
sans préavis — d'où ce connecteur isolé, poli (délai entre appels) et tolérant
aux erreurs.

L'API fonctionne en 3 niveaux :
  1. /api/shows                              catalogue global des films
  2. /api/cinemas                            liste des cinémas Pathé
  3. /api/cinema/{slug}/shows                quels films / quels jours par cinéma
  4. /api/show/{slug}/showtimes/{cine}/{jj}  horaires précis (film × cinéma × jour)

Usage :  python scripts/fetch_pathe.py [--cinemas N] [--days N]
Réglages par défaut volontairement modestes pour le test ; passer --cinemas 0
pour tout récupérer. Aucune dépendance externe (stdlib uniquement).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, movie_key, VERSION_MAP

API = "https://www.pathe.fr/api"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# Un User-Agent de navigateur réel : l'API refuse les clients sans UES crédible.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 0.25  # secondes entre deux appels — politesse / anti-blocage

# L'API Pathé nomme les versions en minuscules ; on réutilise le mapping indés
# pour les cas partagés et on complète les libellés propres à Pathé.
PATHE_VERSION = {"vf": "VF", "vost": "VOST", "vo": "VO", **VERSION_MAP}


def get(path: str) -> object | None:
    """GET JSON tolérant : renvoie None (au lieu de lever) en cas d'échec, pour
    qu'un cinéma ou une séance manquante n'interrompe pas toute la collecte."""
    req = urllib.request.Request(f"{API}/{path}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"    ! échec {path} : {e}")
        return None
    finally:
        time.sleep(DELAY)


def first(value) -> str:
    """directors/genres sont des listes côté Pathé ; on prend le 1er élément
    (les indés n'ont qu'un réalisateur / genre principal)."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def build_catalog() -> dict[str, dict]:
    """Catalogue global indexé par slug de film (titres/affiches propres)."""
    data = get("shows") or {}
    catalog = {}
    for m in data.get("shows", []):
        poster = m.get("posterPath") or {}
        catalog[m["slug"]] = {
            "title": m.get("title", "").strip(),
            "director": first(m.get("directors")),
            "genre": first(m.get("genres")),
            "duration_min": m.get("duration") or None,
            "poster": poster.get("lg") or poster.get("md") or "" if isinstance(poster, dict) else "",
        }
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cinemas", type=int, default=5,
                    help="nombre de cinémas à traiter (0 = tous)")
    ap.add_argument("--days", type=int, default=2,
                    help="fenêtre de jours à venir")
    args = ap.parse_args()

    today = date.today()
    horizon = {(today + timedelta(days=i)).isoformat() for i in range(args.days)}

    print("Catalogue des films Pathé…")
    catalog = build_catalog()
    print(f"  {len(catalog)} films au catalogue")

    print("Liste des cinémas Pathé…")
    all_cinemas = get("cinemas") or []
    all_cinemas = [c for c in all_cinemas if c.get("status")]
    if args.cinemas:
        all_cinemas = all_cinemas[:args.cinemas]
    print(f"  {len(all_cinemas)} cinémas à traiter (fenêtre {args.days} j)")

    cinemas: dict[str, dict] = {}
    movies: dict[str, dict] = {}
    showtimes: list[dict] = []
    calls = 0

    for i, c in enumerate(all_cinemas, 1):
        cslug = c["slug"]
        theater = (c.get("theaters") or [{}])[0]
        gps = theater.get("gpsPosition") or {}
        cid = f"pathe-{cslug}"
        cinemas[cid] = {
            "id": cid,
            "name": c.get("name", "").strip(),
            "address": theater.get("addressLine1", "").strip(),
            "postcode": str(theater.get("addressZip", "")).zfill(5),
            "city": theater.get("addressCity", "").strip(),
            "city_slug": slugify(theater.get("addressCity", "")),
            "lat": gps.get("x"),
            "lon": gps.get("y"),
            "chain": "Pathé",  # marqueur de source (les indés n'ont pas ce champ)
        }

        prog = get(f"cinema/{cslug}/shows") or {}
        print(f"  [{i}/{len(all_cinemas)}] {c.get('name')} : "
              f"{len(prog.get('shows', {}))} films")
        calls += 1

        for show_slug, info in prog.get("shows", {}).items():
            days = [d for d in info.get("days", {}) if d in horizon]
            if not days:
                continue
            film = catalog.get(show_slug)
            if not film or not film["title"]:
                continue
            mkey = movie_key(film["title"], film["director"])
            movies.setdefault(mkey, {
                "key": mkey, "title": film["title"], "director": film["director"],
                "cast": "", "genre": film["genre"], "country": "",
                "duration_min": film["duration_min"], "poster": film["poster"],
                "trailer": "", "storyline": "",
            })
            for day in days:
                slots = get(f"show/{show_slug}/showtimes/{cslug}/{day}") or []
                calls += 1
                for s in slots:
                    start = str(s.get("time", "")).replace(" ", "T")
                    if not start:
                        continue
                    showtimes.append({
                        "id": f"pathe-{show_slug}-{cslug}-{start}",
                        "movie": mkey,
                        "cinema": cid,
                        "start": start,
                        "end": str(s.get("endTime", "")).replace(" ", "T"),
                        "version": PATHE_VERSION.get(s.get("version", ""), ""),
                        "auditorium": str(s.get("auditoriumName", "")),
                    })

    # Garde-fou : si la collecte n'a rien ramené (typiquement l'API a renvoyé
    # 403 à l'IP d'un runner CI datacenter), NE PAS écraser la photo versionnée
    # des données. Le build réutilisera le dernier snapshot valide du repo.
    if not cinemas:
        print("Aucune donnée Pathé récupérée (API bloquée ?) — "
              "snapshot existant conservé, rien n'est réécrit.")
        return 0

    showtimes.sort(key=lambda s: s["start"])

    # Index des villes (même logique que fetch_data)
    shows_by_cinema = defaultdict(int)
    for s in showtimes:
        shows_by_cinema[s["cinema"]] += 1
    cities: dict[str, dict] = {}
    for cinema in cinemas.values():
        city = cities.setdefault(cinema["city_slug"], {
            "slug": cinema["city_slug"], "name": cinema["city"],
            "cinemas": [], "showtime_count": 0,
        })
        city["cinemas"].append(cinema["id"])
        city["showtime_count"] += shows_by_cinema[cinema["id"]]

    DATA_DIR.mkdir(exist_ok=True)
    for name, payload in {
        "pathe_cinemas.json": cinemas,
        "pathe_movies.json": movies,
        "pathe_showtimes.json": showtimes,
        "pathe_cities.json": cities,
    }.items():
        (DATA_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{calls} appels API. Bilan Pathé : {len(cinemas)} cinémas, "
          f"{len(movies)} films, {len(showtimes)} séances, {len(cities)} villes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
