/* Séancéo — page ville : tri par note Letterboxd + filtre par langue.

   La page ville est groupée PAR CINÉMA (on veut savoir dans quelle salle). Ce
   script agit donc sur place, à l'intérieur de chaque bloc cinéma : il réordonne
   les cartes de films et masque celles qui ne correspondent pas à la langue
   choisie. Les cartes portent data-lb (note) et data-v (versions DE CETTE VILLE,
   posées au build). Un cinéma dont plus aucun film n'est visible est masqué.

   Sans JavaScript, le CSS masque la barre d'outils et tout reste affiché dans
   l'ordre du jour. */
(function () {
  "use strict";
  var tools = document.querySelector(".ville-tools");
  if (!tools) return;
  var sortBtns = [].slice.call(tools.querySelectorAll(".ville-sort"));
  var langBtns = [].slice.call(tools.querySelectorAll(".tri-versions button"));
  var compte = tools.querySelector(".ville-compte");
  var blocks = [].slice.call(document.querySelectorAll(".cinema-block"));
  var details = [].slice.call(document.querySelectorAll(".cinema-block .more-films"));

  // Chaque conteneur .films retient son ordre initial (= « prochaine séance »,
  // l'ordre calculé au build). Le tri par note travaille sur une copie.
  var containers = [].slice.call(document.querySelectorAll(".cinema-block .films"));
  containers.forEach(function (c) {
    c._cards = [].slice.call(c.querySelectorAll(".movie-card"));
  });

  var sort = "imminence";
  var langue = "";

  function nbLb(card) { return parseFloat(card.dataset.lb) || 0; }

  function apply() {
    var visible = 0;
    containers.forEach(function (c) {
      var cards = c._cards.slice();
      if (sort === "lb") {
        // Meilleures notes d'abord ; un film sans note part toujours en queue.
        cards.sort(function (a, b) {
          var ra = nbLb(a) > 0, rb = nbLb(b) > 0;
          if (ra !== rb) return ra ? -1 : 1;
          return nbLb(b) - nbLb(a);
        });
      }
      var frag = document.createDocumentFragment();
      cards.forEach(function (card) {
        var ok = !langue || (card.dataset.v || "").split(" ").indexOf(langue) >= 0;
        card.hidden = !ok;
        if (ok) visible++;
        frag.appendChild(card); // réinsérer = déplacer (tri + regroupement)
      });
      c.appendChild(frag);
    });
    // Masquer un repli « plus tard » puis un cinéma entier s'ils n'ont plus
    // aucun film visible après filtrage.
    details.forEach(function (d) {
      d.hidden = !d.querySelector(".movie-card:not([hidden])");
    });
    blocks.forEach(function (b) {
      b.hidden = !b.querySelector(".movie-card:not([hidden])");
    });
    if (compte) {
      compte.textContent = langue
        ? TF("{n} film{s} en {version}", {
            n: visible, s: PL(visible),
            version: langue === "vo" ? T("VO / VOST") : T("VF"),
          })
        : "";
    }
  }

  sortBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      sort = b.dataset.sort;
      sortBtns.forEach(function (o) {
        o.setAttribute("aria-pressed", o === b ? "true" : "false");
      });
      apply();
    });
  });

  langBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      langue = b.dataset.v;
      langBtns.forEach(function (o) {
        o.setAttribute("aria-pressed", o === b ? "true" : "false");
      });
      apply();
    });
  });
})();
