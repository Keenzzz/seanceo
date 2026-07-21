/* Comportements présents sur TOUTES les pages : le bouton « Retour » et la
   recherche de film du header. Regroupés dans un seul fichier pour n'ajouter
   qu'une requête au chargement de chaque page. */

/* Bouton « ← Retour ».

   Affiché UNIQUEMENT si la page précédente appartient au site. Un visiteur
   qui arrive d'une recherche Google n'a pas de « page où il était » chez
   nous : lui proposer « Retour » le renverrait sur Google, c'est-à-dire le
   ferait quitter le site — l'inverse de ce qu'un bouton retour promet.
   Le clic passe par history.back(), qui restitue la position de défilement ;
   l'attribut href pointe la même cible pour que « ouvrir dans un onglet »
   et le clic du milieu fonctionnent normalement. */
(function () {
  "use strict";
  var lien = document.getElementById("retour");
  if (!lien || !document.referrer) return;
  var interne = false;
  try {
    interne = new URL(document.referrer).origin === location.origin;
  } catch (e) {
    interne = false;
  }
  // Même URL = rechargement, pas une navigation : rien à quoi revenir.
  if (!interne || document.referrer === location.href) return;
  lien.href = document.referrer;
  lien.hidden = false;
  lien.addEventListener("click", function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    history.back();
  });
})();

/* Recherche d'un film par son titre OU par son réalisateur, dans le header de
   toutes les pages.

   L'index des ~930 films vit dans /recherche.json et n'est téléchargé qu'à la
   première interaction avec le champ : l'injecter dans chaque page coûterait
   ~90 ko à tous les visiteurs pour une fonction que la plupart n'ouvriront
   jamais. Une fois chargé, tout se passe en mémoire (aucun aller-retour). */
(function () {
  "use strict";
  var input = document.getElementById("film-search");
  var list = document.getElementById("film-suggest");
  if (!input || !list) return;

  var MIN_CHARS = 2;
  var MAX_ITEMS = 8;
  var films = null;    // [[titre, réalisateur, url, année], …]
  var titles = null;   // titres normalisés, même indexation que `films`
  var people = null;   // réalisateurs normalisés, idem
  var loading = false;
  var active = -1;     // index de la suggestion surlignée au clavier

  function fold(s) {
    // NFD sépare lettre et accent ; on retire les diacritiques (U+0300-036F)
    // pour que « amelie » trouve « Amélie » et « bunuel » trouve « Buñuel ».
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function load() {
    if (films || loading) return;
    loading = true;
    fetch(input.dataset.index)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        films = data;
        titles = data.map(function (f) { return fold(f[0]); });
        people = data.map(function (f) { return fold(f[1]); });
        render(); // la frappe a pu commencer pendant le téléchargement
      })
      .catch(function () {
        // Échec réseau : on se remet en état de réessayer à la frappe suivante
        loading = false;
      });
  }

  /* Position d'une correspondance en DÉBUT DE MOT, -1 sinon. C'est ce qui
     sépare une vraie trouvaille d'une coïncidence de lettres : « tati » est
     au milieu de « station » et de « invitation » sans rien avoir à y faire. */
  function debutDeMot(texte, q) {
    var pos = texte.indexOf(q);
    while (pos > 0) {
      if (!/[a-z0-9]/.test(texte.charAt(pos - 1))) return pos;
      pos = texte.indexOf(q, pos + 1);
    }
    return pos; // 0 (le texte commence par la requête) ou -1 (absent)
  }

  /* Quatre paquets, du plus au moins pertinent. Le paquet « au milieu d'un
     mot » ferme la marche : sans ça, « tati » remontait « Il était une fois
     la STATION balnéaire… » avant les films de Jacques Tati. */
  function matches(q) {
    var titreDebut = [], titreMot = [], realisateur = [], titreDedans = [];
    for (var i = 0; i < films.length && titreDebut.length < MAX_ITEMS; i++) {
      var mot = debutDeMot(titles[i], q);
      if (mot === 0) titreDebut.push(i);
      else if (mot > 0) titreMot.push(i);
      else if (debutDeMot(people[i], q) >= 0) realisateur.push(i);
      else if (titles[i].indexOf(q) > 0) titreDedans.push(i);
    }
    return titreDebut.concat(titreMot, realisateur, titreDedans).slice(0, MAX_ITEMS);
  }

  function close() {
    list.hidden = true;
    list.textContent = "";
    active = -1;
  }

  function go(i) {
    close();
    location.href = films[i][2];
  }

  function suggestion(i) {
    var f = films[i];
    var li = document.createElement("li");
    li.dataset.i = i;
    // textContent partout : jamais de HTML construit à partir des données
    var titre = document.createElement("strong");
    titre.textContent = f[0];
    li.appendChild(titre);
    var detail = [f[1], f[3] ? String(f[3]) : ""].filter(Boolean).join(" · ");
    if (detail) {
      var sous = document.createElement("span");
      sous.className = "suggest-meta";
      sous.textContent = detail;
      li.appendChild(sous);
    }
    // mousedown plutôt que click : part avant le blur de l'input
    li.addEventListener("mousedown", function (e) {
      e.preventDefault();
      go(i);
    });
    return li;
  }

  function render() {
    var q = fold(input.value).trim();
    if (q.length < MIN_CHARS) { close(); return; }
    if (!films) { load(); return; } // render() sera rappelé au chargement
    var found = matches(q);
    close();
    if (!found.length) {
      var vide = document.createElement("li");
      vide.className = "suggest-vide";
      vide.textContent = "Aucun film à l'affiche pour « " + input.value.trim() + " »";
      list.appendChild(vide);
    } else {
      found.forEach(function (i) { list.appendChild(suggestion(i)); });
    }
    list.hidden = false;
  }

  function highlight(items) {
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("active", i === active);
    }
  }

  input.addEventListener("focus", load); // l'index arrive pendant la frappe
  input.addEventListener("input", render);
  input.addEventListener("keydown", function (e) {
    var items = list.querySelectorAll("li[data-i]");
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
      if (items.length) go(+items[active >= 0 ? active : 0].dataset.i);
    } else if (e.key === "Escape") {
      close();
    }
  });
  input.addEventListener("blur", function () {
    // léger délai : laisse le mousedown d'une suggestion aboutir
    setTimeout(close, 150);
  });
})();
