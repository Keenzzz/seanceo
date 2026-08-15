"""Traduction du site Séancéo (français ↔ anglais).

CHOIX DE CONCEPTION : la CLÉ de traduction est la phrase française elle-même.

On aurait pu inventer des identifiants (`home.lead`, `nav.watchlist`…). On ne
l'a pas fait, pour deux raisons qui comptent plus que l'élégance :

1. **Le repli est silencieux et lisible.** `t("Séances uniques")` sans entrée
   dans le dictionnaire rend « Séances uniques », pas `MISSING_KEY_42`. Sur un
   site de 1 620 pages traduites d'un bloc, un oubli doit dégrader vers du
   français correct, jamais vers du charabia visible par un visiteur.
2. **Le build français reste identique au bit près.** En français `t()` est
   l'identité : aucune régression possible sur la version qui est déjà en
   production et déjà indexée par Google.

La contrepartie assumée : corriger une faute de frappe dans le texte français
casse le lien avec sa traduction. `python scripts/i18n.py` liste justement les
chaînes que build_site.py demande et que le dictionnaire ne connaît pas.

Aucune dépendance externe (stdlib uniquement), comme tout le pipeline.
"""

from __future__ import annotations

import re
from datetime import date

# Langues produites par le build. L'ordre compte : le français est la langue
# de référence (racine du site), l'anglais vit sous /en/.
LANGS = ("fr", "en")

# Langue en cours de génération. build_site.py appelle set_lang() au début de
# chaque passe. Volontairement un état de module : le générateur est un script
# mono-thread qui produit une langue à la fois, faire circuler la langue dans
# les 80 appels de fonction du fichier n'aurait rien apporté.
LANG = "fr"

# Chaînes demandées par le build et absentes du dictionnaire : remplies au fil
# de la génération, vidées par un rapport en fin de build.
MISSING: set[str] = set()


def set_lang(lang: str) -> None:
    global LANG
    if lang not in LANGS:
        raise ValueError(f"langue inconnue : {lang}")
    LANG = lang


def lang_prefix(lang: str | None = None) -> str:
    """Segment d'URL de la langue : “” en français (racine), “/en” en anglais."""
    return "" if (lang or LANG) == "fr" else f"/{lang or LANG}"


def t(texte: str, /) -> str:
    """Traduit une chaîne d'interface. Identité en français."""
    if LANG == "fr":
        return texte
    tr = EN.get(texte)
    if tr is None:
        MISSING.add(texte)
        return texte
    return tr


def tf(texte: str, /, **kw) -> str:
    """Traduit puis interpole. Les variables sont nommées (`{n}`, `{ville}`) —
    l'ordre des mots change d'une langue à l'autre, des positions numérotées
    rendraient certaines traductions impossibles à écrire correctement.

    Le `/` n'est pas décoratif : il rend le premier paramètre POSITIONNEL SEUL.
    Sans lui, `tf("… film{s}", s=plural(n))` levait « got multiple values for
    argument 's' » — le nom du paramètre entrait en collision avec la variable
    de pluriel la plus utilisée du fichier.
    """
    return t(texte).format(**kw)


# --- Accords et formats ----------------------------------------------------

def plural(n: int) -> str:
    """Le « s » du pluriel — les deux langues ne coupent PAS au même endroit.

    Le français met 0 et 1 au singulier (« 0 film », « 1 film ») ; l'anglais
    ne met que 1 (« 0 films », « 1 film »). Sans cette distinction, les pages
    anglaises afficheraient « 0 film » un peu partout dans les compteurs.
    """
    if LANG == "fr":
        return "s" if n > 1 else ""
    return "" if n == 1 else "s"


def nombre(n: int) -> str:
    """Séparateur de milliers propre à la langue.

    Français : espace INSÉCABLE (« 84 640 ») pour qu'un retour à la ligne ne
    coupe jamais un nombre en deux. Anglais : virgule (« 84,640 »), l'espace
    y serait lue comme une coquille.
    """
    return f"{n:,}" if LANG == "en" else f"{n:,}".replace(",", " ")


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
           "Saturday", "Sunday"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def jour_mois(d: date) -> str:
    """Date sans le repère « aujourd'hui/demain » : « samedi 12 août » ou
    « Saturday 12 August ». Le jour reste en chiffres dans les deux langues
    (l'ordinal anglais « 12th » alourdit une grille d'horaires pour rien)."""
    if LANG == "fr":
        return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return f"{DAYS_EN[d.weekday()]} {d.day} {MONTHS_EN[d.month - 1]}"


def date_label(d: date, today: date) -> str:
    """Libellé d'un jour de programme, capitalisé comme un titre de section."""
    if d == today:
        return t("Aujourd'hui")
    if (d - today).days == 1:
        return t("Demain")
    return jour_mois(d).capitalize() if LANG == "fr" else jour_mois(d)


def is_today_label(label: str) -> bool:
    """Vrai si le libellé est « Aujourd'hui »/« Demain » (ou leur traduction).
    Ces deux-là ne DISENT pas la date : l'accueil leur ajoute la date exacte
    à côté, ce qui serait un doublon sur les autres jours."""
    return label in (t("Aujourd'hui"), t("Demain"))


