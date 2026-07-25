/* Séancéo — page /cinematheque/ : composer une rétrospective personnelle.

   Le visiteur choisit un réalisateur ; on rassemble TOUS ses films de répertoire
   à l'affiche en France (depuis agenda-index, qui porte le réalisateur + les
   séances par ville) en un parcours chronologique. Insight (films, villes,
   week-end groupable), tri chrono/note, filtre ville, et export .ics généré
   ENTIÈREMENT côté client (aucun serveur : on lit des index publics, tout se
   passe dans le navigateur).

   S'appuie sur window.LB (letterboxd.js, chargé sur toutes les pages) pour
   `empreinte`. Un paramètre d'URL ?d=<réalisateur> pré-sélectionne (utilisé par
   les boutons des pages de rétrospective). */

(function () {
  "use strict";

  var form = document.getElementById("cine-form");
  if (!form || !window.LB) return;
  var input = document.getElementById("cine-search");
  var statusEl = document.getElementById("cine-status");
  var result = document.getElementById("cine-result");
  var agendaUrl = form.dataset.agenda;
  var wlUrl = form.dataset.wl;
  var dirUrl = form.dataset.directors;

  var _agenda = null, _wl = null, _dirs = null, _dirByKey = null;
  function loadIndexes() {
    if (_agenda && _wl && _dirs) return Promise.resolve();
    return Promise.all([
      fetch(agendaUrl).then(function (r) { return r.json(); }),
      fetch(wlUrl).then(function (r) { return r.json(); }),
      fetch(dirUrl).then(function (r) { return r.json(); })
    ]).then(function (a) {
      _agenda = a[0]; _wl = a[1]; _dirs = a[2];
      _dirByKey = {};
      _dirs.forEach(function (d) { _dirByKey[d.key] = d; });
    });
  }

  // ---- état du rendu courant ----
  var current = null;   // { name, key, films:[…] }
  var order = "chrono"; // chrono | note
  var city = "";        // "" = toute la France

  function byStart(a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; }

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
  function frLong(iso) {
    var mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre"];
    var d = new Date(iso + "T00:00:00");
    return d.getDate() + " " + mois[d.getMonth()];
  }

  // Rassemble les films de répertoire du réalisateur, dédoublonnés par fiche.
  function gather(key) {
    var byU = {};
    Object.keys(_agenda).forEach(function (k) {
      var e = _agenda[k];
      if ((e.dk || []).indexOf(key) < 0 || byU[e.u]) return;
      var meta = _wl[k] || {};
      byU[e.u] = {
        t: e.t, u: e.u, p: meta.p || "", r: meta.r || 0,
        seances: e.s.slice().sort(byStart)
      };
    });
    return Object.keys(byU).map(function (u) { return byU[u]; });
  }

  // Séance à afficher pour un film selon le filtre ville (la plus tôt).
  function pick(film) {
    var cand = city
      ? film.seances.filter(function (s) { return s[2] === city; })
      : film.seances;
    return cand.length ? cand[0] : null;
  }

  // Ville offrant le plus gros « paquet » de films dans une fenêtre de 3 jours
  // (le week-end groupable). On prend, par film et par ville, sa séance la plus
  // tôt dans cette ville, puis la plus grande fenêtre glissante de 3 jours.
  function groupable(films) {
    var byCity = {};
    films.forEach(function (f) {
      f.seances.forEach(function (s) {
        var c = s[2]; if (!c) return;
        byCity[c] = byCity[c] || {};
        if (!(f.u in byCity[c])) byCity[c][f.u] = s[0].slice(0, 10); // 1re séance du film ici
      });
    });
    var best = null;
    Object.keys(byCity).forEach(function (c) {
      var dates = Object.keys(byCity[c]).map(function (u) { return byCity[c][u]; }).sort();
      var i = 0, n = 0;
      for (var j = 0; j < dates.length; j++) {
        while ((new Date(dates[j]) - new Date(dates[i])) / 86400000 > 3) i++;
        if (j - i + 1 > n) n = j - i + 1;
      }
      if (n >= 2 && (!best || n > best.n)) best = { city: c, n: n };
    });
    return best;
  }

  function card(film, s, groupedCity) {
    var art = document.createElement("article");
    art.className = "movie-card";
    var a = document.createElement("a");
    a.href = film.u;
    if (film.p) {
      var img = document.createElement("img");
      img.src = film.p; img.alt = ""; img.loading = "lazy";
      a.appendChild(img);
    } else {
      var ph = document.createElement("span"); ph.className = "noposter"; ph.textContent = "🎞️";
      a.appendChild(ph);
    }
    art.appendChild(a);

    var info = document.createElement("div");
    info.className = "movie-info";
    var h = document.createElement("h3");
    var ha = document.createElement("a"); ha.href = film.u; ha.textContent = film.t;
    h.appendChild(ha); info.appendChild(h);

    var meta = document.createElement("p");
    meta.className = "meta";
    if (film.r) {
      var note = document.createElement("span"); note.className = "note-lb"; note.textContent = film.r;
      var sur = document.createElement("span"); sur.className = "sur"; sur.textContent = "/5";
      note.appendChild(sur); meta.appendChild(note); meta.appendChild(document.createTextNode(" · "));
    }
    meta.appendChild(document.createTextNode(frDate(s[0].slice(0, 10)) + " à " + s[0].slice(11, 16)));
    info.appendChild(meta);

    var line = document.createElement("p");
    line.className = "seance-line";
    var lieu = s[2] ? s[1] + ", " + s[2] : s[1];
    line.appendChild(document.createTextNode("📍 " + lieu));
    var others = film.seances.length - 1;
    if (others > 0) {
      var more = document.createElement("span");
      more.className = "cine-more";
      more.textContent = " · +" + others + " autre" + (others > 1 ? "s" : "") + " séance" + (others > 1 ? "s" : "");
      line.appendChild(more);
    }
    if (s[5] && /^https?:\/\//i.test(s[5])) {
      line.appendChild(document.createTextNode(" · "));
      var book = document.createElement("a");
      book.className = "seance-book"; book.href = s[5];
      book.target = "_blank"; book.rel = "noopener noreferrer"; book.textContent = "Réserver ↗";
      line.appendChild(book);
    }
    info.appendChild(line);
    if (groupedCity && s[2] === groupedCity) art.classList.add("cine-grouped");
    art.appendChild(info);
    return art;
  }

  function render() {
    result.textContent = "";
    var films = current.films.slice();

    // séance affichée par film (selon le filtre ville), puis on écarte ceux qui
    // n'ont rien dans la ville choisie.
    var shown = [];
    films.forEach(function (f) {
      var s = pick(f);
      if (s) shown.push({ film: f, s: s });
    });
    shown.sort(function (x, y) {
      if (order === "note") return (y.film.r || 0) - (x.film.r || 0);
      return byStart(x.s, y.s);
    });

    if (!shown.length) {
      var none = document.createElement("p");
      none.className = "wl-summary";
      none.textContent = "Aucune séance dans cette ville. Choisis une autre ville.";
      result.appendChild(none);
      return;
    }

    // ---- insight ----
    var cities = {};
    current.films.forEach(function (f) {
      f.seances.forEach(function (s) { if (s[2]) cities[s[2]] = 1; });
    });
    var nCities = Object.keys(cities).length;
    var last = current.films.map(function (f) { return f.seances[0][0].slice(0, 10); }).sort().pop();
    var grp = groupable(current.films);

    var box = document.createElement("div");
    box.className = "cine-insight";
    var big = document.createElement("p");
    big.className = "cine-big";
    big.innerHTML = "Tu peux voir <b>" + current.films.length + "</b> film"
      + (current.films.length > 1 ? "s" : "") + " de " + escapeText(current.name)
      + " sur grand écran d'ici le <b>" + frLong(last) + "</b>, dans <b>" + nCities + "</b> ville"
      + (nCities > 1 ? "s" : "") + "."
      + (grp ? " " + grp.n + " sont groupables à " + escapeText(grp.city) + "." : "");
    box.appendChild(big);
    result.appendChild(box);

    // ---- controls ----
    var ctr = document.createElement("div");
    ctr.className = "cine-controls";
    ctr.appendChild(seg("Ordre", [
      { v: "chrono", l: "Chronologique" }, { v: "note", l: "Par note" }
    ], order, function (v) { order = v; render(); }));
    var cityOpts = [{ v: "", l: "Toute la France" }].concat(
      Object.keys(cities).sort(function (a, b) { return a.localeCompare(b, "fr"); })
        .map(function (c) { return { v: c, l: c }; }));
    ctr.appendChild(seg("Où", cityOpts, city, function (v) { city = v; render(); }, true));
    result.appendChild(ctr);

    // ---- timeline ----
    var grid = document.createElement("div");
    grid.className = "grid cine-grid";
    var grpCity = grp ? grp.city : null;
    shown.forEach(function (o) { grid.appendChild(card(o.film, o.s, grpCity)); });
    result.appendChild(grid);

    // ---- export ----
    var foot = document.createElement("div");
    foot.className = "cine-export";
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "bouton";
    btn.textContent = "＋ Ajouter ces " + shown.length + " séances à mon agenda";
    btn.addEventListener("click", function () { downloadIcs(current.name, shown); });
    foot.appendChild(btn);
    var note = document.createElement("p");
    note.className = "meta";
    note.textContent = "Un fichier .ics à ouvrir dans Google Agenda, Apple Calendrier ou Outlook. "
      + "Chaque séance devient un événement daté, avec le cinéma et le lien de réservation.";
    foot.appendChild(note);
    result.appendChild(foot);
  }

  // Menu de segments (réutilise le style des filtres de liste).
  function seg(label, opts, active, onPick, scroll) {
    var wrap = document.createElement("span");
    wrap.className = "cine-seg-group";
    var lab = document.createElement("span");
    lab.className = "ctl-label"; lab.textContent = label;
    wrap.appendChild(lab);
    var bar = document.createElement(scroll ? "div" : "span");
    bar.className = "cine-segbar";
    opts.forEach(function (o) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "cine-seg"; b.textContent = o.l;
      b.setAttribute("aria-pressed", o.v === active ? "true" : "false");
      b.addEventListener("click", function () { onPick(o.v); });
      bar.appendChild(b);
    });
    wrap.appendChild(bar);
    return wrap;
  }

  // ---- .ics généré côté client ----
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function icsEsc(s) {
    return String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;")
      .replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  }
  function stampNow() {
    var d = new Date();
    return d.getUTCFullYear() + pad(d.getUTCMonth() + 1) + pad(d.getUTCDate()) + "T"
      + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + pad(d.getUTCSeconds()) + "Z";
  }
  function plus2h(start) {
    var d = start.slice(0, 10).split("-").map(Number);
    var t = start.slice(11, 16).split(":").map(Number);
    var dt = new Date(Date.UTC(d[0], d[1] - 1, d[2], t[0] + 2, t[1])); // arithmétique UTC = reste flottant
    return dt.getUTCFullYear() + pad(dt.getUTCMonth() + 1) + pad(dt.getUTCDate()) + "T"
      + pad(dt.getUTCHours()) + pad(dt.getUTCMinutes()) + "00";
  }
  function downloadIcs(name, shown) {
    var lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Seanceo//Cinematheque//FR",
      "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
      "X-WR-CALNAME:" + icsEsc("Cinémathèque " + name), "X-WR-TIMEZONE:Europe/Paris"
    ];
    shown.forEach(function (o, i) {
      var s = o.s; // [start, cinema, city, lat, lon, booking]
      var dtStart = s[0].replace(/[-:]/g, "").slice(0, 13) + "00"; // 2026-08-16T20:00 -> 20260816T200000
      var loc = s[2] ? s[1] + ", " + s[2] : s[1];
      var desc = (s[5] ? "Réserver : " + s[5] + "\\n" : "")
        + "Fiche : " + location.origin + o.film.u;
      lines.push("BEGIN:VEVENT",
        "UID:cine-" + i + "-" + dtStart + "@seanceo",
        "DTSTAMP:" + stampNow(),
        "DTSTART:" + dtStart,
        "DTEND:" + plus2h(s[0]),
        "SUMMARY:" + icsEsc("🎬 " + o.film.t),
        "LOCATION:" + icsEsc(loc),
        "DESCRIPTION:" + icsEsc(desc),
        "URL:" + (s[5] || (location.origin + o.film.u)),
        "END:VEVENT");
    });
    lines.push("END:VCALENDAR", "");
    var blob = new Blob([lines.join("\r\n")], { type: "text/calendar;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "cinematheque-" + LB.empreinte(name) + ".ics";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function escapeText(s) {
    var d = document.createElement("span"); d.textContent = s; return d.innerHTML;
  }

  // ---- point d'entrée : sélection d'un réalisateur ----
  function setStatus(text, kind) {
    statusEl.innerHTML = '<p class="' + (kind === "err" ? "wl-erreur" : "wl-summary") + '"></p>';
    statusEl.querySelector("p").textContent = text;
  }

  function assemble(query) {
    loadIndexes().then(function () {
      var key = LB.empreinte(query);
      var dir = _dirByKey[key];
      if (!dir) {
        setStatus("Ce réalisateur n'a pas (ou plus) au moins deux films de répertoire à l'affiche. "
          + "Choisis-en un dans la liste.", "err");
        result.textContent = "";
        return;
      }
      order = "chrono"; city = "";
      current = { name: dir.name, key: dir.key, films: gather(dir.key) };
      if (input) input.value = dir.name;
      setStatus("Rétrospective " + dir.name + " — " + current.films.length
        + " films de répertoire à l'affiche.", "");
      render();
    }).catch(function () {
      setStatus("Chargement impossible. Réessaie.", "err");
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = (input.value || "").trim();
    if (q) assemble(q);
  });
  var chips = document.querySelectorAll(".cine-chip");
  for (var i = 0; i < chips.length; i++) {
    chips[i].addEventListener("click", function () { assemble(this.dataset.dir); });
  }

  // ?d=<réalisateur> : pré-sélection depuis les pages de rétrospective.
  var m = /[?&]d=([^&]+)/.exec(location.search);
  if (m) {
    try { assemble(decodeURIComponent(m[1].replace(/\+/g, " "))); } catch (e) {}
  }
})();
