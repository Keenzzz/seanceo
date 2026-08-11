/* nav.js — amène la pastille de la page courante dans le champ de vision.
   Sur mobile la barre de navigation déborde horizontalement (elle défile au
   doigt) : si la page courante est la 5e ou la 6e pastille, le repère
   aria-current est hors écran au chargement et ne sert donc à rien. */
(function () {
  var nav = document.querySelector('.site-nav');
  if (!nav) return;
  var cur = nav.querySelector('[aria-current="page"]');
  if (!cur) return;
  // scrollWidth > clientWidth = la barre déborde, donc on est en mode défilant.
  // Sur desktop tout tient sur une ligne : rien à faire.
  if (nav.scrollWidth <= nav.clientWidth) return;
  // On centre la pastille. Calcul en coordonnées écran puis ajout du scroll
  // courant : plus fiable que offsetLeft, qui dépend de offsetParent.
  var n = nav.getBoundingClientRect(), c = cur.getBoundingClientRect();
  // Affectation directe de scrollLeft : strictement horizontal, donc aucun
  // risque de faire sauter la page verticalement — ce que ferait
  // scrollIntoView si le visiteur arrive sur une ancre #.
  nav.scrollLeft += (c.left - n.left) - (n.width - c.width) / 2;
})();