def heure(iso_start: str) -> str:
    """Heure d'une séance. « 20h30 » en français, « 8:30 pm » en anglais —
    le format 24 h est illisible pour un anglophone, et c'est justement
    l'information qu'il vient chercher."""
    hh, mm = iso_start[11:13], iso_start[14:16]
    if LANG == "fr":
        return f"{hh}h{mm}"
    h = int(hh)
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{mm} {suffix}"


def decimal(x: float, digits: int = 1) -> str:
    """Séparateur décimal : virgule en français, point en anglais."""
    s = f"{x:.{digits}f}"
    return s if LANG == "en" else s.replace(".", ",")


def cinema_kind_label(chain: str) -> str:
    """« cinéma indépendant » / « cinéma Pathé » → « independent cinema » /
    « Pathé cinema ». La chaîne est un nom propre, elle ne se traduit pas ;
    seule la structure de la formule change de langue."""
    if not chain:
        return t("cinéma indépendant")
    return tf("cinéma {chaine}", chaine=chain)


# --- Contenu des films -----------------------------------------------------

def localize_movies(movies: dict) -> dict:
    """Vue anglaise du catalogue : promeut les champs `*_en` du cache TMDB.

    Renvoie des copies superficielles où `title`, `storyline`, `genre` et
    `country_tmdb` portent la valeur anglaise QUAND elle existe, et la valeur
    française sinon (un film sans fiche TMDB anglaise vaut mieux affiché en
    français qu'affiché vide).

    Faire la substitution ici plutôt qu'au point d'affichage est délibéré :
    les 200 endroits de build_site.py qui lisent `m["title"]` continuent de
    marcher sans modification, et il n'existe qu'UN seul endroit où la règle
    « anglais si disponible, français sinon » est écrite.

    ⚠️ Les URLs (slugs) ne passent PAS par ici : elles sont calculées une fois
    à partir des titres FRANÇAIS, pour que /en/film/mon-oncle/ et
    /film/mon-oncle/ désignent bien la même fiche.
    """
    if LANG == "fr":
        return movies
    out = {}
    for key, m in movies.items():
        c = dict(m)
        for champ, source in (("title", "title_en"), ("storyline", "storyline_en"),
                              ("genre", "genre_en"), ("country_tmdb", "country_en"),
                              ("poster", "poster_en")):
            if m.get(source):
                c[champ] = m[source]
        out[key] = c
    return out


# --- Dictionnaire ----------------------------------------------------------
# Clé = chaîne française telle qu'écrite dans build_site.py.
# Les accolades sont des variables nommées passées à tf().

