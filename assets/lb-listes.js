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

  function activer(tab) {
    tabs.forEach(function (t) {
      var pane = document.getElementById(t.dataset.panel);
      var on = t === tab;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      if (pane) pane.hidden = !on;
    });
  }

  if (tabs.length) {
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () { activer(tab); });
    });
    // Arrivée par /ma-watchlist/#liste (accueil, portail) : l'onglet des
    // listes doit être celui qu'on trouve ouvert. Sans ça l'ancre amenait le
    // visiteur sur une barre d'onglets où « Ma watchlist » restait actif —
    // exactement l'inverse de ce qu'il venait de cliquer.
    if (location.hash === "#liste") {
      var t = document.getElementById("liste");
      if (t) activer(t);
    }
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

  // Site bilingue : `EN` décide du format des dates et des heures. On lit la
  // langue sur <html lang>, posée au build — surtout PAS les réglages de
  // l'appareil via toLocaleDateString(), qui donnerait une date française sur
  // la page anglaise d'un visiteur au téléphone réglé en français.
  var EN = document.documentElement.lang === "en";

  function frDate(iso) {
    var jours = EN
      ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
      : ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
    var mois = EN
      ? ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
      : ["janv.", "févr.", "mars", "avril", "mai", "juin", "juil.",
         "août", "sept.", "oct.", "nov.", "déc."];
    var d = new Date(iso + "T00:00:00");
    var auj = new Date(); auj.setHours(0, 0, 0, 0);
    var delta = Math.round((d - auj) / 86400000);
    if (delta <= 0) return T("aujourd'hui");
    if (delta === 1) return T("demain");
    // L'ANNÉE n'apparaît que si la séance sort de l'année en cours. Les
    // salles de répertoire programment opéras et rétrospectives plus d'un an
    // à l'avance : « mer. 7 avril » lu au mois d'août se comprend comme dans
    // huit mois, alors que la séance est dans vingt.
    var an = d.getFullYear() !== auj.getFullYear() ? " " + d.getFullYear() : "";
    return jours[d.getDay()] + " " + d.getDate() + " " + mois[d.getMonth()] + an;
  }

  // Heure d'une séance à partir d'un « …THH:MM ». Le format 24 h reste tel
  // quel en français ; en anglais il devient « 8:30 pm », faute de quoi
  // l'information la plus utile de la carte se lit de travers.
  function hhmm(iso) {
    var hh = iso.slice(11, 13), mm = iso.slice(14, 16);
    if (!EN) return hh + ":" + mm;
    var h = parseInt(hh, 10);
    return (h % 12 || 12) + ":" + mm + (h < 12 ? " am" : " pm");
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
    var when = TF("prochaine séance {jour} à {heure}",
                  { jour: frDate(s[0].slice(0, 10)), heure: hhmm(s[0]) });
    meta.appendChild(document.createTextNode(when));
    info.appendChild(meta);

    var line = document.createElement("p");
    line.className = "seance-line";
    var lieu = s[2] ? s[1] + ", " + s[2] : s[1];
    if (near && isFinite(pick.dist)) {
      lieu += " · " + TF("à ~{km} km", { km: Math.round(pick.dist) });
    }
    line.appendChild(document.createTextNode("📍 " + lieu));
    // Lien de billetterie : nouvel onglet, uniquement si http(s).
    if (s[5] && /^https?:\/\//i.test(s[5])) {
      line.appendChild(document.createTextNode(" · "));
      var book = document.createElement("a");
      book.className = "seance-book";
      book.href = s[5];
      book.target = "_blank";
      book.rel = "noopener noreferrer";
      book.textContent = T("Réserver ↗");
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
      // T() comme partout ailleurs : ces deux phrases partaient en français sur
      // la version anglaise, alors qu'elles sont justement celles que voit un
      // visiteur dont la liste ne donne rien.
      summary.textContent = currentCity
        ? T("Aucun film de cette liste ne repasse dans cette ville pour l'instant. "
          + "Choisis une autre ville.")
        : T("Aucun film de cette liste ne repasse en salle pour l'instant. La "
          + "programmation change souvent, reviens y jeter un œil.");
      results.appendChild(summary);
      return;
    }
    var cadre = currentCity
      ? T(" dans cette ville")
      : near ? T(", du plus proche au plus loin") : "";
    summary.innerHTML = TF(
      "<strong>{n}</strong> film{s} de cette liste {verbe} en salle{cadre}.",
      { n: shown.length, s: PL(shown.length),
        verbe: shown.length > 1 ? T("repassent") : T("repasse"),
        cadre: cadre });
    results.appendChild(summary);

    var grid = document.createElement("div");
    grid.className = "grid";
    shown.forEach(function (o) { grid.appendChild(card(o.film, o.pick)); });
    results.appendChild(grid);
  }

  // Construit la barre de contrôles (champ de ville + bouton géoloc) une fois
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
    var noms = cities.map(function (k) { return cityMap[k]; });

    var label = document.createElement("label");
    label.className = "list-city-label";
    label.setAttribute("for", "list-city");
    label.textContent = T("Ville");

    // Un CHAMP DE SAISIE, pas un <select>. Une liste croisée couvre couramment
    // trente ou quarante villes : les faire défiler pour trouver la sienne
    // coûtait plusieurs secondes, alors que trois lettres suffisent à la
    // désigner. Le menu reste atteignable — la liste se déroule au focus, sans
    // rien taper — mais ce n'est plus le seul chemin.
    // `min: 0` + `surFocus` sont licites ICI et pas dans le champ de ville du
    // portail : on ne propose que les villes de la liste affichée, pas les 257
    // du site.
    var input = document.createElement("input");
    input.type = "text";
    input.id = "list-city";
    input.className = "lb-input list-city";
    input.setAttribute("aria-label", T("Ville"));
    controls.appendChild(label);
    // autoVille insère un conteneur AUTOUR du champ : il doit déjà être dans
    // le document (sinon `input.parentNode` est nul).
    controls.appendChild(input);
    LB.autoVille(input, function (nom) {
      currentCity = empreinteCity(nom);
      majReset();
      renderResults();
    }, {
      noms: noms, min: 0, surFocus: true,
      placeholder: TF("Tapez une ville ({n})", { n: cities.length })
    });

    // Champ vidé à la main = retour à toutes les villes, sans avoir à viser le
    // bouton. On ne filtre PAS sur une saisie partielle : « Bo » n'est pas une
    // ville, et filtrer à chaque touche ferait clignoter la grille.
    input.addEventListener("input", function () {
      if (!input.value.trim() && currentCity) {
        currentCity = "";
        majReset();
        renderResults();
      }
    });

    var reset = document.createElement("button");
    reset.type = "button";
    reset.className = "lb-secondary list-city-reset";
    reset.textContent = TF("Toutes les villes ({n})", { n: cities.length });
    reset.hidden = true;
    reset.addEventListener("click", function () {
      input.value = "";
      currentCity = "";
      majReset();
      renderResults();
    });
    controls.appendChild(reset);

    function majReset() { reset.hidden = !currentCity; }

    var geo = document.createElement("button");
    geo.type = "button";
    geo.className = "lb-secondary list-geo";
    geo.textContent = T("📍 autour de moi");
    geo.addEventListener("click", function () {
      if (near) {
        near = null; geo.textContent = T("📍 autour de moi");
        renderResults(); return;
      }
      if (!navigator.geolocation) {
        geo.textContent = T("Géolocalisation indisponible"); return;
      }
      geo.textContent = T("…localisation");
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          near = { lat: pos.coords.latitude, lon: pos.coords.longitude };
          geo.textContent = T("🌍 revenir au national");
          renderResults();
        },
        function () { geo.textContent = T("📍 autour de moi"); }
      );
    });

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
      setStatus(T("Colle l'URL complète de la liste (letterboxd.com/…/list/…), "
                + "pas le lien court boxd.it."), "err");
      return;
    }
    var m = raw.match(LIST_RE);
    if (!m) {
      setStatus(T("Ce lien n'a pas l'air d'être une liste Letterboxd. "
                + "Exemple : letterboxd.com/pseudo/list/ma-liste/"), "err");
      return;
    }
    var user = m[1].toLowerCase(), slug = m[2].toLowerCase();
    clearAll();
    setStatus(T("Lecture de la liste…"), "");
    var btn = form.querySelector("button");
    btn.disabled = true;

    Promise.all([fetchList(user, slug), loadIndexes()])
      .then(function (arr) {
        var data = arr[0];
        listName = data.name || T("Cette liste");
        matched = crossList(data.films);
        // Réinitialise le filtre pour une nouvelle liste.
        near = null; currentCity = "";
        setStatus(TF("{liste} — {total} films dans la liste, "
                   + "{trouves} repassent en salle.",
                     { liste: listName,
                       total: data.count || (data.films || []).length,
                       trouves: matched.length }), "");
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
