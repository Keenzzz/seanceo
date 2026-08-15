/* Page /derniere-chance/ : filtrer par ville et par jour, classer par note,
   exporter vers son agenda.

   La page contient TOUTES les séances uniques de France (une liste d'agenda
   groupée par jour), déjà écrites dans le HTML : sans JavaScript, le visiteur
   voit l'intégralité de la liste — c'est le même contrat que les villes des
   fiches film et que la pagination de tri.js. Le script ne fait qu'y ajouter
   des filtres, un tri et un bouton, jamais du contenu.

   ⚠️ `.seance` et `.jour` portent une règle `display:` en CSS. L'attribut
   `hidden` seul serait donc SANS EFFET : les règles `[hidden] { display: none }`
   qui les accompagnent dans style.css font partie de ce mécanisme. */

(function () {
  "use strict";

  var selVille = document.getElementById("chance-ville");
  var selJour = document.getElementById("chance-jour");
  var selTri = document.getElementById("chance-tri");
  var compte = document.getElementById("chance-compte");
  var vide = document.getElementById("chance-vide");
  var bouton = document.getElementById("chance-ics");
  var plate = document.getElementById("chance-note");
  var lignes = [].slice.call(document.querySelectorAll(".seance[data-start]"));
  var jours = [].slice.call(document.querySelectorAll(".jour"));
  if (!selVille || !lignes.length) return;

  /* Le tri par note casse le groupement par jour : une liste classée par note
     mélange forcément les journées. Plutôt que de réécrire des lignes, on
     DÉPLACE les <li> existants dans une liste plate (#chance-note), vide dans
     le HTML servi, et on masque les sections de jour. Retour au tri par date =
     chaque ligne revient dans le <ul> de sa journée. Il faut donc savoir où
     chaque ligne habite : c'est cette table, construite une fois. Les libellés
     de date, invisibles en tri chronologique (l'en-tête de section les porte
     déjà), s'affichent dans la liste plate via `.par-note .jour-inline`. */
  var accueil = {};
  jours.forEach(function (j) {
    var li = j.querySelector(".seance[data-start]");
    if (li) accueil[li.dataset.start.slice(0, 10)] = li.parentNode;
  });

  function jourDe(li) { return li.dataset.start.slice(0, 10); }

  // Les séances visibles, dans l'ordre où elles sont affichées.
  function visibles() {
    return lignes.filter(function (li) { return !li.hidden; });
  }

  /* Meilleures notes d'abord ; à note égale, la séance la plus proche d'abord
     (c'est une page « dernière chance », l'imminence départage). Un film sans
     note Letterboxd porte 0 et part donc en queue, comme dans tri.js — l'en
     écarter ferait mentir le compte affiché juste au-dessus de la liste. */
  function parNote(a, b) {
    var na = parseFloat(a.dataset.lb) || 0;
    var nb = parseFloat(b.dataset.lb) || 0;
    if (na !== nb) return nb - na;
    return a.dataset.start < b.dataset.start ? -1 : 1;
  }

  function libelleJour() {
    if (!selJour || !selJour.value) return "";
    var opt = selJour.options[selJour.selectedIndex];
    return (opt && opt.dataset.label) || "";
  }

  function appliquer() {
    var ville = selVille.value;
    var jour = selJour ? selJour.value : "";
    var note = !!selTri && selTri.value === "note";

    // Les deux filtres se cumulent : une séance doit passer les deux.
    lignes.forEach(function (li) {
      li.hidden = !!((ville && li.dataset.city !== ville) ||
                     (jour && jourDe(li) !== jour));
    });
    var gardees = visibles();

    if (note) {
      var frag = document.createDocumentFragment();
      gardees.slice().sort(parNote).forEach(function (li) {
        frag.appendChild(li);
      });
      plate.appendChild(frag);
      // Les sections de jour ne contiennent plus que des lignes masquées.
      jours.forEach(function (j) { j.hidden = true; });
    } else {
      // Remettre TOUTES les lignes chez elles, masquées comprises : l'ordre du
      // tableau `lignes` est celui du document, donc les réinsérer dans cet
      // ordre reconstruit exactement l'agenda servi par le build.
      lignes.forEach(function (li) { accueil[jourDe(li)].appendChild(li); });
      // Un jour dont toutes les séances sont masquées ne doit pas laisser son
      // titre orphelin (« JEUDI 21 AOÛT » suivi de rien).
      jours.forEach(function (j) {
        j.hidden = !j.querySelector(".seance:not([hidden])");
      });
    }

    var n = gardees.length;
    if (vide) vide.hidden = n > 0;
    if (compte) {
      var lieu = ville
        ? TF("{n} séance{s} à {ville}", { n: n, s: PL(n), ville: ville })
        : TF("{n} séance{s} en France", { n: n, s: PL(n) });
      var jlbl = libelleJour();
      compte.textContent = jlbl ? lieu + " · " + jlbl : lieu;
    }
    if (bouton) {
      bouton.hidden = n === 0;
      bouton.textContent = TF("＋ Ajouter ces {n} séances à mon agenda", { n: n });
    }
  }

  [selVille, selJour, selTri].forEach(function (sel) {
    if (sel) sel.addEventListener("change", appliquer);
  });

  if (bouton && window.ICS) {
    bouton.addEventListener("click", function () {
      var ville = selVille.value;
      var jour = selJour ? selJour.value : "";
      ICS.telecharger(
        ville ? TF("Dernière chance à {ville}", { ville: ville })
              : T("Dernière chance en France"),
        // Le jour entre dans le NOM DU FICHIER (et pas dans le titre de
        // l'agenda) : deux exports filtrés différemment ne doivent pas
        // s'écraser dans le dossier de téléchargements.
        "derniere-chance"
          + (ville ? "-" + ville.toLowerCase().replace(/[^a-z0-9]+/g, "-") : "")
          + (jour ? "-" + jour : ""),
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
