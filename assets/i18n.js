/* Séancéo — dictionnaire de traduction des scripts (français → anglais).
   =====================================================================

   CHARGÉ SUR LES SEULES PAGES ANGLAISES. Une page française ne télécharge pas
   un octet de ce fichier : `T()` y vaut l'identité, puisqu'il n'existe alors
   aucun `window.I18N` à consulter (voir T_HELPER dans scripts/build_site.py).

   La CLÉ est la phrase française elle-même, exactement comme côté Python
   (scripts/i18n.py) et pour les mêmes raisons : une clé absente rend du
   français correct plutôt qu'un identifiant technique, et le comportement de
   la version française reste rigoureusement inchangé.

   `defer` sur la balise : ce fichier s'exécute donc AVANT les scripts qui
   l'utilisent (les scripts différés s'exécutent dans l'ordre du document), et
   `window.I18N` est en place quand le premier `T()` est appelé.

   Les variables entre accolades sont interpolées par `TF()` : elles doivent
   apparaître à l'identique des deux côtés (une variable inventée resterait
   affichée telle quelle). Une variable en MOINS est licite — le français
   accorde parfois deux mots là où l'anglais n'en accorde qu'un.

   ⚠️ ACCORD DU VERBE. Le français fait varier « est / sont », « passe /
   passent », « repasse / repassent » ; l'anglais ne bouge pas. Ces verbes
   circulent donc en variable `{verbe}`, et leurs deux formes françaises se
   traduisent toutes deux par la même forme anglaise, plus bas. */
