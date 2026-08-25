/* Séancéo — recommandations « Pour toi » sur l'ACCUEIL
   ====================================================

   Intégrées à l'accueil (pas de page ni d'onglet dédiés) : dès que le visiteur
   a saisi son pseudo (portail Letterboxd de letterboxd.js), on affiche un bloc
   « ✨ Pour toi » avec le répertoire à l'affiche signé par ses réalisateurs de
   prédilection.

   On déduit ces réalisateurs de sa watchlist + ses 4 favoris (les seules pages
   Letterboxd lisibles depuis le Worker ; les pages « films notés » y sont
   bloquées en 403). Le réalisateur de chacun de ces films est retrouvé dans
   NOTRE catalogue (film-directors.json) — aucun fetch de fiche film. On
   recommande alors leur répertoire à l'affiche (agenda-index, qui porte le
   réalisateur), en excluant les films déjà listés (pure découverte).

   Déclenché de deux façons : au chargement si le visiteur est déjà connecté
   (localStorage), et sur l'événement `seanceo:lb-connected` émis par le portail.
   S'appuie sur window.LB (empreinte, load). */

(function () {
  "use strict";

  var home = document.getElementById("reco-home");
  if (!home || !window.LB) return;
  var agendaUrl = home.dataset.agenda;
  var wlUrl = home.dataset.wl;
  var dirUrl = home.dataset.directors;

  var FAV_WEIGHT = 3;   // un favori pèse autant que 3 films de watchlist
  var MIN_SCORE = 3;    // seuil pour retenir un réalisateur (1 favori, ou 3 watchlist)
  var MAX_SECTIONS = 6; // sur l'accueil, on reste compact
  var MAX_PER_DIR = 8;  // films montrés par réalisateur

  var _agenda = null, _wl = null, _dir = null;
  function loadIndexes() {
    if (_agenda && _wl && _dir) return Promise.resolve();
    return Promise.all([
      fetch(agendaUrl).then(function (r) { return r.json(); }),
      fetch(wlUrl).then(function (r) { return r.json(); }),
      fetch(dirUrl).then(function (r) { return r.json(); })
    ]).then(function (a) { _agenda = a[0]; _wl = a[1]; _dir = a[2]; });
  }

  function lookupDir(f) {
    var kSlug = LB.empreinte(f.slug), kName = LB.empreinte(f.name);
    return _dir[kSlug] || _dir[kName + (f.year || "")] || _dir[kName] || null;
  }
  function splitDirs(s) {
    return (s || "").split(",").map(function (x) { return x.trim(); })
      .filter(function (x) { return x; });
  }

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

  function screeningByDir() {
    var byDir = {}, seenU = {};
    Object.keys(_agenda).forEach(function (k) {
      var e = _agenda[k];
      if (seenU[e.u]) return;
      seenU[e.u] = 1;
      var meta = _wl[k] || {};
      var film = { key: k, t: e.t, u: e.u, s: e.s, p: meta.p || "", r: meta.r || 0 };
      (e.dk || []).forEach(function (dk) {
        (byDir[dk] = byDir[dk] || []).push(film);
      });
    });
    return byDir;
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
    var h = document.createElement("h4");
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
    meta.appendChild(document.createTextNode(TF(
      "prochaine séance {jour} à {heure}",
      { jour: frDate(s[0].slice(0, 10)), heure: hhmm(s[0]) })));
    info.appendChild(meta);

    var line = document.createElement("p");
    line.className = "seance-line";
    var lieu = s[2] ? s[1] + ", " + s[2] : s[1];
    if (nV > 1) {
      lieu += " · " + TF("et {n} autre{s} ville{s2}",
                         { n: nV - 1, s: PL(nV - 1), s2: PL(nV - 1) });
    }
    line.appendChild(document.createTextNode("📍 " + lieu));
    if (s[5] && /^https?:\/\//i.test(s[5])) {
      line.appendChild(document.createTextNode(" · "));
      var book = document.createElement("a");
      book.className = "seance-book";
      book.href = s[5]; book.target = "_blank"; book.rel = "noopener noreferrer";
      book.textContent = T("Réserver ↗");
      line.appendChild(book);
    }
    info.appendChild(line);
    art.appendChild(info);
    return art;
  }

  function section(dir, films) {
    var sec = document.createElement("section");
    sec.className = "reco-dir";
    var h = document.createElement("h3");
    h.textContent = TF("Parce que tu aimes {realisateur}", { realisateur: dir.name });
    sec.appendChild(h);
    if (dir.films.length) {
      var sub = document.createElement("p");
      sub.className = "reco-sub";
      sub.textContent = TF("Repéré via {films} dans tes listes.",
                           { films: dir.films.join(", ") });
      sec.appendChild(sub);
    }
    var grid = document.createElement("div");
    grid.className = "grid";
    films.slice(0, MAX_PER_DIR).forEach(function (f) { grid.appendChild(card(f)); });
    sec.appendChild(grid);
    return sec;
  }

  // Construit le bloc « Pour toi » dans #reco-home. Si rien à recommander, on
  // laisse le bloc masqué : inutile d'encombrer l'accueil d'un message négatif.
  function renderInto(data) {
    if (!data || !data.user) { home.hidden = true; return; }
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

    if (!matched.length) { home.hidden = true; return; }

    home.textContent = "";
    var h = document.createElement("h2");
    h.className = "reco-home-titre";
    // textContent = aucune injection possible, quel que soit le pseudo
    h.textContent = TF("✨ Pour toi, {pseudo}", { pseudo: data.user });
    home.appendChild(h);
    var sub = document.createElement("p");
    sub.className = "meta";
    sub.textContent = T("D'après ta watchlist et tes favoris Letterboxd : le répertoire "
                      + "à l'affiche signé par tes réalisateurs préférés.");
    home.appendChild(sub);
    matched.slice(0, MAX_SECTIONS).forEach(function (mo) {
      home.appendChild(section(mo.dir, mo.films));
    });
    home.hidden = false;
  }

  function renderFrom(data) {
    loadIndexes().then(function () { renderInto(data); }).catch(function () {});
  }

  // Connexion via le portail : rendu immédiat, sans rechargement.
  document.addEventListener("seanceo:lb-connected", function (e) {
    renderFrom(e.detail || (LB.load && LB.load()));
  });

  // Visiteur déjà connecté (visite précédente) : rendu au chargement.
  var state = LB.load && LB.load();
  if (state && state.user && ((state.films && state.films.length) ||
      (state.favorites && state.favorites.length))) {
    renderFrom(state);
  }
})();
