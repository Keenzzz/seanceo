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
import re
import unicodedata
from collections import Counter, defaultdict
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


# « Part. 2 » et « Partie 2 » désignent la même découpe d'un film en parties
_TOKEN_CANON = {"part": "partie", "vol": "volume"}
# Crédits génériques des programmes de courts-métrages : pas un vrai
# réalisateur, donc pas un critère de séparation (une source crédite
# « Collectif », l'autre liste les réalisateurs des courts — même programme).
_PLACEHOLDER_DIRECTORS = {"collectif", "divers"}

# Mentions creuses rencontrées dans le champ `cast` : elles occupent la place
# d'une vraie distribution sans rien apprendre, on les retire. Clés déjà
# repliées par _fold_person() (donc en minuscules et à mots TRIÉS).
_PLACEHOLDER_PEOPLE = {
    "acteurs inconnus", "acteur inconnu", "distribution inconnue",
    "inconnu", "inconnue", "inconnus", "inconnues", "collectif", "divers",
}


def _fold_title(t: str) -> str:
    """« LE BON, LA BRUTE ET LE TRUAND » et « Le Bon, la Brute et le Truand »
    doivent tomber sur la même empreinte : minuscules, sans accents ni
    ponctuation, espaces normalisés. La ponctuation (dont l'apostrophe
    typographique « ’ ») devient une espace — la supprimer collerait les mots
    (« J’écris » → « jecris » ≠ « j ecris »)."""
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    words = "".join(c if c.isalnum() else " " for c in t.lower()).split()
    return " ".join(_TOKEN_CANON.get(w, w) for w in words)


def _fold_person(name: str) -> str:
    """Empreinte d'un nom de PERSONNE : casse, accents, ponctuation **et ordre
    des mots** neutralisés. « TATI Jacques » et « Jacques Tati » tombent sur la
    même clé. On trie les mots — contrairement à `_fold_title()`, où l'ordre
    porte du sens (« Les Dents de la mer » n'est pas « La mer des dents »)."""
    return " ".join(sorted(_fold_title(name).split()))


def _capitalize(word: str) -> str:
    """Met une capitale à chaque suite de lettres : « JEAN-JACQUES » →
    « Jean-Jacques », « B.POJAR » → « B.Pojar »."""
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), word)


def _is_shouty(token: str) -> bool:
    """Mot entièrement en capitales (au moins deux lettres, pour ne pas
    confondre avec une initiale comme « A. »)."""
    return sum(c.isalpha() for c in token) >= 2 and token.isupper()


def _tidy_person(name: str) -> str:
    """Remet un nom dans la graphie d'usage.

    Trois motifs observés dans les données, traités séparément :

    - « ANNAUD Jean-Jacques » → « Jean-Jacques Annaud ». Patronyme en capitales
      EN TÊTE : on rétablit la casse et on réordonne. Exigé net (capitales au
      début, plus aucune ensuite), sinon on ne touche à rien.
    - « Daniel ROHER » → « Daniel Roher ». Patronyme en capitales À LA FIN :
      l'ordre est déjà le bon, on ne fait que la casse.
    - « ERIC ROHMER » → « Eric Rohmer ». Tout en capitales : impossible de
      deviner lequel est le patronyme, on se contente de la casse.

    Les listes de réalisateurs (programmes de courts-métrages) sont séparées
    par des virgules et traitées nom par nom.
    """
    name = (name or "").strip()
    if "," in name:
        parts = [_tidy_person(p) for p in name.split(",")]
        return ", ".join(p for p in parts if p)
    tokens = name.split()
    if not tokens:
        return name
    if all(_is_shouty(t) for t in tokens):
        return " ".join(_capitalize(t) for t in tokens)

    head = []
    for t in tokens:
        if not _is_shouty(t):
            break
        head.append(t)
    tail = tokens[len(head):]
    if head and not any(_is_shouty(t) for t in tail):
        return " ".join(tail + [" ".join(_capitalize(t) for t in head)])

    # Capitales en fin de nom : même traitement, sans réordonner.
    queue = []
    for t in reversed(tokens):
        if not _is_shouty(t):
            break
        queue.append(t)
    if queue and len(queue) < len(tokens):
        garde = tokens[:len(tokens) - len(queue)]
        return " ".join(garde + [_capitalize(t) for t in reversed(queue)])
    return name


