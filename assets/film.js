/* Fiche film : recherche de ville dans le sommaire des séances.
   La liste des villes du film est dans le <datalist> (autocomplétion native) ;
   #city-map (JSON inerte) associe chaque nom de ville à son ancre. On saute à
   l'ancre dès que la saisie correspond à une ville, accents ignorés. */
(function () {
  "use strict";
  var input = document.getElementById("city-search");
  var mapEl = document.getElementById("city-map");
  if (!input || !mapEl) return;

  var byName = JSON.parse(mapEl.textContent);

  function fold(s) {
    // NFD sépare lettre et accent ; on retire les diacritiques (U+0300-036F)
    return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }
  var index = {};
  Object.keys(byName).forEach(function (name) {
    index[fold(name)] = byName[name];
  });

  function jump() {
    var anchor = index[fold(input.value)];
    if (anchor) {
      location.hash = anchor;
      input.blur();
    }
  }
  // `change` couvre la sélection dans la datalist ET Entrée après saisie
  input.addEventListener("change", jump);
})();