EN: dict[str, str] = {
    # --- Identité et chrome ---
    "Le répertoire en salle, partout en France":
        "Repertory cinema across France",
    "Sections du site": "Site sections",
    "Chercher un film ou un réalisateur…": "Search a film or director…",
    "Chercher un film ou un réalisateur": "Search a film or director",
    "Retour en haut de page": "Back to top",
    "↑ Haut": "↑ Top",
    "← Retour": "← Back",
    "Aujourd'hui": "Today",
    "Demain": "Tomorrow",

    # --- Navigation ---
    "Watchlist": "Watchlist",
    "🎬 À l'affiche": "🎬 Now showing",
    "🎞️ Rétrospectives": "🎞️ Retrospectives",
    "🍿 Marathons": "🍿 Double bills",
    "🗺️ Carte": "🗺️ Map",
    "🏛️ Ma cinémathèque": "🏛️ My film club",

    # --- Sélecteur de langue ---
    "Version anglaise": "English version",
    "Version française": "French version",
    "Langue": "Language",

    # --- Pied de page ---
    "Données de programmation :": "Programme data:",
    "(Syndicat des Cinémas d'Art, de Répertoire et d'Essai), sous Licence Ouverte 2.0.":
        "(French union of arthouse and repertory cinemas), under Licence Ouverte 2.0.",
    "{site} réunit les séances des cinémas indépendants et des grandes enseignes, et met en avant les salles Art &amp; Essai.":
        "{site} brings together showtimes from independent cinemas and major chains, "
        "and highlights arthouse venues.",
    "Fiches films (titres, notes, affiches, synopsis) enrichies via":
        "Film data (titles, ratings, posters, synopses) enriched via",
    "Ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB.":
        "This product uses the TMDB API but is not endorsed or certified by TMDB.",

    # --- Badges et pastilles ---
    "Indé": "Indie",
    "Cinéma indépendant": "Independent cinema",
    "cinéma indépendant": "independent cinema",
    "cinéma {chaine}": "{chaine} cinema",
    "Classique": "Classic",
    "Séance unique": "One-off screening",
    "🏛️ Culte": "🏛️ Cult",
    "{age} ans": "{age} years",
    "100 ans": "100 years",
    "fête son siècle": "turns one hundred",
    "fête ses {age} ans": "turns {age}",
    "Sorti en {annee}, {celebration} en {cette_annee}":
        "Released in {annee}, {celebration} in {cette_annee}",
    "Note moyenne Letterboxd": "Average Letterboxd rating",
    "Affiche de {titre}": "{titre} poster",

    # --- Séances et billetterie ---
    "Réserver la séance de {heure} sur la billetterie du cinéma (nouvel onglet)":
        "Book the {heure} screening on the cinema's ticketing site (new tab)",
    "Réserver cette séance (nouvel onglet)": "Book this screening (new tab)",
    "prochaine séance : {jour}": "next screening: {jour}",
    "Aucune séance annoncée pour les deux prochaines semaines.":
        "No screenings announced for the next two weeks.",
    "Aucune séance cette semaine.": "No screenings this week.",
    "Aucune séance à venir.": "No upcoming screenings.",
    "Pas de séance aujourd'hui. Prochaines dates :":
        "No screening today. Next dates:",
    "+ {n} autre{s} film{s2} plus tard cette semaine":
        "+ {n} more film{s2} later this week",

    # --- Tri et filtres ---
    "Trier par": "Sort by",
    "Trier les films": "Sort films",
    "Trier et filtrer les films": "Sort and filter films",
    "Filtrer les films": "Filter films",
    "Filtrer par version": "Filter by version",
    "Filtrer par langue": "Filter by language",
    "Note Letterboxd": "Letterboxd rating",
    "Titre": "Title",
    # Marques de sens de tri : elles se lisent à l'identique dans les deux
    # langues. Présentes quand même pour que le rapport de fin de build ne les
    # signale pas comme des oublis — un rapport bruyant finit ignoré.
    "A → Z": "A → Z",
    "Z → A": "Z → A",
    "↑": "↑",
    "↓": "↓",
    "Année": "Year",
    "Cinémas": "Cinemas",
    "Prochaine séance": "Next screening",
    "Toutes": "All",
    "Tous": "All",
    "VO / VOST": "Original / subtitled",
    # Sigles de version. Un francophone les lit d'un coup d'œil, un anglophone
    # ne peut pas les deviner — et c'est l'information la plus décisive pour
    # lui : le film est-il doublé en français ? On les développe donc, en
    # restant assez court pour tenir dans une pastille d'horaire.
    "VF": "French dub",
    "VO": "Original",
    "VOST": "Orig. + FR subs",
    "Muet": "Silent",
    "Décennie": "Decade",
    "Années {d}": "{d}s",
    "Genre": "Genre",
    "Pays": "Country",
    "{n} films": "{n} films",
    "Afficher plus": "Show more",

    # --- Recherche de ville ---
    "Chercher votre ville ({n} villes)…": "Search your city ({n} cities)…",
    "Chercher une ville": "Search a city",
    "📍 Autour de moi": "📍 Near me",

    # --- Passerelle vers le site frère ---
    "Vous êtes à Paris ?": "Are you in Paris?",
    "Pour la capitale, Paris Ciné Aujourd'hui recense tout plus efficacement. "
    "C'est un hub dédié à Paris : films à l'affiche, rétrospectives, séances de "
    "plein air de cet été, carte des cinémas et idées de marathon. Uniquement pour Paris.":
        "For the capital, Paris Ciné Aujourd'hui covers everything more "
        "thoroughly. It is a Paris-only hub: films showing, retrospectives, this "
        "summer's open-air screenings, a map of cinemas and double-bill ideas. "
        "Paris only.",
    "Ouvrir Paris Ciné ↗": "Open Paris Ciné ↗",

    # --- Page cinéma ---
    "{cinema} ({ville}) : séances et programme — {site}":
        "{cinema} ({ville}): showtimes and programme — {site}",
    "Programme et horaires des séances du cinéma {cinema} à {ville} sur les 15 prochains jours. {nature}.":
        "Programme and showtimes for {cinema} in {ville} over the next 15 days. {nature}.",
    "Voir tous les cinémas de {ville}": "See all cinemas in {ville}",
    "Programme complet": "Full programme",

    # --- Page ville ---
    "Cinéma à {ville} : séances et horaires — {site}":
        "Cinemas in {ville}: showtimes and listings — {site}",
    "Quel film voir à {ville} ? Séances et horaires des {n} cinéma(s) de la ville : programme du jour et de la semaine.":
        "What's on in {ville}? Showtimes for the city's {n} cinema(s): "
        "today's programme and the week ahead.",
    "Cinémas à {ville}": "Cinemas in {ville}",
    "{n} cinéma{s} indépendant{s}": "{n} independent cinema{s}",
    "{n} cinéma{s} de chaîne": "{n} chain cinema{s}",
    "{inventaire} à {ville}.": "{inventaire} in {ville}.",
    # Connecteur d'énumération, isolé parce qu'il est assemblé au code plutôt
    # qu'écrit dans une phrase (« 3 indés ET 2 cinémas de chaîne »).
    "et": "and",
    "Les séances d'aujourd'hui d'abord, puis celles des jours suivants.":
        "Today's screenings first, then the days that follow.",
    " Dont {n} film{s} de plus de {age} ans : ":
        " Including {n} film{s} over {age} years old: ",
    "voir le classement": "see the ranking",

    # --- Fiche film ---
    "{titre} : séances près de chez vous — {site}":
        "{titre}: showtimes near you — {site}",
    "Où voir {titre}{de_realisateur} ? Séances et horaires ville par ville, dans {n} cinéma(s) en France.":
        "Where to watch {titre}{de_realisateur}? Showtimes city by city, "
        "in {n} cinema(s) across France.",
    "Où voir {titre} ? Séances et horaires ville par ville en France.":
        "Where to watch {titre}? Showtimes city by city across France.",
    " de {realisateur}": " by {realisateur}",
    "Où voir {titre} ?": "Where to watch {titre}?",
    "De {realisateur}": "Directed by {realisateur}",
    "Avec {acteurs}": "Starring {acteurs}",
    "{n} min": "{n} min",
    "{n} cinéma{s}": "{n} cinema{s}",
    "Tous les cinémas de {ville} →": "All cinemas in {ville} →",
    "À l'affiche dans {n} cinéma{s} de {v} villes. Choisissez la vôtre pour voir les horaires.":
        "Showing in {n} cinema{s} across {v} cities. Pick yours to see showtimes.",
    "▶ Bande-annonce": "▶ Trailer",
    "Voir sur Letterboxd ↗": "View on Letterboxd ↗",
    "🎂 Ce film {celebration} en {annee}.": "🎂 This film {celebration} in {annee}.",

    # --- Accueil ---
    "Reprises et rétrospectives au cinéma en France — {site}":
        "Repertory screenings and retrospectives in French cinemas — {site}",
    "Quel classique voir en salle ? {n} reprises, versions restaurées et rétrospectives à l'affiche cette semaine dans {c} cinémas en France. Cherchez votre ville.":
        "Which classic is playing near you? {n} revivals, restorations and "
        "retrospectives showing this week in {c} cinemas across France. "
        "Search your city.",
    "Ce soir, un classique passe près de chez vous":
        "Tonight, a classic is playing near you",
    "Les films anciens qui repassent en salle cette semaine, partout en France : reprises, copies restaurées, séances de ciné-club.":
        "Older films back on the big screen this week, all across France: "
        "revivals, restored prints and film-club screenings.",
    "<strong>{n} de ces séances n'ont pas de deuxième date.</strong>":
        "<strong>{n} of these screenings have no second date.</strong>",
    "films de répertoire": "repertory films",
    "séances cette semaine": "screenings this week",
    "cinémas": "cinemas",
    "villes": "cities",
    "séances uniques": "one-off screenings",
    "Choisissez votre ville": "Choose your city",
    "Les villes les plus fournies : {liste}.": "Best-served cities: {liste}.",
    "Vous êtes sur Letterboxd ?": "Are you on Letterboxd?",
    "Entrez votre pseudo : {site} vous dit lesquels de vos films à voir sont à l'affiche <strong>et vous recommande des reprises selon vos réalisateurs préférés</strong>. Tout se passe dans votre navigateur.":
        "Enter your username: {site} tells you which of your watchlist films are "
        "showing <strong>and recommends revivals based on your favourite "
        "directors</strong>. Everything happens in your browser.",
    "Entrer mon pseudo": "Enter my username",
    "Ma watchlist en détail →": "My watchlist in detail →",
    "À ne pas rater": "Don't miss",
    "Des séances qui ne repassent nulle part ailleurs en France cette semaine.":
        "Screenings that play nowhere else in France this week.",
    "Note moyenne donnée par les spectateurs de": "Average rating from viewers on",
    "Les séances ci-dessous sont les mieux notées de la semaine.":
        "The screenings below are the best rated of the week.",
    "Aucune séance unique repérée cette semaine.":
        "No one-off screenings spotted this week.",

    # --- Dernière chance (page /derniere-chance/) ---
    "Dernière chance": "Last chance",
    "⏳ Dernière chance": "⏳ Last chance",
    "Dernière chance : les séances uniques de la semaine — {site}":
        "Last chance: this week's one-off screenings — {site}",
    "{n} films de répertoire ne passent qu'une seule fois en France cette semaine. Toutes les séances sans deuxième date, ville par ville, avec la réservation.":
        "{n} repertory films play only once in France this week. Every screening "
        "with no second date, city by city, with booking links.",
    "Ces <strong>{n} films de répertoire</strong> ne passent qu'une seule fois en France cette semaine, dans {v} villes. Pas de deuxième date, pas de reprise le lendemain dans la salle d'à côté. Ils sont classés du jour le plus proche au plus lointain.":
        "These <strong>{n} repertory films</strong> play only once in France this "
        "week, across {v} cities. No second date, no encore the next day at the "
        "cinema down the road. They are listed from the nearest day to the furthest.",
    "Ville": "City",
    "{n} séances en France": "{n} screenings in France",
    "＋ Ajouter ces séances à mon agenda": "＋ Add these screenings to my calendar",
    "Un fichier .ics à ouvrir dans Google Agenda, Apple Calendrier ou Outlook. Le filtre de ville s'applique : choisissez votre ville avant d'exporter et vous n'emportez que ce qui vous concerne.":
        "An .ics file to open in Google Calendar, Apple Calendar or Outlook. The "
        "city filter applies: pick your city before exporting and you only take "
        "away what concerns you.",
    "Les {n} séances sans deuxième date, ville par ville →":
        "All {n} screenings with no second date, city by city →",
    "🎂 Les anniversaires de {annee}": "🎂 {annee} anniversaries",
    "{n} films de patrimoine fêtent un anniversaire rond cette année (un demi-siècle, un centenaire…) et repassent en salle. L'occasion de les revoir sur grand écran.":
        "{n} heritage films hit a round anniversary this year (half a century, "
        "a centenary…) and are back in cinemas. A chance to see them on the big "
        "screen again.",
    "Et {n} autre{s} film{s2} fêtent un cap cette année.":
        "And {n} more film{s2} hit a milestone this year.",
    "Parcourir les classiques →": "Browse the classics →",
    "🎞️ Compose ta cinémathèque": "🎞️ Build your own film club",
    "Choisis un réalisateur : {site} réunit toutes ses séances de répertoire de France en une rétrospective à toi, à mettre dans ton agenda. Ne subis plus la séance unique à 400 km, programme-la.":
        "Pick a director: {site} gathers every repertory screening of their work "
        "in France into a retrospective of your own, ready for your calendar. "
        "Stop missing that one-off screening 250 miles away — plan it.",
    "Composer ma cinémathèque →": "Build my film club →",
    "Rétrospectives en cours": "Retrospectives running now",
    "Les cycles programmés en ce moment, salle par salle.":
        "Seasons playing right now, venue by venue.",
    "Toutes les rétrospectives →": "All retrospectives →",
    "Aucun cycle en cours.": "No season running right now.",
    "Salles de patrimoine": "Heritage venues",
    "Les cinémas qui consacrent la plus grande part de leurs séances de la semaine au répertoire, ces films ressortis en salle plutôt qu'aux nouveautés. Un pourcentage, pas un volume : une petite salle qui ne programme que des reprises devance un multiplexe.":
        "The cinemas devoting the largest share of their weekly screenings to "
        "repertory — films re-released rather than new titles. A percentage, not "
        "a volume: a small venue showing nothing but revivals outranks a "
        "multiplex.",
    "Le classement complet →": "The full ranking →",
    "Où voir du répertoire": "Where to find repertory",
    "{n} villes sur {total} programment au moins une reprise cette semaine.":
        "{n} cities out of {total} are showing at least one revival this week.",
    "Vous cherchez une sortie récente ?": "Looking for a new release?",
    "{n} films à l'affiche cette semaine dans {c} cinémas, indépendants et grandes enseignes.":
        "{n} films showing this week in {c} cinemas, independents and major chains.",
    "Voir ce qui est à l'affiche": "See what's on",
    "{n} films": "{n} films",
    "{n} séances": "{n} screenings",

    # --- Cartes de cycle ---
    "Rétrospective": "Retrospective",
    "<strong>{n} films</strong> · {seances} séances · {villes}":
        "<strong>{n} films</strong> · {seances} screenings · {villes}",
    "{n} villes": "{n} cities",
    "{n} ville{s}": "{n} city{s}",
    " et {n} autre{s} salle{s2}": " and {n} more venue{s2}",
    "Voir le cycle →": "See the season →",
    "{part} % de séances de répertoire": "{part}% repertory screenings",
    "<strong>{part} %</strong> de répertoire · {rep} séances sur {total}":
        "<strong>{part}%</strong> repertory · {rep} of {total} screenings",
    "{n} films": "{n} films",

    # --- Page « À l'affiche » ---
    "Films à l'affiche cette semaine : séances et horaires — {site}":
        "Films showing this week: showtimes and listings — {site}",
    "Quel film voir au cinéma cette semaine ? Séances et horaires de {c} cinémas dans {v} villes en France, indépendants et grandes enseignes. Mis à jour chaque jour.":
        "What to watch in cinemas this week? Showtimes for {c} cinemas across {v} "
        "French cities, independents and major chains. Updated daily.",
    "Quel film voir au cinéma cette semaine ?": "What's on in cinemas this week?",
    "{n} cinémas indépendants": "{n} independent cinemas",
    " et {n} cinémas de chaîne": " and {n} chain cinemas",
    "{inventaire} répartis dans {v} villes, et {s} séances annoncées. La liste est refaite chaque nuit.":
        "{inventaire} across {v} cities, and {s} screenings announced. "
        "The list is rebuilt every night.",
    "Toutes les villes ({n})": "All cities ({n})",
    "Tous les films à l'affiche": "Every film showing",
    "{n} classiques sont aussi à l'affiche": "{n} classics are showing too",
    "Rétrospectives, copies restaurées et ciné-clubs, partout en France.":
        "Retrospectives, restored prints and film clubs, all across France.",
    "Voir le répertoire": "See the repertory",
    "{n} ciné{s}": "{n} cinema{s}",

    # --- Salles de patrimoine ---
    "Les salles de patrimoine en France : où voir du répertoire — {site}":
        "Heritage cinemas in France: where to find repertory — {site}",
    "Quels cinémas programment le plus de films de répertoire en France ? Classement des salles par part de reprises, rétrospectives et copies restaurées dans leur programmation.":
        "Which cinemas show the most repertory films in France? Venues ranked by "
        "the share of revivals, retrospectives and restored prints in their "
        "programme.",
    "Une salle de patrimoine, ici, désigne un cinéma dont une grande part de la programmation est du répertoire : des films ressortis en salle (versions restaurées, reprises, séances de ciné-club), par opposition aux sorties récentes. Le classement mesure la <strong>part</strong> de ces séances de répertoire dans le total des séances de la salle sur la semaine. C'est donc un pourcentage, pas un décompte de rétrospectives ni le nombre de films à l'affiche : compter en volume mettrait les multiplexes en tête, puisqu'ils programment plus de tout. Il faut au moins {min} séances dans la semaine pour y figurer.":
        "A heritage venue, here, means a cinema devoting much of its programme to "
        "repertory: films back on release (restorations, revivals, film-club "
        "screenings) as opposed to new titles. The ranking measures the "
        "<strong>share</strong> of those repertory screenings in the venue's total "
        "for the week. So it is a percentage, not a count of retrospectives nor a "
        "number of films showing: counting by volume would put multiplexes on top, "
        "since they programme more of everything. A venue needs at least {min} "
        "screenings in the week to appear.",
    "Retrouver ces salles sur la carte →": "Find these venues on the map →",

    # --- Classiques ---
    "Films classiques et rétrospectives au cinéma — {site}":
        "Classic films and retrospectives in cinemas — {site}",
    "Quel film classique revoir en salle ? {n} reprises, rétrospectives et versions restaurées à l'affiche en France, classées par note Letterboxd.":
        "Which classic to see again on the big screen? {n} revivals, "
        "retrospectives and restorations showing across France, ranked by "
        "Letterboxd rating.",
    "Classiques & rétrospectives à l'affiche": "Classics & retrospectives showing",
    "{n} films de plus de {age} ans repassent en ce moment dans {c} cinémas en France. Ils sont classés par la note que leur donnent les spectateurs de":
        "{n} films over {age} years old are back in {c} cinemas across France "
        "right now. They are ranked by the rating viewers give them on",
    "Aucune reprise annoncée en ce moment.": "No revival announced right now.",
    "n° {rang}": "no. {rang}",

    # --- Pages de rétrospective ---
    "Rétrospective {realisateur} : où voir ses films en salle — {site}":
        "{realisateur} retrospective: where to see the films — {site}",
    "Où voir les films de {realisateur} au cinéma ? {n} films à l'affiche cette semaine en {seances} séances, dans {salles} salle(s) : {villes}.":
        "Where to watch {realisateur}'s films? {n} films showing this week across "
        "{seances} screenings, in {salles} venue(s): {villes}.",
    "Rétrospective {realisateur}": "{realisateur} retrospective",
    "<strong>{n} films</strong> de {realisateur} passent cette semaine dans {salles} salle{s} ({villes}){fin} Soit {seances} séances en tout.":
        "<strong>{n} films</strong> by {realisateur} are showing this week in "
        "{salles} venue{s} ({villes}){fin} That is {seances} screenings in all.",
    "Au programme : {titres}.": "On the programme: {titres}.",
    "🎞️ Compose ta rétrospective {realisateur} →":
        "🎞️ Build your {realisateur} retrospective →",
    "← Toutes les rétrospectives en cours": "← All retrospectives running now",
    "{n} film{s} du cycle": "{n} film{s} from the season",

    # --- Index des rétrospectives ---
    "Rétrospectives et cycles au cinéma en France — {site}":
        "Retrospectives and seasons in French cinemas — {site}",
    "Quelles rétrospectives voir en salle ? {n} cycles de cinéastes programmés cette semaine en France, salle par salle : {films} films à l'affiche.":
        "Which retrospectives are running? {n} director seasons programmed in "
        "France this week, venue by venue: {films} films showing.",
    "<strong>{n} cinéastes</strong> font l'objet d'un cycle en ce moment, soit {films} films au total. On compte un cycle dès qu'une même salle passe au moins deux films du même réalisateur dans la semaine.":
        "<strong>{n} directors</strong> have a season running right now, "
        "{films} films in total. A season counts as soon as one venue shows at "
        "least two films by the same director within the week.",
    "← L'agenda du répertoire": "← The repertory diary",

    # --- Marathons ---
    "Idées de marathon cinéma : deux films à la suite — {site}":
        "Double-bill ideas: two films back to back — {site}",
    "{n} idées de marathon dans les grandes villes de France : deux films du même genre à la suite, dans la même salle ou deux salles voisines. Marathons cultes mis en avant.":
        "{n} double-bill ideas in France's biggest cities: two films of the same "
        "genre back to back, in the same venue or two neighbouring ones. Cult "
        "double bills first.",
    "Idées de marathon": "Double-bill ideas",
    "Deux films du même genre à enchaîner le même jour : soit dans <strong>deux salles voisines</strong> (le trajet à pied tient dans l'entracte), soit <strong>à la suite dans la même salle</strong>, sans bouger. Horaires et entracte calculés sur les séances réelles. Les {lien_cultes} passent en tête. Pour les {n} plus grandes villes de France.":
        "Two films of the same genre to watch back to back on the same day: either "
        "in <strong>two neighbouring venues</strong> (the walk fits in the "
        "interval), or <strong>one after the other in the same venue</strong>, "
        "without moving. Times and intervals computed from real screenings. "
        "{lien_cultes} come first. For France's {n} biggest cities.",
    "marathons de films cultes": "cult double bills",
    "🏛️ Marathons cultes": "🏛️ Cult double bills",
    "🏛️ Cultes": "🏛️ Cult",
    "Deux classiques très bien notés sur Letterboxd à enchaîner le même jour, dans la même salle ou à deux pas. Le meilleur du répertoire, d'affilée.":
        "Two highly rated Letterboxd classics to watch back to back on the same "
        "day, in the same venue or a stone's throw away. The best of repertory, "
        "in a row.",
    "Toutes les séances à {ville} →": "All screenings in {ville} →",
    "{jour}{lieu} · marathon {genre}": "{jour}{lieu} · {genre} double bill",
    "🍿 Les deux films dans la même salle, {salle} : {gap} min d'entracte, sans bouger.":
        "🍿 Both films in the same venue, {salle}: a {gap} min interval, "
        "without moving.",
    "🚶 {km} km entre les deux salles, soit ~{marche} min à pied. Il vous reste {gap} min d'entracte à la fin du premier film.":
        "🚶 {km} km between the two venues, about a {marche} min walk. That leaves "
        "you a {gap} min interval when the first film ends.",

    # --- Watchlist ---
    "Ma watchlist Letterboxd au cinéma — {site}":
        "My Letterboxd watchlist in cinemas — {site}",
    "Donne ton pseudo Letterboxd : {site} te montre lesquels de tes films à voir sont à l'affiche, et dans quels cinémas près de chez toi.":
        "Give your Letterboxd username: {site} shows which of your watchlist films "
        "are playing, and in which cinemas near you.",
    "Votre watchlist au cinéma": "Your watchlist in cinemas",
    "Mode de connexion": "Connection method",
    "Par pseudo": "By username",
    "Depuis une liste": "From a list",
    "Tu as une liste de films à voir sur": "Do you keep a watchlist on",
    "? Donne ton <strong>pseudo</strong> : {site} te dit <strong>lesquels de tes films à voir sont à l'affiche, et dans quels cinémas près de chez toi</strong>. On croise ta watchlist avec {n} films actuellement programmés en France.":
        "? Give your <strong>username</strong>: {site} tells you <strong>which of "
        "your watchlist films are showing, and in which cinemas near you</strong>. "
        "We cross your watchlist with {n} films currently playing in France.",
    "Ton pseudo Letterboxd": "Your Letterboxd username",
    "pseudo Letterboxd": "Letterboxd username",
    "Synchroniser": "Sync",
    "C'est l'identifiant de l'<strong>URL</strong> du profil, pas le nom affiché : pour <code>letterboxd.com/<b>cinephile_92</b>/</code>, tape <code>cinephile_92</code>. Les deux diffèrent souvent (à l'écran « Marie Dupont », dans l'URL <code>mariedupont__</code>). En cas de doute, ouvre le profil sur Letterboxd et recopie ce qui suit le slash.":
        "That is the handle in the profile <strong>URL</strong>, not the display "
        "name: for <code>letterboxd.com/<b>cinephile_92</b>/</code>, type "
        "<code>cinephile_92</code>. The two often differ (on screen "
        "“Marie Dupont”, in the URL <code>mariedupont__</code>). If in doubt, "
        "open the profile on Letterboxd and copy what follows the slash.",
    "On lit seulement ta watchlist <strong>publique</strong>. Rien n'est stocké côté serveur : la liste ne sert qu'à l'afficher sur ton appareil.":
        "We only read your <strong>public</strong> watchlist. Nothing is stored "
        "server-side: the list is only used to display it on your device.",
    "Watchlist privée, ou tu préfères un fichier ? Importer l'export":
        "Private watchlist, or prefer a file? Import your export",
    "Dépose le <code>watchlist.csv</code> de ton export Letterboxd : tout se passe dans le navigateur, rien n'est envoyé.":
        "Drop the <code>watchlist.csv</code> from your Letterboxd export: "
        "everything happens in the browser, nothing is sent.",
    "Choisir mon fichier watchlist.csv": "Choose my watchlist.csv file",
    "ou glissez-le dans ce cadre": "or drag it into this box",
    "ouvre les réglages, onglet <strong>Data</strong> (ou « Import &amp; Export »).":
        "open settings, <strong>Data</strong> tab (or “Import &amp; Export”).",
    "Sur": "On",
    "Clique sur <strong>Export your data</strong>. Un fichier <code>.zip</code> se télécharge.":
        "Click <strong>Export your data</strong>. A <code>.zip</code> file "
        "downloads.",
    "Décompresse-le et dépose le fichier <code>watchlist.csv</code> ci-dessus.":
        "Unzip it and drop the <code>watchlist.csv</code> file above.",
    "Une <strong>liste</strong> Letterboxd publique (« 1001 films à voir », Palme d'or, tes classiques…) ? Colle son URL : {site} te montre <strong>lesquels de ces films de patrimoine repassent en salle</strong>, ville par ville, avec la séance et la réservation.":
        "A public Letterboxd <strong>list</strong> (“1001 Movies to See”, Palme "
        "d'Or winners, your own classics…)? Paste its URL: {site} shows you "
        "<strong>which of those heritage films are back in cinemas</strong>, city "
        "by city, with the screening and the booking link.",
    "URL de la liste Letterboxd": "Letterboxd list URL",
    "Chercher les séances": "Find screenings",
    "On lit seulement une liste <strong>publique</strong>. Rien n'est stocké côté serveur, et ta géolocalisation (pour trier par proximité) reste sur ton appareil.":
        "We only read a <strong>public</strong> list. Nothing is stored "
        "server-side, and your location (used to sort by distance) stays on your "
        "device.",

    # --- Cinémathèque ---
    "Ta cinémathèque : compose ta rétrospective — {site}":
        "Your film club: build your own retrospective — {site}",
    "Choisis un réalisateur : {site} réunit toutes ses séances de répertoire à l'affiche en France en une rétrospective personnelle, à ajouter à ton agenda.":
        "Pick a director: {site} gathers all their repertory screenings across "
        "France into a personal retrospective, ready to add to your calendar.",
    "Ta cinémathèque": "Your film club",
    "6 films de répertoire sur 10 ne passent qu'une seule fois en France sur une semaine. Au lieu de subir cet éparpillement, compose-le : choisis un réalisateur, {site} réunit <strong>toutes ses séances du pays</strong> en une rétrospective à toi, à mettre dans ton agenda.":
        "6 repertory films out of 10 play only once in the whole of France in a "
        "given week. Instead of putting up with that scattering, shape it: pick a "
        "director and {site} gathers <strong>every screening in the "
        "country</strong> into a retrospective of your own, ready for your "
        "calendar.",
    "Choisis un réalisateur ({n} ont au moins deux films à l'affiche)":
        "Pick a director ({n} have at least two films showing)",
    "Choisis un réalisateur": "Pick a director",
    "ex. Akira Kurosawa": "e.g. Akira Kurosawa",
    "Assembler": "Build it",
    "Les plus programmés en ce moment": "Most programmed right now",

    # --- Alertes ---
    "Mes alertes — {site}": "My alerts — {site}",
    "Les films que tu suis : {site} te prévient quand ils repassent dans ta ville.":
        "The films you follow: {site} lets you know when they come back to "
        "your city.",
    "Mes alertes": "My alerts",
    "Sur la fiche d'un film, le bouton « Préviens-moi quand il repasse » te prévient dès qu'une séance est programmée dans ta ville. Les reprises ne s'annoncent pas : 6 films de répertoire sur 10 ne passent qu'une seule fois en France sur une semaine.":
        "On a film's page, the “Notify me when it returns” button alerts you as "
        "soon as a screening is programmed in your city. Revivals get no fanfare: "
        "6 repertory films out of 10 play only once in France in a given week.",
    "Rien n'est envoyé à personne : ton navigateur reçoit la notification directement, et tu peux retirer une alerte à tout moment.":
        "Nothing is sent to anyone: your browser receives the notification "
        "directly, and you can remove an alert at any time.",

    # --- Carte ---
    "Carte des cinémas en France — {site}": "Map of cinemas in France — {site}",
    "Carte interactive de {n} cinémas en France. « Autour de moi » vous montre les salles les plus proches et lesquelles programment du répertoire cette semaine.":
        "Interactive map of {n} cinemas across France. “Near me” shows the "
        "closest venues and which of them are showing repertory this week.",
    "Carte des cinémas": "Map of cinemas",
    "{n} cinémas situés sur la carte, dont {r} programment du répertoire cette semaine. Trouvez une salle près de chez vous et ouvrez son programme.":
        "{n} cinemas placed on the map, {r} of which are showing repertory this "
        "week. Find a venue near you and open its programme.",
    "Salles de répertoire seulement": "Repertory venues only",
    "Grande enseigne": "Major chain",

    # --- 404 ---
    "Page introuvable — {site}": "Page not found — {site}",
    "Cette page n'existe pas ou plus.": "This page does not exist, or no longer does.",
    "Oups, séance introuvable": "Oops, screening not found",
    "Cette adresse ne mène à aucune page. Le programme change tous les jours, et la fiche d'un film disparaît quand il quitte l'affiche.":
        "This address leads nowhere. The programme changes every day, and a film's "
        "page disappears when it stops showing.",
    "← Le répertoire": "← The repertory",

    # --- Manifeste ---
    "{site}, le répertoire en salle": "{site}, repertory cinema listings",
    "Les reprises, classiques et rétrospectives à l'affiche partout en France.":
        "Revivals, classics and retrospectives showing all across France.",
}