def _name_score(name: str, frequency: int) -> tuple:
    """Départage plusieurs graphies d'un même nom. Dans l'ordre : le moins de
    mots hurlés, puis la présence d'accents (« Almodóvar » bat « Almodovar »),
    puis la graphie la plus répandue dans les données, puis l'ordre
    alphabétique pour que le build soit reproductible."""
    shouty = sum(1 for t in name.split() if _is_shouty(t))
    accents = any(ord(c) > 127 for c in name)
    return (-shouty, accents, frequency, name)


def _elire(variantes: dict) -> dict[str, str]:
    """Pour chaque clé de repli, élit la graphie de référence.
    On juge la graphie APRÈS remise en forme : « ANNAUD Jean-Jacques »
    concourt sous « Jean-Jacques Annaud »."""
    registre = {}
    for cle, compte in variantes.items():
        propositions = Counter()
        for graphie, n in compte.items():
            propositions[_tidy_person(graphie)] += n
        registre[cle] = max(propositions,
                            key=lambda g: _name_score(g, propositions[g]))
    return registre


def _people_registry(movies: dict) -> tuple[dict, dict]:
    """Deux registres, volontairement distincts — ne pas les fusionner.

    - `entiers` : indexé sur la CHAÎNE ENTIÈRE du champ `director`. C'est le
      comportement historique et il faut le préserver : `_fold_person()` trie
      les mots, donc « Stanton, McKenna » et « McKenna, Stanton » tombent sur
      la même clé et reçoivent la même graphie. Découper sur les virgules
      perdrait cette unification et recouperait les cycles de rétrospective.
    - `unitaires` : indexé nom par nom, pour le casting. Alimenté AUSSI par les
      noms de réalisateurs : une même personne réalise et joue (« Jacques
      Tati »), les deux côtés doivent s'écrire pareil.
    """
    entiers, unitaires = defaultdict(Counter), defaultdict(Counter)

    def recense_noms(champ: str) -> None:
        for nom in (champ or "").split(","):
            nom = nom.strip()
            if nom:
                unitaires[_fold_person(nom)][nom] += 1

    for m in movies.values():
        d = (m.get("director") or "").strip()
        if d:
            entiers[_fold_person(d)][d] += 1
        recense_noms(d)
        recense_noms(m.get("cast"))

    return _elire(entiers), _elire(unitaires)


def _canonical_people(movies: dict) -> tuple[int, int]:
    """Uniformise les noms de personnes (réalisateurs et casting) entre sources.

    Les caisses des indés, Pathé, CGR et UGC n'écrivent pas les noms de la même
    façon : « David Lynch » ici, « LYNCH David » là. Sans cette passe, le
    moteur de rétrospectives (repertoire.py) voit DEUX réalisateurs et coupe le
    cycle en deux — Tati perdait « Mon oncle », Lynch perdait « Eraserhead ».

    Le casting suit la même règle, nom par nom. L'enjeu y est cosmétique (pas
    de cycle à couper) mais réel : « Marina FOIS » et « Marina Foïs » sur deux
    fiches voisines font négligé. Les mentions creuses (« acteurs inconnus »)
    sont retirées plutôt qu'affichées.

    Renvoie (fiches réalisateur corrigées, fiches casting corrigées).
    """
    entiers, unitaires = _people_registry(movies)

    reals = castings = 0
    for m in movies.values():
        d = (m.get("director") or "").strip()
        if d:
            retenu = entiers[_fold_person(d)]
            if retenu != m["director"]:
                m["director"] = retenu
                reals += 1

        brut = (m.get("cast") or "").strip()
        if not brut:
            continue
        noms = []
        for nom in brut.split(","):
            nom = nom.strip()
            if not nom or _fold_person(nom) in _PLACEHOLDER_PEOPLE:
                continue
            retenu = unitaires[_fold_person(nom)]
            if retenu not in noms:  # une source liste parfois deux fois le même
                noms.append(retenu)
        propre = ", ".join(noms)
        if propre != m["cast"]:
            m["cast"] = propre
            castings += 1
    return reals, castings


