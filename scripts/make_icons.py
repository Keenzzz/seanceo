"""Icônes de Séancéo (favicon, écran d'accueil, manifeste) et carte de partage.

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

from PIL import Image, ImageDraw, ImageFont

STATIC = Path(__file__).resolve().parent.parent / "static"

FOND = (13, 16, 20, 255)      # --bg  : noir bleuté de salle obscure
AMBRE = (217, 164, 65, 255)   # --accent : lumière tungstène du projecteur
GRIS = (152, 160, 171, 255)   # --muted : le gris des lignes secondaires

GRAND = 1024  # on dessine ici, on réduit ensuite

# Carte de partage (Open Graph). 1200×630 est le format attendu par Facebook,
# LinkedIn, Bluesky, Discord et WhatsApp — un ratio de 1,91:1 que tous rognent
# de la même façon, donc la seule taille à produire.
OG = (1200, 630)


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


def police(taille: int, graisse: str = "gras") -> ImageFont.FreeTypeFont:
    """Une police système, en gras ou en demi-gras.

    Pillow n'embarque qu'une police bitmap minuscule (`load_default()`), qui
    donnerait un texte illisible à 96 px. On pioche donc dans les polices de
    la machine — acceptable ici, et ICI SEULEMENT : ce script tourne à la main
    et son résultat est versionné, donc la carte produite est la même pour
    tout le monde, quelle que soit la machine qui sert le site.
    """
    familles = {
        "gras": ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
        "demi": ("seguisb.ttf", "arial.ttf", "DejaVuSans.ttf"),
    }[graisse]
    for nom in familles:
        for dossier in ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu"):
            chemin = Path(dossier) / nom
            if chemin.exists():
                return ImageFont.truetype(str(chemin), taille)
    raise SystemExit(f"Aucune police {graisse} trouvée parmi {familles}. "
                     "Installe l'une d'elles ou complète la liste.")


# Le texte de la carte, par langue. Repris MOT POUR MOT du slogan du header
# et de sa traduction (i18n.py, « Le répertoire en salle, partout en France ») :
# la vignette et la page qu'elle annonce doivent dire la même chose.
OG_TEXTES = {
    "fr": (("Le répertoire en salle,", "partout en France"),
           "Reprises · copies restaurées · rétrospectives"),
    "en": (("Repertory cinema", "across France"),
           "Revivals · restorations · retrospectives"),
}


def carte_partage(langue: str = "fr") -> Image.Image:
    """La vignette affichée quand un lien du site est partagé (Open Graph).

    Elle sert de VALEUR PAR DÉFAUT : les fiches film, elles, partagent leur
    affiche TMDB, bien plus parlante. Cette carte-ci ne s'affiche donc que
    pour les pages sans image propre (accueil, ville, cinéma, outils), où ce
    qu'il faut annoncer est la nature du site, pas un film en particulier.

    Une carte PAR LANGUE : un lien vers /en/ partagé sur un forum anglophone
    afficherait sinon une accroche en français, juste sous un titre anglais.
    """
    lignes, sous_titre = OG_TEXTES[langue]
    img = Image.new("RGBA", OG, FOND)
    d = ImageDraw.Draw(img)

    # Filet ambre en pied : la même signature que le header du site, et de quoi
    # accrocher l'œil dans un fil de discussion où tout est gris.
    d.rectangle([0, OG[1] - 10, OG[0], OG[1]], fill=AMBRE)

    # Le clap, repris à l'identique des icônes (le logo du site) : dessiné en
    # 1024 puis réduit, sinon ses obliques seraient crénelées.
    logo = clap(marge=0.12, coins=True).resize((300, 300), Image.LANCZOS)
    img.paste(logo, (96, 150), logo)

    x = 96 + 300 + 64
    d.text((x, 214), "Séancéo", font=police(112, "gras"), fill=AMBRE)
    corps = police(44, "demi")
    d.text((x, 344), lignes[0], font=corps, fill=(233, 236, 239, 255))
    d.text((x, 400), lignes[1], font=corps, fill=(233, 236, 239, 255))
    d.text((x, 476), sous_titre, font=police(30, "demi"), fill=GRIS)
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

    # Cartes de partage : pas carrées, donc pas passées par ecrire().
    for langue in OG_TEXTES:
        nom = "og.png" if langue == "fr" else f"og-{langue}.png"
        chemin = STATIC / nom
        carte_partage(langue).convert("RGB").save(chemin, "PNG", optimize=True)
        print(f"  {nom:<28} {OG[0]}×{OG[1]}  {chemin.stat().st_size // 1024 or 1} ko")


if __name__ == "__main__":
    main()
