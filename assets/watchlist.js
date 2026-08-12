/* Repli « importer le fichier » de /ma-watchlist/, pour les watchlists privées.

   Tout se passe DANS LE NAVIGATEUR : le fichier déposé n'est jamais envoyé.
   Ce fichier ne fait que DEUX choses : lire le CSV d'export Letterboxd
   (colonnes Date, Name, Year, Letterboxd URI) et le remettre à `LB.render`
   (assets/letterboxd.js) sous la même forme qu'une réponse du Worker. Le
   croisement, le cadrage par ville et le rendu des cartes sont donc exactement
   ceux du chemin « par pseudo » — les deux entrées de la page avaient divergé
   par le passé, on ne duplique plus rien.

   Le CSV ne donne pas de slug Letterboxd, seulement un « Name » ; `LB.cross`
   retombe alors sur l'empreinte du titre (+ année). Comme le slug et le « Name »
   dérivent du même titre principal, « Shoplifters » retrouve notre « Une Affaire
   de famille » : le matching traverse les langues sans dépendre du titre
   français. Le lien court `boxd.it` du CSV, lui, est inutilisable côté client
   (résolution bloquée par CORS). */
(function () {
  "use strict";
  var drop = document.getElementById("wl-drop");
  var input = document.getElementById("wl-file");
  var pick = document.getElementById("wl-pick");
  var results = document.getElementById("wl-results");
  if (!drop || !input || !pick || !results || !window.LB) return;

  var index = null;
  var agenda = null;

  /* Parseur CSV minimal mais correct : gère les champs entre guillemets
     (un titre peut contenir une virgule) et les guillemets doublés (""). */
  function parseCSV(texte) {
    var lignes = [], champ = "", ligne = [], dansGuillemets = false;
    texte = texte.replace(/\r\n?/g, "\n");
    for (var i = 0; i < texte.length; i++) {
      var ch = texte[i];
      if (dansGuillemets) {
        if (ch === '"') {
          if (texte[i + 1] === '"') { champ += '"'; i++; }
          else dansGuillemets = false;
        } else champ += ch;
      } else if (ch === '"') dansGuillemets = true;
      else if (ch === ",") { ligne.push(champ); champ = ""; }
      else if (ch === "\n") { ligne.push(champ); lignes.push(ligne); ligne = []; champ = ""; }
      else champ += ch;
    }
    if (champ !== "" || ligne.length) { ligne.push(champ); lignes.push(ligne); }
    return lignes;
  }

  // Le rendu est celui du chemin « par pseudo » : LB.render, dans letterboxd.js,
  // chargé avant ce fichier. Il apporte gratuitement le cadrage sur la ville,
  // la section « ville la plus proche » et les cartes avec salle/ville/heure.
  // Sans ça les deux entrées de la page divergeaient — c'est déjà arrivé.
  // On habille le résultat du CSV comme une réponse du Worker : seul `films`
  // change de forme (le CSV n'a ni favoris ni notion de watchlist privée).
  function rendu(films, total) {
    // `films` a la forme que LB.cross attend ({ slug, name, year }) : le CSV n'a
    // pas de slug, mais cross retombe sur l'empreinte du titre (+ année), ce que
    // faisait déjà ce fichier de son côté. On lui laisse donc aussi le matching.
    LB.render(results, { films: films, favorites: [], total: total, empty: !total },
              index, agenda, LB.city());
  }

  function erreur(msg) {
    results.innerHTML = '<p class="wl-erreur"></p>';
    results.querySelector(".wl-erreur").textContent = msg;
  }

  function croiser(texte) {
    var lignes = parseCSV(texte);
    if (!lignes.length) { erreur(T("Ce fichier est vide.")); return; }
    // Repérer les colonnes par leur en-tête (Letterboxd les nomme en anglais).
    var head = lignes[0].map(function (h) { return h.trim().toLowerCase(); });
    var iName = head.indexOf("name"), iYear = head.indexOf("year");
    if (iName < 0) {
      erreur("Ce fichier ne ressemble pas à un export Letterboxd (colonne « Name » "
        + "introuvable). Déposez le fichier watchlist.csv de votre export.");
      return;
    }
    var films = [];
    for (var i = 1; i < lignes.length; i++) {
      var nom = (lignes[i][iName] || "").trim();
      if (!nom) continue;
      films.push({ slug: "", name: nom,
                   year: iYear >= 0 ? (lignes[i][iYear] || "").trim() : "" });
    }
    rendu(films, films.length);
  }

  function traiter(file) {
    if (!file) return;
    if (!/\.csv$/i.test(file.name)) {
      erreur("Déposez un fichier .csv (celui de votre export Letterboxd).");
      return;
    }
    results.innerHTML = '<p class="wl-summary">Lecture de votre liste…</p>';
    var lire = function () {
      var fr = new FileReader();
      fr.onload = function () { croiser(String(fr.result)); };
      fr.onerror = function () { erreur(T("Impossible de lire ce fichier.")); };
      fr.readAsText(file);
    };
    if (index) { lire(); return; }
    // Les index ne sont chargés qu'ici, à la première utilisation réelle.
    // L'agenda est un bonus (heure exacte + billetterie) : LB.loadAgenda absorbe
    // son échec, seul l'index principal peut faire échouer le croisement.
    Promise.all([
      fetch(drop.dataset.index).then(function (r) { return r.json(); }),
      window.LB.loadAgenda(drop.dataset.agenda)
    ])
      .then(function (both) { index = both[0]; agenda = both[1]; lire(); })
      .catch(function () { erreur("Chargement de l'index impossible. Réessayez."); });
  }

  pick.addEventListener("click", function () { input.click(); });
  input.addEventListener("change", function () { traiter(input.files[0]); });

  // Glisser-déposer sur le cadre.
  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault(); drop.classList.add("wl-over");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault(); drop.classList.remove("wl-over");
    });
  });
  drop.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files[0]) traiter(e.dataTransfer.files[0]);
  });
})();
