/* Séancéo — page ville : filtre « je n'affiche que les salles qui acceptent
   ma carte d'abonnement illimité » (UGC Illimité, CinéPass Pathé).

   Le choix est RETENU d'une page à l'autre (localStorage) : une carte
   d'abonnement, on l'a pour l'année, pas pour une visite. Un abonné UGC qui
   consulte Lyon puis Nancy veut le même filtre aux deux endroits sans le
   redemander.

   Le script agit au niveau du bloc cinéma, pas du film : la carte donne accès
   à une SALLE, tous ses films y compris. Il coexiste avec ville.js, qui masque
   des films à l'intérieur des blocs — d'où le `data-carte-off` plutôt qu'un
   style.display écrit en dur, que ville.js écraserait au tri suivant.

   Sans JavaScript, le CSS masque la barre et toutes les salles restent
   affichées : le filtre est un confort, jamais un passage obligé. */
(function () {
  "use strict";
  var tools = document.querySelector(".cartes-tools");
  if (!tools) return;
  var btns = [].slice.call(tools.querySelectorAll("button[data-carte]"));
  var compte = tools.querySelector(".cartes-compte");
  var blocks = [].slice.call(document.querySelectorAll(".cinema-block"));
  var jump = document.querySelector(".city-jump");
  var CLE = "seanceo:carte";

  // localStorage peut lever (navigation privée stricte, cookies bloqués) : le
  // filtre doit continuer de marcher pour la visite en cours, simplement sans
  // mémoire. Même prudence que le pseudo Letterboxd.
  function lire() {
    try { return localStorage.getItem(CLE) || ""; } catch (e) { return ""; }
  }
  function ecrire(v) {
    try { v ? localStorage.setItem(CLE, v) : localStorage.removeItem(CLE); }
    catch (e) { /* tant pis, le choix ne survivra pas à la page */ }
  }

  function accepte(bloc, carte) {
    if (!carte) return true;
    var l = (bloc.dataset.cartes || "").split(" ");
    return l.indexOf(carte) !== -1;
  }

  function apply(carte) {
    var visibles = 0;
    blocks.forEach(function (b) {
      var ok = accepte(b, carte);
      if (ok) { delete b.dataset.carteOff; visibles++; }
      else { b.dataset.carteOff = "1"; }
    });
    // Le sommaire ancré doit suivre : un lien vers une salle masquée mènerait
    // à une ancre invisible, ce qui donne l'impression d'un lien cassé.
    if (jump) {
      [].slice.call(jump.querySelectorAll("a")).forEach(function (a) {
        var cible = document.querySelector(a.getAttribute("href"));
        if (cible) a.hidden = !!cible.dataset.carteOff;
      });
    }
    btns.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.carte === carte));
    });
    if (compte) {
      // « acceptent / accepte » : le français accorde, l'anglais non — le
      // verbe circule donc en variable, comme partout ailleurs sur le site.
      compte.textContent = carte
        ? TF("{n} salle{s} {verbe} cette carte",
             { n: visibles, s: PL(visibles),
               verbe: visibles > 1 ? T("acceptent") : T("accepte") })
        : "";
    }
  }

  btns.forEach(function (b) {
    b.addEventListener("click", function () {
      var carte = b.dataset.carte;
      ecrire(carte);
      apply(carte);
    });
  });

  // Un choix mémorisé peut désigner une carte qu'aucune salle de CETTE ville
  // n'accepte — le build ne rend un bouton que pour les cartes représentées.
  // On retombe alors sur « Peu importe » plutôt que de vider la page : une
  // ville sans salle partenaire doit montrer son programme, pas une liste
  // vide qu'aucun bouton visible n'expliquerait. Le choix reste mémorisé et
  // reprendra effet sur une ville où il a du sens.
  var initial = lire();
  if (initial && !btns.some(function (b) { return b.dataset.carte === initial; })) {
    initial = "";
  }
  apply(initial);
})();
