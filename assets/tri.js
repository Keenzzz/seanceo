/* Tri et filtre d'une liste de films, sans rechargement.

   Les cartes portent toutes leurs critères en attributs data-* posés au build
   (card_attrs() dans build_site.py) : data-title (titre sans accent ni article
   initial), data-lb (note Letterboxd), data-year, data-venues (nombre de
   salles), data-v (« vf », « vo », ou les deux), data-genres (genres slugifiés
   séparés par des espaces) et data-country (pays slugifié, vide tant que le
   cache TMDB ne le porte pas). Les menus décennie/genre/pays viennent de
   film_tools() ; la décennie est dérivée de data-year, pas d'un attribut à part.

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
  var selDecennie = tools.querySelector(".tri-decennie");
  var selGenre = tools.querySelector(".tri-genre");
  var selPays = tools.querySelector(".tri-pays");
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
  var decennie = "";  // ex. « 1970 » (borne basse de la décennie)
  var genre = "";     // slug de genre, ex. « drame »
  var pays = "";      // slug de pays, ex. « france »

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

  /* Les filtres se cumulent : une carte doit passer TOUS ceux qui sont posés.
     La décennie est calculée depuis l'année (borne basse = année arrondie à la
     dizaine inférieure) ; genre et pays testent l'appartenance à une liste. */
  function aGenre(carte) {
    return (carte.dataset.genres || "").split(" ").indexOf(genre) >= 0;
  }
  function correspond(carte) {
    if (version && carte.dataset.v.split(" ").indexOf(version) < 0) return false;
    if (decennie) {
      var y = nb(carte, "year");
      if (!y || String(Math.floor(y / 10) * 10) !== decennie) return false;
    }
    if (genre && !aGenre(carte)) return false;
    if (pays && carte.dataset.country !== pays) return false;
    return true;
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
      ? T("Aucun film ne correspond à ces filtres")
      : TF("{n} film{s}", { n: trouves, s: PL(trouves) })
        + (reste ? " · " + TF("{n} affichés", { n: Math.min(trouves, affichees) }) : "");
    plus.hidden = reste === 0;
    plus.textContent = TF("Afficher {n} films de plus", { n: Math.min(reste, PAGE) });
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
      b.title = actif
        ? T("Cliquer pour inverser l'ordre")
        : TF("Trier par {critere}",
             { critere: b.querySelector(".tri-nom").textContent.toLowerCase() });
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

  // Menus déroulants (décennie / genre / pays) : chaque changement re-filtre et
  // repart du haut de la liste. Certains menus peuvent être absents de la page.
  function brancherSelect(sel, poser) {
    if (!sel) return;
    sel.addEventListener("change", function () {
      poser(sel.value);
      affichees = PAGE;
      appliquer();
    });
  }
  brancherSelect(selDecennie, function (v) { decennie = v; });
  brancherSelect(selGenre, function (v) { genre = v; });
  brancherSelect(selPays, function (v) { pays = v; });

  plus.addEventListener("click", function () {
    affichees += PAGE;
    appliquer();
    plus.focus(); // le bouton s'est déplacé sous les nouvelles cartes
  });

  marquerTris();
  appliquer();
})();