# --- Contrôle --------------------------------------------------------------

def report_missing() -> list[str]:
    """Chaînes demandées pendant le build sans traduction anglaise."""
    return sorted(MISSING)


def _audit() -> int:
    """`python scripts/i18n.py` : signale les entrées douteuses du dictionnaire.

    Ne remplace pas une relecture, mais attrape les deux erreurs mécaniques
    qu'on ne voit pas à l'œil : une traduction qui INVENTE une variable, et une
    entrée restée identique au français.

    Une traduction qui LAISSE TOMBER une variable n'est pas une erreur : le
    français accorde parfois deux mots (« {n} autre{s} film{s2} ») là où
    l'anglais n'en accorde qu'un. `str.format()` ignore les arguments en trop,
    ces entrées fonctionnent telles quelles.
    """
    champs = re.compile(r"\{(\w+)\}")
    souci = 0
    for fr, en in EN.items():
        inventees = set(champs.findall(en)) - set(champs.findall(fr))
        if inventees:
            print(f"VARIABLE INCONNUE  {inventees} : {fr[:70]}")
            souci += 1
        if fr == en and len(fr) > 12:
            print(f"IDENTIQUE  {fr[:70]}")
            souci += 1
    print(f"{len(EN)} entrées, {souci} à vérifier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_audit())
