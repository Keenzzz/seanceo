/* Page /derniere-chance/ : filtrer par ville et exporter vers son agenda.

   La page contient TOUTES les séances uniques de France (une liste d'agenda
   groupée par jour), déjà écrites dans le HTML : sans JavaScript, le visiteur
   voit l'intégralité de la liste — c'est le même contrat que les villes des
   fiches film et que la pagination de tri.js. Le script ne fait qu'y ajouter
   un filtre et un bouton, jamais du contenu.

   ⚠️ `.seance` et `.jour` portent une règle `display:` en CSS. L'attribut
   `hidden` seul serait donc SANS EFFET : les règles `[hidden] { display: none }`
   qui les accompagnent dans style.css font partie de ce mécanisme. */

(function () {
  "use strict";

  var select = document.getElementById("chance-ville");
  var compte = document.getElementById("chance-compte");
  var bouton = document.getElementById("chance-ics");
  var lignes = [].slice.call(document.querySelectorAll(".seance[data-start]"));
  if (!select || !lignes.length) return;

  // Les séances visibles, dans l'ordre où elles sont affichées (chronologique).
  function visibles() {
    return lignes.filter(function (li) { return !li.hidden; });
  }

  function appliquer() {
    var ville = select.value;
    lignes.forEach(function (li) {
      li.hidden = !!ville && li.dataset.city !== ville;
    });
    // Un jour dont toutes les séances sont masquées ne doit pas laisser son
    // titre orphelin (« JEUDI 21 AOÛT » suivi de rien).
    var jours = document.querySelectorAll(".jour");
    for (var i = 0; i < jours.length; i++) {
      var reste = jours[i].querySelectorAll(".seance:not([hidden])").length;
      jours[i].hidden = reste === 0;
    }
    var n = visibles().length;
    if (compte) {
      compte.textContent = ville
        ? TF("{n} séance{s} à {ville}", { n: n, s: PL(n), ville: ville })
        : TF("{n} séances en France", { n: n });
    }
    if (bouton) {
      bouton.hidden = n === 0;
      bouton.textContent = TF("＋ Ajouter ces {n} séances à mon agenda", { n: n });
    }
  }

  select.addEventListener("change", appliquer);

  if (bouton && window.ICS) {
    bouton.addEventListener("click", function () {
      var ville = select.value;
      ICS.telecharger(
        ville ? TF("Dernière chance à {ville}", { ville: ville })
              : T("Dernière chance en France"),
        "derniere-chance" + (ville ? "-" + ville.toLowerCase().replace(/[^a-z0-9]+/g, "-") : ""),
        visibles().map(function (li) {
          var d = li.dataset;
          return {
            titre: d.title,
            start: d.start,
            lieu: d.lieu,
            // `url` est un chemin de fiche : l'agenda du visiteur a besoin
            // d'une adresse complète, pas d'un chemin relatif à ce site.
            url: location.origin + d.url,
            booking: d.booking || ""
          };
        }));
    });
  }

  appliquer(); // pose le compte et le libellé du bouton dès le chargement
})();