window.I18N = {
  /* —— Dates et heures ———————————————————————————————————————————————————— */
  "aujourd'hui": "today",
  "demain": "tomorrow",
  "{jour} à {heure}": "{jour} at {heure}",
  "à {heure}": "at {heure}",
  "prochaine séance {jour}": "next screening {jour}",
  "prochaine séance {jour} à {heure}": "next screening {jour} at {heure}",

  /* —— Accords : formes verbales portées par {verbe} ————————————————————— */
  "est": "is",
  "sont": "are",
  "passe": "is playing",
  "passent": "are playing",
  "repasse": "is back",
  "repassent": "are back",

  /* —— Versions de projection ———————————————————————————————————————————— */
  "VF": "French dub",
  "VO / VOST": "Original / subtitled",

  /* —— Tri et filtres (tri.js, ville.js) ————————————————————————————————— */
  "Aucun film ne correspond à ces filtres": "No film matches these filters",
  "{n} film{s}": "{n} film{s}",
  "{n} affichés": "{n} shown",
  "Afficher {n} films de plus": "Show {n} more films",
  "Cliquer pour inverser l'ordre": "Click to reverse the order",
  "Trier par {critere}": "Sort by {critere}",
  "{n} film{s} en {version}": "{n} film{s} in {version}",

  /* —— Recherche (search.js) ————————————————————————————————————————————— */
  "Aucun film à l'affiche pour « {requete} »": "No film showing for “{requete}”",

  /* —— Carte (map.js) ———————————————————————————————————————————————————— */
  "{n} séance{s} de répertoire cette semaine":
    "{n} repertory screening{s} this week",
  "Cinéma indépendant": "Independent cinema",
  "indépendant": "independent",
  "Voir le programme →": "See the programme →",
  "Salles de répertoire les plus proches": "Nearest repertory venues",
  "Cinémas les plus proches": "Nearest cinemas",
  "Aucune salle ne correspond. Décochez le filtre pour voir tous les cinémas.":
    "No venue matches. Uncheck the filter to see every cinema.",
  "Vous êtes ici": "You are here",
  "Accès à la position refusé. Autorisez la géolocalisation pour voir les salles autour de vous.":
    "Location access denied. Allow location to see the venues around you.",

  /* —— Autour de moi, accueil (proximite.js) ————————————————————————————— */
  "{n} film{s} de répertoire": "{n} repertory film{s}",
  "Les villes les plus proches de vous :": "The cities closest to you:",
  "Votre navigateur ne permet pas la géolocalisation.":
    "Your browser does not support location.",
  "Recherche de votre position…": "Finding your location…",
  "Accès à la position refusé. Autorisez la géolocalisation pour voir les villes autour de vous.":
    "Location access denied. Allow location to see the cities around you.",
  "Position indisponible pour l'instant. Réessayez dans un moment.":
    "Location unavailable right now. Try again in a moment.",

  /* —— Import de fichier (watchlist.js) —————————————————————————————————— */
  "Ce fichier est vide.": "This file is empty.",
  "Impossible de lire ce fichier.": "This file could not be read.",

  /* —— Cartes de séance (letterboxd.js, lb-*.js, cinematheque.js) ———————— */
  "Réserver ↗": "Book ↗",
  "Séance unique en France": "One-off screening in France",
  "{n} autre{s} cinéma{s2}": "{n} more cinema{s2}",
  "et {n} autre{s} ville{s2}": "and {n} more city{s2}",
  "+{n} autre{s} séance{s2}": "+{n} more screening{s2}",
  "à ~{km} km": "about {km} km away",

  /* —— Watchlist : rendu principal (letterboxd.js) ——————————————————————— */
  "Tes films préférés à revoir en salle": "Your favourite films, back on screen",
  "Un de tes films préférés à revoir en salle":
    "One of your favourite films is back on screen",
  "{n} de tes films préférés repassent": "{n} of your favourite films are back",
  "Un de tes films préférés repasse": "One of your favourite films is back",
  "en ce moment. L'occasion de le revoir sur grand écran.":
    "right now. A chance to see it on the big screen again.",
  "Aucun des {total} films de ta watchlist Letterboxd n'est à l'affiche pour l'instant. La programmation change souvent, reviens y jeter un œil.":
    "None of the {total} films on your Letterboxd watchlist is showing right now. "
    + "Programmes change often — come back and take another look.",
  "<strong>{n}</strong> des {total} films de ta watchlist Letterboxd {verbe} à l'affiche. Ouvre une fiche pour voir toutes les séances près de chez toi.":
    "<strong>{n}</strong> of the {total} films on your Letterboxd watchlist {verbe} "
    + "showing. Open a film's page to see every screening near you.",
  "<strong>{n}</strong> des {total} films de ta watchlist Letterboxd {verbe} à l'affiche en France.":
    "<strong>{n}</strong> of the {total} films on your Letterboxd watchlist {verbe} "
    + "showing across France.",
  "🎬 À {ville}": "🎬 In {ville}",
  "{n} film{s} de ta watchlist {verbe} près de chez toi.":
    "{n} film{s} from your watchlist {verbe} near you.",
  "Rien de ta watchlist à {ville} pour l'instant":
    "Nothing from your watchlist in {ville} right now",
  "Rien à {ville} pour l'instant": "Nothing in {ville} right now",
  "En revanche,": "On the other hand,",
  "{n} de tes films préférés y repassent":
    "{n} of your favourite films are back there",
  "un de tes films préférés y repasse": "one of your favourite films is back there",
  ", juste en dessous.": " — just below.",
  "La ville la plus proche où un film de ta watchlist repasse est {ville}, à environ {km} km.":
    "The nearest city where a film from your watchlist is playing is {ville}, "
    + "about {km} km away.",
  "Aucun film de ta watchlist ne repasse à proximité. Voici ce qui passe ailleurs en France.":
    "No film from your watchlist is playing nearby. Here is what is on elsewhere "
    + "in France.",
  "Ailleurs en France": "Elsewhere in France",
  "{n} autre{s} film{s2} de ta watchlist {verbe} hors {ville}.":
    "{n} more film{s2} from your watchlist {verbe} outside {ville}.",
  "La watchlist de <b class=\"lb-who\"></b> est <strong>privée</strong>, on ne peut pas la lire. Rends-la publique dans les réglages Letterboxd, ou importe ton fichier ci-dessous.":
    "<b class=\"lb-who\"></b>'s watchlist is <strong>private</strong>, so we cannot "
    + "read it. Make it public in your Letterboxd settings, or import your file below.",
  "La watchlist de <b class=\"lb-who\"></b> est vide pour l'instant. Ajoute des films à voir sur Letterboxd, puis resynchronise. Si tu t'attendais à y trouver des films, vérifie le pseudo : c'est celui de l'URL du profil (<code>letterboxd.com/<b class=\"lb-eg\">cinephile_92</b>/</code>), pas le nom affiché.":
    "<b class=\"lb-who\"></b>'s watchlist is empty for now. Add films to watch on "
    + "Letterboxd, then sync again. If you expected to find films there, check the "
    + "username: it is the one in the profile URL "
    + "(<code>letterboxd.com/<b class=\"lb-eg\">cinephile_92</b>/</code>), not the "
    + "display name.",

  /* —— Portail Letterboxd (letterboxd.js) ———————————————————————————————— */
  "C'est l'identifiant de l'<strong>URL</strong> du profil, pas le nom affiché : pour <code>letterboxd.com/<b>cinephile_92</b>/</code>, tape <code>cinephile_92</code>. Les deux diffèrent souvent (à l'écran « Marie Dupont », dans l'URL <code>mariedupont__</code>).":
    "That is the handle in the profile <strong>URL</strong>, not the display name: "
    + "for <code>letterboxd.com/<b>cinephile_92</b>/</code>, type "
    + "<code>cinephile_92</code>. The two often differ (on screen “Marie Dupont”, "
    + "in the URL <code>mariedupont__</code>).",
  "Chercher ta ville…": "Search your city…",
  "Fermer": "Close",
  "Entre ton pseudo Letterboxd : on te montre lesquels de tes films à voir repassent au cinéma, et on te recommande des reprises selon tes <strong>réalisateurs préférés</strong>.":
    "Enter your Letterboxd username: we show you which of your watchlist films are "
    + "back in cinemas, and recommend revivals based on your <strong>favourite "
    + "directors</strong>.",
  "pseudo Letterboxd": "Letterboxd username",
  "Ton pseudo Letterboxd": "Your Letterboxd username",
  "Synchroniser": "Sync",
  "Continuer sans compte": "Continue without an account",
  "Watchlist privée ? Importer un fichier": "Private watchlist? Import a file",
  "On lit seulement ta watchlist <strong>publique</strong>. Rien n'est stocké côté serveur.":
    "We only read your <strong>public</strong> watchlist. Nothing is stored "
    + "server-side.",
  "Lecture de ta watchlist…": "Reading your watchlist…",
  "Dans quelle <strong>ville</strong> cherches-tu ? On te montrera d'abord ce qui passe près de chez toi, plutôt que partout en France.":
    "Which <strong>city</strong> are you looking in? We will show what is on near "
    + "you first, rather than everywhere in France.",
  "Ta ville": "Your city",
  "Continuer": "Continue",
  "📍 me localiser": "📍 locate me",
  "Voir toute la France": "See all of France",
  "✅ Salut {pseudo} !": "✅ Hi {pseudo}!",
  "{n} film{s} de ta watchlist {verbe} à l'affiche en France":
    "{n} film{s} from your watchlist {verbe} showing in France",
  "{n} film{s} de ta watchlist {verbe} à l'affiche":
    "{n} film{s} from your watchlist {verbe} showing",
  "{n} de tes films préférés à revoir": "{n} of your favourite films to see again",
  "On ne programme rien à « {ville} » pour l'instant. Essaie la grande ville la plus proche, ou passe cette étape.":
    "Nothing is programmed in “{ville}” right now. Try the nearest large city, "
    + "or skip this step.",
  "Géolocalisation indisponible sur ce navigateur.":
    "Location is unavailable in this browser.",
  "…localisation": "…locating",
  "Impossible de déterminer ta ville.": "Your city could not be determined.",
  "Ville la plus proche : {ville} (à ~{km} km).":
    "Nearest city: {ville} (about {km} km away).",
  "Localisation refusée. Tape ta ville à la main.":
    "Location denied. Type your city instead.",
  "Voir les séances →": "See showtimes →",
  "Ouvrir ma watchlist →": "Open my watchlist →",
  "{n} film{s} de ta watchlist {verbe} à {ville}":
    "{n} film{s} from your watchlist {verbe} in {ville}",
  "(et {n} ailleurs en France).": "(and {n} elsewhere in France).",
  "Rien à {ville} pour l'instant. Le plus proche est à {proche}, à environ {km} km.":
    "Nothing in {ville} right now. The nearest is in {proche}, about {km} km away.",
  "Rien à {ville} pour l'instant, mais {n} film{s} {verbe} à l'affiche ailleurs en France.":
    "Nothing in {ville} right now, but {n} film{s} {verbe} showing elsewhere "
    + "in France.",
  "Ta watchlist est privée : on ne peut pas la lire. Rends-la publique, ou importe ton fichier.":
    "Your watchlist is private, so we cannot read it. Make it public, or import "
    + "your file.",
  "Rien de ta liste n'est à l'affiche pour l'instant, mais on la garde.":
    "Nothing from your list is showing right now, but we are keeping it.",
  "Ce pseudo n'a pas l'air valide (lettres, chiffres, - et _).":
    "That username does not look valid (letters, digits, - and _).",
  "Pseudo introuvable sur Letterboxd. Vérifie l'orthographe.":
    "Username not found on Letterboxd. Check the spelling.",
  "Impossible de lire cette watchlist pour l'instant. Réessaie, ou importe ton fichier.":
    "This watchlist cannot be read right now. Try again, or import your file.",

  /* —— Page watchlist : calendrier et cadrage (lb-watchlist.js) —————————— */
  "📆 Ne rate plus une reprise": "📆 Never miss a revival again",
  "Ajoute tes reprises à ton agenda : chaque nouvelle séance d'un film de ta watchlist (ou de tes favoris) apparaît toute seule, avec un rappel.":
    "Add revivals to your calendar: every new screening of a film on your watchlist "
    + "(or among your favourites) appears on its own, with a reminder.",
  "Ajouter à Google Agenda": "Add to Google Calendar",
  "📍 seulement près de moi": "📍 near me only",
  "Autre agenda (Apple, Outlook…) :": "Another calendar (Apple, Outlook…):",
  "Lien du calendrier": "Calendar link",
  "Copier": "Copy",
  "Copié ✓": "Copied ✓",
  "Calendrier limité à environ 30 km autour de toi.":
    "Calendar limited to about 30 km around you.",
  "Calendrier national (toutes les reprises de ta watchlist en France).":
    "Nationwide calendar (every revival from your watchlist in France).",
  "🌍 revenir au national": "🌍 back to nationwide",
  "Localisation refusée : calendrier national conservé.":
    "Location denied: keeping the nationwide calendar.",
  "Chargement de l'index impossible. Réessaie.":
    "The index could not be loaded. Try again.",
  "Résultats cadrés sur": "Results focused on",
  "Changer de ville": "Change city",
  "Toute la France": "All of France",
  "📍 Dans quelle ville cherches-tu ?": "📍 Which city are you looking in?",
  "Cadrer": "Focus",
  "Annuler": "Cancel",
  "Géolocalisation indisponible.": "Location unavailable.",
  "Ville introuvable.": "City not found.",
  "Ville la plus proche : {ville} (~{km} km).": "Nearest city: {ville} (~{km} km).",
  "Localisation refusée. Tape ta ville.": "Location denied. Type your city.",
  "On ne programme rien à « {ville} » pour l'instant.":
    "Nothing is programmed in “{ville}” right now.",
  "Connecté : {pseudo}": "Signed in as {pseudo}",
  "Resynchroniser": "Sync again",
  "Changer de pseudo": "Change username",
  "Lecture de la watchlist de {pseudo}…": "Reading {pseudo}'s watchlist…",

  /* —— Listes Letterboxd (lb-listes.js) —————————————————————————————————— */
  "<strong>{n}</strong> film{s} de cette liste {verbe} en salle{cadre}.":
    "<strong>{n}</strong> film{s} from this list {verbe} in cinemas{cadre}.",
  " dans cette ville": " in this city",
  ", du plus proche au plus loin": ", from nearest to furthest",
  "Ville": "City",
  "Toutes les villes ({n})": "All cities ({n})",
  "📍 autour de moi": "📍 near me",
  "Géolocalisation indisponible": "Location unavailable",
  "Colle l'URL complète de la liste (letterboxd.com/…/list/…), pas le lien court boxd.it.":
    "Paste the full list URL (letterboxd.com/…/list/…), not the short boxd.it link.",
  "Ce lien n'a pas l'air d'être une liste Letterboxd. Exemple : letterboxd.com/pseudo/list/ma-liste/":
    "That link does not look like a Letterboxd list. Example: "
    + "letterboxd.com/username/list/my-list/",
  "Lecture de la liste…": "Reading the list…",
  "Cette liste": "This list",
  "{liste} — {total} films dans la liste, {trouves} repassent en salle.":
    "{liste} — {total} films in the list, {trouves} back in cinemas.",

  /* —— Recommandations (lb-reco.js) —————————————————————————————————————— */
  "Parce que tu aimes {realisateur}": "Because you like {realisateur}",
  "Repéré via {films} dans tes listes.": "Spotted via {films} in your lists.",
  "✨ Pour toi, {pseudo}": "✨ For you, {pseudo}",
  "D'après ta watchlist et tes favoris Letterboxd : le répertoire à l'affiche signé par tes réalisateurs préférés.":
    "Based on your Letterboxd watchlist and favourites: repertory screenings by "
    + "your favourite directors.",

  /* —— Ta cinémathèque (cinematheque.js) ————————————————————————————————— */
  "Aucune séance dans cette ville. Choisis une autre ville.":
    "No screening in this city. Pick another one.",
  "Tu peux voir <b>{n}</b> film{s} de {realisateur} sur grand écran d'ici le <b>{date}</b>, dans <b>{villes}</b> ville{s2}.":
    "You can see <b>{n}</b> film{s} by {realisateur} on the big screen before "
    + "<b>{date}</b>, across <b>{villes}</b> city{s2}.",
  "{n} sont groupables à {ville}.": "{n} of them can be grouped in {ville}.",
  "Ordre": "Order",
  "Chronologique": "Chronological",
  "Par note": "By rating",
  "Où": "Where",
  "＋ Ajouter ces {n} séances à mon agenda":
    "＋ Add these {n} screenings to my calendar",
  "Un fichier .ics à ouvrir dans Google Agenda, Apple Calendrier ou Outlook. Chaque séance devient un événement daté, avec le cinéma et le lien de réservation.":
    "An .ics file to open in Google Calendar, Apple Calendar or Outlook. Each "
    + "screening becomes a dated event, with the cinema and the booking link.",
  "Cinémathèque {realisateur}": "{realisateur} season",
  "Réserver :": "Book:",
  "Fiche :": "Details:",

  // --- Dernière chance (chance.js) ---
  "{n} séance{s} à {ville}": "{n} screening{s} in {ville}",
  "{n} séances en France": "{n} screenings in France",
  "Dernière chance à {ville}": "Last chance in {ville}",
  "Dernière chance en France": "Last chance in France",
  "Ce réalisateur n'a pas (ou plus) au moins deux films de répertoire à l'affiche. Choisis-en un dans la liste.":
    "This director does not (or no longer) has at least two repertory films "
    + "showing. Pick one from the list.",
  "Rétrospective {realisateur} — {n} films de répertoire à l'affiche.":
    "{realisateur} retrospective — {n} repertory films showing.",
  "Chargement impossible. Réessaie.": "Loading failed. Try again.",

  /* —— Alertes (alertes.js) —————————————————————————————————————————————— */
  "<strong>Être prévenu quand ce film repasse</strong><br>Sur iPhone, les notifications demandent d'ajouter Séancéo à ton écran d'accueil : touche <strong>Partager</strong> en bas de Safari, puis <strong>« Sur l'écran d'accueil »</strong>. Rouvre ensuite cette page depuis l'icône.":
    "<strong>Get notified when this film returns</strong><br>On iPhone, "
    + "notifications require adding Séancéo to your home screen: tap "
    + "<strong>Share</strong> at the bottom of Safari, then <strong>“Add to Home "
    + "Screen”</strong>. Then reopen this page from the icon.",
  "🔔 Préviens-moi quand il repasse à {ville}":
    "🔔 Notify me when it returns to {ville}",
  "🔔 Préviens-moi quand il repasse": "🔔 Notify me when it returns",
  "Dans quelle ville veux-tu être prévenu ?":
    "Which city do you want to be notified about?",
  "Valider": "Confirm",
  "Ta ville…": "Your city…",
  "Tu as refusé les notifications. Réactive-les dans les réglages du navigateur pour ce site.":
    "You declined notifications. Re-enable them in your browser settings for "
    + "this site.",
  "L'alerte n'a pas pu être enregistrée. Réessaie plus tard.":
    "The alert could not be saved. Try again later.",
  "Il y est déjà à l'affiche ({n} salles).":
    "It is already showing there ({n} venues).",
  "Il y est déjà à l'affiche.": "It is already showing there.",
  "🔔 Tu seras prévenu quand ce film repassera à {ville}.":
    "🔔 You will be notified when this film returns to {ville}.",
  "Ne plus me prévenir": "Stop notifying me",
  "Mes alertes": "My alerts",
  "Ce navigateur ne peut pas recevoir de notifications":
    "This browser cannot receive notifications",
  "tant que Séancéo n'est pas ajouté à ton écran d'accueil.":
    "until Séancéo is added to your home screen.",
  "Chargement…": "Loading…",
  "Tu ne suis aucun film pour le moment. Sur la fiche d'un film, le bouton « Préviens-moi quand il repasse » te préviendra dès qu'une séance est programmée dans ta ville.":
    "You are not following any film yet. On a film's page, the “Notify me when it "
    + "returns” button will alert you as soon as a screening is programmed in "
    + "your city.",
  "La liste n'a pas pu être chargée. Réessaie plus tard.":
    "The list could not be loaded. Try again later.",
  "Tu ne suis aucun film pour le moment.": "You are not following any film yet.",
  "à {ville}": "in {ville}",
  "retirer": "remove",
};
