/* Séancéo — pont Letterboxd « par pseudo »
   =========================================

   Le visiteur donne son PSEUDO Letterboxd ; on récupère sa watchlist publique
   (via le Worker `worker/`) et on la croise avec l'index des séances. Plus
   besoin d'exporter un fichier CSV.

   ⚠️ MODE MOCK pour l'instant : le Worker n'est pas encore déployé, donc
   `sync()` renvoie une fausse watchlist. SEUL LE RÉSEAU est simulé — le
   croisement, le stockage et l'affichage ci-dessous sont le vrai code, celui
   qui tournera en prod. Pour passer en réel : déployer le Worker (voir
   worker/README.md), coller son URL dans WORKER_URL, et mettre MOCK = false.

   Ce fichier est chargé sur TOUTES les pages (via `page()` dans build_site.py) :
   il expose `window.LB` (utilisé par lb-watchlist.js sur /ma-watchlist/) et
   affiche le PORTAIL d'accueil. Le portail est construit ENTIÈREMENT en
   JavaScript, donc il n'existe pas dans le HTML source : Googlebot ne le voit
   pas, il ne peut pas bloquer le premier rendu ni gêner l'indexation. */

(function () {
  "use strict";

  // —— Configuration ————————————————————————————————————————————————————————

  // Worker déployé (worker/, Cloudflare). MOCK = false → vraies watchlists.
  var WORKER_URL = "https://seanceo-watchlist.keenzzz.workers.dev";
  var MOCK = false;

  var KEY = "seanceo.lb"; // une seule entrée localStorage (objet JSON)
  var USER_RE = /^[a-z0-9_-]{1,40}$/;

  // Empreinte STRICTEMENT identique à watchlist.js et à lb_slug_key() (Python) :
  // NFKD → on retire le non-ASCII → on ne garde que [a-z0-9] collés. C'est la
  // clé qui fait matcher le slug anglais « the-leopard » avec « Le Guépard ».
  function empreinte(s) {
    return (s || "").normalize("NFKD")
      .replace(/[^\x00-\x7F]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  // —— Stockage local ———————————————————————————————————————————————————————
  // { user, films:[{slug,name,year}], at:<ms>, seen:true } — `seen` seul = le
  // visiteur a fermé le portail sans se connecter (on ne le rouvre plus).

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "null"); }
    catch (e) { return null; }
  }
  function save(obj) {
    try { localStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) {}
  }
  function patch(fields) {
    var s = load() || {};
    for (var k in fields) if (Object.prototype.hasOwnProperty.call(fields, k)) s[k] = fields[k];
    save(s);
    return s;
  }
  function clear() { try { localStorage.removeItem(KEY); } catch (e) {} }

  // —— Récupération de la watchlist (mock ou Worker réel) ————————————————————

  function sync(username) {
    var user = (username || "").trim().toLowerCase();
    if (!USER_RE.test(user)) return Promise.reject({ error: "invalid_username" });
    if (MOCK) return mockSync(user);
    return fetch(WORKER_URL + "/watchlist/" + encodeURIComponent(user))
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

  // Fausse watchlist : des slugs qui EXISTENT dans l'index (pour voir de vrais
  // matchs multilingues) mêlés à d'autres qui n'y sont pas. C'est exactement le
  // format que le Worker renverra.
  var MOCK_FILMS = [
    { slug: "tuner", name: "Tuner", year: "2025" },
    { slug: "blue-heron", name: "Blue Heron", year: "2025" },
    { slug: "toy-story-5", name: "Toy Story 5", year: "2026" },
    { slug: "parallel-tales", name: "Parallel Tales", year: "2026" },
    { slug: "the-invite-2026", name: "The Invite", year: "2026" },
    { slug: "fjord-2026", name: "Fjord", year: "2026" },
    { slug: "all-of-a-sudden-2026", name: "All of a Sudden", year: "2026" },
    { slug: "the-leopard", name: "The Leopard", year: "1963" },
    { slug: "dune-part-three", name: "Dune: Part Three", year: "2026" },
    { slug: "the-great-beyond", name: "The Great Beyond", year: "2027" },
    { slug: "saturn-return", name: "Saturn Return", year: "2025" },
    { slug: "digger-2026", name: "Digger", year: "2026" }
  ];
  // Les 4 films préférés (section profil). Ceux qui repassent sont mis en avant
  // « à revoir ». La vraie watchlist de « dave » sert d'exemple : ses favoris
  // matchent l'index et montrent le croisement multilingue (high-and-low →
  // « Entre le ciel et l'enfer »).
  var MOCK_FAVORITES = [
    { slug: "high-and-low", name: "High and Low", year: "1963" },
    { slug: "burning-2018", name: "Burning", year: "2018" },
    { slug: "my-neighbor-totoro", name: "My Neighbor Totoro", year: "1988" },
    { slug: "mulholland-drive", name: "Mulholland Drive", year: "2001" }
  ];

  function mockSync(user) {
    return new Promise(function (resolve, reject) {
      setTimeout(function () {
        // Pseudos magiques pour tester les cas limites tant qu'on est en mock :
        //   notfound → 404, oops → erreur serveur, private → watchlist privée.
        if (user === "notfound") return reject({ error: "not_found" });
        if (user === "oops") return reject({ error: "upstream_error" });
        if (user === "private") {
          return resolve({ ok: true, user: user, count: 0, total: 0, empty: true,
                           private: true, favorites: MOCK_FAVORITES, films: [], mock: true });
        }
        if (user === "vide" || user === "empty") {
          return resolve({ ok: true, user: user, count: 0, total: 0, empty: true,
                           private: false, favorites: MOCK_FAVORITES, films: [], mock: true });
        }
        resolve({ ok: true, user: user, count: MOCK_FILMS.length, total: MOCK_FILMS.length,
                  favorites: MOCK_FAVORITES, films: MOCK_FILMS, mock: true });
      }, 600); // latence réseau simulée
    });
  }

  // —— Index des séances + croisement ————————————————————————————————————————

  var _index = null;
  function loadIndex(url) {
    if (_index) return Promise.resolve(_index);
    return fetch(url).then(function (r) { return r.json(); })
      .then(function (d) { _index = d; return d; });
  }

  function cross(films, index) {
    var hits = [], seen = {};
    (films || []).forEach(function (f) {
      // Clé primaire = empreinte du slug (la plus fiable) ; repli sur le titre.
      var m = index[empreinte(f.slug)]
           || index[empreinte(f.name) + (f.year || "")]
           || index[empreinte(f.name)];
      if (m && !seen[m.u]) { seen[m.u] = 1; hits.push(m); }
    });
    // Prochaine séance d'abord (ce qu'on peut voir le plus tôt), mieux notés à
    // date égale — même tri que l'import CSV.
    hits.sort(function (a, b) { return a.d < b.d ? -1 : a.d > b.d ? 1 : (b.r - a.r); });
    return hits;
  }

  // —— Rendu (mêmes classes CSS que watchlist.js) ————————————————————————————

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

  function card(f) {
    var art = document.createElement("article");
    art.className = "movie-card";
    var poster = f.p
      ? '<a href="' + f.u + '"><img src="' + f.p + '" alt="" loading="lazy"></a>'
      : '<a href="' + f.u + '"><span class="noposter">🎞️</span></a>';
    var note = f.r ? '<span class="note-lb">' + f.r + '<span class="sur">/5</span></span> · ' : "";
    var salles = f.n + (f.n > 1 ? " cinémas" : " cinéma");
    // innerHTML ne reçoit que des valeurs de NOTRE index (jamais le pseudo saisi).
    art.innerHTML =
      poster +
      '<div class="movie-info">' +
      '<h3><a href="' + f.u + '"></a></h3>' +
      '<p class="meta">' + note + salles + ' · prochaine séance ' + frDate(f.d) + '</p>' +
      "</div>";
    art.querySelector("h3 a").textContent = f.t; // titre en textContent, ceinture+bretelles
    return art;
  }

  function grid(hits) {
    var g = document.createElement("div");
    g.className = "grid";
    hits.forEach(function (f) { g.appendChild(card(f)); });
    return g;
  }

  // Rendu complet dans `container` à partir de la réponse (mock ou Worker) et de
  // l'index. En tête : les FAVORIS qui repassent (« à revoir ») ; puis la
  // watchlist, ou un message si elle est vide/privée. Renvoie les compteurs pour
  // que l'appelant compose son propre résumé (portail, barre d'état).
  function render(container, data, index) {
    container.textContent = "";
    var favHits = cross(data.favorites || [], index);
    var favUrls = {};
    favHits.forEach(function (f) { favUrls[f.u] = 1; });
    // Un film à la fois dans les favoris ET la watchlist ne s'affiche qu'en favori.
    var listHits = cross(data.films || [], index).filter(function (f) { return !favUrls[f.u]; });

    if (favHits.length) {
      var sec = document.createElement("section");
      sec.className = "lb-favs";
      var h = document.createElement("h3");
      h.textContent = "⭐ " + (favHits.length > 1
        ? "Tes films préférés à revoir en salle"
        : "Un de tes films préférés à revoir en salle");
      var sub = document.createElement("p");
      sub.className = "lb-favs-sub";
      sub.textContent = (favHits.length > 1 ? favHits.length + " de tes films préférés repassent"
        : "Un de tes films préférés repasse") + " en ce moment. L'occasion de le revoir sur grand écran.";
      sec.appendChild(h); sec.appendChild(sub); sec.appendChild(grid(favHits));
      container.appendChild(sec);
    }

    if (data.empty) {
      container.appendChild(emptyNote(data));
    } else {
      var titre = document.createElement("p");
      titre.className = "wl-summary";
      if (!listHits.length) {
        titre.textContent = "Aucun de tes " + (data.total || 0) + " films à voir n'est à "
          + "l'affiche pour l'instant. La programmation change souvent, reviens y jeter un œil.";
        container.appendChild(titre);
      } else {
        titre.innerHTML = "<strong>" + listHits.length + "</strong> de tes "
          + (data.total || listHits.length) + " films à voir "
          + (listHits.length > 1 ? "sont" : "est")
          + " à l'affiche. Ouvre une fiche pour voir les séances près de chez toi.";
        container.appendChild(titre);
        container.appendChild(grid(listHits));
      }
    }
    return { list: listHits.length, favs: favHits.length,
             empty: !!data.empty, priv: !!data.private };
  }

  // Message quand la watchlist est vide ou privée (les favoris ont pu s'afficher
  // au-dessus malgré tout). Le pseudo n'est mis qu'en textContent.
  function emptyNote(data) {
    var p = document.createElement("p");
    p.className = "lb-empty";
    if (data.private) {
      p.innerHTML = "La watchlist de <b></b> est <strong>privée</strong>, on ne peut pas la lire. "
        + "Rends-la publique dans les réglages Letterboxd, ou importe ton fichier ci-dessous.";
    } else {
      p.innerHTML = "La watchlist de <b></b> est vide pour l'instant. Ajoute des films à voir "
        + "sur Letterboxd, puis resynchronise.";
    }
    p.querySelector("b").textContent = data.user;
    return p;
  }

  // —— Portail d'accueil ————————————————————————————————————————————————————
  // Construit en JS => absent du HTML source (SEO). Overlay PAR-DESSUS le
  // contenu déjà chargé ; « Continuer sans compte » et Échap le referment.

  function showPortal(indexUrl) {
    var base = indexUrl.replace(/\/watchlist-index\.json.*$/, "");
    var maWatchlist = base + "/ma-watchlist/";
    var prev = document.body.style.overflow;

    var overlay = document.createElement("div");
    overlay.className = "lb-portal";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "lb-portal-h");
    overlay.innerHTML =
      '<div class="lb-portal-card">' +
        '<button type="button" class="lb-close" aria-label="Fermer">×</button>' +
        '<h2 id="lb-portal-h">🎬 Ta watchlist Letterboxd, en salle</h2>' +
        '<p>Entre ton pseudo Letterboxd : on te montre lesquels de tes films à voir ' +
          'repassent au cinéma, et où.</p>' +
        '<form class="lb-field" id="lb-portal-form">' +
          '<input class="lb-input" id="lb-portal-user" type="text" autocomplete="off" ' +
            'autocapitalize="none" spellcheck="false" placeholder="pseudo Letterboxd" ' +
            'aria-label="Ton pseudo Letterboxd">' +
          '<button class="bouton bouton-lb" type="submit">Synchroniser</button>' +
        '</form>' +
        '<p class="lb-msg" id="lb-portal-msg" hidden></p>' +
        '<p class="lb-portal-alt">' +
          '<button type="button" class="lb-secondary" id="lb-portal-skip">Continuer sans compte</button>' +
          '<a href="' + maWatchlist + '">Watchlist privée ? Importer un fichier</a>' +
        '</p>' +
        '<p class="lb-portal-note">On lit seulement ta watchlist <strong>publique</strong>. ' +
          'Rien n\'est stocké côté serveur.</p>' +
      '</div>';

    function close(markSeen) {
      if (markSeen) patch({ seen: true });
      document.body.style.overflow = prev;
      document.removeEventListener("keydown", onKey);
      overlay.remove();
    }
    function onKey(e) { if (e.key === "Escape") close(true); }

    var form = overlay.querySelector("#lb-portal-form");
    var input = overlay.querySelector("#lb-portal-user");
    var msg = overlay.querySelector("#lb-portal-msg");

    overlay.querySelector(".lb-close").addEventListener("click", function () { close(true); });
    overlay.querySelector("#lb-portal-skip").addEventListener("click", function () { close(true); });
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(true); });
    document.addEventListener("keydown", onKey);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var user = input.value.trim();
      showMsg("Lecture de ta watchlist…", "");
      form.querySelector("button").disabled = true;
      sync(user)
        .then(function (data) {
          patch({ user: data.user, films: data.films || [], favorites: data.favorites || [],
                  empty: !!data.empty, private: !!data.private,
                  total: data.total || 0, at: Date.now() });
          // On compte tout de suite ce qui est à l'affiche pour la récompense.
          return loadIndex(indexUrl).then(function (index) {
            var favHits = cross(data.favorites || [], index);
            var favUrls = {}; favHits.forEach(function (f) { favUrls[f.u] = 1; });
            var listHits = cross(data.films || [], index).filter(function (f) { return !favUrls[f.u]; });
            success(data, listHits.length, favHits.length);
          });
        })
        .catch(function (err) {
          form.querySelector("button").disabled = false;
          showMsg(errText(err && err.error), "err");
        });
    });

    function showMsg(text, kind) {
      msg.hidden = false;
      msg.textContent = text;
      msg.className = "lb-msg" + (kind === "err" ? " lb-error" : "");
    }
    function success(data, n, f) {
      var pcard = overlay.querySelector(".lb-portal-card");
      var label = (n || f) ? "Voir où les voir →" : "Ouvrir ma watchlist →";
      pcard.innerHTML =
        '<button type="button" class="lb-close" aria-label="Fermer">×</button>' +
        '<h2></h2>' +
        '<p class="lb-ok-count"></p>' +
        '<p class="lb-field"><a class="bouton bouton-lb" href="' + maWatchlist + '"></a></p>';
      pcard.querySelector("h2").textContent = "✅ Salut " + data.user + " !";
      pcard.querySelector(".bouton-lb").textContent = label;
      var parts = [];
      if (n) parts.push(n + " de tes films à voir " + (n > 1 ? "sont" : "est") + " à l'affiche");
      if (f) parts.push(f + " de tes films préférés à revoir");
      var p = pcard.querySelector(".lb-ok-count");
      if (parts.length) {
        var s = parts.join(" · ");
        p.textContent = s.charAt(0).toUpperCase() + s.slice(1) + ".";
      } else if (data.private) {
        p.textContent = "Ta watchlist est privée : on ne peut pas la lire. Rends-la publique, ou importe ton fichier.";
      } else {
        p.textContent = "Rien de ta liste n'est à l'affiche pour l'instant, mais on la garde.";
      }
      pcard.querySelector(".lb-close").addEventListener("click", function () { close(false); });
    }

    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";
    input.focus();
  }

  function errText(code) {
    if (code === "invalid_username") return "Ce pseudo n'a pas l'air valide (lettres, chiffres, - et _).";
    if (code === "not_found") return "Pseudo introuvable sur Letterboxd. Vérifie l'orthographe.";
    return "Impossible de lire cette watchlist pour l'instant. Réessaie, ou importe ton fichier.";
  }

  // —— API publique + auto-run du portail ————————————————————————————————————

  window.LB = {
    sync: sync, load: load, save: save, patch: patch, clear: clear,
    loadIndex: loadIndex, cross: cross, render: render,
    empreinte: empreinte, errText: errText,
    WORKER_URL: WORKER_URL, MOCK: MOCK
  };

  document.addEventListener("DOMContentLoaded", function () {
    var script = document.getElementById("lb-core");
    var indexUrl = script && script.dataset.index ? script.dataset.index : "/watchlist-index.json";
    var state = load();
    // Déjà connecté (`user`) ou déjà fermé (`seen`) → on ne rouvre pas.
    if (state && (state.user || state.seen)) return;
    // Sur la page dédiée, le portail ferait doublon avec le champ de la page.
    if (/\/ma-watchlist\//.test(location.pathname)) return;
    showPortal(indexUrl);
  });
})();
