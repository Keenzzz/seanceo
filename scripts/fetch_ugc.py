"""Connecteur UGC (phase 2 — chaînes) pour Séancéo.

Le site web ugc.fr fait de la détection de bot (les requêtes non-navigateur
reçoivent une page vidée de séances). MAIS l'API mobile `backend.ugc.fr` — celle
de l'app UGC Direct — est propre, en JSON, et non protégée. On l'utilise donc.

Endpoints (découverts via /v2/api-docs, la spec OpenAPI exposée) :
  /api/cinemas                                → 48 cinémas (code numérique, GPS)
  /api/cinemas/{codeComplexe}/showings/days   → dates disponibles
  /api/cinemas/{codeComplexe}/showings/{date} → films + séances du jour
    ⚠ {codeComplexe} est l'id NUMÉRIQUE (champ code_complexe), pas le code texte.

Usage :  python scripts/fetch_ugc.py [--cinemas N] [--days N]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import slugify, movie_key, booking_url

# Billetterie UGC : l'API donne `urlReservation` en chemin RELATIF, tronqué
# juste après « ?id= » — l'identifiant de séance est à concaténer. Vérifié :
# https://www.ugc.fr/reservationSeances.html?id=<seance_id> répond 200 et
# affiche bien la séance demandée.
UGC_SITE = "https://www.ugc.fr/"

API = "https://backend.ugc.fr/api"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DELAY = 0.2

VERSION_MAP = {"VF": "VF", "VOSTF": "VOST", "VOST": "VOST", "VO": "VO", "VFSTF": "VF"}
_DUREE = re.compile(r"(\d+)h(\d+)")


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"    ! échec {url[:70]} : {e}")
        return None
    finally:
        time.sleep(DELAY)


def parse_duree(s: str) -> int | None:
    """« 2h52 » → 172 minutes."""
    m = _DUREE.search(s or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def ugc_booking(seance: dict) -> str:
    """Lien de réservation d'une séance UGC, ou "" si elle n'est pas réservable.
    On repart de `urlReservation` fourni par l'API plutôt que d'écrire le
    chemin en dur : si UGC déplace sa page de réservation, on suit."""
    rel = (seance.get("urlReservation") or "").lstrip("/")
    sid = seance.get("seance_id")
    if not rel or not sid or not seance.get("reservable"):
        return ""
    return booking_url(f"{UGC_SITE}{rel}{sid}")


def epoch_to_iso(ms: int, tz: str) -> str:
    """Epoch millisecondes + offset « +0200 » → heure locale « 2026-07-19T15:00:00 »."""
    off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5]))
    if tz.startswith("-"):
        off = -off
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) + off
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cinemas", type=int, default=0, help="nb de cinémas (0 = tous)")
    ap.add_argument("--days", type=int, default=7, help="fenêtre de jours")
    args = ap.parse_args()

    today = date.today()
    window = {(today + timedelta(days=i)).isoformat() for i in range(args.days)}

    print("Liste des cinémas UGC (API mobile)…")
    raw = get(f"{API}/cinemas") or []
    if args.cinemas:
        raw = raw[:args.cinemas]
    print(f"  {len(raw)} cinémas UGC (fenêtre {args.days} j)")

    cinemas: dict[str, dict] = {}
    movies: dict[str, dict] = {}
    showtimes: list[dict] = []

    for i, c in enumerate(raw, 1):
        complexe = c.get("code_complexe")
        if complexe is None:
            continue
        cid = f"ugc-{complexe}"
        cinemas[cid] = {
            "id": cid, "name": c.get("libelle", "").strip(),
            "address": c.get("adresse", "").strip(),
            "postcode": str(c.get("cp", "")).zfill(5),
            "city": (c.get("ville") or "").strip().title(),  # API en CAPITALES
            "city_slug": slugify(c.get("ville", "")),
            "lat": c.get("latitude"), "lon": c.get("longitude"), "chain": "UGC",
        }
        days = get(f"{API}/cinemas/{complexe}/showings/days") or []
        wanted = [d for d in days if d in window]
        n = 0
        for day in wanted:
            entries = get(f"{API}/cinemas/{complexe}/showings/{day}") or []
            for entry in entries:
                film = entry.get("film") or {}
                title = (film.get("titre") or "").strip()
                if not title:
                    continue
                director = (film.get("realisateur") or "").strip()
                mkey = movie_key(title, director)
                genre = film.get("genre") or ""
                movies.setdefault(mkey, {
                    "key": mkey, "title": title, "director": director,
                    "cast": (film.get("acteur") or "").strip(),
                    "genre": genre.split(",")[0].strip(), "country": "",
                    "duration_min": parse_duree(film.get("duree")),
                    "poster": film.get("image_affiche") or "",
                    "trailer": "", "storyline": (film.get("synopsis") or "").strip(),
                })
                for vt in entry.get("seancesAndVersionTypes") or []:
                    for s in vt.get("seances") or []:
                        if not s.get("date_heure"):
                            continue
                        start = epoch_to_iso(s["date_heure"], s.get("date_timezone", "+0200"))
                        showtimes.append({
                            "id": f"ugc-{s.get('seance_id')}", "movie": mkey, "cinema": cid,
                            "start": start, "end": "",
                            "version": VERSION_MAP.get(s.get("version", ""), s.get("version", "")),
                            "auditorium": (s.get("nom_salle") or "").replace("Salle ", ""),
                            "booking": ugc_booking(s),
                        })
                        n += 1
        print(f"  [{i}/{len(raw)}] {c.get('libelle')} : {n} séances")

    showtimes.sort(key=lambda s: s["start"])

    if not cinemas:
        print("Aucune donnée UGC récupérée (API bloquée ?) — snapshot conservé.")
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
        "ugc_cinemas.json": cinemas, "ugc_movies.json": movies,
        "ugc_showtimes.json": showtimes, "ugc_cities.json": cities,
    }.items():
        (DATA_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nBilan UGC : {len(cinemas)} cinémas, {len(movies)} films, "
          f"{len(showtimes)} séances, {len(cities)} villes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
