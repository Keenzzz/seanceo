"""Cartes d'abonnement illimité (UGC Illimité, CinéPass Pathé) pour Séancéo.

Ce n'est PAS une source de séances : aucun film, aucun horaire. C'est un
**enrichissement de fiche cinéma** — « cette salle accepte telle carte » — d'où
son absence de `CHAIN_PREFIXES` (sources.py) et son format à part, un simple
dictionnaire `{cinema_id: {"ugc_illimite": bool, "cinepass": bool}}`.

Pourquoi un fichier par cinéma et pas une règle par enseigne : parce que
l'enseigne ne détermine PAS l'abonnement, dans les deux sens.
  - Des indépendants acceptent les cartes (19 chez UGC, ~14 chez Pathé) : c'est
    même tout l'intérêt de l'info, un visiteur ne peut pas la deviner.
  - Et l'inverse : 6 des 14 Grand Écran sont EXCLUS d'UGC Illimité alors que
    les 8 autres l'acceptent. Une table par chaîne se tromperait 6 fois.

Sources (deux requêtes HTTP, ~400 Ko, moins d'une seconde) :

  UGC — https://www.ugc.fr/cinemas-acceptant-ui.html
    Page HTML éditoriale, 144 salles avec adresse ET code postal. Contrairement
    aux pages de séances d'ugc.fr (vidées par la détection de bot, cf.
    fetch_ugc.py), celle-ci se sert entière même sans User-Agent de navigateur
    et depuis une IP datacenter — donc collectable en CI. robots.txt d'ugc.fr
    n'interdit que /dynamique/, /AjaxAction!, /js/objs.js et *?origin=* : cette
    URL est autorisée.

  Pathé — https://media.pathe.fr/files/conditions/Reseau%20CinePass-CineCartes.pdf
    PDF officiel (export Excel), 137 lignes. ATTENTION, PIÈGE : la même URL sur
    www.pathe.fr renvoie 403 depuis une IP datacenter (le blocage Pathé déjà
    connu du projet) ; le CDN Akamai `media.pathe.fr` sert le fichier IDENTIQUE
    octet pour octet et passe. Taper le CDN, jamais www.

Pas de CGR : l'offre n'existe pas. Vérifié sur cgrcinemas.fr — le « Club CGR »
est un programme de fidélité, « La Box CGR » un carnet de 5/10/15 places,
/le-pass/ et /pass-illimite/ renvoient 404. Ne pas re-chercher dans six mois.
Ne pas confondre non plus avec le « CinéPass » de grandecran.fr : homonyme
total, c'est une carte rechargeable sans rapport avec l'abonnement Pathé.

Usage :  python scripts/fetch_abonnements.py [--dry-run]
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from time import sleep

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UGC_URL = "https://www.ugc.fr/cinemas-acceptant-ui.html"
PATHE_PDF = ("https://media.pathe.fr/files/conditions/"
             "Reseau%20CinePass-CineCartes.pdf")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Garde-fous : en dessous, on refuse d'écrire. Une source qui change de forme
# doit casser bruyamment, jamais écraser abonnements.json par une liste vide.
# Même réflexe que le garde-fou best-effort de fetch_pathe.py.
MIN_UGC = 100      # 144 lignes le 2026-08-24
MIN_PATHE = 100    # 137 lignes le 2026-08-24

# Fichiers de données lus pour l'appariement (tous les cinémas connus du site).
SNAPSHOTS = [("cinemas.json", None), ("ugc_cinemas.json", "UGC"),
             ("pathe_cinemas.json", "Pathé"), ("cgr_cinemas.json", "CGR"),
             ("grandecran_cinemas.json", "Grand Écran")]


# --- Réseau ---------------------------------------------------------------

def lire_octets(url: str, essais: int = 4) -> bytes:
    """Télécharge une ressource binaire, en réessayant les ruptures de transport.

    Même doctrine que `lire_page()` de fetch_data.py, dont ceci est le pendant
    « octets bruts » (là-bas on parse du JSON, ici de l'HTML et du PDF) : on
    rejoue les coupures de connexion — chaque tentative rouvrant une connexion
    NEUVE, seule façon de rattraper un corps tronqué — mais une erreur HTTP
    remonte tout de suite, parce que la réessayer ne ferait que retarder un
    échec mérité.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for n in range(essais):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            if n == essais - 1:
                raise
            attente = 2 ** n * 2
            print(f"  connexion coupée ({type(err).__name__}), "
                  f"reprise {n + 1}/{essais - 1} dans {attente} s…", flush=True)
            sleep(attente)
    raise AssertionError("inatteignable")


# --- Normalisation et appariement ----------------------------------------

# Mots d'enseigne. Ils ne discriminent rien EN TÊTE de nom — « Grand Écran
# Arcachon » et « Arcachon » sont la même salle — mais ils peuvent être le nom
# lui-même. D'où le retrait en PRÉFIXE UNIQUEMENT, et c'est tout sauf de la
# coquetterie : les retirer partout écrasait « L'Écran de Saint-Denis » en
# « SAINT DENIS », qui s'appariait alors au Pathé Saint-Denis — un faux positif
# silencieux, et par-dessus le marché la vraie salle (L'Écran, indé) perdait
# son badge. Un mot d'enseigne au milieu d'un nom est porteur de sens.
PREFIXES = ("GRAND ECRAN", "UGC CINE CITE", "UGC", "PATHE", "CGR", "MK2",
            "CINEMA", "CINEMAS", "CINE", "LE", "LA", "LES", "L")
# Mots vides retirés partout : articles et génériques dont la présence varie
# d'une source à l'autre (« Les 3 Robespierre » / « 3 CINES ROBESPIERRE »).
# ECRAN n'y est PAS, volontairement — voir ci-dessus.
VIDES = {"LE", "LA", "LES", "L", "DU", "DE", "DES", "D", "CINEMA", "CINEMAS",
         "CINE", "CINES", "SALLE"}
# Enseignes concurrentes : deux salles qui les revendiquent différemment ne
# sont JAMAIS la même. « MK2 Parnasse » (75006) et « Pathé Parnasse » (75014)
# se réduisent tous deux à « PARNASSE » et se seraient appariés au rattrapage
# par commune — Paris est une commune, et une grande.
ENSEIGNES = ("GRAND ECRAN", "UGC", "PATHE", "CGR", "MK2", "KINEPOLIS", "MEGARAMA")
IDF = re.compile(r"^(?:75|77|78|91|92|93|94|95)")


def sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def cle_nom(s: str) -> str:
    """Clé d'appariement d'un nom de salle : sans accents, sans ponctuation,
    sans enseigne en tête, sans articles. Repli sur le nom nu si tout était du
    bruit (une salle qui s'appellerait « Le Cinéma » ne doit pas donner une
    clé vide, elle doit rester distinguable)."""
    nom = sans_accents(s)
    change = True
    while change:                      # « CINEMA LE STUDIO » → « LE STUDIO » → « STUDIO »
        change = False
        for p in PREFIXES:
            if nom == p:
                break
            if nom.startswith(p + " "):
                nom, change = nom[len(p) + 1:], True
                break
    toks = [x for x in nom.split() if x not in VIDES]
    return " ".join(toks) or nom or sans_accents(s)


def enseigne(nom: str) -> str | None:
    """Enseigne revendiquée par un nom de salle, si elle est en tête."""
    n = sans_accents(nom)
    return next((e for e in ENSEIGNES if n == e or n.startswith(e + " ")), None)


def compatibles(a: str, b: str) -> bool:
    """Deux noms peuvent-ils désigner la même salle ? Non si chacun affiche une
    enseigne et que ce n'est pas la même. Si un seul en affiche une, on laisse
    passer : nos snapshots nomment « Arcachon » ce qu'UGC appelle « GRAND ÉCRAN
    ARCACHON », et c'est bien la même salle."""
    ea, eb = enseigne(a), enseigne(b)
    return ea is None or eb is None or ea == eb


def cles_cinema(c: dict) -> set[str]:
    """Clés acceptables pour UNE de nos salles.

    Deux graphies, parce que les snapshots Grand Écran nomment les salles
    « Ville - Nom » (« Limoges - Le Lido ») là où les listes officielles disent
    « LE LIDO ». On indexe donc aussi le nom privé de son préfixe de ville.
    """
    cles = {cle_nom(c["name"])}
    ville = sans_accents(c.get("city", ""))
    nom = sans_accents(c["name"])
    if ville and nom.startswith(ville + " ") and len(nom) > len(ville) + 1:
        cles.add(cle_nom(nom[len(ville):]))
    return {k for k in cles if k}


def charger_cinemas() -> dict:
    """Les cinémas du site, tous snapshots confondus, indexés par id."""
    tout = {}
    for nom, chaine in SNAPSHOTS:
        chemin = DATA_DIR / nom
        if not chemin.exists():
            continue
        for cid, c in json.loads(chemin.read_text(encoding="utf-8")).items():
            tout[cid] = dict(c, chain=c.get("chain") or chaine)
    return tout


# --- UGC Illimité ---------------------------------------------------------

_BLOC_UGC = re.compile(
    r'item--cinema-content text-center">\s*'
    r'<div class="color--white text-uppercase">(.*?)</div>\s*'
    r'<div class="color--blue-grey">\s*(.*?)\s*</div>', re.S)


def parser_ugc(page: str) -> list[dict]:
    """Extrait les salles de la page « cinémas acceptant UGC Illimité ».

    HTML statique et ultra régulier : un bloc par salle, nom en capitales puis
    adresse sur plusieurs lignes séparées par des <br>, la dernière portant
    « 75008&nbsp;PARIS ». Pas de JS, pas de JSON caché, pas de cookie.

    Deux pièges : les entités HTML (&eacute;, &nbsp;) — d'où html.unescape()
    suivi du remplacement de l'espace insécable qu'il produit — et le fait que
    les salles UGC et les partenaires portent EXACTEMENT le même markup. On ne
    peut donc pas les distinguer ici ; c'est l'appariement avec les snapshots
    qui s'en charge, et c'est très bien ainsi : la liste dit « accepte la
    carte », c'est la seule chose qui nous intéresse.
    """
    page = html.unescape(page).replace("\xa0", " ")
    salles = []
    for m in _BLOC_UGC.finditer(page):
        nom = re.sub(r"\s+", " ", m.group(1)).strip()
        lignes = [re.sub(r"\s+", " ", x).strip()
                  for x in re.split(r"<br\s*/?>", m.group(2)) if x.strip()]
        derniere = lignes[-1] if lignes else ""
        cp = re.match(r"(\d{5})\s+(.*)", derniere)
        salles.append({
            "name": nom,
            "address": " ".join(lignes[:-1]),
            "postcode": cp.group(1) if cp else "",
            "city": (cp.group(2) if cp else derniere).strip(),
        })
    return salles


def apparier_ugc(salles: list[dict], cinemas: dict) -> tuple[dict, list[dict]]:
    """Rapproche les salles UGC de nos ids. Blocage par code postal, puis nom.

    Le code postal fait tout le travail : il réduit les 357 candidats à deux ou
    trois, après quoi l'égalité des clés de nom suffit presque toujours. Le
    repli `difflib` à 0.85 rattrape les variantes lexicales résiduelles sans
    ouvrir la porte aux rapprochements douteux — sur un lot déjà restreint au
    même code postal, une similarité de 85 % ne se produit pas par hasard.

    Second passage par la VILLE pour les lignes que le code postal a ratées :
    UGC range les trois salles de Limoges en 87100 quand nos snapshots disent
    87000. Le code postal reste le bloc préféré (plus précis) ; la ville n'est
    qu'un rattrapage, et elle reste un bloc — jamais d'appariement au nom seul.

    Les lignes non appariées ne sont PAS des échecs : une soixantaine de salles
    de la liste (MK2, Luminor, Reflet Médicis…) n'existent tout simplement pas
    dans Séancéo. On les renvoie pour les compter, pas pour s'en alarmer.
    """
    par_cp: dict[str, list[str]] = {}
    par_ville: dict[str, list[str]] = {}
    cles = {cid: cles_cinema(c) for cid, c in cinemas.items()}
    for cid, c in cinemas.items():
        par_cp.setdefault(c.get("postcode", ""), []).append(cid)
        par_ville.setdefault(sans_accents(c.get("city", "")), []).append(cid)

    def chercher(k: str, nom: str, candidats: list[str]) -> str | None:
        candidats = [c for c in candidats if compatibles(nom, cinemas[c]["name"])]
        hit = next((c for c in candidats if k in cles[c]), None)
        if hit or not candidats:
            return hit
        # Repli flou : sur un lot déjà restreint à un code postal ou une
        # commune, 85 % de similarité ne se produit pas par hasard.
        score, best = 0.0, None
        for c in candidats:
            r = max(difflib.SequenceMatcher(None, k, x).ratio() for x in cles[c])
            if r > score:
                score, best = r, c
        return best if score >= 0.85 else None

    trouves, restes = {}, []
    for s in salles:
        k = cle_nom(s["name"])
        hit = chercher(k, s["name"], [c for c in par_cp.get(s["postcode"], [])
                                      if c not in trouves])
        if not hit:
            hit = chercher(k, s["name"],
                           [c for c in par_ville.get(sans_accents(s["city"]), [])
                            if c not in trouves])
        if hit:
            trouves[hit] = s
        else:
            restes.append(s)
    return trouves, restes


# --- CinéPass Pathé -------------------------------------------------------

_LITTERAL_PDF = re.compile(rb"\((?:\\.|[^()\\])*\)", re.S)
GROUPES = {"Les Cinémas Pathé", "Cinéma indépendant"}


def texte_pdf(pdf: bytes) -> list[str]:
    """Extrait le texte du PDF CinéPass, en stdlib pure (zlib + regex).

    Aucune dépendance externe, comme tout le pipeline — et c'est jouable ici
    parce que ce PDF est un export Excel : le texte est en clair dans des flux
    compressés, un opérateur `Tj` par cellule, une cellule par ligne. On
    décompresse chaque flux, on ne garde que ceux qui contiennent du texte, et
    on recolle les littéraux `(…)` de chaque ligne.

    FRAGILITÉ ASSUMÉE : si Pathé régénère ce fichier avec un autre outil (ou
    en image scannée), ce parseur rend une liste vide. D'où le garde-fou
    MIN_PATHE côté appelant — on échoue bruyamment plutôt que de publier un
    abonnements.json amputé.
    """
    lignes = []
    for flux in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            brut = zlib.decompress(flux)
        except zlib.error:
            continue
        if b"Tj" not in brut and b"TJ" not in brut:
            continue
        for ligne in brut.split(b"\n"):
            morceaux = _LITTERAL_PDF.findall(ligne)
            if not morceaux:
                continue
            s = b"".join(m[1:-1] for m in morceaux)
            s = re.sub(rb"\\([()\\])", rb"\1", s)
            lignes.append(s.decode("latin-1").strip())
    return [l for l in lignes if l]


def parser_cinepass(lignes: list[str]) -> list[dict]:
    """Reconstitue les lignes du tableau CinéPass à partir du texte du PDF.

    Le tableau a 8 colonnes : Groupe | Agglomération | Site | CinéPass -26 |
    CinéPass | Silver | Gold | CinéCartes. On reconnaît une ligne à son entrée
    (un des deux libellés de groupe) suivie, 3 cellules plus loin, de 5 valeurs
    toutes en « Accepté » / « Non acceptées » — c'est cette double condition
    qui évite de prendre un en-tête ou un pied de page pour une salle.

    Les 4 colonnes CinéPass valent « Accepté » sur les 137 lignes : la liste
    EST la réponse, il n'y a pas de sous-cas par formule d'abonnement. On lit
    quand même la colonne pour ne pas coder en dur une hypothèse qui pourrait
    cesser d'être vraie.
    """
    recs, i = [], 0
    while i < len(lignes):
        if lignes[i] in GROUPES and i + 7 < len(lignes):
            vals = lignes[i + 3:i + 8]
            if all(v.startswith(("Accept", "Non accept")) for v in vals):
                recs.append({"groupe": lignes[i], "agglo": lignes[i + 1],
                             "site": lignes[i + 2],
                             "cinepass": vals[1].startswith("Accept"),
                             "cinecartes": vals[4].startswith("Accept")})
                i += 8
                continue
        i += 1
    return recs


def apparier_cinepass(recs: list[dict], cinemas: dict) -> tuple[dict, list[dict]]:
    """Rapproche les partenaires CinéPass de nos ids. Nom + filtre géographique.

    Ici PAS de code postal : le PDF ne donne qu'une « agglomération », qui n'est
    même pas une commune (Pathé Cité Europe est rangé sous CALAIS alors que la
    salle est à Coquelles, et toute l'Île-de-France est écrasée sous
    « PARIS - ILE DE France »). Sur le nom seul, la précision tombe à 59 % avec
    des faux positifs silencieux et spectaculaires : « Le Capitole (Paris-IDF) »
    s'apparie à Ciné Capitole de Clermont, « Les Capucins (Paris-IDF) » à Pathé
    Capucins de Brest.

    Le filtre géographique restaure 100 % de précision : agglomération « PARIS -
    ILE DE France » ⇒ on n'accepte qu'un code postal francilien ; sinon on exige
    que la commune et l'agglomération se contiennent l'une l'autre. Il coûte
    2-3 vrais positifs — c'est exactement ce que le fichier d'overrides est là
    pour rattraper. Préférer le silence au faux : un badge « accepte ta carte »
    qui se trompe envoie quelqu'un au guichet pour rien.

    Second garde-fou, tiré de la colonne « Groupe » du PDF : une ligne annoncée
    « Cinéma indépendant » ne peut pas désigner une de nos salles Pathé, et
    réciproquement. C'est ce qui distingue « Ciné Massy » (l'indé Cinémassy) du
    Pathé Massy, et « L'Écran de Saint-Denis » du Pathé Saint-Denis — deux
    paires dont les noms normalisés sont identiques et les villes correctes,
    donc que rien d'autre ne séparait.

    Contrairement à UGC, on ne se contente PAS d'une règle d'enseigne pour les
    salles Pathé : le PDF liste 77 salles Pathé, nos snapshots en connaissent
    77 aussi, mais ce ne sont pas les mêmes — Le Renoir (Aix) et Pathé Île
    Seguin ne figurent pas sur la liste du 6 mai 2026. Badger « accepte le
    CinéPass » les 77 nôtres serait donc affirmer deux choses que la source ne
    dit pas. On badge ce qui est listé, rien de plus.
    """
    par_cle: dict[str, list[str]] = {}
    for cid, c in cinemas.items():
        for k in cles_cinema(c):
            par_cle.setdefault(k, []).append(cid)

    trouves, restes = {}, []
    for r in recs:
        if not r["cinepass"]:
            continue
        agglo = sans_accents(r["agglo"])
        francilienne = agglo.startswith("PARIS")
        pathe = r["groupe"] == "Les Cinémas Pathé"
        bons = []
        for cid in par_cle.get(cle_nom(r["site"]), []):
            c = cinemas[cid]
            if (c.get("chain") == "Pathé") is not pathe:
                continue
            if not compatibles(r["site"], c["name"]):
                continue
            ville = sans_accents(c.get("city", ""))
            if francilienne:
                ok = bool(IDF.match(c.get("postcode", "")))
            elif pathe:
                # Les salles Pathé portent un nom que l'exploitant choisit et
                # qui ne se répète pas (« Pathé Labège », « Ciné Cap Vert ») :
                # l'unicité du nom suffit à les identifier, et c'est heureux
                # car l'agglomération du PDF n'est presque jamais la commune
                # (Labège sous TOULOUSE, Coquelles sous CALAIS, Quetigny sous
                # DIJON…). Exiger la commune ici perdait 11 salles Pathé.
                ok = True
            else:
                # Les indés, eux, s'appellent Le Vox, Le Capitole ou Les
                # Capucins — des noms que la France entière partage. On exige
                # la commune, et on assume les quelques ratés.
                ok = ville in agglo or agglo in ville
            if ok and cid not in trouves:
                bons.append(cid)
        if len(bons) == 1:
            trouves[bons[0]] = r
        else:
            restes.append(r)   # 0 candidat, ou ambigu : à l'humain de trancher
    return trouves, restes


# --- Assemblage -----------------------------------------------------------

def construire(cinemas: dict, ugc_ok: dict, cp_ok: dict) -> dict:
    """Fusionne les appariements et les overrides manuels.

    Aucune règle d'enseigne ici : tout vient des deux listes officielles, et
    les overrides — appliqués en dernier, donc toujours gagnants — portent les
    quelques cas que l'appariement automatique ne peut pas trancher seul.
    """
    ab: dict[str, dict] = {}

    def poser(cid: str, carte: str, valeur: bool = True) -> None:
        ab.setdefault(cid, {})[carte] = valeur

    for cid in ugc_ok:
        poser(cid, "ugc_illimite")
    for cid in cp_ok:
        poser(cid, "cinepass")

    overrides = DATA_DIR / "abonnements_overrides.json"
    if overrides.exists():
        manuels = json.loads(overrides.read_text(encoding="utf-8"))
        for cid, cartes in manuels.items():
            if cid.startswith("_"):      # clés de commentaire
                continue
            for carte, valeur in cartes.items():
                poser(cid, carte, bool(valeur))

    # Une salle sans aucune carte n'a rien à faire dans le fichier : le site
    # lit « absent = n'accepte rien », pas besoin de 200 entrées à false.
    return {cid: v for cid, v in sorted(ab.items()) if any(v.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description="Collecte les cartes d'abonnement illimité.")
    ap.add_argument("--dry-run", action="store_true",
                    help="affiche le rapport sans écrire data/abonnements.json")
    args = ap.parse_args()

    cinemas = charger_cinemas()
    if not cinemas:
        print("Aucun snapshot de cinémas : lance d'abord fetch_data.py", file=sys.stderr)
        return 1
    print(f"{len(cinemas)} cinémas connus du site.")

    print(f"\nUGC Illimité — {UGC_URL}")
    salles = parser_ugc(lire_octets(UGC_URL).decode("utf-8", "replace"))
    if len(salles) < MIN_UGC:
        print(f"  ! {len(salles)} salles extraites (< {MIN_UGC}) : la page a "
              f"changé de forme. Rien n'est écrit.", file=sys.stderr)
        return 1
    ugc_ok, ugc_reste = apparier_ugc(salles, cinemas)
    print(f"  {len(salles)} salles listées -> {len(ugc_ok)} appariées, "
          f"{len(ugc_reste)} hors base Séancéo")

    print(f"\nCinéPass Pathé — {PATHE_PDF}")
    recs = parser_cinepass(texte_pdf(lire_octets(PATHE_PDF)))
    if len(recs) < MIN_PATHE:
        print(f"  ! {len(recs)} lignes extraites (< {MIN_PATHE}) : le PDF a "
              f"changé de forme. Rien n'est écrit.", file=sys.stderr)
        return 1
    cp_ok, cp_reste = apparier_cinepass(recs, cinemas)
    n_inde = sum(1 for r in recs if r["groupe"] == "Cinéma indépendant")
    print(f"  {len(recs)} lignes ({len(recs) - n_inde} Pathé + {n_inde} indés) -> "
          f"{len(cp_ok)} appariées, {len(cp_reste)} hors base ou ambigus")

    ab = construire(cinemas, ugc_ok, cp_ok)
    n_u = sum(1 for v in ab.values() if v.get("ugc_illimite"))
    n_c = sum(1 for v in ab.values() if v.get("cinepass"))
    deux = [cid for cid, v in ab.items()
            if v.get("ugc_illimite") and v.get("cinepass")]
    print(f"\n{len(ab)}/{len(cinemas)} cinémas concernés — "
          f"UGC Illimité {n_u}, CinéPass {n_c}, les deux {len(deux)}")
    for cid in deux:
        c = cinemas[cid]
        print(f"    * {c['name']} ({c.get('postcode','')} {c.get('city','')})")

    if args.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
        return 0
    (DATA_DIR / "abonnements.json").write_text(
        json.dumps(ab, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ndata/abonnements.json écrit ({len(ab)} entrées).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
