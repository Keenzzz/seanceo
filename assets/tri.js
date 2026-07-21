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
  var select = document.getElementById("tri-sort");
  var compte = document.getElementById("tri-compte");
  if (!list || !select || !compte) return;

  var boutons = tools.querySelectorAll(".tri-versions button");
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

  // Les tris numériques sont décroissants (la meilleure note, l'année la plus
  // récente et la plus large diffusion en tête) ; le titre, lui, va de A à Z.
  var TRIS = {
    lb: function (a, b) { return nb(b, "lb") - nb(a, "lb"); },
    year: function (a, b) { return nb(b, "year") - nb(a, "year"); },
    venues: function (a, b) { return nb(b, "venues") - nb(a, "venues"); },
    title: function (a, b) {
      return a.dataset.title.localeCompare(b.dataset.title, "fr");
    }
  };

  function correspond(carte) {
    return !version || carte.dataset.v.split(" ").indexOf(version) >= 0;
  }

  function appliquer() {
    var ordre = initial.slice().sort(TRIS[select.value] || TRIS.lb);
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
    list.classList.toggle("hors-classement", select.value !== "lb");

    var reste = trouves - Math.min(trouves, affichees);
    compte.textContent = trouves === 0
      ? "Aucun film dans cette version"
      : trouves + (trouves > 1 ? " films" : " film")
        + (reste ? " · " + Math.min(trouves, affichees) + " affichés" : "");
    plus.hidden = reste === 0;
    plus.textContent = "Afficher " + Math.min(reste, PAGE) + " films de plus";
  }

  select.addEventListener("change", function () {
    affichees = PAGE; // nouveau tri = on repart du haut de la liste
    appliquer();
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

  appliquer();
})();
