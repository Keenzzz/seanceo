/* Recherche de ville (fiche film, accueil, classiques).
   Suggestions maison (pas de datalist : elle déroulerait tout au clic).
   Rien ne s'affiche avant 2 lettres ; ensuite les villes correspondantes
   apparaissent au fil de la frappe (accents ignorés, préfixes d'abord).
   Clic ou Entrée (ou flèches puis Entrée) → la cible du #city-map :
   ancre « v-slug » (fiche film) ou URL commençant par « / » (navigation). */
(function () {
  "use strict";
  var input = document.getElementById("city-search");
  var list = document.getElementById("city-suggest");
  var mapEl = document.getElementById("city-map");
  if (!input || !list || !mapEl) return;

  var byName = JSON.parse(mapEl.textContent);
  var names = Object.keys(byName).sort();
  var MIN_CHARS = 2;
  var MAX_ITEMS = 8;
  var active = -1; // index de la suggestion surlignée au clavier

  function fold(s) {
    // NFD sépare lettre et accent ; on retire les diacritiques (U+0300-036F)
    return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }
  var folded = names.map(fold);

  function matches(q) {
    var starts = [], contains = [];
    for (var i = 0; i < names.length; i++) {
      var pos = folded[i].indexOf(q);
      if (pos === 0) starts.push(names[i]);
      else if (pos > 0) contains.push(names[i]);
    }
    return starts.concat(contains).slice(0, MAX_ITEMS);
  }

  function close() {
    list.hidden = true;
    list.textContent = "";
    active = -1;
  }

  function go(name) {
    close();
    input.value = name;
    var target = byName[name];
    if (target.charAt(0) === "/") { // cible = URL (accueil, classiques)
      location.href = target;
      return;
    }
    // cible = ancre d'une ville repliée : déplier avant de sauter
    var el = document.getElementById(target);
    if (el && el.tagName === "DETAILS") el.open = true;
    location.hash = target;
    input.blur();
  }

  function render() {
    var q = fold(input.value);
    if (q.length < MIN_CHARS) { close(); return; }
    var found = matches(q);
    if (!found.length) { close(); return; }
    close();
    found.forEach(function (name) {
      var li = document.createElement("li");
      li.textContent = name; // textContent : jamais d'injection HTML
      // mousedown plutôt que click : part avant le blur de l'input
      li.addEventListener("mousedown", function (e) {
        e.preventDefault();
        go(name);
      });
      list.appendChild(li);
    });
    list.hidden = false;
  }

  function highlight(items) {
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", i === active);
    }
  }

  input.addEventListener("input", render);
  input.addEventListener("keydown", function (e) {
    var items = list.querySelectorAll("li");
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      active = (active + 1) % items.length;
      highlight(items);
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      active = (active - 1 + items.length) % items.length;
      highlight(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items.length) go(items[active >= 0 ? active : 0].textContent);
    } else if (e.key === "Escape") {
      close();
    }
  });
  input.addEventListener("blur", function () {
    // léger délai : laisse le mousedown d'une suggestion aboutir
    setTimeout(close, 150);
  });
})();

/* Villes repliées (<details>) : tout saut d'ancre doit déplier sa cible —
   pastille de grande ville, lien partagé avec #v-…, bouton précédent. */
(function () {
  function openHash() {
    var id = location.hash.slice(1);
    if (!id) return;
    var el = document.getElementById(id);
    if (el && el.tagName === "DETAILS" && !el.open) {
      el.open = true;
      el.scrollIntoView();
    }
  }
  window.addEventListener("hashchange", openHash);
  openHash(); // arrivée directe avec une ancre dans l'URL (script defer : DOM prêt)
})();
