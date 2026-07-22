/* Croisement de la watchlist Letterboxd avec les séances de la semaine.

   Tout se passe DANS LE NAVIGATEUR : le fichier déposé n'est jamais envoyé.
   On lit le CSV d'export Letterboxd (colonnes Date, Name, Year, Letterboxd
   URI), et pour chaque film on calcule l'empreinte de son titre — la même
   normalisation que `lb_slug_key()` côté build — pour la chercher dans
   l'index. Comme le slug Letterboxd et le « Name » du CSV viennent du même
   titre principal, « Shoplifters » retombe sur notre « Une Affaire de
   famille » : le matching traverse les langues sans dépendre du titre français. */
(function () {
  "use strict";
  var drop = document.getElementById("wl-drop");
  var input = document.getElementById("wl-file");
  var pick = document.getElementById("wl-pick");
  var results = document.getElementById("wl-results");
  if (!drop || !input || !pick || !results) return;

  var index = null;

  // MÊME normalisation que lb_slug_key() en Python : NFKD, on retire tout
  // caractère non-ASCII (équivalent de encode("ascii","ignore")), puis on ne
  // garde que les lettres/chiffres, collés et en minuscules.
  function empreinte(s) {
    return (s || "").normalize("NFKD")
      .replace(/[^\x00-\x7F]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

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

  function frDate(iso) {
    var jours = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
    var mois = ["janv.", "févr.", "mars", "avril", "mai", "juin", "juil.",
                "août", "sept.", "oct.", "nov.", "déc."];
    var d = new Date(iso + "T00:00:00");
    var auj = new Date(); auj.setHours(0, 0, 0, 0);
    var delta = Math.round((d - auj) / 86400000);
    if (delta <= 0) return "aujourd'hui";
    if (delta === 1) return "demain";
    return jours[d.getDay()] + " " + d.getDate() + " " + mois[d.getMonth()];
  }

  function carte(f) {
    var art = document.createElement("article");
    art.className = "movie-card";
    var lien = f.u;
    var poster = f.p
      ? '<a href="' + lien + '"><img src="' + f.p + '" alt="" loading="lazy"></a>'
      : '<a href="' + lien + '"><span class="noposter">🎞️</span></a>';
    var note = f.r ? '<span class="note-lb">' + f.r + '<span class="sur">/5</span></span> · ' : "";
    var salles = f.n + (f.n > 1 ? " cinémas" : " cinéma");
    // innerHTML ne reçoit que des valeurs de NOTRE index (jamais le CSV) :
    // titres, posters et notes viennent du build, pas du fichier déposé.
    art.innerHTML =
      poster +
      '<div class="movie-info">' +
      '<h3><a href="' + lien + '"></a></h3>' +
      '<p class="meta">' + note + salles + ' · prochaine séance ' + frDate(f.d) + '</p>' +
      "</div>";
    // Le titre en textContent : ceinture et bretelles, même s'il vient de nous.
    art.querySelector("h3 a").textContent = f.t;
    return art;
  }

  function rendu(trouves, total) {
    results.textContent = "";
    var titre = document.createElement("p");
    titre.className = "wl-summary";
    if (!trouves.length) {
      titre.textContent = "Aucun de vos " + total + " films à voir n'est à l'affiche pour "
        + "l'instant. La programmation change souvent, revenez y jeter un œil.";
      results.appendChild(titre);
      return;
    }
    titre.innerHTML = "<strong>" + trouves.length + "</strong> de vos " + total
      + " films à voir " + (trouves.length > 1 ? "sont" : "est")
      + " à l'affiche. Ouvrez une fiche pour voir les séances près de chez vous.";
    results.appendChild(titre);
    // Les séances les plus proches d'abord (c'est ce qu'on peut voir bientôt),
    // les mieux notées départageant à date égale.
    trouves.sort(function (a, b) {
      return a.d < b.d ? -1 : a.d > b.d ? 1 : (b.r - a.r);
    });
    var grille = document.createElement("div");
    grille.className = "grid";
    trouves.forEach(function (f) { grille.appendChild(carte(f)); });
    results.appendChild(grille);
  }

  function erreur(msg) {
    results.innerHTML = '<p class="wl-erreur"></p>';
    results.querySelector(".wl-erreur").textContent = msg;
  }

  function croiser(texte) {
    var lignes = parseCSV(texte);
    if (!lignes.length) { erreur("Ce fichier est vide."); return; }
    // Repérer les colonnes par leur en-tête (Letterboxd les nomme en anglais).
    var head = lignes[0].map(function (h) { return h.trim().toLowerCase(); });
    var iName = head.indexOf("name"), iYear = head.indexOf("year");
    if (iName < 0) {
      erreur("Ce fichier ne ressemble pas à un export Letterboxd (colonne « Name » "
        + "introuvable). Déposez le fichier watchlist.csv de votre export.");
      return;
    }
    var trouves = [], vus = {}, total = 0;
    for (var i = 1; i < lignes.length; i++) {
      var nom = (lignes[i][iName] || "").trim();
      if (!nom) continue;
      total++;
      var an = iYear >= 0 ? (lignes[i][iYear] || "").trim() : "";
      var e = empreinte(nom);
      var f = index[e + an] || index[e];
      if (f && !vus[f.u]) { vus[f.u] = 1; trouves.push(f); }
    }
    rendu(trouves, total);
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
      fr.onerror = function () { erreur("Impossible de lire ce fichier."); };
      fr.readAsText(file);
    };
    if (index) { lire(); return; }
    // L'index n'est chargé qu'ici, à la première utilisation réelle.
    fetch(drop.dataset.index)
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; lire(); })
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
