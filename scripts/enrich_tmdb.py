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

DEUXIÈME PASSE, ANGLAISE. Le site est bilingue : chaque fiche trouvée reçoit
aussi son titre, son synopsis, ses genres et son pays en anglais (`title_en`,
`overview_en`, `genres_en`, `country_en`). Ces champs ne sont écrits QUE s'ils
diffèrent du français — un film anglophone a le même titre dans les deux
langues, le stocker deux fois gonflerait le cache pour rien. Le drapeau `en`
marque une fiche déjà passée en anglais, pour que la passe reste incrémentale
même quand elle n'a rien eu à écrire.

Usage :  TMDB_API_KEY=xxxx python scripts/enrich_tmdb.py [--limit N] [--refresh]
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
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

# TMDB est une base communautaire : certaines fiches ont un titre fr erroné
# (constaté : id 81 « Nausicaä » affiché « Le Vaisseau fantôme »). On corrige
# ici, par id TMDB — à retirer quand la fiche est réparée côté TMDB.
TITLE_OVERRIDES = {
    81: "Nausicaä de la vallée du vent",
}


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


def _name_tokens(name: str) -> list[str]:
    """Nom de personne → jetons ascii minuscules (« Rossellini Roberto » → [rossellini, roberto])."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z]+", s) if len(t) > 1]


def _same_person(a: str, b: str) -> bool:
    """Vrai si deux noms désignent plausiblement la même personne.

    Insensible aux accents, à l'ordre prénom/nom et aux petites variantes
    d'orthographe (« Nicholas Roeg » ≈ « Nicolas Roeg ») : chaque jeton du nom
    le plus court doit trouver un jeton très proche dans l'autre nom.
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(
        any(difflib.SequenceMatcher(None, s, l).ratio() >= 0.8 for l in long_)
        for s in short
    )


def _director_ok(movie_id: int, src_director: str) -> bool:
    """Vérifie que le réalisateur TMDB du film correspond à celui de la source."""
    credits = get(f"movie/{movie_id}/credits") or {}
    tmdb_dirs = [p.get("name", "") for p in credits.get("crew", [])
                 if p.get("job") == "Director"]
    src_dirs = [d for d in (s.strip() for s in src_director.split(",")) if d]
    return any(_same_person(sd, td) for sd in src_dirs for td in tmdb_dirs)


# ISO 3166-1 -> nom FR, pour les principaux pays de cinéma. Les autres pays
# retombent sur le nom TMDB (anglais), rare et corrigeable au coup par coup.
# TMDB ne localise pas `production_countries`, d'où cette table.
COUNTRY_FR = {
    "US": "États-Unis", "FR": "France", "GB": "Royaume-Uni", "IT": "Italie",
    "DE": "Allemagne", "JP": "Japon", "KR": "Corée du Sud", "ES": "Espagne",
    "SE": "Suède", "DK": "Danemark", "RU": "Russie", "SU": "URSS", "CN": "Chine",
    "HK": "Hong Kong", "TW": "Taïwan", "IN": "Inde", "CA": "Canada",
    "BE": "Belgique", "NL": "Pays-Bas", "CH": "Suisse", "AT": "Autriche",
    "PL": "Pologne", "CZ": "Tchéquie", "HU": "Hongrie", "PT": "Portugal",
    "GR": "Grèce", "IR": "Iran", "BR": "Brésil", "AR": "Argentine",
    "MX": "Mexique", "AU": "Australie", "NO": "Norvège", "FI": "Finlande",
    "IE": "Irlande", "TR": "Turquie",
}


def _country_fr(det: dict) -> str:
    """Pays d'origine (1er pays de production) en français, pour le filtre pays.
    TMDB rend les noms en anglais : on mappe l'ISO, avec repli sur le nom brut."""
    pcs = det.get("production_countries") or []
    if not pcs:
        return ""
    iso = pcs[0].get("iso_3166_1") or ""
    return COUNTRY_FR.get(iso) or pcs[0].get("name") or ""


def enrich_one(title: str, director: str = "") -> dict:
    """Cherche un film sur TMDB et renvoie ses données propres, ou {found: False}.

    La recherche TMDB trie par popularité, pas par exactitude : « Ten » de
    Kiarostami ressortait « 10 bonnes raisons de te larguer ». Quand la source
    fournit un réalisateur, on ne retient donc un candidat que si son
    réalisateur TMDB concorde ; sans candidat validé, mieux vaut ne rien
    enrichir que d'afficher les données d'un autre film.
    """
    data = get("search/movie", query=title, language="fr-FR", include_adult="false")
    results = (data or {}).get("results") or []
    if not results:
        return {"found": False}
    if director:
        m = next((c for c in results[:5] if _director_ok(c["id"], director)), None)
        if m is None:
            return {"found": False}
    else:
        m = results[0]  # pas de réalisateur source : on garde le plus populaire
    det = get(f"movie/{m['id']}", language="fr-FR") or {}
    return {
        "found": True,
        "tmdb_id": m["id"],
        "title": TITLE_OVERRIDES.get(m["id"]) or (m.get("title") or title).strip(),
        "rating": round(m["vote_average"], 1) if m.get("vote_average") else None,
        "votes": m.get("vote_count") or 0,  # sert à filtrer les notes non fiables
        "poster": IMG + m["poster_path"] if m.get("poster_path") else "",
        "overview": (det.get("overview") or m.get("overview") or "").strip(),
        "runtime": det.get("runtime") or None,
        "genres": ", ".join(g["name"] for g in (det.get("genres") or [])[:2]),
        "country": _country_fr(det),
        "year": (m.get("release_date") or "")[:4],
    }