def _dedup_movies(movies: dict, showtimes: list, tmdb: dict) -> None:
    """Fusionne les fiches qui décrivent le même film sous deux clés différentes.

    La clé (titre, réalisateur) laisse passer des doublons : une caisse écrit
    « LA BATAILLE - PARTIE 2 » sans réalisateur, une autre « La Bataille
    Partie 2 » avec — deux clés, deux cartes à l'écran pour le même film.
    Règle : même titre normalisé + réalisateurs compatibles (un nom en commun
    à l'orthographe près, ou l'un des deux absent) = même film. Deux films
    homonymes de réalisateurs DIFFÉRENTS restent séparés. Les séances sont
    rattachées à la fiche survivante (connue de TMDB de préférence)."""
    alias: dict[str, str] = {}

    def score(k: str):
        t = tmdb.get(k) or {}
        return (1 if t.get("found") else 0,
                1 if movies[k].get("director") else 0,
                _title_richness(movies[k]["title"]))

    def absorb(keep: str, k: str) -> None:
        base, extra = movies[keep], movies[k]
        base["title"] = _cleaner_title(base["title"], extra["title"])
        for field in ("director", "cast", "genre", "country",
                      "duration_min", "poster", "trailer", "storyline"):
            if not base.get(field) and extra.get(field):
                base[field] = extra[field]
        alias[k] = keep
        del movies[k]

    def dir_tokens(key: str) -> set:
        toks = set(_fold_title(movies[key].get("director") or "").split())
        # « Collectif » / « Divers » = pas d'information, comme un champ vide
        return set() if toks <= _PLACEHOLDER_DIRECTORS else toks

    # --- Passe 1 : même titre normalisé, réalisateurs compatibles ---
    groups = defaultdict(list)
    for key, m in movies.items():
        folded = _fold_title(m["title"])
        if folded:
            groups[folded].append(key)
    for keys in groups.values():
        if len(keys) < 2:
            continue
        clusters: list[dict] = []
        for key in keys:
            toks = dir_tokens(key)
            for cl in clusters:
                if not toks or not cl["toks"] or toks & cl["toks"]:
                    cl["keys"].append(key)
                    cl["toks"] |= toks
                    break
            else:
                clusters.append({"keys": [key], "toks": toks})
        for cl in clusters:
            keep = max(cl["keys"], key=score)
            for k in cl["keys"]:
                if k != keep:
                    absorb(keep, k)

    # --- Passe 2, par réalisateur : titre billeté avec et sans son numéro
    # de partie (« La Bataille de Gaulle : J'écris ton nom » vs « … Partie 2 :
    # J'écris ton nom »). Fusion si le surplus de tokens n'est que
    # « partie »/« volume »/« chapitre » + chiffres, ET si le titre court a
    # au moins 4 tokens (un vrai sous-titre) — jamais « Avatar » avec
    # « Avatar 2 ». ---
    # Tokens tolérés en surplus : la numérotation de partie, les chiffres, et
    # les mots-outils français (« Le Bon, la Brute, le Cinglé » vs « … et le
    # Cinglé » : même réalisateur, même film, un « et » d'écart).
    part_extra = {"partie", "volume", "chapitre",
                  "et", "and", "de", "du", "des", "le", "la", "les", "l", "d", "un", "une"}
    by_dir = defaultdict(list)
    for key, m in movies.items():
        d = _fold_title(m.get("director") or "")
        if d and d not in _PLACEHOLDER_DIRECTORS:
            by_dir[d].append(key)
    for keys in by_dir.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: len(_fold_title(movies[k]["title"]).split()))
        for i, short in enumerate(keys):
            for longk in keys[i + 1:]:
                if short not in movies or longk not in movies:
                    continue
                a = set(_fold_title(movies[short]["title"]).split())
                b = set(_fold_title(movies[longk]["title"]).split())
                if (len(a) >= 4 and a < b
                        and all(t in part_extra or t.isdigit() for t in b - a)):
                    keep, drop = max(short, longk, key=score), None
                    drop = longk if keep == short else short
                    absorb(keep, drop)

    # --- Passe 3 : même identifiant TMDB = littéralement le même film. ---
    # C'est le signal le plus sûr des trois, et il rattrape ce que le titre ne
    # peut pas voir : une caisse écrit « Les Vacances de Mr Hulot », une autre
    # « … de monsieur Hulot ». Les deux titres ne se replient PAS pareil, donc
    # la passe 1 les laisse passer ; c'est ensuite _apply_tmdb() qui leur donne
    # le même titre propre, et le doublon n'apparaissait qu'à l'écran.
    # On ne fait confiance qu'aux fiches validées par réalisateur (`found`) :
    # une recherche TMDB non validée peut pointer le mauvais film, et fusionner
    # sur cette base collerait deux œuvres différentes.
    by_tmdb = defaultdict(list)
    for key in movies:
        t = tmdb.get(key) or {}
        if t.get("found") and t.get("tmdb_id"):
            by_tmdb[t["tmdb_id"]].append(key)
    for keys in by_tmdb.values():
        if len(keys) < 2:
            continue
        keep = max(keys, key=score)
        for k in keys:
            if k != keep:
                absorb(keep, k)

    if alias:
        def resolve(k: str) -> str:
            # La passe 2 peut absorber un survivant de la passe 1 : suivre
            # la chaîne d'alias jusqu'à la fiche réellement conservée.
            while k in alias:
                k = alias[k]
            return k
        for s in showtimes:
            s["movie"] = resolve(s["movie"])
        # Deux fiches doublonnées listaient parfois la même séance : purge
        seen = set()
        unique = []
        for s in showtimes:
            sig = (s["cinema"], s["movie"], s["start"], s.get("version"))
            if sig not in seen:
                seen.add(sig)
                unique.append(s)
        showtimes[:] = unique


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


