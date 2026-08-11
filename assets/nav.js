/* nav.js — la barre de navigation quand elle déborde (téléphone et tablette).
   Deux rôles, tous deux inutiles sur desktop où les 6 pastilles tiennent :
     1. amener la pastille de la page courante dans le champ de vision ;
     2. piloter les dégradés de bord qui annoncent « il y a la suite ». */
(function () {
  var nav = document.querySelector('.site-nav');
  if (!nav) return;
  var FADE = 24;  // doit rester cohérent avec le commentaire du CSS

  /* Les dégradés vivent en variables CSS (--fade-l / --fade-r) plutôt qu'en
     dur dans la feuille : un dégradé permanent estomperait une pastille même
     là où la barre tient tout juste et n'a rien à faire défiler (largeurs
     proches de 900 px). On ne l'affiche donc que du côté où il reste
     réellement du contenu — à droite au départ, à gauche une fois défilé. */
  function bords() {
    var max = nav.scrollWidth - nav.clientWidth;
    // <= 1 et non == 0 : les navigateurs rendent des largeurs fractionnaires,
    // un reliquat d'un demi-pixel ne doit pas déclencher un dégradé.
    if (max <= 1) {
      nav.style.setProperty('--fade-l', '0px');
      nav.style.setProperty('--fade-r', '0px');
      return;
    }
    var x = nav.scrollLeft;
    // Le dégradé rétrécit à l'approche du bout, sinon il « mentirait » en
    // laissant croire qu'il reste du contenu alors qu'on est arrivé.
    // Math.max(0, …) n'est pas de la superstition : scrollLeft et
    // (scrollWidth - clientWidth) sont arrondis différemment, donc arrivé au
    // bout la soustraction donne -0.4px. Une longueur négative dans le
    // linear-gradient met les points d'arrêt dans le désordre.
    nav.style.setProperty('--fade-l', Math.max(0, Math.min(FADE, x)) + 'px');
    nav.style.setProperty('--fade-r', Math.max(0, Math.min(FADE, max - x)) + 'px');
  }

  // passive:true — on ne fait que lire des positions, jamais preventDefault :
  // le navigateur peut donc défiler sans attendre ce code.
  nav.addEventListener('scroll', bords, { passive: true });
  // La rotation d'un téléphone peut faire apparaître ou disparaître le
  // débordement : on recalcule.
  addEventListener('resize', bords);

  var cur = nav.querySelector('[aria-current="page"]');
  // scrollWidth > clientWidth = la barre déborde, donc on est en mode
  // défilant. Sur desktop tout tient sur une ligne : rien à centrer.
  if (cur && nav.scrollWidth > nav.clientWidth) {
    // On centre la pastille. Calcul en coordonnées écran puis ajout du scroll
    // courant : plus fiable que offsetLeft, qui dépend de offsetParent.
    var n = nav.getBoundingClientRect(), c = cur.getBoundingClientRect();
    // Affectation directe de scrollLeft : strictement horizontal, donc aucun
    // risque de faire sauter la page verticalement — ce que ferait
    // scrollIntoView si le visiteur arrive sur une ancre #.
    nav.scrollLeft += (c.left - n.left) - (n.width - c.width) / 2;
  }
  bords();
})();
