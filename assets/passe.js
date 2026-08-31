/* Séancéo — les séances déjà commencées disparaissent
   ===================================================

   Le site est STATIQUE : il est reconstruit une fois par jour, mais il est lu
   toute la journée. À 19 h 30, la page servie le matin propose encore la
   séance de 19 h — une information devenue fausse, et la plus agaçante qui
   soit sur un site d'horaires. Comme le build ne peut rien y faire (il ne
   sait pas à quelle heure on le lira), c'est le NAVIGATEUR qui tranche, au
   chargement de chaque page.

   Le script RETIRE du document les séances passées, il ne les masque pas avec
   `hidden`. Deux raisons :
     - `.seance` et `.jour` portent une règle `display:` en CSS, donc `hidden`
       seul n'a aucun effet sans la règle `[hidden] { display: none }` qui
       l'accompagne — c'est le piège CSS le plus récurrent du projet ;
     - surtout, chance.js et agenda-ville.js RÉÉCRIVENT `li.hidden` à chaque
       filtre. Une séance simplement masquée ici réapparaîtrait au premier
       clic sur une ville. Retirée, elle ne peut plus revenir, et les compteurs
       de ces deux scripts (« 12 séances à Nancy ») redeviennent justes tout
       seuls, sans qu'ils aient à connaître l'heure.

   Il doit donc s'exécuter AVANT eux : il est chargé en premier dans le <head>
   et tous les scripts du site sont `defer`, donc exécutés dans l'ordre du
   document. Ne pas le déplacer plus bas.

   Il expose aussi `window.PASSE` pour les scripts qui construisent leurs
   cartes en JavaScript (watchlist, listes Letterboxd, cinémathèque) : eux ne
   nettoient pas du DOM, ils filtrent leurs données en amont. */

