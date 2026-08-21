"""Génère `redirect/` : le site fantôme qui reste sur l'ANCIENNE adresse.

Contexte. Séancéo a vécu sur `https://keenzzz.github.io/seanceo/` puis a
déménagé sur son propre sous-domaine (voir `BASE_URL` dans `build_site.py`).
Google avait déjà indexé des milliers d'anciennes URL : les laisser mourir en
404 jetterait à la poubelle des mois de montée en indexation.

Pourquoi pas une vraie redirection 301 ? Parce que GitHub Pages sert des
fichiers statiques et **ne permet pas de choisir les en-têtes HTTP** : on ne
peut pas répondre « 301 Moved Permanently ». Le seul levier restant est ce que
la PAGE peut dire d'elle-même, d'où les trois signaux posés ici :

  1. `<link rel="canonical">` — dit à Google « la vraie page est là-bas ».
     C'est le signal qui transfère la réputation acquise.
  2. `<meta http-equiv="refresh" content="0; …">` — la redirection à délai nul.
     Google la documente comme équivalente à une 301 (« redirection permanente
     côté client ») et elle emmène vraiment le visiteur humain.
  3. Un lien visible en dur — pour le visiteur dont le navigateur bloque le
     refresh, et pour qu'il reste quelque chose à cliquer si tout échoue.

Volontairement PAS de `noindex` : il ordonnerait de désindexer, et combiné à un
`canonical` qui désigne la nouvelle page, le risque est que la consigne
« n'indexe pas » soit reportée sur la CIBLE. On veut consolider, pas supprimer.

Le fichier `404.html` complète le dispositif : GitHub Pages le sert pour toute
adresse inconnue, ce qui rattrape les URL éphémères par nature (fiches film et
pages de rétrospective apparaissent et disparaissent avec la programmation) et
qui ne sont donc plus dans le sitemap au moment où ce script tourne.

Usage : `python scripts/build_redirects.py`, APRÈS `build_site.py` (il lit le
sitemap que celui-ci vient d'écrire).
"""

from __future__ import annotations

import html
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import BASE_URL  # noqa: E402  (le module a un garde __main__)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = ROOT / "redirect"

# Sous-chemin qu'occupait le site sur GitHub Pages. C'est un site de PROJET :
# le dépôt est servi sous « /<nom-du-dépôt>/ », d'où ce préfixe dans toutes les
# URL indexées. Il ne sert plus qu'ici, à reconstituer l'ancienne adresse.
OLD_PATH = "/seanceo"

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def stub(cible: str, titre: str) -> str:
    """Page de redirection minimale vers `cible` (URL absolue, déjà sûre)."""
    c = html.escape(cible, quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="fr">\n<head>\n'
        '<meta charset="utf-8">\n'
        f'<link rel="canonical" href="{c}">\n'
        f'<meta http-equiv="refresh" content="0; url={c}">\n'
        f"<title>{html.escape(titre)}</title>\n"
        "</head>\n<body>\n"
        "<p>Séancéo a déménagé. Cette page est désormais ici :<br>\n"
        f'<a href="{c}">{c}</a></p>\n'
        "</body>\n</html>\n"
    )


def chemins_du_sitemap() -> list[str]:
    """Chemins (« /carte/ ») listés par le sitemap fraîchement construit."""
    sm = SITE / "sitemap.xml"
    if not sm.exists():
        sys.exit("sitemap.xml introuvable : lancer build_site.py d'abord.")
    racine = ET.fromstring(sm.read_text(encoding="utf-8"))
    chemins = []
    for loc in racine.iter(f"{SITEMAP_NS}loc"):
        url = (loc.text or "").strip()
        if url.startswith(BASE_URL):
            chemins.append(url[len(BASE_URL):] or "/")
    return chemins


def ecrire(chemin_relatif: str, contenu: str) -> None:
    f = OUT / chemin_relatif
    f.parent.mkdir(parents=True, exist_ok=True)
    # Octets, pas write_text : sous Windows celui-ci réécrirait les fins de
    # ligne et le build local cesserait d'être identique à celui du CI.
    f.write_bytes(contenu.encode("utf-8"))


def main() -> None:
    chemins = chemins_du_sitemap()

    for chemin in chemins:
        # « /carte/ » → « carte/index.html » ; « / » → « index.html ».
        interne = chemin.strip("/")
        dest = f"{interne}/index.html" if interne else "index.html"
        ecrire(dest, stub(BASE_URL + chemin, "Séancéo a déménagé"))

    # Rattrapage des URL absentes du sitemap : on reporte le chemin demandé sur
    # la nouvelle adresse, en retirant l'ancien préfixe de projet. `replace(…, 1)`
    # et pas un strip : seul le préfixe de TÊTE doit sauter, une page qui
    # contiendrait « /seanceo » ailleurs dans son chemin ne doit pas être mutilée.
    js = (
        "var p = location.pathname;\n"
        f"if (p.indexOf({OLD_PATH!r}) === 0) p = p.slice({len(OLD_PATH)});\n"
        f"location.replace({BASE_URL!r} + (p || '/') + location.search + location.hash);\n"
    )
    ecrire(
        "404.html",
        "<!doctype html>\n"
        '<html lang="fr">\n<head>\n'
        '<meta charset="utf-8">\n'
        f'<link rel="canonical" href="{BASE_URL}/">\n'
        "<title>Séancéo a déménagé</title>\n"
        f"<script>{js}</script>\n"
        "</head>\n<body>\n"
        "<p>Séancéo a déménagé. Le site est désormais ici :<br>\n"
        f'<a href="{BASE_URL}/">{BASE_URL}/</a></p>\n'
        "</body>\n</html>\n",
    )

    # Un robots.txt qui ne renvoie PAS de sitemap : l'ancienne adresse n'a plus
    # rien à faire découvrir, elle n'a plus qu'à laisser suivre les canoniques.
    # On autorise l'exploration — interdire empêcherait Google de LIRE les
    # redirections, donc de les suivre.
    ecrire("robots.txt", "User-agent: *\nAllow: /\n")

    print(f"redirect/ genere : {len(chemins) + 1} pages vers {BASE_URL}")


if __name__ == "__main__":
    main()
