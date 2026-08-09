/* Séancéo — pont Letterboxd « par pseudo »
   =========================================

   Le visiteur donne son PSEUDO Letterboxd ; on récupère sa watchlist publique
   (via le Worker `worker/`) et on la croise avec l'index des séances. Plus
   besoin d'exporter un fichier CSV.

   Le Worker est DÉPLOYÉ et `MOCK = false` : `sync()` interroge la vraie
   watchlist (voir WORKER_URL ci-dessous). Le mode MOCK reste dans le code
   (mettre `MOCK = true`) pour développer le croisement/l'affichage sans
   dépendre du réseau — SEUL le réseau y est simulé, tout le reste est le
   vrai code de prod.

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

  // Le piège n°1 du formulaire : sur Letterboxd le NOM AFFICHÉ et l'identifiant
  // de l'URL sont deux choses différentes, et c'est le second qu'il nous faut.
  // Taper le nom affiché tombe souvent sur un homonyme au compte vide, et le
  // visiteur lit « ta watchlist est vide » sans comprendre pourquoi. Ce rappel
  // est repris à l'identique sur /ma-watchlist/ (voir build_site.py).
  var USER_HINT =
    '<p class="lb-hint">C\'est l\'identifiant de l\'<strong>URL</strong> du profil, pas le nom ' +
    'affiché : pour <code>letterboxd.com/<b>cinephile_92</b>/</code>, tape ' +
    '<code>cinephile_92</code>. Les deux diffèrent souvent (à l\'écran « Marie Dupont », ' +
    'dans l\'URL <code>mariedupont__</code>).</p>';

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

  // Ville de cadrage choisie par le visiteur. Stockée par son NOM (lisible, et
  // qui survit à une reconstruction de l'index où les index numériques de `_v`
  // auraient bougé) ; résolue en { nom, key, lat, lon } contre la table de
  // l'index, donc seulement après loadIndex().
  function city() {
    var s = load();
    return s && s.city ? villeParNom(s.city) : null;
  }
  function setCity(nom) { patch({ city: nom || "" }); }

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

  // L'index porte, en plus des films, deux TABLES PARTAGÉES construites au build
  // (voir build_site.py) : `_s` = les salles `[nom, index de ville]`, `_v` = les
  // villes `[nom, lat, lon]`. Chaque film référence ses salles par index dans
  // `k` = `[[index de salle, date de la prochaine séance dans cette salle]]`,
  // trié par date. Tout le cadrage géographique repose là-dessus.
  var _index = null;
  var _salles = [], _villes = [];
  function loadIndex(url) {
    if (_index) return Promise.resolve(_index);
    return fetch(url).then(function (r) { return r.json(); })
      .then(function (d) {
        _index = d;
        _salles = d._s || [];
        _villes = d._v || [];
        return d;
      });
  }

  // Salle par index → { nom, ville, lat, lon }. `null` si l'index est hors table
  // (fichier d'une version antérieure resté en cache, par exemple).
  function salleInfo(i) {
    var s = _salles[i];
    if (!s) return null;
    var v = _villes[s[1]] || ["", null, null];
    return { nom: s[0], ville: v[0], lat: v[1], lon: v[2] };
  }

  // Lien de billetterie d'une séance : le préfixe commun de la salle (`_s[i][2]`)
  // plus le suffixe stocké sur la séance. Le build garantit qu'un suffixe n'est
  // jamais vide quand une billetterie existe, donc `""` veut bien dire « pas de
  // réservation en ligne pour cette séance ».
  function billetterie(salleIdx, suffixe) {
    if (!suffixe) return "";
    var s = _salles[salleIdx];
    return ((s && s[2]) || "") + suffixe;
  }

  // Toutes les villes programmées, triées pour l'autocomplétion du formulaire.
  function villes() {
    return _villes.map(function (v) { return v[0]; })
      .filter(function (n) { return !!n; })
      .sort(function (a, b) { return a.localeCompare(b, "fr"); });
  }

  // Ville connue la plus proche d'un point, pour convertir une géolocalisation
  // en nom de ville (le visiteur raisonne en villes, pas en coordonnées).
  function villeLaPlusProche(lat, lon) {
    var best = null;
    _villes.forEach(function (v) {
      if (!v[0] || v[1] == null) return;
      var d = distKm(lat, lon, v[1], v[2]);
      if (!best || d < best.km) best = { nom: v[0], km: d };
    });
    return best;
  }

  // Retrouve une ville saisie à la main (casse/accents/tirets neutralisés par
  // `empreinte`) → sa fiche { nom, key, lat, lon }, ou null si inconnue.
  function villeParNom(nom) {
    var cible = empreinte(nom);
    if (!cible) return null;
    for (var i = 0; i < _villes.length; i++) {
      if (empreinte(_villes[i][0]) === cible) {
        return { nom: _villes[i][0], key: cible, lat: _villes[i][1], lon: _villes[i][2] };
      }
    }
    return null;
  }

  // —— Autocomplétion de ville (maison, comme film.js) ——————————————————————————
  // Pas de <datalist> : au premier clic elle déroule les 257 villes programmées,
  // c'est-à-dire une liste à PARCOURIR alors que la bonne action est de TAPER
  // deux lettres. Ici rien n'apparaît tant que le visiteur n'a pas tapé
  // MIN_VILLE caractères ; ensuite seules les villes qui correspondent
  // remontent, celles qui COMMENCENT par la saisie d'abord.
  // Le repli des noms passe par `empreinte`, la même fonction que
  // `villeParNom` : ce qui est proposé est donc exactement ce qui sera résolu
  // (« saint e » trouve « Saint-Étienne », accents et tirets neutralisés).
  var MIN_VILLE = 2, MAX_VILLE = 8;

  function autoVille(input, onPick) {
    var noms = villes();
    var plies = noms.map(empreinte);

    // Placeholder posé ICI plutôt que dans les deux gabarits HTML : une seule
    // formulation pour le portail et pour /ma-watchlist/. Même modèle que les
    // champs de ville de l'accueil et de /classiques/ (« Chercher votre
    // ville… »), au tutoiement près, qui est la règle de la section Letterboxd.
    // Pas de compte de villes entre parenthèses, contrairement à ces deux
    // pages : l'index de la watchlist n'en couvre pas tout à fait autant
    // (256 contre 257), et deux nombres différents à l'écran font douter.
    input.placeholder = "Chercher ta ville…";

    // Le menu est positionné par rapport à un conteneur inséré autour du champ :
    // les formulaires hôtes sont en display:flex, un <ul> posé à côté du champ
    // deviendrait un élément de la ligne au lieu de flotter par-dessus.
    var wrap = document.createElement("span");
    wrap.className = "lb-suggest-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var liste = document.createElement("ul");
    liste.className = "lb-suggest";
    liste.setAttribute("role", "listbox");
    liste.hidden = true;
    wrap.appendChild(liste);
    var actif = -1; // suggestion surlignée au clavier

    function fermer() { liste.hidden = true; liste.textContent = ""; actif = -1; }

    function retenir(nom) {
      input.value = nom;
      fermer();
      if (onPick) onPick(nom);
    }

    function proposer() {
      var q = empreinte(input.value);
      fermer();
      if (q.length < MIN_VILLE) return;
      var debut = [], dedans = [];
      for (var i = 0; i < noms.length; i++) {
        var pos = plies[i].indexOf(q);
        if (pos === 0) debut.push(noms[i]);
        else if (pos > 0) dedans.push(noms[i]);
      }
      var trouves = debut.concat(dedans).slice(0, MAX_VILLE);
      if (!trouves.length) return;
      trouves.forEach(function (nom) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.textContent = nom; // textContent : jamais d'injection
        // mousedown, pas click : il part AVANT le blur du champ, qui referme.
        li.addEventListener("mousedown", function (e) { e.preventDefault(); retenir(nom); });
        liste.appendChild(li);
      });
      liste.hidden = false;
    }

    function surligner(items) {
      for (var i = 0; i < items.length; i++) items[i].classList.toggle("active", i === actif);
    }

    input.setAttribute("autocomplete", "off");
    input.removeAttribute("list"); // plus de <datalist>, même si le HTML en portait un
    input.addEventListener("input", proposer);
    input.addEventListener("keydown", function (e) {
      var items = liste.querySelectorAll("li");
      if (e.key === "ArrowDown" && items.length) {
        e.preventDefault(); actif = (actif + 1) % items.length; surligner(items);
      } else if (e.key === "ArrowUp" && items.length) {
        e.preventDefault(); actif = (actif - 1 + items.length) % items.length; surligner(items);
      } else if (e.key === "Enter") {
        // Une suggestion surlignée l'emporte ; sinon on laisse le formulaire
        // valider ce qui est tapé (une ville se résout très bien sans passer
        // par la liste).
        if (items.length && actif >= 0) { e.preventDefault(); retenir(items[actif].textContent); }
        else fermer();
      } else if (e.key === "Escape") {
        fermer();
      }
    });
    // Léger délai : laisse le mousedown d'une suggestion aboutir avant la fermeture.
    input.addEventListener("blur", function () { setTimeout(fermer, 150); });
  }

  // Distance Haversine en km — même formule que map.js, lb-listes.js et le Worker.
  function distKm(lat1, lon1, lat2, lon2) {
    if (lat1 == null || lat2 == null) return Infinity;
    var R = 6371, toRad = function (d) { return d * Math.PI / 180; };
    var dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  // La séance à MONTRER pour un film, selon la ville de cadrage. `k` étant trié
  // par date, la première salle qui correspond est aussi la plus tôt. `cityKey`
  // vide = pas de cadrage, on prend la prochaine séance où qu'elle soit.
  // Renvoie { salle, date, heure, booking, n } (n = nombre de salles retenues),
  // ou null quand le film ne passe pas du tout dans la ville demandée.
  // `heure`/`booking` viennent des positions 2 et 3 des entrées de `k` ; un
  // index d'une version antérieure (resté en cache) n'en a pas, d'où les
  // valeurs par défaut vides plutôt qu'un accès direct.
  function pickSalle(f, cityKey) {
    var ks = f.k || [], choisi = null, n = 0;
    for (var i = 0; i < ks.length; i++) {
      var inf = salleInfo(ks[i][0]);
      if (!inf) continue;
      if (cityKey && empreinte(inf.ville) !== cityKey) continue;
      n++;
      if (!choisi) {
        choisi = { salle: inf, date: ks[i][1], heure: ks[i][2] || "",
                   booking: billetterie(ks[i][0], ks[i][3]) };
      }
    }
    if (!choisi) return null;
    choisi.n = n;
    return choisi;
  }

  // Index AGENDA (facultatif) : le détail séance par séance (heure, salle,
  // ville, billetterie), mais seulement pour le répertoire sur 5 semaines. Il
  // enrichit les cartes quand le film y figure ; watchlist-index reste le socle
  // pour tous les autres. Réindexé par URL de fiche : c'est la seule clé
  // commune sûre entre les deux fichiers (l'empreinte, elle, est dédoublée
  // entre forme complète et forme sans année).
  var _agenda = null;
  function loadAgenda(url) {
    if (!url) return Promise.resolve(null);
    if (_agenda) return Promise.resolve(_agenda);
    return fetch(url).then(function (r) { return r.json(); })
      .then(function (d) {
        var byUrl = {};
        for (var k in d) {
          if (Object.prototype.hasOwnProperty.call(d, k)) byUrl[d[k].u] = d[k];
        }
        _agenda = byUrl;
        return byUrl;
      })
      .catch(function () { return null; }); // bonus : une panne ici ne casse rien
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

  // Dans agenda-index, la séance qui correspond EXACTEMENT à la salle et au jour
  // retenus — c'est elle qui porte l'heure et le lien de billetterie. Prendre
  // `ag.s[0]` à la place donnerait l'heure d'une séance à l'autre bout du pays
  // dès que le visiteur cadre sur sa ville.
  function agSeance(ag, nom, jour) {
    if (!ag || !ag.s) return null;
    for (var i = 0; i < ag.s.length; i++) {
      if (ag.s[i][1] === nom && ag.s[i][0].slice(0, 10) === jour) return ag.s[i];
    }
    return null;
  }

  // Carte film. `pick` = { salle, date, heure, booking, n } choisi par pickSalle
  // (donc déjà cadré sur la ville du visiteur s'il en a donné une) ; `ag` =
  // entrée d'agenda-index, facultative.
  //
  // L'heure et la billetterie sont désormais portées par watchlist-index
  // lui-même (`k`), donc disponibles pour TOUS les films. agenda-index ne sert
  // plus que de repli, le temps qu'un index plus ancien resté en cache soit
  // remplacé : il ne couvre que le répertoire, et c'est exactement ce qui
  // faisait qu'un film récent (Kneecap) n'avait pas de bouton « Réserver »
  // alors que la fiche de son cinéma en proposait un.
  function card(f, ag, pick) {
    if (!pick) pick = pickSalle(f, "");
    var cine = pick && pick.salle.nom;
    var ville = pick && pick.salle.ville;
    var jour = pick ? pick.date : f.d;
    var repli = pick && !pick.heure ? agSeance(ag, cine, jour) : null;
    var heure = (pick && pick.heure) || (repli ? repli[0].slice(11, 16) : "");
    var lien = (pick && pick.booking) || (repli ? repli[5] : "");

    var art = document.createElement("article");
    art.className = "movie-card";
    var poster = f.p
      ? '<a href="' + f.u + '"><img src="' + f.p + '" alt="" loading="lazy"></a>'
      : '<a href="' + f.u + '"><span class="noposter">🎞️</span></a>';
    var note = f.r ? '<span class="note-lb">' + f.r + '<span class="sur">/5</span></span> · ' : "";
    var quand = "prochaine séance " + frDate(jour) + (heure ? " à " + heure : "");
    // Séance unique (champ `x`, posé au build) : le film ne repasse nulle part
    // ailleurs en France sur la fenêtre. Dit platement, sans point
    // d'exclamation ni compte à rebours : le fait se suffit, et c'est
    // justement parce qu'on ne crie jamais que ça se remarque quand on le dit.
    var unique = f.x ? '<p class="wl-unique">Séance unique en France</p>' : "";
    // innerHTML ne reçoit que des valeurs de NOTRE index (jamais le pseudo saisi).
    art.innerHTML =
      poster +
      '<div class="movie-info">' +
      '<h3><a href="' + f.u + '"></a></h3>' +
      '<p class="meta">' + note + quand + '</p>' +
      unique +
      "</div>";
    art.querySelector("h3 a").textContent = f.t; // titre en textContent, ceinture+bretelles

    if (cine) {
      var line = document.createElement("p");
      line.className = "seance-line";
      var lieu = ville ? cine + ", " + ville : cine;
      var autres = pick.n - 1;
      if (autres > 0) lieu += " + " + autres + (autres > 1 ? " autres cinémas" : " autre cinéma");
      line.appendChild(document.createTextNode("📍 " + lieu)); // textContent : noms de salles
      // Billetterie : nouvel onglet, et seulement si l'URL est bien en http(s).
      if (lien && /^https?:\/\//i.test(lien)) {
        line.appendChild(document.createTextNode(" · "));
        var book = document.createElement("a");
        book.className = "seance-book";
        book.href = lien;
        book.target = "_blank";
        book.rel = "noopener noreferrer";
        book.textContent = "Réserver ↗";
        line.appendChild(book);
      }
      art.querySelector(".movie-info").appendChild(line);
    }
    return art;
  }

  // `cityKey` vide = pas de cadrage. Les films sont re-triés sur la date de LEUR
  // séance dans cette ville : cadré sur Nancy, un film qui y passe demain doit
  // précéder celui qui y passe dans trois semaines, quel que soit l'ordre national.
  function grid(hits, ag, cityKey) {
    var g = document.createElement("div");
    g.className = "grid";
    hits.map(function (f) { return { f: f, pick: pickSalle(f, cityKey || "") }; })
      .filter(function (o) { return !!o.pick; })
      .sort(function (a, b) {
        return a.pick.date < b.pick.date ? -1 : a.pick.date > b.pick.date ? 1 : (b.f.r - a.f.r);
      })
      .forEach(function (o) { g.appendChild(card(o.f, ag && ag[o.f.u], o.pick)); });
    return g;
  }

  // Parmi `hits`, la ville la plus proche de `city` où au moins un film passe.
  // Sert quand la ville du visiteur ne programme rien de sa watchlist : plutôt
  // que de le renvoyer à une liste nationale, on lui désigne où aller.
  function villeProcheAvecFilm(hits, city) {
    if (!city || city.lat == null) return null;
    var best = null;
    hits.forEach(function (f) {
      (f.k || []).forEach(function (ks) {
        var inf = salleInfo(ks[0]);
        if (!inf || !inf.ville || inf.lat == null) return;
        var key = empreinte(inf.ville);
        if (key === city.key) return; // sa propre ville : déjà traitée
        var km = distKm(city.lat, city.lon, inf.lat, inf.lon);
        if (!best || km < best.km) best = { nom: inf.ville, key: key, km: km };
      });
    });
    return best;
  }

  // Rendu complet dans `container` à partir de la réponse (mock ou Worker) et de
  // l'index. En tête : les FAVORIS qui repassent (« à revoir ») ; puis la
  // watchlist, ou un message si elle est vide/privée. Renvoie les compteurs pour
  // que l'appelant compose son propre résumé (portail, barre d'état).
  // « hors de Albi » → « hors d'Albi ». Les noms de villes françaises commençant
  // par une voyelle sont assez nombreux (Albi, Angers, Orléans, Épinal…) pour
  // que l'absence d'élision se remarque.
  function deVille(nom) {
    return (/^[aeiouyàâäéèêëîïôöùûü]/i.test(nom || "") ? "d'" : "de ") + nom;
  }

  // Petite section titrée + grille, le motif répété par le rendu géographique.
  function section(cls, titre, sousTitre, hits, ag, cityKey) {
    var sec = document.createElement("section");
    sec.className = cls;
    var h = document.createElement("h3");
    h.textContent = titre;
    sec.appendChild(h);
    if (sousTitre) {
      var sub = document.createElement("p");
      sub.className = "lb-sec-sub";
      sub.textContent = sousTitre;
      sec.appendChild(sub);
    }
    sec.appendChild(grid(hits, ag, cityKey));
    return sec;
  }

  // Sépare `hits` entre ce qui passe dans la ville de cadrage et le reste.
  function parVille(hits, cityKey) {
    var ici = [], ailleurs = [];
    hits.forEach(function (f) {
      (pickSalle(f, cityKey) ? ici : ailleurs).push(f);
    });
    return { ici: ici, ailleurs: ailleurs };
  }

  function render(container, data, index, ag, city) {
    container.textContent = "";
    var cityKey = city ? city.key : "";
    var favHits = cross(data.favorites || [], index);
    var favUrls = {};
    favHits.forEach(function (f) { favUrls[f.u] = 1; });
    // Un film à la fois dans les favoris ET la watchlist ne s'affiche qu'en favori.
    var listHits = cross(data.films || [], index).filter(function (f) { return !favUrls[f.u]; });
    // Les favoris qui passent dans la ville du visiteur : calculés tôt, parce
    // que le verdict sur sa ville en dépend (dire « rien à Paris » alors qu'un
    // favori y repasse serait faux).
    var favIci = (favHits.length && cityKey) ? parVille(favHits, cityKey).ici : [];

    // ⚠️ ORDRE DE LA PAGE : le verdict sur SA ville passe AVANT les favoris.
    // Les favoris ne sont jamais filtrés par ville (voir plus bas) ; placés en
    // tête, ils annonçaient une séance à Nantes à quelqu'un qui venait de
    // demander Paris, et ce n'est qu'en dessous qu'il apprenait qu'il n'y avait
    // rien chez lui. On répond d'abord à la question posée (« et chez moi ? »),
    // les séances lointaines viennent après. D'où cette section construite ici
    // mais insérée par `ajouteFavoris()` au bon moment dans chaque branche.
    function ajouteFavoris() {
      if (!favHits.length) return;
      // Les favoris ne sont JAMAIS filtrés par ville : ils sont rares (4 films
      // au maximum) et « un de tes films préférés repasse, à 60 km » reste une
      // information qu'on veut donner. Ils sont seulement cadrés quand c'est
      // possible, pour montrer la séance la plus pertinente.
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
      sec.appendChild(h); sec.appendChild(sub);
      // Cadrage par film : ceux qui passent dans la ville le montrent, les
      // autres gardent leur séance nationale (d'où les deux grilles).
      if (favIci.length) sec.appendChild(grid(favIci, ag, cityKey));
      var favAilleurs = favHits.filter(function (f) { return favIci.indexOf(f) < 0; });
      if (favAilleurs.length) sec.appendChild(grid(favAilleurs, ag, ""));
      container.appendChild(sec);
    }

    var compte = { list: listHits.length, ici: 0, favs: favHits.length,
                   empty: !!data.empty, priv: !!data.private, city: city ? city.nom : "" };

    if (data.empty) {
      container.appendChild(emptyNote(data));
      ajouteFavoris();
      return compte;
    }

    var titre = document.createElement("p");
    titre.className = "wl-summary";
    // On nomme la source (« de ta watchlist ») : la page affiche aussi les
    // favoris du profil juste au-dessus, « tes films à voir » ne disait pas
    // de quelle des deux listes venait le compte.
    if (!listHits.length) {
      titre.textContent = "Aucun des " + (data.total || 0) + " films de ta watchlist "
        + "Letterboxd n'est à l'affiche pour l'instant. La programmation change "
        + "souvent, reviens y jeter un œil.";
      container.appendChild(titre);
      ajouteFavoris();
      return compte;
    }

    // —— Sans ville : la vue nationale. Rien à dire sur « chez moi » puisqu'on
    // ne sait pas où c'est, mais le compte de la watchlist reste en tête.
    if (!city) {
      titre.innerHTML = "<strong>" + listHits.length + "</strong> des "
        + (data.total || listHits.length) + " films de ta watchlist Letterboxd "
        + (listHits.length > 1 ? "sont" : "est")
        + " à l'affiche. Ouvre une fiche pour voir toutes les séances près de chez toi.";
      container.appendChild(titre);
      ajouteFavoris();
      container.appendChild(grid(listHits, ag, ""));
      return compte;
    }

    // —— Avec ville : sa ville d'abord, le reste en second rideau.
    var split = parVille(listHits, cityKey);
    compte.ici = split.ici.length;
    titre.innerHTML = "<strong>" + listHits.length + "</strong> des "
      + (data.total || listHits.length) + " films de ta watchlist Letterboxd "
      + (listHits.length > 1 ? "sont" : "est") + " à l'affiche en France.";
    container.appendChild(titre);

    if (split.ici.length) {
      container.appendChild(section("lb-ici", "🎬 À " + city.nom,
        split.ici.length + (split.ici.length > 1 ? " films de ta watchlist passent"
          : " film de ta watchlist passe") + " près de chez toi.",
        split.ici, ag, cityKey));
    } else {
      // Rien dans sa ville : on ne le renvoie pas à une liste nationale, on lui
      // désigne la ville la plus proche qui programme un de ses films.
      var proche = villeProcheAvecFilm(listHits, city);
      var vide = document.createElement("section");
      vide.className = "lb-ici lb-ici-vide";
      var hv = document.createElement("h3");
      // Un favori peut passer dans sa ville alors que sa watchlist n'y a rien :
      // un « Rien à Paris » sec serait alors démenti par la section des favoris
      // juste en dessous. On précise donc de quelle liste on parle.
      hv.textContent = favIci.length
        ? "Rien de ta watchlist à " + city.nom + " pour l'instant"
        : "Rien à " + city.nom + " pour l'instant";
      vide.appendChild(hv);
      if (favIci.length) {
        var pf = document.createElement("p");
        pf.className = "lb-sec-sub";
        pf.textContent = "En revanche, " + (favIci.length > 1
          ? favIci.length + " de tes films préférés y repassent"
          : "un de tes films préférés y repasse") + ", juste en dessous.";
        vide.appendChild(pf);
      }
      if (proche) {
        var pv = document.createElement("p");
        pv.className = "lb-sec-sub";
        pv.textContent = "La ville la plus proche où un film de ta watchlist repasse est "
          + proche.nom + ", à environ " + Math.round(proche.km) + " km.";
        vide.appendChild(pv);
        var procheHits = parVille(listHits, proche.key).ici;
        vide.appendChild(grid(procheHits, ag, proche.key));
        // Mis en avant ici, ils ne doivent pas réapparaître dans « Ailleurs ».
        split.ailleurs = split.ailleurs.filter(function (f) {
          return procheHits.indexOf(f) < 0;
        });
      } else {
        var pn = document.createElement("p");
        pn.className = "lb-sec-sub";
        pn.textContent = "Aucun film de ta watchlist ne repasse à proximité. "
          + "Voici ce qui passe ailleurs en France.";
        vide.appendChild(pn);
      }
      container.appendChild(vide);
    }

    // Les favoris seulement MAINTENANT : le visiteur sait déjà ce qu'il en est
    // dans sa ville, une séance à 400 km ne peut plus passer pour une réponse.
    ajouteFavoris();

    if (split.ailleurs.length) {
      container.appendChild(section("lb-ailleurs", "Ailleurs en France",
        split.ailleurs.length + (split.ailleurs.length > 1
          ? " autres films de ta watchlist repassent" : " autre film de ta watchlist repasse")
          + " hors " + deVille(city.nom) + ".",
        split.ailleurs, ag, ""));
    }
    return compte;
  }

  // Message quand la watchlist est vide ou privée (les favoris ont pu s'afficher
  // au-dessus malgré tout). Le pseudo n'est mis qu'en textContent.
  function emptyNote(data) {
    var p = document.createElement("p");
    p.className = "lb-empty";
    if (data.private) {
      p.innerHTML = "La watchlist de <b class=\"lb-who\"></b> est <strong>privée</strong>, on ne peut pas la lire. "
        + "Rends-la publique dans les réglages Letterboxd, ou importe ton fichier ci-dessous.";
    } else {
      // Cas très fréquent en vrai : le visiteur a tapé le NOM AFFICHÉ et est
      // tombé sur un homonyme au compte vide. On le dit ici, pas seulement
      // au-dessus du champ, parce que c'est le moment où il se pose la question.
      p.innerHTML = "La watchlist de <b class=\"lb-who\"></b> est vide pour l'instant. Ajoute des films à voir "
        + "sur Letterboxd, puis resynchronise. Si tu t'attendais à y trouver des films, "
        + "vérifie le pseudo : c'est celui de l'URL du profil "
        + "(<code>letterboxd.com/<b class=\"lb-eg\">cinephile_92</b>/</code>), pas le nom affiché.";
    }
    p.querySelector(".lb-who").textContent = data.user;
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
        '<h2 id="lb-portal-h">🎬 Letterboxd + Séancéo</h2>' +
        '<p>Entre ton pseudo Letterboxd : on te montre lesquels de tes films à voir ' +
          'repassent au cinéma, et on te recommande des reprises selon tes ' +
          '<strong>réalisateurs préférés</strong>.</p>' +
        '<form class="lb-field" id="lb-portal-form">' +
          '<input class="lb-input" id="lb-portal-user" type="text" autocomplete="off" ' +
            'autocapitalize="none" spellcheck="false" placeholder="pseudo Letterboxd" ' +
            'aria-label="Ton pseudo Letterboxd">' +
          '<button class="bouton bouton-lb" type="submit">Synchroniser</button>' +
        '</form>' +
        USER_HINT +
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
          // Signale la connexion : l'accueil (lb-reco.js) affiche alors les
          // recommandations par réalisateur sans rechargement.
          document.dispatchEvent(new CustomEvent("seanceo:lb-connected", { detail: data }));
          // On compte tout de suite ce qui est à l'affiche pour la récompense.
          return loadIndex(indexUrl).then(function (index) {
            var favHits = cross(data.favorites || [], index);
            var favUrls = {}; favHits.forEach(function (f) { favUrls[f.u] = 1; });
            var listHits = cross(data.films || [], index).filter(function (f) { return !favUrls[f.u]; });
            // Étape 2 : la ville. Sans elle, « 32 films à l'affiche » veut dire
            // « quelque part en France » — inexploitable. On ne la demande que
            // maintenant : demander deux choses avant le moindre résultat
            // ferait abandonner, là le visiteur a déjà vu que ça marche.
            askCity(data, listHits, favHits);
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
    // Étape 2 du portail : la ville. Le champ est libre, avec des suggestions
    // qui n'apparaissent qu'au fil de la frappe (`autoVille`) ; `villeParNom`
    // neutralise casse et accents à la validation. Le bouton de géolocalisation
    // ne fait que convertir la position en nom de ville, dans le navigateur —
    // rien n'est envoyé au site.
    function askCity(data, listHits, favHits) {
      var n = listHits.length, f = favHits.length;
      if (!n && !f) { success(data, listHits, favHits, null); return; } // rien à cadrer
      var pcard = overlay.querySelector(".lb-portal-card");
      pcard.innerHTML =
        '<button type="button" class="lb-close" aria-label="Fermer">×</button>' +
        '<h2></h2>' +
        '<p class="lb-ok-count"></p>' +
        '<p>Dans quelle <strong>ville</strong> cherches-tu ? On te montrera d\'abord ' +
          'ce qui passe près de chez toi, plutôt que partout en France.</p>' +
        '<form class="lb-field" id="lb-city-form">' +
          // Placeholder posé par autoVille (il connaît le nombre de villes).
          '<input class="lb-input" id="lb-city-input" type="text" autocomplete="off" ' +
            'spellcheck="false" aria-label="Ta ville">' +
          '<button class="bouton bouton-lb" type="submit">Continuer</button>' +
        '</form>' +
        '<p class="lb-msg" id="lb-city-msg" hidden></p>' +
        '<p class="lb-portal-alt">' +
          '<button type="button" class="lb-secondary" id="lb-city-geo">📍 me localiser</button>' +
          '<button type="button" class="lb-secondary" id="lb-city-skip">Voir toute la France</button>' +
        '</p>';
      pcard.querySelector("h2").textContent = "✅ Salut " + data.user + " !";
      var parts = [];
      if (n) parts.push(n + " film" + (n > 1 ? "s" : "") + " de ta watchlist "
        + (n > 1 ? "sont" : "est") + " à l'affiche en France");
      if (f) parts.push(f + " de tes films préférés à revoir");
      var s0 = parts.join(" · ");
      pcard.querySelector(".lb-ok-count").textContent =
        s0.charAt(0).toUpperCase() + s0.slice(1) + ".";

      var cmsg = pcard.querySelector("#lb-city-msg");
      var cin = pcard.querySelector("#lb-city-input");
      var geo = pcard.querySelector("#lb-city-geo");
      function cityMsg(t, kind) {
        cmsg.hidden = false; cmsg.textContent = t;
        cmsg.className = "lb-msg" + (kind === "err" ? " lb-error" : "");
      }
      function choisir(nom) {
        var v = villeParNom(nom);
        if (!v) {
          cityMsg("On ne programme rien à « " + nom + " » pour l'instant. Essaie la "
            + "grande ville la plus proche, ou passe cette étape.", "err");
          return;
        }
        setCity(v.nom);
        success(data, listHits, favHits, v);
      }
      pcard.querySelector("#lb-city-form").addEventListener("submit", function (e) {
        e.preventDefault();
        var v = cin.value.trim();
        if (v) choisir(v);
      });
      // Cliquer une suggestion vaut validation : la ville est certaine, faire
      // cliquer « Continuer » derrière n'ajoute qu'un geste.
      autoVille(cin, choisir);
      pcard.querySelector("#lb-city-skip").addEventListener("click", function () {
        setCity("");
        success(data, listHits, favHits, null);
      });
      geo.addEventListener("click", function () {
        if (!navigator.geolocation) { cityMsg("Géolocalisation indisponible sur ce navigateur.", "err"); return; }
        geo.textContent = "…localisation";
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            var v = villeLaPlusProche(pos.coords.latitude, pos.coords.longitude);
            geo.textContent = "📍 me localiser";
            if (!v) { cityMsg("Impossible de déterminer ta ville.", "err"); return; }
            cin.value = v.nom;
            cityMsg("Ville la plus proche : " + v.nom + " (à ~" + Math.round(v.km) + " km).", "");
          },
          function () {
            geo.textContent = "📍 me localiser";
            cityMsg("Localisation refusée. Tape ta ville à la main.", "err");
          });
      });
      pcard.querySelector(".lb-close").addEventListener("click", function () { close(false); });
      cin.focus();
    }

    // Écran final : ce qui attend le visiteur, cadré sur sa ville s'il en a
    // donné une, avec le repli « ville la plus proche » quand la sienne ne
    // programme rien — sinon le bouton mènerait à une page qui a l'air vide.
    function success(data, listHits, favHits, city) {
      var n = listHits.length, f = favHits.length;
      var pcard = overlay.querySelector(".lb-portal-card");
      var label = (n || f) ? "Voir les séances →" : "Ouvrir ma watchlist →";
      pcard.innerHTML =
        '<button type="button" class="lb-close" aria-label="Fermer">×</button>' +
        '<h2></h2>' +
        '<p class="lb-ok-count"></p>' +
        '<p class="lb-field"><a class="bouton bouton-lb" href="' + maWatchlist + '"></a></p>';
      pcard.querySelector("h2").textContent = "✅ Salut " + data.user + " !";
      pcard.querySelector(".bouton-lb").textContent = label;
      var p = pcard.querySelector(".lb-ok-count");

      if (city && (n || f)) {
        var ici = parVille(listHits, city.key).ici.length;
        if (ici) {
          p.textContent = ici + " film" + (ici > 1 ? "s" : "") + " de ta watchlist "
            + (ici > 1 ? "passent" : "passe") + " à " + city.nom
            + (n > ici ? " (et " + (n - ici) + " ailleurs en France)." : ".");
        } else {
          var proche = villeProcheAvecFilm(listHits, city);
          p.textContent = proche
            ? "Rien à " + city.nom + " pour l'instant. Le plus proche est à " + proche.nom
              + ", à environ " + Math.round(proche.km) + " km."
            : "Rien à " + city.nom + " pour l'instant, mais " + n + " film"
              + (n > 1 ? "s sont" : " est") + " à l'affiche ailleurs en France.";
        }
      } else {
        var parts = [];
        if (n) parts.push(n + " film" + (n > 1 ? "s" : "") + " de ta watchlist "
          + (n > 1 ? "sont" : "est") + " à l'affiche");
        if (f) parts.push(f + " de tes films préférés à revoir");
        if (parts.length) {
          var s = parts.join(" · ");
          p.textContent = s.charAt(0).toUpperCase() + s.slice(1) + ".";
        } else if (data.private) {
          p.textContent = "Ta watchlist est privée : on ne peut pas la lire. Rends-la publique, ou importe ton fichier.";
        } else {
          p.textContent = "Rien de ta liste n'est à l'affiche pour l'instant, mais on la garde.";
        }
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

  // Masque l'encart « entrer mon pseudo » de l'accueil (.wl-cta) une fois le
  // visiteur connecté : le bloc « ✨ Pour toi » a pris le relais, réinviter à
  // saisir son pseudo n'aurait plus de sens.
  function hideConnectCta() {
    var els = document.querySelectorAll(".wl-cta");
    for (var i = 0; i < els.length; i++) els[i].hidden = true;
  }
  // Après une synchro réussie (portail), masquer sans rechargement.
  document.addEventListener("seanceo:lb-connected", hideConnectCta);

  window.LB = {
    sync: sync, load: load, save: save, patch: patch, clear: clear,
    loadIndex: loadIndex, loadAgenda: loadAgenda, cross: cross, render: render,
    card: card, empreinte: empreinte, errText: errText, showPortal: showPortal,
    city: city, setCity: setCity, villes: villes, villeParNom: villeParNom,
    villeLaPlusProche: villeLaPlusProche, pickSalle: pickSalle, autoVille: autoVille,
    USER_HINT: USER_HINT, WORKER_URL: WORKER_URL, MOCK: MOCK
  };

  document.addEventListener("DOMContentLoaded", function () {
    var script = document.getElementById("lb-core");
    var indexUrl = script && script.dataset.index ? script.dataset.index : "/watchlist-index.json";
    // Boutons « entrer mon pseudo » (encart wl-cta de l'accueil) : ils rouvrent
    // le portail, y compris pour un visiteur déjà connecté (changer de pseudo).
    var openers = document.querySelectorAll("[data-lb-open]");
    for (var i = 0; i < openers.length; i++) {
      openers[i].addEventListener("click", function () { showPortal(indexUrl); });
    }
    var state = load();
    // Déjà connecté : on retire l'invitation « entrer mon pseudo » de l'accueil.
    if (state && state.user) hideConnectCta();
    // Déjà connecté (`user`) ou déjà fermé (`seen`) → on ne rouvre pas tout seul.
    if (state && (state.user || state.seen)) return;
    // Sur la page dédiée, le portail ferait doublon avec le champ de la page.
    if (/\/ma-watchlist\//.test(location.pathname)) return;
    showPortal(indexUrl);
  });
})();
