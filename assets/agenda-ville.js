/* Accueil, section « À ne pas rater » : filtrer la sélection par ville.

   La section liste une douzaine de séances uniques groupées par jour, déjà
   écrites dans le HTML. Sans JavaScript le visiteur les voit toutes, et la
   barre de filtre est masquée en CSS (`html:not(.js) .agenda-tools`) : une
   barre morte serait pire que pas de barre. Même contrat que `.film-tools`,
   la pagination de tri.js et les villes des fiches film.

   Version RÉDUITE de chance.js, volontairement. La page « Dernière chance »
   filtre aussi par jour, classe par note et exporte un .ics ; ici il n'y a
   qu'une seule question, « et dans ma ville ? ». Réutiliser chance.js aurait
   voulu dire charger tout ça sur l'accueil pour n'en garder qu'un dixième.

   ⚠️ `.seance` et `.jour` portent une règle `display:` en CSS. L'attribut
   `hidden` seul serait donc SANS EFFET : ce sont les règles
   `[hidden] { display: none }` de style.css qui rendent le masquage réel.
   C'est le piège CSS le plus récurrent du projet. */

(function () {
  "use strict";

  var compte = document.getElementById("agenda-compte");
  var vide = document.getElementById("agenda-vide");
  // Portée EXPLICITE (#agenda-uniques) plutôt que le document entier : rien ne
  // garantit que l'accueil n'accueillera pas un second agenda un jour, et le
  // filtre ville de celui-ci masquerait alors des lignes qui ne le regardent
  // pas. Le conteneur coûte une div et supprime la question.
  var bloc = document.getElementById("agenda-uniques");
  if (!bloc) return;
  var groupe = bloc.querySelector(".agenda-villes");
  if (!groupe) return;
  var boutons = [].slice.call(groupe.querySelectorAll("button[data-city]"));
  var lignes = [].slice.call(bloc.querySelectorAll(".seance[data-city]"));
  var jours = [].slice.call(bloc.querySelectorAll(".jour"));
  if (!boutons.length || !lignes.length) return;

  // La ville active est portée par `aria-pressed` et NON par une variable à
  // part : l'état lisible par un lecteur d'écran et l'état interne sont ainsi
  // le même, ils ne peuvent pas diverger. Même principe que les boutons de tri.
  function villeActive() {
    for (var i = 0; i < boutons.length; i++) {
      if (boutons[i].getAttribute("aria-pressed") === "true") {
        return boutons[i].dataset.city;
      }
    }
    return "";
  }

  function appliquer() {
    var ville = villeActive();
    var n = 0;
    for (var i = 0; i < lignes.length; i++) {
      var garde = !ville || lignes[i].dataset.city === ville;
      lignes[i].hidden = !garde;
      if (garde) n++;
    }
    // Une journée dont toutes les séances sont masquées laisserait un titre de
    // jour orphelin (« Mardi 25 août » suivi de rien). On masque la section
    // entière. Bug déjà rencontré et corrigé sur « Dernière chance ».
    for (var j = 0; j < jours.length; j++) {
      var restantes = jours[j].querySelectorAll(".seance:not([hidden])").length;
      jours[j].hidden = restantes === 0;
    }
    if (vide) vide.hidden = n > 0;
    if (compte) {
      compte.textContent = ville
        ? window.TF("{n} séance{s} à {ville}", { n: n, s: window.PL(n), ville: ville })
        : window.TF("{n} séance{s} en France", { n: n, s: window.PL(n) });
    }
  }

  // Un seul écouteur sur le groupe plutôt qu'un par bouton : le nombre de
  // villes change à chaque build, autant ne pas en dépendre.
  groupe.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("button[data-city]") : null;
    if (!btn || !groupe.contains(btn)) return;
    // Re-cliquer la ville déjà active ne la désélectionne pas : il faut qu'une
    // ville soit toujours choisie, sinon la liste tomberait dans un état sans
    // bouton actif où plus rien n'indiquerait ce qui est affiché.
    if (btn.getAttribute("aria-pressed") === "true") return;
    for (var i = 0; i < boutons.length; i++) {
      boutons[i].setAttribute("aria-pressed", boutons[i] === btn ? "true" : "false");
    }
    appliquer();
  });
  // Pas d'appel au chargement : le HTML servi est déjà l'état « toutes villes »,
  // et le rejouer ferait clignoter la liste pour rien.
})();