def _apply_letterboxd(movies: dict, lb: dict) -> None:
    """Applique le cache Letterboxd : note moyenne /5 de la communauté.
    Champ `lb_rating` (None si absent ou trop peu de votes pour être fiable)."""
    for key, m in movies.items():
        e = lb.get(key)
        ok = e and e.get("found") and (e.get("votes") or 0) >= 50
        m["lb_rating"] = e.get("rating") if ok else None


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

    tmdb = _load(data_dir, "tmdb.json") or {}
    # Uniformise les noms de réalisateurs AVANT le dédoublonnage et les cycles :
    # « TATI Jacques » et « Jacques Tati » doivent être le même homme partout.
    _canonical_people(movies)
    # Rattrape les doublons que la clé (titre, réalisateur) laisse passer
    _dedup_movies(movies, showtimes, tmdb)
    # Enrichissement TMDB (cache local optionnel : titres propres, notes, affiches)
    _apply_tmdb(movies, tmdb)
    # Notes Letterboxd (cache local optionnel : classement des Classiques)
    _apply_letterboxd(movies, _load(data_dir, "letterboxd.json") or {})

    # Recalcule le tri des villes par volume de séances (l'ordre a changé)
    cities = dict(sorted(cities.items(), key=lambda kv: -kv[1]["showtime_count"]))
    return cinemas, movies, showtimes, cities


def cinema_kind(cinema: dict) -> str:
    """Libellé de nature : « cinéma indépendant » ou « cinéma Pathé »."""
    chain = cinema.get("chain")
    return f"cinéma {chain}" if chain else "cinéma indépendant"
