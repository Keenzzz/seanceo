/* Tri et filtre d'une liste de films, sans rechargement.

   Les cartes portent toutes leurs critères en attributs data-* posés au build
   (card_attrs() dans build_site.py) : data-title (titre sans accent ni article
   initial), data-lb (note Letterboxd), data-year, data-venues (nombre de
   salles) et data-v (« vf », « vo », ou les deux).

   La liste est aussi paginée ici : le HTML contient toutes les cartes — pour
   les robots et pour les visiteurs sans JavaScript — mais on n'en montre que
   `data-page` à la fois, avec un bouton « Afficher plus ». */
(function () {
  "use strict";
  var tools = document.querySelector(".film-tools");
  if (!tools) return;
  var list = document.getElementById(tools.dataset.list);
  var compte = document.getElementById("tri-compte");
  if (!list || !compte) return;

  var tris = tools.querySelectorAll(".tri-tri button");
  var boutons = tools.querySelectorAll(".tri-versions button");
  // Tri courant : le bouton marqué actif au build porte le tri par défaut
  // de la page, dans son sens naturel (meilleures notes d'abord, titres A→Z).
  var triActif = tools.querySelector('.tri-tri button[aria-pressed="true"]') || tris[0];
  // Ordre de départ = celui calculé au build, qui est déjà le tri par défaut
  // de la page. Le tri JavaScript étant stable, re-trier cette liste sur ce
  // même critère redonne exactement l'ordre servi par le serveur.
  var initial = [].slice.call(list.querySelectorAll(".movie-card"));
  var PAGE = parseInt(tools.dataset.page, 10) || 40;
  var affichees = PAGE;
  var version = "";

  var plus = document.createElement("button");
  plus.type = "button";
  plus.className = "tri-plus";
  plus.hidden = true;
  list.parentNode.insertBefore(plus, list.nextSibling);

  function nb(carte, champ) { return parseFloat(carte.dataset[champ]) || 0; }

  /* Comparateurs écrits en ORDRE CROISSANT ; `appliquer()` inverse le signe
     pour le sens décroissant. Un seul comparateur par critère, donc aucun
     risque que les deux sens divergent. */
  var TRIS = {
    lb: function (a, b) { return nb(a, "lb") - nb(b, "lb"); },
    year: function (a, b) { return nb(a, "year") - nb(b, "year"); },
    venues: function (a, b) { return nb(a, "venues") - nb(b, "venues"); },
    title: function (a, b) {
      return a.dataset.title.localeCompare(b.dataset.title, "fr");
    }
  };

  function correspond(carte) {
    return !version || carte.dataset.v.split(" ").indexOf(version) >= 0;
  }

  /* Une fiche sans valeur pour le critère courant (film sans note Letterboxd,
     année inconnue) part TOUJOURS en queue, dans les deux sens. Sans ça, un
     tri « note croissante » ouvrait sur les 49 films sans note plutôt que sur
     les moins bien notés — ce n'est pas ce qu'on demande en cliquant. */
  function renseigne(carte, critere) {
    return critere === "title" ? true : nb(carte, critere) > 0;
  }

  function appliquer() {
    var critere = triActif.dataset.sort;
    var sens = triActif.dataset.dir === "asc" ? 1 : -1;
    var compare = TRIS[critere] || TRIS.lb;
    var ordre = initial.slice().sort(function (a, b) {
      var ra = renseigne(a, critere), rb = renseigne(b, critere);
      if (ra !== rb) return ra ? -1 : 1;
      return sens * compare(a, b);
    });
    var trouves = 0;
    var frag = document.createDocumentFragment();
    ordre.forEach(function (carte) {
      if (correspond(carte)) {
        trouves++;
        carte.hidden = trouves > affichees;
      } else {
        carte.hidden = true;
      }
      frag.appendChild(carte); // réinsérer une carte déjà là = la déplacer
    });
    list.appendChild(frag);

    // Le numéro du classement Letterboxd ne veut plus rien dire dès qu'on
    // trie autrement : un « n° 3 » en septième position serait un mensonge.
    // Le sens, lui, n'y change rien : trié à l'envers, la liste déroule
    // simplement les rangs du dernier au premier.
    list.classList.toggle("hors-classement", critere !== "lb");

    var reste = trouves - Math.min(trouves, affichees);
    compte.textContent = trouves === 0
      ? "Aucun film dans cette version"
      : trouves + (trouves > 1 ? " films" : " film")
        + (reste ? " · " + Math.min(trouves, affichees) + " affichés" : "");
    plus.hidden = reste === 0;
    plus.textContent = "Afficher " + Math.min(reste, PAGE) + " films de plus";
  }

  /* Un seul bouton actif, portant la marque de son sens ; les autres restent
     nus, sinon la barre ressemblerait à quatre tris simultanés. */
  function marquerTris() {
    [].forEach.call(tris, function (b) {
      var actif = b === triActif;
      b.setAttribute("aria-pressed", actif ? "true" : "false");
      b.querySelector(".tri-sens").textContent =
        actif ? b.dataset[b.dataset.dir] : "";
      // Le libellé seul ne dit pas ce que fera le clic : on l'annonce.
      b.title = actif ? "Cliquer pour inverser l'ordre"
                      : "Trier par " + b.querySelector(".tri-nom").textContent.toLowerCase();
    });
  }

  [].forEach.call(tris, function (b) {
    b.addEventListener("click", function () {
      if (b === triActif) {
        // Re-clic sur le tri déjà actif = on inverse le sens
        b.dataset.dir = b.dataset.dir === "asc" ? "desc" : "asc";
      } else {
        triActif = b; // premier clic : le critère prend son sens naturel
      }
      affichees = PAGE; // nouveau tri = on repart du haut de la liste
      marquerTris();
      appliquer();
    });
  });

  [].forEach.call(boutons, function (b) {
    b.addEventListener("click", function () {
      version = b.dataset.v;
      affichees = PAGE;
      [].forEach.call(boutons, function (autre) {
        autre.setAttribute("aria-pressed", autre === b ? "true" : "false");
      });
      appliquer();
    });
  });

  plus.addEventListener("click", function () {
    affichees += PAGE;
    appliquer();
    plus.focus(); // le bouton s'est déplacé sous les nouvelles cartes
  });

  marquerTris();
  appliquer();
})();