(function () {
  "use strict";

  /* Tolérance, en minutes, après l'heure annoncée. À 0, une séance de 19 h
     disparaît à 19 h pile. La passer à 15 laisserait le temps des bandes-
     annonces à qui court encore vers la salle — c'est un arbitrage éditorial,
     pas technique : un seul chiffre à changer ici. */
  var GRACE_MIN = 0;

  var LIMITE = Date.now() - GRACE_MIN * 60000;

  /* « 2026-08-31T19:00 » est une heure de SALLE : locale, sans fuseau. On la
     reconstruit composant par composant plutôt que via `new Date(iso)`, dont
     l'interprétation (locale ou UTC) a longtemps varié d'un navigateur à
     l'autre selon la présence des secondes. Ici, aucune ambiguïté. */
  function debut(iso) {
    if (!iso || iso.length < 16) return NaN;
    var d = new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10),
                     +iso.slice(11, 13), +iso.slice(14, 16));
    return d.getTime();
  }

  function estPassee(iso) {
    var t = debut(iso);
    return !isNaN(t) && t < LIMITE;
  }

  /* API pour les rendus JavaScript. `futures` filtre une liste d'entrées en
     lisant la date de chacune via `quandFn` ; sans `quandFn`, l'entrée EST la
     chaîne ISO. Tolérant à une liste absente : les index servis peuvent venir
     d'un cache plus ancien. */
  window.PASSE = {
    est: estPassee,
    futures: function (liste, quandFn) {
      if (!liste || !liste.length) return liste || [];
      return liste.filter(function (e) {
        return !estPassee(quandFn ? quandFn(e) : e);
      });
    }
  };

  // —— Nettoyage du HTML servi ————————————————————————————————————————————————

  function tous(sel, racine) {
    return Array.prototype.slice.call((racine || document).querySelectorAll(sel));
  }

  function oter(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  /* La date d'un élément : `data-start` quand le build l'a posée, sinon le
     `<time datetime>` que porte toute ligne d'agenda. Les deux formes existent
     depuis longtemps ; les unifier au build aurait touché plus de gabarits que
     de lire l'une ou l'autre ici. */
  function quand(el) {
    if (el.dataset && el.dataset.start) return el.dataset.start;
    var t = el.querySelector("time[datetime]");
    return t ? t.getAttribute("datetime") : "";
  }

  function retirer(sel) {
    tous(sel).forEach(function (el) {
      if (estPassee(quand(el))) oter(el);
    });
  }

  /* Retire les conteneurs qui ne contiennent plus rien de `contenu`. Sans ça
     on laisserait des titres orphelins — « JEUDI 21 AOÛT » suivi de rien, un
     bloc cinéma réduit à son nom. `quoi` est un sélecteur ou une liste
     d'éléments déjà relevée (voir `blocsSeances`). */
  function purger(quoi, contenu) {
    (typeof quoi === "string" ? tous(quoi) : quoi).forEach(function (el) {
      if (!el.querySelector(contenu)) oter(el);
    });
  }

  /* Ce qui portait des séances AVANT le nettoyage. Sans ces deux relevés on
     supprimerait des blocs qui n'ont jamais rien eu à perdre : une carte
     « prochaine séance : jeudi » (page ville, films de plus tard) n'a pas
     d'horaires, et un cinéma en relâche affiche « Aucune séance cette
     semaine » — les juger vides après coup les ferait disparaître tous les
     deux, alors qu'ils disent quelque chose de vrai. */
  var cartesHoraires = tous("ul.showtimes").map(function (ul) {
    return ul.closest(".movie-card"); // null sur une fiche film : pas de carte
  });
  var blocsSeances = tous(".cinema-block").filter(function (b) {
    return b.querySelector(".showtimes li, .movie-card");
  });

  retirer(".seance");                 // lignes d'agenda (accueil, dernière chance…)
  retirer(".showtimes li");           // pastilles d'horaires (cinéma, ville, film)
  retirer(".marathon[data-start]");   // idée de marathon dont le 1er film a commencé

  /* Une liste d'horaires vidée. Sur une page ville, la carte n'affiche QUE les
     séances du jour : le build a posé juste à côté un repli masqué
     (« prochaine séance : demain »), et c'est le moment de le révéler plutôt
     que de faire disparaître un film qui repasse. Sur une fiche film, les
     horaires sont précédés d'un `<span class="day">` qui n'a plus d'objet. */
  tous("ul.showtimes").forEach(function (ul) {
    if (ul.querySelector("li")) return;
    var jour = ul.previousElementSibling;
    if (jour && jour.classList.contains("day")) oter(jour);
    var repli = ul.parentNode.querySelector(".seances-finies");
    oter(ul);
    if (repli) repli.hidden = false;
  });

  cartesHoraires.forEach(function (c) {
    if (!c || !c.parentNode) return;
    if (c.querySelector(".showtimes li")) return;
    if (c.querySelector(".seances-finies:not([hidden])")) return;
    oter(c);
  });

  // Du plus petit conteneur au plus grand : un bloc cinéma ne peut être jugé
  // vide qu'une fois ses cartes retirées, un groupe de villes qu'une fois ses
  // blocs cinéma retirés.
  purger("section.jour", ".seance");                     // agendas groupés par jour
  purger("section.jour-cine", ".movie-card");            // fiche cinéma, une journée
  purger(blocsSeances, ".showtimes li, .movie-card");    // fiche film ET page ville
  purger(".city-group", ".cinema-block");                // fiche film, un groupe de villes
  purger(".marathon-ville, .marathon-cults", ".marathon"); // idées de marathon d'une ville

  /* Page ville : le bloc « aujourd'hui » d'une salle s'est vidé, mais elle
     programme encore plus tard dans la semaine. On lui redonne alors EXACTEMENT
     la forme que le build écrit quand une salle n'a rien le jour même : la
     phrase « Pas de séance aujourd'hui. Prochaines dates : » suivie des films,
     à plat. Le repli est donc déverrouillé (on sort sa grille et on jette le
     <details>) plutôt que simplement déplié : son résumé, « + 9 autres films
     plus tard cette semaine », ne veut plus rien dire une fois qu'il n'y a plus
     de « premiers » films au-dessus.

     La phrase vient du build, masquée, et non d'une chaîne écrite ici : c'est
     la seule façon d'être sûr qu'elle est dans la bonne langue sur /en/ sans
     dupliquer une traduction.

     Le bloc du jour est un enfant DIRECT de la section ; celui du repli est
     enfermé dans le <details>. D'où le parcours des enfants plutôt qu'un
     querySelector, qui ramènerait l'un ou l'autre selon ce qui reste. */
  tous(".cinema-block").forEach(function (bloc) {
    var plus = bloc.querySelector("details.more-films");
    if (!plus) return;
    var jour = null;
    for (var i = 0; i < bloc.children.length; i++) {
      if (bloc.children[i].classList.contains("films")) { jour = bloc.children[i]; break; }
    }
    if (jour && jour.querySelector(".movie-card")) return;
    oter(jour);
    var phrase = bloc.querySelector(".jour-fini");
    if (phrase) phrase.hidden = false;
    var grille = plus.querySelector(".films");
    if (grille) plus.parentNode.insertBefore(grille, plus);
    oter(plus);
  });

  /* Une fiche film annonce « 3 cinémas » par groupe de villes : le compte
     devient faux dès qu'un bloc disparaît. Il est trop visible, juste à côté
     du titre du groupe, pour le laisser mentir. */
  tous(".city-group").forEach(function (g) {
    var compte = g.querySelector("h3 .meta");
    if (!compte) return;
    var n = g.querySelectorAll(".cinema-block").length;
    compte.textContent = window.TF("{n} cinéma{s}", { n: n, s: window.PL(n) });
  });

  /* Sommaires ancrés (`.city-jump`) : villes d'une fiche film (`#v-slug`) et
     salles d'une page ville (`#c-id`). Un lien dont la cible vient d'être
     retirée mènerait à un saut dans le vide. */
  tous('.city-jump a[href^="#"]').forEach(function (a) {
    if (!document.getElementById(a.getAttribute("href").slice(1))) oter(a);
  });

  /* Recherche de villes des fiches film : ses cibles sont les mêmes ancres.
     Une ville dont le groupe a disparu doit sortir de l'index, sinon la taper
     ouvre le vide. */
  var carte = document.getElementById("city-map");
  if (carte) {
    try {
      var noms = JSON.parse(carte.textContent), garde = {};
      Object.keys(noms).forEach(function (nom) {
        var cible = noms[nom];
        if (cible.charAt(0) === "/" || document.getElementById(cible)) {
          garde[nom] = cible;
        }
      });
      carte.textContent = JSON.stringify(garde);
    } catch (e) { /* index illisible : on n'y touche pas */ }
  }
})();
