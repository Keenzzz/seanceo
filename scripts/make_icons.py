"""Icônes de Séancéo (favicon, écran d'accueil, manifeste).

⚠️ Ce script n'est PAS dans le pipeline. Il se lance à la main, ses sorties
sont versionnées dans `static/`, et le CI ne l'exécute jamais — même posture
que `enrich_tmdb.py`, dont seul le cache est commité. C'est la seule raison
pour laquelle il peut dépendre de Pillow alors que tout le reste du projet
est en stdlib pur : rien en production ne l'appelle.

    python scripts/make_icons.py

Le motif est un clap de cinéma, repris du 🎬 du logo, en ambre sur le noir
bleuté de la salle obscure. Dessiné en grand (1024 px) puis réduit : les
bords obliques du clap seraient crénelés s'ils étaient tracés directement en
48 px.
"""

from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "static"

FOND = (13, 16, 20, 255)      # --bg  : noir bleuté de salle obscure
AMBRE = (217, 164, 65, 255)   # --accent : lumière tungstène du projecteur

GRAND = 1024  # on dessine ici, on réduit ensuite


def clap(marge: float, coins: bool) -> Image.Image:
    """Le clap, dessiné à `GRAND` px.

    `marge` : part de l'image laissée vide autour du motif. Les icônes
    « maskable » d'Android peuvent être rognées en cercle par le système :
    tout ce qui compte doit tenir dans les 80 % centraux, d'où une marge plus
    généreuse pour cette variante.
    `coins` : arrondir les angles (icône classique) ou laisser le fond couvrir
    tout le carré (maskable, que le système découpe lui-même).
    """
    img = Image.new("RGBA", (GRAND, GRAND), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if coins:
        d.rounded_rectangle([0, 0, GRAND - 1, GRAND - 1], radius=int(GRAND * 0.22), fill=FOND)
    else:
        d.rectangle([0, 0, GRAND - 1, GRAND - 1], fill=FOND)

    # Repère interne : le motif occupe la zone [marge, 1 - marge].
    def p(x: float, y: float) -> tuple[int, int]:
        return (int((marge + x * (1 - 2 * marge)) * GRAND),
                int((marge + y * (1 - 2 * marge)) * GRAND))

    # Ardoise (le corps du clap).
    d.rounded_rectangle([p(0.0, 0.34), p(1.0, 1.0)], radius=int(GRAND * 0.035), fill=AMBRE)

    # Barre supérieure, inclinée comme un clap ouvert. Elle est dessinée dans
    # son propre calque pour que les bandes sombres soient découpées PAR sa
    # forme : tracées directement, elles dépasseraient de la barre.
    barre = [p(0.0, 0.16), p(1.0, 0.0), p(1.0, 0.20), p(0.0, 0.36)]
    masque = Image.new("L", (GRAND, GRAND), 0)
    ImageDraw.Draw(masque).polygon(barre, fill=255)

    calque = Image.new("RGBA", (GRAND, GRAND), AMBRE)
    dc = ImageDraw.Draw(calque)
    # Bandes obliques : on les prolonge largement au-delà du cadre, le masque
    # se charge de les couper net sur les bords de la barre.
    large = int(GRAND * 0.075)
    for i in range(5):
        x = int((marge + (0.06 + i * 0.22) * (1 - 2 * marge)) * GRAND)
        dc.polygon([(x, -GRAND), (x + large, -GRAND),
                    (x + large - int(GRAND * 0.30), 2 * GRAND),
                    (x - int(GRAND * 0.30), 2 * GRAND)], fill=FOND)

    img.paste(calque, (0, 0), masque)
    return img


def ecrire(img: Image.Image, taille: int, nom: str) -> None:
    petit = img.resize((taille, taille), Image.LANCZOS)
    chemin = STATIC / nom
    petit.save(chemin, "PNG", optimize=True)
    print(f"  {nom:<28} {taille}×{taille}  {chemin.stat().st_size // 1024 or 1} ko")


def main() -> None:
    STATIC.mkdir(exist_ok=True)
    classique = clap(marge=0.12, coins=True)
    maskable = clap(marge=0.24, coins=False)

    print("Icônes écrites dans static/ :")
    ecrire(classique, 512, "icon-512.png")
    ecrire(classique, 192, "icon-192.png")
    # iOS ne lit pas le manifeste pour l'icône d'écran d'accueil : il lui faut
    # apple-touch-icon, en 180 px, et sans transparence (il l'aplatirait sur
    # du noir de toute façon — notre fond l'est déjà).
    ecrire(classique, 180, "apple-touch-icon.png")
    ecrire(maskable, 512, "icon-maskable-512.png")
    ecrire(classique, 32, "favicon.png")


if __name__ == "__main__":
    main()
