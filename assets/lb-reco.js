/* Séancéo — page /pour-moi/ : recommandations par affinité de réalisateur
   ======================================================================

   On lit la watchlist du visiteur + ses 4 films favoris (route Worker
   /watchlist/<pseudo>, via LB.sync — les SEULES pages Letterboxd lisibles
   depuis une IP datacenter ; les pages « films notés » y sont bloquées en 403).
   Pour chacun de ces films, on retrouve le RÉALISATEUR dans NOTRE catalogue
   (film-directors.json) — aucun fetch de fiche film. On agrège : le réalisateur
   qui revient le plus (les favoris comptant plus lourd) est un réalisateur de
   prédilection. On recommande alors son répertoire À L'AFFICHE (agenda-index,
   qui porte le réalisateur), en excluant les films déjà listés par le visiteur.

   Limite assumée : seuls les films du visiteur PRÉSENTS dans notre catalogue
   donnent un signal (on ne connaît pas le réalisateur des autres). Les 4 favoris,
   souvent des classiques, ont un bon taux de recouvrement.

   S'appuie sur window.LB (assets/letterboxd.js) : LB.sync (watchlist+favoris),
   LB.empreinte, LB.errText, LB.load. */

(function () {
  "use strict";

  var form = document.getElementById("reco-form");
  if (!form || !window.LB) return;
  var input = document.getElementById("reco-user");
  var statusEl = document.getElementById("reco-status");
  var results = document.getElementById("reco-results");
  var agendaUrl = form.dataset.agenda;
  var wlUrl = form.dataset.wl;
  var dirUrl = form.dataset.directors;

  var FAV_WEIGHT = 3;   // un favori pèse autant que 3 films de watchlist
  var MIN_SCORE = 3;    // seuil pour retenir un réalisateur (1 favori, ou 3 watchlist)
  var MAX_SECTIONS = 8; // au-delà, la page devient un mur

  var _agenda = null, _wl = null, _dir = null;
  function loadIndexes() {
    if (_agenda && _wl && _dir) return Promise.resolve();
    return Promise.all([
      fetch(agendaUrl).then(function (r) { return r.json(); }),
      fetch(wlUrl).then(function (r) { return r.json(); }),
      fetch(dirUrl).then(function (r) { return r.json(); })
    ]).then(function (a) { _agenda = a[0]; _wl = a[1]; _dir = a[2]; });
  }

  // Réalisateur(s) d'un film du visiteur, retrouvé dans notre catalogue par
  // empreinte de slug (repli titre + année, puis titre). Renvoie la chaîne brute
  // (« Joel Coen, Ethan Coen » possible), découpée ensuite par réalisateur.
  function lookupDir(f) {
    var kSlug = LB.empreinte(f.slug), kName = LB.empreinte(f.name);
    return _dir[kSlug] || _dir[kName + (f.year || "")] || _dir[kName] || null;
  }
  function splitDirs(s) {
    return (s || "").split(",").map(function (x) { return x.trim(); })
      .filter(function (x) { return x; });
  }

  // Empreintes de tous les films déjà listés par le visiteur : on ne lui
  // recommande pas un film qu'il a déjà (watchlist ou favori).
  function seenSet(data) {
    var seen = {};
    function mark(f) {
      seen[LB.empreinte(f.slug)] = 1;
      seen[LB.empreinte(f.name) + (f.year || "")] = 1;
      seen[LB.empreinte(f.name)] = 1;
    }
    (data.films || []).forEach(mark);
    (data.favorites || []).forEach(mark);
    return seen;
  }

  // Réalisateurs de prédilection : score = somme des poids des films du visiteur
  // signés par ce réalisateur (favoris pondérés). On garde aussi jusqu'à 3 noms
  // de films « déclencheurs » pour l'expliquer.
  function tasteDirectors(data) {
    var score = {};
    function add(f, weight) {
      var raw = lookupDir(f);
      if (!raw) return;
      splitDirs(raw).forEach(function (name) {
        var k = LB.empreinte(name);
        if (!k) return;
        var e = score[k] || (score[k] = { name: name, key: k, score: 0, films: [] });
        e.score += weight;
        if (e.films.indexOf(f.name) < 0 && e.films.length < 3) e.films.push(f.name);
      });
    }
    (data.favorites || []).forEach(function (f) { add(f, FAV_WEIGHT); });
    (data.films || []).forEach(function (f) { add(f, 1); });
    return Object.keys(score).map(function (k) { return score[k]; })
      .filter(function (e) { return e.score >= MIN_SCORE; })
      .sort(function (a, b) { return b.score - a.score || a.name.localeCompare(b.name); });
  }

  // Index réalisateur -> films de répertoire À L'AFFICHE, depuis agenda-index
  // (dédoublonné par URL de fiche ; la note/l'affiche viennent de watchlist-index
  // sous la même clé). Chaque film porte sa clé d'empreinte pour l'exclusion.
  function screeningByDir() {
    var byDir = {}, seenU = {};
    Object.keys(_agenda).forEach(function (k) {
      var e = _agenda[k];
      if (seenU[e.u]) return;
      seenU[e.u] = 1;
      var meta = _wl[k] || {};
      var film = { key: k, t: e.t, u: e.u, s: e.s,
                   p: meta.p || "", r: meta.r || 0 };
      (e.dk || []).forEach(function (dk) {
        (byDir[dk] = byDir[dk] || []).push(film);
      });
    });
    return byDir;
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

  function card(film) {
    var seances = film.s.slice().sort(function (a, b) {
      return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;
    });
    var s = seances[0];
    var villes = {};
    seances.forEach(function (x) { if (x[2]) villes[x[2]] = 1; });
    var nV = Object.keys(villes).length;

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
      note.className = "note-lb"; note.textContent = film.r;
      var sur = document.createElement("span");
      sur.className = "sur"; sur.textContent = "/5";
      note.appendChild(sur);
      meta.appendChild(note);
      meta.appendChild(document.createTextNode(" · "));
    }
    meta.appendChild(document.createTextNode(
      "prochaine séance " + frDate(s[0].slice(0, 10)) + " à " + s[0].slice(11, 16)));
    info.appendChild(meta);

    var line = document.createElement("p");
    line.className = "seance-line";
    var lieu = s[2] ? s[1] + ", " + s[2] : s[1];
    if (nV > 1) lieu += " · et " + (nV - 1) + " autre" + (nV > 2 ? "s" : "") + " ville" + (nV > 2 ? "s" : "");
    line.appendChild(document.createTextNode("📍 " + lieu));
    if (s[5] && /^https?:\/\//i.test(s[5])) {
      line.appendChild(document.createTextNode(" · "));
      var book = document.createElement("a");
      book.className = "seance-book";
      book.href = s[5]; book.target = "_blank"; book.rel = "noopener noreferrer";
      book.textContent = "Réserver ↗";
      line.appendChild(book);
    }
    info.appendChild(line);
    art.appendChild(info);
    return art;
  }

  function section(dir, films) {
    var sec = document.createElement("section");
    sec.className = "reco-dir";
    var h = document.createElement("h2");
    h.textContent = "Parce que tu aimes " + dir.name;
    sec.appendChild(h);
    if (dir.films.length) {
      var sub = document.createElement("p");
      sub.className = "reco-sub";
      sub.textContent = "Repéré via " + dir.films.join(", ") + " dans tes listes.";
      sec.appendChild(sub);
    }
    var grid = document.createElement("div");
    grid.className = "grid";
    films.forEach(function (f) { grid.appendChild(card(f)); });
    sec.appendChild(grid);
    return sec;
  }

  function render(data) {
    results.textContent = "";
    var dirs = tasteDirectors(data);
    var byDir = screeningByDir();
    var seen = seenSet(data);

    var matched = [];
    var shownFilm = {};
    dirs.forEach(function (dir) {
      var films = (byDir[dir.key] || []).filter(function (f) {
        return !seen[f.key] && !shownFilm[f.u];
      });
      if (!films.length) return;
      films.forEach(function (f) { shownFilm[f.u] = 1; });
      matched.push({ dir: dir, films: films });
    });

    var summary = document.createElement("p");
    summary.className = "wl-summary";
    if (!matched.length) {
      // Deux causes possibles : pas d'affinité détectable (peu de recouvrement
      // avec notre catalogue), ou aucun de ces réalisateurs à l'affiche.
      summary.textContent = dirs.length
        ? "Tes réalisateurs de prédilection n'ont pas de reprise à l'affiche pour l'instant. "
          + "La programmation change souvent, reviens y jeter un œil."
        : "On n'a pas pu déduire tes réalisateurs préférés : trop peu de tes films figurent "
          + "dans notre catalogue de reprises. Réessaie avec une watchlist plus fournie.";
      results.appendChild(summary);
      return;
    }
    summary.innerHTML = "D'après ta watchlist et tes favoris, voici le répertoire à l'affiche "
      + "signé par <strong>" + matched.length + "</strong> réalisateur"
      + (matched.length > 1 ? "s" : "") + " que tu aimes.";
    results.appendChild(summary);
    matched.slice(0, MAX_SECTIONS).forEach(function (mo) {
      results.appendChild(section(mo.dir, mo.films));
    });
  }

  function setStatus(text, kind) {
    statusEl.innerHTML = '<p class="' + (kind === "err" ? "wl-erreur" : "wl-summary") + '"></p>';
    statusEl.querySelector("p").textContent = text;
  }

  function run(user) {
    results.textContent = "";
    setStatus("Lecture de ta watchlist et de tes favoris…", "");
    var btn = form.querySelector("button");
    btn.disabled = true;
    Promise.all([LB.sync(user), loadIndexes()])
      .then(function (arr) {
        var data = arr[0];
        var n = (data.films || []).length + (data.favorites || []).length;
        if (!n) {
          setStatus("On n'a trouvé ni watchlist publique ni favoris pour ce pseudo. "
            + "Rends ton profil public, ou ajoute des films, puis réessaie.", "err");
          return;
        }
        setStatus("Analyse de " + n + " films (watchlist + favoris).", "");
        render(data);
      })
      .catch(function (err) { setStatus(LB.errText(err && err.error), "err"); })
      .then(function () { btn.disabled = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var user = (input.value || "").trim();
    if (user) run(user);
  });

  var state = LB.load && LB.load();
  if (state && state.user) input.value = state.user;
})();
