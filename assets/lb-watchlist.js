/* Séancéo — page /ma-watchlist/ : connexion par PSEUDO Letterboxd.

   S'appuie sur window.LB (assets/letterboxd.js, chargé avant dans le <head>).
   Deux entrées possibles sur cette page, qui écrivent dans #wl-results :
     - ce script : le visiteur tape son pseudo (ou revient déjà synchronisé) ;
     - watchlist.js : le fallback « dépose ton fichier CSV » (watchlist privée).

   Le Worker est déployé (LB en réel). Pour tester sans réseau, repasser LB en
   MOCK dans letterboxd.js : pseudos magiques → notfound, oops, private, vide. */

(function () {
  "use strict";

  var form = document.getElementById("lb-form");
  var input = document.getElementById("lb-user");
  var status = document.getElementById("lb-status");
  var results = document.getElementById("wl-results");
  var drop = document.getElementById("wl-drop"); // porte data-index (réutilisé)
  var fallback = document.querySelector(".wl-alt"); // le <details> import CSV
  var calBox = document.getElementById("lb-calendar");
  var cityBox = document.getElementById("lb-city"); // barre « cadré sur <ville> »
  if (!form || !input || !results || !drop || !window.LB) return;

  // Bloc « Ajouter à Google Agenda » : construit l'URL du calendrier .ics servi
  // par le Worker (/calendar/<pseudo>.ics), avec option « près de moi » (géoloc,
  // rien n'est envoyé au site — juste ajouté en paramètre de l'URL du Worker).
  function calendarBlock(user) {
    if (!calBox) return;
    calBox.hidden = false;
    calBox.innerHTML =
      '<h3>📆 Ne rate plus une reprise</h3>' +
      '<p class="lb-cal-sub">Ajoute tes reprises à ton agenda : chaque nouvelle séance ' +
      "d'un film de ta watchlist (ou de tes favoris) apparaît toute seule, avec un rappel.</p>" +
      '<p class="lb-cal-actions">' +
        '<a class="bouton bouton-lb" id="lb-cal-gcal" target="_blank" rel="noopener noreferrer">Ajouter à Google Agenda</a>' +
        '<button type="button" class="lb-secondary" id="lb-cal-near">📍 seulement près de moi</button>' +
      '</p>' +
      '<p class="lb-cal-scope" id="lb-cal-scope"></p>' +
      '<p class="lb-cal-other">Autre agenda (Apple, Outlook…) : ' +
        '<input class="lb-input lb-cal-url" id="lb-cal-url" readonly aria-label="Lien du calendrier"> ' +
        '<button type="button" class="lb-secondary" id="lb-cal-copy">Copier</button></p>';

    var near = null;
    var gcal = calBox.querySelector("#lb-cal-gcal");
    var urlField = calBox.querySelector("#lb-cal-url");
    var scope = calBox.querySelector("#lb-cal-scope");
    var nearBtn = calBox.querySelector("#lb-cal-near");

    function icsUrl() {
      var u = LB.WORKER_URL + "/calendar/" + encodeURIComponent(user) + ".ics";
      if (near) u += "?near=" + near.lat.toFixed(4) + "," + near.lon.toFixed(4) + "&km=30";
      return u;
    }
    function refresh() {
      var webcal = icsUrl().replace(/^https?:/, "webcal:");
      gcal.href = "https://calendar.google.com/calendar/render?cid=" + encodeURIComponent(webcal);
      urlField.value = webcal;
      scope.textContent = near
        ? "Calendrier limité à environ 30 km autour de toi."
        : "Calendrier national (toutes les reprises de ta watchlist en France).";
    }
    refresh();

    nearBtn.addEventListener("click", function () {
      if (near) { near = null; nearBtn.textContent = "📍 seulement près de moi"; refresh(); return; }
      if (!navigator.geolocation) { scope.textContent = "Géolocalisation indisponible sur ce navigateur."; return; }
      nearBtn.textContent = "…localisation";
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          near = { lat: pos.coords.latitude, lon: pos.coords.longitude };
          nearBtn.textContent = "🌍 revenir au national";
          refresh();
        },
        function () { nearBtn.textContent = "📍 seulement près de moi";
          scope.textContent = "Localisation refusée : calendrier national conservé."; });
    });

    calBox.querySelector("#lb-cal-copy").addEventListener("click", function () {
      urlField.select();
      if (navigator.clipboard) navigator.clipboard.writeText(urlField.value);
      else document.execCommand("copy");
      this.textContent = "Copié ✓";
    });
  }

  var indexUrl = drop.dataset.index;
  var agendaUrl = drop.dataset.agenda; // facultatif : enrichit les cartes

  // Reconstitue l'objet « réponse » à partir de l'état stocké, pour que LB.render
  // affiche pareil au retour du visiteur qu'après une synchro fraîche.
  function dataFrom(s) {
    return {
      user: s.user,
      films: s.films || [],
      favorites: s.favorites || [],
      empty: !!s.empty,
      private: !!s.private,
      total: s.total || (s.films || []).length
    };
  }

  // Watchlist vide/privée → on déplie le repli « importer un fichier » pour
  // offrir tout de suite l'alternative.
  function openFallback() {
    if (fallback) fallback.open = true;
  }

  // L'agenda est chargé EN PARALLÈLE de l'index et son échec est absorbé par
  // LB.loadAgenda (il renvoie null) : sans lui les cartes retombent sur la
  // salle et la ville portées par watchlist-index, jamais sur rien.
  function show(data) {
    Promise.all([LB.loadIndex(indexUrl), LB.loadAgenda(agendaUrl)])
      .then(function (both) {
        // LB.city() doit être appelé APRÈS loadIndex : c'est la table `_v` de
        // l'index qui résout le nom stocké en coordonnées.
        cityBar(data);
        var r = LB.render(results, data, both[0], both[1], LB.city());
        if (r.empty) openFallback();
      })
      .catch(function () {
        results.innerHTML = '<p class="wl-erreur">Chargement de l\'index impossible. Réessaie.</p>';
      });
  }

  // Barre de cadrage géographique, au-dessus des résultats. Deux états :
  //  - une ville active → ligne compacte, avec un bouton visible pour en
  //    changer (elle est juste, on ne veut pas encombrer les résultats) ;
  //  - aucune ville → le CHAMP DE SAISIE directement, pas un lien qui ouvre un
  //    champ. Une liste nationale n'est pas actionnable, demander sa ville est
  //    l'action principale de cet écran : elle doit être faisable sans clic
  //    préalable.
  function cityBar(data) {
    if (!cityBox) return;
    var v = LB.city();
    cityBox.hidden = false;
    cityBox.textContent = "";
    if (!v) { editeur(data, ""); return; }

    var ligne = document.createElement("p");
    ligne.className = "lb-city-bar";
    var quoi = document.createElement("span");
    quoi.className = "lb-city-on";
    quoi.textContent = "📍 " + v.nom;
    ligne.appendChild(document.createTextNode("Résultats cadrés sur "));
    ligne.appendChild(quoi);
    ligne.appendChild(document.createTextNode(" "));
    var chg = document.createElement("button");
    chg.type = "button";
    chg.className = "lb-city-chg";
    chg.textContent = "Changer de ville";
    chg.addEventListener("click", function () { editeur(data, v.nom); });
    ligne.appendChild(chg);
    ligne.appendChild(document.createTextNode(" · "));
    ligne.appendChild(lien("Toute la France", function () {
      LB.setCity(""); redessine(data);
    }));
    cityBox.appendChild(ligne);
  }

  function lien(texte, onClick) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "lb-secondary";
    b.textContent = texte;
    b.addEventListener("click", onClick);
    return b;
  }

  // Champ de saisie de la ville. Suggestions maison (`LB.autoVille`) et non un
  // <datalist> : celui-ci déroulait les 257 villes programmées dès le clic dans
  // le champ, ce qui invite à chercher dans une liste alors que la bonne action
  // est de taper. Ici rien ne s'affiche avant deux lettres, puis seules les
  // villes correspondantes remontent. Résolution tolérante aux accents,
  // géolocalisation traitée dans le navigateur seulement.
  function editeur(data, valeur) {
    cityBox.textContent = "";
    var form = document.createElement("form");
    form.className = "lb-city-edit";
    form.innerHTML =
      '<label for="wl-city">📍 Dans quelle ville cherches-tu ?</label>' +
      '<span class="lb-field">' +
        // Placeholder posé par LB.autoVille (il connaît le nombre de villes).
        '<input class="lb-input" id="wl-city" type="text" autocomplete="off" ' +
          'spellcheck="false" aria-label="Ta ville">' +
        '<button class="bouton bouton-lb" type="submit">Cadrer</button>' +
      '</span>' +
      '<span class="lb-city-actions"></span>' +
      '<span class="lb-city-msg" role="status"></span>';
    cityBox.appendChild(form);

    var input = form.querySelector("#wl-city");
    input.value = valeur || "";
    var msg = form.querySelector(".lb-city-msg");
    var actions = form.querySelector(".lb-city-actions");

    actions.appendChild(lien("📍 me localiser", function () {
      if (!navigator.geolocation) { msg.textContent = "Géolocalisation indisponible."; return; }
      msg.textContent = "…localisation";
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          var p = LB.villeLaPlusProche(pos.coords.latitude, pos.coords.longitude);
          if (!p) { msg.textContent = "Ville introuvable."; return; }
          input.value = p.nom;
          msg.textContent = "Ville la plus proche : " + p.nom + " (~" + Math.round(p.km) + " km).";
        },
        function () { msg.textContent = "Localisation refusée. Tape ta ville."; });
    }));
    // « Annuler » n'a de sens que pour REVENIR à une ville déjà cadrée. Sans
    // ville, le champ n'est pas une parenthèse qu'on referme : c'est l'état
    // normal de l'écran, et les résultats nationaux sont déjà dessous.
    if (valeur) {
      actions.appendChild(document.createTextNode(" · "));
      actions.appendChild(lien("Annuler", function () { cityBar(data); }));
    }

    function cadrer(nom) {
      if (!nom) { LB.setCity(""); redessine(data); return; }
      var v = LB.villeParNom(nom);
      if (!v) {
        msg.textContent = "On ne programme rien à « " + nom + " » pour l'instant.";
        return;
      }
      LB.setCity(v.nom);
      redessine(data);
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      cadrer(input.value.trim());
    });
    // Cliquer une suggestion cadre tout de suite : la ville ne fait plus de doute.
    LB.autoVille(input, cadrer);
    // Focus seulement quand le visiteur a DEMANDÉ à changer de ville. Le champ
    // s'affiche aussi tout seul au premier affichage : y voler le focus ferait
    // sauter la page vers lui et ouvrirait le clavier sur mobile.
    if (valeur) input.focus();
  }

  // Re-rendu complet après un changement de ville (index déjà en cache).
  function redessine(data) {
    Promise.all([LB.loadIndex(indexUrl), LB.loadAgenda(agendaUrl)])
      .then(function (both) {
        cityBar(data);
        LB.render(results, data, both[0], both[1], LB.city());
      });
  }

  // Barre d'état « connecté » : pseudo + resynchroniser + oublier.
  function connectedBar(user) {
    status.textContent = "";
    var wrap = document.createElement("p");
    wrap.className = "lb-connected";
    var who = document.createElement("span");
    who.textContent = "Connecté : " + user; // textContent = pas d'injection
    var resync = document.createElement("button");
    resync.type = "button"; resync.className = "lb-secondary"; resync.textContent = "Resynchroniser";
    var forget = document.createElement("button");
    forget.type = "button"; forget.className = "lb-secondary"; forget.textContent = "Changer de pseudo";
    resync.addEventListener("click", function () { run(user); });
    forget.addEventListener("click", function () {
      LB.clear(); results.textContent = ""; status.textContent = ""; input.value = "";
      if (calBox) { calBox.hidden = true; calBox.textContent = ""; }
      if (cityBox) { cityBox.hidden = true; cityBox.textContent = ""; }
      input.focus();
    });
    wrap.appendChild(who);
    wrap.appendChild(document.createTextNode(" · "));
    wrap.appendChild(resync);
    wrap.appendChild(document.createTextNode(" · "));
    wrap.appendChild(forget);
    status.appendChild(wrap);
  }

  function showError(code) {
    results.textContent = ""; // on n'affiche pas un résultat périmé sous l'erreur
    status.innerHTML = '<p class="wl-erreur"></p>';
    status.querySelector(".wl-erreur").textContent = LB.errText(code);
  }

  // Lance une synchronisation (réseau mock/Worker) puis affiche.
  function run(user) {
    status.innerHTML = '<p class="wl-summary"></p>';
    status.querySelector(".wl-summary").textContent = "Lecture de la watchlist de " + user + "…";
    var btn = form.querySelector("button");
    btn.disabled = true;
    LB.sync(user)
      .then(function (data) {
        LB.patch({ user: data.user, films: data.films || [], favorites: data.favorites || [],
                   empty: !!data.empty, private: !!data.private, total: data.total || 0, at: Date.now() });
        connectedBar(data.user);
        show(dataFrom(LB.load()));
        calendarBlock(data.user);
      })
      .catch(function (err) { showError(err && err.error); })
      .then(function () { btn.disabled = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var user = input.value.trim();
    if (user) run(user);
  });

  // Visiteur déjà synchronisé (portail d'accueil ou visite précédente) :
  // on réaffiche ses résultats sans rien lui redemander.
  var state = LB.load();
  if (state && state.user) {
    input.value = state.user;
    connectedBar(state.user);
    show(dataFrom(state));
    calendarBlock(state.user);
  }
})();