def enrich_english(entry: dict) -> None:
    """Complète une fiche du cache avec sa version anglaise, SUR PLACE.

    Une seule requête par film : on repart de l'identifiant TMDB déjà validé
    par la passe française (réalisateur vérifié), donc pas de nouvelle
    recherche — et surtout aucun risque de tomber sur un autre film.

    Les champs identiques au français ne sont pas écrits : « Blue Velvet » se
    dit « Blue Velvet », et `localize_movies()` (i18n.py) retombe de toute
    façon sur le français quand le champ anglais manque. Le drapeau `en` note
    que la passe a bien eu lieu, y compris quand elle n'a rien écrit.
    """
    entry["en"] = 1
    det = get(f"movie/{entry['tmdb_id']}", language="en-US")
    if not det:
        # Réseau en vrac : on retire le drapeau pour retenter au prochain run
        # plutôt que de figer une fiche sans anglais.
        del entry["en"]
        return
    titre = (det.get("title") or "").strip()
    if titre and titre != entry.get("title"):
        entry["title_en"] = titre
    resume = (det.get("overview") or "").strip()
    if resume and resume != entry.get("overview"):
        entry["overview_en"] = resume
    genres = ", ".join(g["name"] for g in (det.get("genres") or [])[:2])
    if genres and genres != entry.get("genres"):
        entry["genres_en"] = genres
    # TMDB rend `production_countries` en anglais quelle que soit la langue
    # demandée : c'est exactement ce qu'il nous faut ici, sans table de
    # correspondance (COUNTRY_FR fait le chemin inverse pour le français).
    pcs = det.get("production_countries") or []
    pays = (pcs[0].get("name") or "").strip() if pcs else ""
    if pays and pays != entry.get("country"):
        entry["country_en"] = pays
    # AFFICHE localisée. TMDB en stocke une par langue quand le distributeur en
    # a fourni une : le visiteur anglophone doit voir « The Handmaiden » sur la
    # jaquette, pas « Mademoiselle ». Sans version anglaise, TMDB renvoie
    # l'affiche par défaut et la comparaison ci-dessous l'écarte d'elle-même.
    aff = det.get("poster_path")
    if aff:
        url = IMG + aff
        if url != entry.get("poster"):
            entry["poster_en"] = url


def load_all_movies() -> dict[str, tuple[str, str]]:
    """Union des films de toutes les sources : {clé film → (titre, réalisateur)}."""
    films: dict[str, tuple[str, str]] = {}
    for path in DATA_DIR.glob("*movies.json"):
        try:
            movies = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for key, m in movies.items():
            films.setdefault(key, (m.get("title", ""), m.get("director") or ""))
    return films


def main() -> int:
    if not KEY:
        print("ERREUR : variable TMDB_API_KEY absente. "
              "Lancer :  TMDB_API_KEY=xxxx python scripts/enrich_tmdb.py")
        return 1

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="n films max (test)")
    ap.add_argument("--refresh", action="store_true", help="réinterroger même si en cache")
    ap.add_argument("--refresh-en", action="store_true",
                    help="refaire la seule passe anglaise (garde la passe française)")
    args = ap.parse_args()

    cache = {}
    if CACHE.exists() and not args.refresh:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    films = load_all_movies()
    todo = [(k, t, d) for k, (t, d) in films.items()
            if t and (args.refresh or k not in cache)]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(films)} films au total, {len(todo)} à enrichir "
          f"({len(cache)} déjà en cache)…")

    for i, (key, title, director) in enumerate(todo, 1):
        cache[key] = enrich_one(title, director)
        if i % 50 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}]")

    # Passe anglaise : uniquement les fiches trouvées (une fiche sans
    # correspondance n'a pas d'identifiant à interroger) et pas encore passées.
    # `--refresh-en` lève le drapeau `en` pour tout refaire sans toucher à la
    # passe française, bien plus coûteuse (deux requêtes par film + credits).
    if args.refresh_en:
        for v in cache.values():
            v.pop("en", None)
    todo_en = [v for v in cache.values()
               if v.get("found") and v.get("tmdb_id") and not v.get("en")]
    if args.limit:
        todo_en = todo_en[:args.limit]
    if todo_en:
        print(f"\nVersion anglaise : {len(todo_en)} fiches à compléter…")
        for i, entry in enumerate(todo_en, 1):
            enrich_english(entry)
            if i % 50 == 0 or i == len(todo_en):
                print(f"  [{i}/{len(todo_en)}]")

    DATA_DIR.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    found = sum(1 for v in cache.values() if v.get("found"))
    n_en = sum(1 for v in cache.values() if v.get("en"))
    n_titre_en = sum(1 for v in cache.values() if v.get("title_en"))
    print(f"\nCache TMDB : {len(cache)} films ({found} trouvés, "
          f"{len(cache) - found} sans correspondance).")
    print(f"Anglais : {n_en} fiches complétées, dont {n_titre_en} avec un titre "
          f"anglais distinct du titre français.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
