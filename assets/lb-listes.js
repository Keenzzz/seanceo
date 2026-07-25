/* Séancéo — page /ma-watchlist/, onglet « depuis une liste »
   =========================================================

   Le visiteur colle l'URL d'une LISTE Letterboxd publique
   (letterboxd.com/<pseudo>/list/<slug>/). On récupère la liste via le Worker
   (route /list/<pseudo>/<slug>, même parsing que la watchlist), puis on la
   croise avec DEUX index servis par le site :
     - agenda-index.json : le DÉTAIL des séances de répertoire, par ville, avec
       coordonnées et billetterie (c'est lui qui permet le filtre géographique) ;
     - watchlist-index.json : l'affiche et la note Letterboxd (l'agenda ne les
       porte pas), jointes par la MÊME clé d'empreinte de slug.

   Comme le reste du pont Letterboxd, tout se passe dans le navigateur : la
   géolocalisation n'est jamais envoyée au site, elle ne sert qu'à trier
   localement les séances par proximité.

   S'appuie sur window.LB (assets/letterboxd.js) pour `empreinte`, `WORKER_URL`
   et `errText`. Pour développer sans réseau/déploiement, passer MOCK à true :
   la liste factice n'utilise que des slugs présents dans l'agenda. */

(function () {
  "use strict";

  // —— Onglets (pseudo / liste) —————————————————————————————————————————————
  // Sans JavaScript, les deux panneaux restent visibles (le CSS masque la barre
  // d'onglets) : rien n'est caché derrière un onglet mort.

  var tabs = Array.prototype.slice.call(document.querySelectorAll(".wl-tab"));
  if (tabs.length) {
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) {
          var pane = document.getElementById(t.dataset.panel);
          var on = t === tab;
          t.classList.toggle("is-active", on);
          t.setAttribute("aria-selected", on ? "true" : "false");
          if (pane) pane.hidden = !on;
        });
      });
    });
  }

  // —— Import de liste ———————————————————————————————————————————————————————

  var form = document.getElementById("list-form");
  if (!form || !window.LB) return;
  var input = document.getElementById("list-url");
  var statusEl = document.getElementById("list-status");
  var controls = document.getElementById("list-controls");
  var results = document.getElementById("list-results");
  var agendaUrl = form.dataset.agenda;
  var wlUrl = form.dataset.wl;

  // Passer à true pour tester le rendu sans déployer le Worker : la liste
  // factice pointe des slugs qui EXISTENT dans l'agenda (donc de vrais matchs).
  var MOCK = false;
  var MOCK_LIST = {
    ok: true, name: "Ma liste de test", count: 10,
    films: [
      { slug: "monsieurhulotsholiday", name: "Monsieur Hulot's Holiday", year: "1953" },
      { slug: "cowboybebopthemovie", name: "Cowboy Bebop: The Movie", year: "2001" },
      { slug: "playtime", name: "PlayTime", year: "1967" },
      { slug: "mononcle", name: "Mon Oncle", year: "1958" },
      { slug: "jourdefete", name: "Jour de fête", year: "1949" },
      { slug: "killbillthewholebloodyaffair", name: "Kill Bill: The Whole Bloody Affair", year: "2011" },
      { slug: "trafic", name: "Trafic", year: "1971" },
      { slug: "parade", name: "Parade", year: "1974" },
      { slug: "kwaidan", name: "Kwaidan", year: "1964" },
      { slug: "the-great-nonexistent-film", name: "Nowhere", year: "2099" }
    ]
  };

  // URL d'une liste → { user, slug }. On tolère les variantes (/detail/,
  // /by/rating/, /page/2/… en suffixe) : la regex ne capte que les deux
  // segments qui nous intéressent. Les liens courts boxd.it ne sont pas
  // résolubles côté client (CORS) : on les refuse avec un message clair.
  var LIST_RE = /letterboxd\.com\/([a-z0-9_-]+)\/list\/([a-z0-9-]+)/i;

  var _agenda = null, _wl = null;
  function loadIndexes() {
    if (_agenda && _wl) return Promise.resolve();
    return Promise.all([
      fetch(agendaUrl).then(function (r) { return r.json(); }),
      fetch(wlUrl).then(function (r) { return r.json(); })
    ]).then(function (arr) { _agenda = arr[0]; _wl = arr[1]; });
  }

  function fetchList(user, slug) {
    if (MOCK) return Promise.resolve(MOCK_LIST);
    return fetch(LB.WORKER_URL + "/list/" + encodeURIComponent(user) + "/" + encodeURIComponent(slug))
      .then(function (r) {
        if (r.status === 404) throw { error: "not_found" };
        if (!r.ok) throw { error: "upstream_error" };
        return r.json();
      })
      .then(function (data) {
        if (!data.ok) throw { error: data.error || "upstream_error" };
        return data;
      });
  }

  // Croise les films de la liste avec l'agenda (séances par ville) et enrichit
  // avec l'affiche + la note de la watchlist-index. Clé = empreinte du slug,
  // repli sur le titre (+ année) — même logique que LB.cross.
  function crossList(films) {
    var out = [], seen = {};
    (films || []).forEach(function (f) {
      var kSlug = LB.empreinte(f.slug);
      var kName = LB.empreinte(f.name);
      var a = _agenda[kSlug] || _agenda[kName + (f.year || "")] || _agenda[kName];
      if (!a || seen[a.u]) return;
      seen[a.u] = 1;
      var meta = _wl[kSlug] || _wl[kName + (f.year || "")] || _wl[kName] || {};
      out.push({ t: a.t, u: a.u, p: meta.p || "", r: meta.r || 0, s: a.s });
    });
    return out;
  }

  // —— État courant du rendu ————————————————————————————————————————————————

  var matched = [];      // films croisés (avec leurs séances)
  var listName = "";     // nom de la liste (og:title)
  var near = null;       // { lat, lon } si géoloc active
  var currentCity = "";  // "" = toutes les villes

  function empreinteCity(name) { return (name || "").toLowerCase(); }

  // Distance Haversine en km (identique à map.js et au Worker).
  function distKm(lat, lon) {
    if (!near || lat == null || lon == null) return Infinity;
    var R = 6371, toRad = function (d) { return d * Math.PI / 180; };
    var dLat = toRad(lat - near.lat), dLon = toRad(lon - near.lon);
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(near.lat)) * Math.cos(toRad(lat)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  // Pour un film, choisit la séance à afficher selon le filtre courant :
  // filtrée par ville si une ville est choisie ; la plus proche si géoloc
  // active, sinon la plus imminente. Renvoie { s, dist } ou null.
  function pickSeance(film) {
    var cand = film.s;
    if (currentCity) {
      cand = cand.filter(function (s) { return empreinteCity(s[2]) === currentCity; });
    }
    if (!cand.length) return null;
    var best = null, bestVal = Infinity;
    cand.forEach(function (s) {
      var val = near ? distKm(s[3], s[4]) : 0;
      // À distance/imminence égale, on garde la séance la plus tôt.
      if (best === null || val < bestVal ||
        (val === bestVal && s[0] < best[0])) {
        best = s; bestVal = val;
      }
    });
    return { s: best, dist: near ? bestVal : Infinity };
  }

  function frDate(iso) {
    var jours = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
    var mois = ["janv.", "févr.", "mars", "avril", "mai", "juin", "juil.",
                "août", "sept.", "oct.", "nov.", "déc."];
    var d = new Date(iso + "T00:00:00");
    var auj = new Date(); auj.setHours(0, 0, 0, 0);
    var delta = Math.round((d - auj) / 86400000);
    if (delta <= 0) return "aujourd'hui";
    if (delta === 1) return "demain";
    return jours[d.getDay()] + " " + d.getDate() + " " + mois[d.getMonth()];
  }

  // Carte film : affiche + titre + une séance (date, ville, cinéma, heure,
  // billetterie). Toutes les valeurs viennent de NOS index ; les chaînes
  // externes (titre, cinéma, ville) passent par textContent, jamais innerHTML,
  // et le lien de billetterie n'est posé que s'il est en http(s).
  function card(film, pick) {
    var s = pick.s; // [start, cinéma, ville, lat, lon, billetterie]
    var art = document.createElement("article");
    art.className = "movie-card";

    var a = document.createElement("a");
    a.href = film.u;
    if (film.p) {
      var img = document.createElement("img");
      img.src = film.p; img.alt = ""; img.loading = "lazy";
      a.appendChild(img);
    } else {
      var ph = document.createElement("span");
      ph.className = "noposter"; ph.textContent = "🎞️";
      a.appendChild(ph);
    }
    art.appendChild(a);

    var info = document.createElement("div");
    info.className = "movie-info";

    var h = document.createElement("h3");
    var ha = document.createElement("a");
    ha.href = film.u; ha.textContent = film.t;
    h.appendChild(ha);
    info.appendChild(h);

    var meta = document.createElement("p");
    meta.className = "meta";
    if (film.r) {
      var note = document.createElement("span");
      note.className = "note-lb";
      note.textContent = film.r;
      var sur = document.createElement("span");
      sur.className = "sur"; sur.textContent = "/5";
      note.appendChild(sur);
      meta.appendChild(note);
      meta.appendChild(document.createTextNode(" · "));
    }
    var when = "prochaine séance " + frDate(s[0].slice(0, 10)) + " à " + s[0].slice(11, 16);
    meta.appendChild(document.createTextNode(when));
    info.appendChild(meta);

    var line = document.createElement("p");
    line.className = "seance-line";
    var lieu = s[2] ? s[1] + ", " + s[2] : s[1];
    if (near && isFinite(pick.dist)) lieu += " · à ~" + Math.round(pick.dist) + " km";
    line.appendChild(document.createTextNode("📍 " + lieu));
    // Lien de billetterie : nouvel onglet, uniquement si http(s).
    if (s[5] && /^https?:\/\//i.test(s[5])) {
      line.appendChild(document.createTextNode(" · "));
      var book = document.createElement("a");
      book.className = "seance-book";
      book.href = s[5];
      book.target = "_blank";
      book.rel = "noopener noreferrer";
      book.textContent = "Réserver ↗";
      line.appendChild(book);
    }
    info.appendChild(line);

    art.appendChild(info);
    return art;
  }

  // (Re)construit la grille selon `currentCity` et `near`.
  function renderResults() {
    results.textContent = "";
    var shown = [];
    matched.forEach(function (film) {
      var pick = pickSeance(film);
      if (pick) shown.push({ film: film, pick: pick });
    });

    // Tri : par proximité si géoloc, sinon par imminence de la séance.
    shown.sort(function (x, y) {
      if (near) return x.pick.dist - y.pick.dist;
      return x.pick.s[0] < y.pick.s[0] ? -1 : x.pick.s[0] > y.pick.s[0] ? 1 : 0;
    });

    var summary = document.createElement("p");
    summary.className = "wl-summary";
    if (!shown.length) {
      summary.textContent = currentCity
        ? "Aucun film de cette liste ne repasse dans cette ville pour l'instant. Choisis une autre ville."
        : "Aucun film de cette liste ne repasse en salle pour l'instant. La programmation change souvent, reviens y jeter un œil.";
      results.appendChild(summary);
      return;
    }
    summary.innerHTML = "<strong>" + shown.length + "</strong> film"
      + (shown.length > 1 ? "s" : "") + " de cette liste "
      + (shown.length > 1 ? "repassent" : "repasse") + " en salle"
      + (currentCity ? " dans cette ville" : near ? ", du plus proche au plus loin" : "") + ".";
    results.appendChild(summary);

    var grid = document.createElement("div");
    grid.className = "grid";
    shown.forEach(function (o) { grid.appendChild(card(o.film, o.pick)); });
    results.appendChild(grid);
  }

  // Construit la barre de contrôles (menu des villes + bouton géoloc) une fois
  // qu'on a des résultats.
  function buildControls() {
    controls.hidden = false;
    controls.textContent = "";

    // Villes distinctes présentes parmi les séances des films croisés.
    var cityMap = {};
    matched.forEach(function (film) {
      film.s.forEach(function (s) {
        if (s[2]) cityMap[empreinteCity(s[2])] = s[2];
      });
    });
    var cities = Object.keys(cityMap).sort(function (a, b) {
      return cityMap[a].localeCompare(cityMap[b], "fr");
    });

    var label = document.createElement("label");
    label.className = "list-city-label";
    label.setAttribute("for", "list-city");
    label.textContent = "Ville";
    var select = document.createElement("select");
    select.id = "list-city";
    select.className = "list-city";
    var optAll = document.createElement("option");
    optAll.value = ""; optAll.textContent = "Toutes les villes (" + cities.length + ")";
    select.appendChild(optAll);
    cities.forEach(function (key) {
      var o = document.createElement("option");
      o.value = key; o.textContent = cityMap[key];
      select.appendChild(o);
    });
    select.addEventListener("change", function () {
      currentCity = select.value;
      renderResults();
    });

    var geo = document.createElement("button");
    geo.type = "button";
    geo.className = "lb-secondary list-geo";
    geo.textContent = "📍 autour de moi";
    geo.addEventListener("click", function () {
      if (near) {
        near = null; geo.textContent = "📍 autour de moi";
        renderResults(); return;
      }
      if (!navigator.geolocation) {
        geo.textContent = "Géolocalisation indisponible"; return;
      }
      geo.textContent = "…localisation";
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          near = { lat: pos.coords.latitude, lon: pos.coords.longitude };
          geo.textContent = "🌍 revenir au national";
          renderResults();
        },
        function () { geo.textContent = "📍 autour de moi"; }
      );
    });

    controls.appendChild(label);
    controls.appendChild(select);
    controls.appendChild(geo);
  }

  // —— Statut / erreurs ——————————————————————————————————————————————————————

  function setStatus(text, kind) {
    statusEl.innerHTML = '<p class="' + (kind === "err" ? "wl-erreur" : "wl-summary") + '"></p>';
    statusEl.querySelector("p").textContent = text;
  }
  function clearAll() {
    controls.hidden = true; controls.textContent = "";
    results.textContent = "";
  }

  // —— Recherche ————————————————————————————————————————————————————————————

  function search(raw) {
    if (/boxd\.it\//i.test(raw)) {
      setStatus("Colle l'URL complète de la liste (letterboxd.com/…/list/…), pas le lien court boxd.it.", "err");
      return;
    }
    var m = raw.match(LIST_RE);
    if (!m) {
      setStatus("Ce lien n'a pas l'air d'être une liste Letterboxd. Exemple : letterboxd.com/pseudo/list/ma-liste/", "err");
      return;
    }
    var user = m[1].toLowerCase(), slug = m[2].toLowerCase();
    clearAll();
    setStatus("Lecture de la liste…", "");
    var btn = form.querySelector("button");
    btn.disabled = true;

    Promise.all([fetchList(user, slug), loadIndexes()])
      .then(function (arr) {
        var data = arr[0];
        listName = data.name || "Cette liste";
        matched = crossList(data.films);
        // Réinitialise le filtre pour une nouvelle liste.
        near = null; currentCity = "";
        setStatus(listName + " — " + (data.count || (data.films || []).length)
          + " films dans la liste, " + matched.length + " repassent en salle.", "");
        if (matched.length) {
          buildControls();
        } else {
          controls.hidden = true; controls.textContent = "";
        }
        renderResults();
      })
      .catch(function (err) {
        clearAll();
        setStatus(LB.errText(err && err.error), "err");
      })
      .then(function () { btn.disabled = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var raw = input.value.trim();
    if (raw) search(raw);
  });
})();
