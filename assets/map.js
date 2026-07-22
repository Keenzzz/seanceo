/* Carte nationale des cinémas Séancéo.
 * Lit les données injectées dans <script id="cinemas-data"> (pas de fetch :
 * robuste, aucun souci de chemin sous-dossier), plote des marqueurs groupés.
 * Anneau rouge = cinéma indépendant (la signature Séancéo) ; point bleu = chaîne.
 *
 * Deux outils au service du « répertoire près de chez moi » :
 *  - « Autour de moi » : géolocalise le visiteur (dans son navigateur, rien
 *    n'est envoyé), centre la carte et liste les salles les plus proches ;
 *  - filtre « salles de répertoire seulement » : masque celles qui ne
 *    programment aucune reprise cette semaine (champ `rep`).
 */
(function () {
  var el = document.getElementById("cine-map");
  var raw = document.getElementById("cinemas-data");
  if (!el || !raw || typeof L === "undefined") return;

  var cinemas = JSON.parse(raw.textContent);

  var map = L.map(el, { scrollWheelZoom: true, zoomControl: true })
    .setView([46.6, 2.4], 6); // centre de la France métropolitaine

  // Fond CartoDB Positron (light_all) : clair et sobre, labels de villes qui
  // apparaissent progressivement au zoom (grosses villes dézoomé, plus petites
  // en zoomant). Remplace l'ancien dark_nolabels qui n'affichait aucun nom :
  // impossible de se repérer. Mêmes serveurs de tuiles, aucune dépendance de plus.
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution:
      '© OpenStreetMap contributors © <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  var clusters = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    iconCreateFunction: function (cluster) {
      // La légende promet rouge = indé, bleu = chaîne : un cluster qui ne
      // groupe QUE des chaînes passe au bleu au lieu de mentir en rouge.
      var allChain = cluster.getAllChildMarkers().every(function (m) {
        return m.options.isChain;
      });
      return L.divIcon({
        className: "cine-cluster" + (allChain ? " cine-cluster-chain" : ""),
        html: "<span>" + cluster.getChildCount() + "</span>",
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });
    },
  });

  function pin(isChain) {
    return L.divIcon({
      className: "cine-pin" + (isChain ? " cine-pin-chain" : " cine-pin-indep"),
      html: "<span></span>",
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  // Échappe le texte injecté dans les popups (noms venant de sources externes)
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function repLabel(n) {
    return n + (n > 1 ? " séances de répertoire" : " séance de répertoire") + " cette semaine";
  }

  // Un marqueur par cinéma géolocalisé, gardé en mémoire pour filtrer et trier.
  var entrees = [];
  cinemas.forEach(function (c) {
    if (c.lat == null || c.lon == null) return;
    var isChain = !!c.chain;
    var kind = isChain ? esc(c.chain) : "Cinéma indépendant";
    var rep = c.rep
      ? '<br><span class="pop-rep">🎞️ ' + repLabel(c.rep) + "</span>"
      : "";
    var popup =
      '<strong>' + esc(c.name) + "</strong><br>" +
      '<span class="pop-kind">' + kind + "</span><br>" +
      esc(c.city) + rep +
      '<br><a href="' + esc(c.url) + '">Voir le programme →</a>';
    var m = L.marker([c.lat, c.lon], { icon: pin(isChain), isChain: isChain })
      .bindPopup(popup);
    entrees.push({ c: c, m: m });
  });

  // ── Filtre « salles de répertoire seulement » ──────────────────────────
  var repOnly = document.getElementById("rep-only");
  function garde(o) { return !repOnly || !repOnly.checked || o.c.rep > 0; }

  function remplirClusters() {
    clusters.clearLayers();
    entrees.forEach(function (o) { if (garde(o)) clusters.addLayer(o.m); });
  }
  remplirClusters();
  map.addLayer(clusters);

  // ── « Autour de moi » ──────────────────────────────────────────────────
  var btn = document.getElementById("geoloc-btn");
  var statutEl = document.getElementById("geoloc-status");
  var nearbyEl = document.getElementById("map-nearby");
  var moi = null, moiMarker = null;

  function statut(msg) {
    if (!statutEl) return;
    statutEl.textContent = msg || "";
    statutEl.hidden = !msg;
  }

  // Distance à vol d'oiseau en km (Haversine) — suffisant pour classer.
  function km(la1, lo1, la2, lo2) {
    var R = 6371, r = Math.PI / 180;
    var dLa = (la2 - la1) * r, dLo = (lo2 - lo1) * r;
    var a = Math.sin(dLa / 2) * Math.sin(dLa / 2) +
      Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dLo / 2) * Math.sin(dLo / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function fmtKm(d) {
    if (d < 1) return Math.round(d * 1000) + " m";
    if (d < 10) return d.toFixed(1).replace(".", ",") + " km";
    return Math.round(d) + " km";
  }

  function itemProche(o, d) {
    var li = document.createElement("li");
    li.className = "near-item" + (o.c.rep ? " has-rep" : "");
    var dist = document.createElement("span");
    dist.className = "near-dist";
    dist.textContent = fmtKm(d);
    var corps = document.createElement("div");
    var titre = document.createElement("a");
    titre.className = "near-nom";
    titre.href = o.c.url;
    titre.textContent = o.c.name;      // textContent : jamais d'injection
    var meta = document.createElement("p");
    meta.className = "near-meta";
    meta.textContent = o.c.city + (o.c.chain ? " · " + o.c.chain : " · indépendant");
    corps.appendChild(titre);
    corps.appendChild(meta);
    if (o.c.rep) {
      var rep = document.createElement("p");
      rep.className = "near-rep";
      rep.textContent = "🎞️ " + repLabel(o.c.rep);
      corps.appendChild(rep);
    }
    li.appendChild(dist);
    li.appendChild(corps);
    // Cliquer la ligne (hors lien) recentre la carte sur la salle.
    li.addEventListener("click", function (e) {
      if (e.target === titre) return; // le lien fait son travail
      map.setView([o.c.lat, o.c.lon], 14);
      o.m.openPopup();
      nearbyEl.scrollIntoView({ block: "nearest" });
    });
    return li;
  }

  function listerProches() {
    if (!moi || !nearbyEl) return;
    var proches = entrees.filter(garde)
      .map(function (o) { return { o: o, d: km(moi.lat, moi.lon, o.c.lat, o.c.lon) }; })
      .sort(function (a, b) { return a.d - b.d; })
      .slice(0, 12);
    nearbyEl.textContent = "";
    var h = document.createElement("h2");
    h.textContent = repOnly && repOnly.checked
      ? "Salles de répertoire les plus proches"
      : "Cinémas les plus proches";
    nearbyEl.appendChild(h);
    if (!proches.length) {
      var p = document.createElement("p");
      p.className = "meta";
      p.textContent = "Aucune salle ne correspond. Décochez le filtre pour voir tous les cinémas.";
      nearbyEl.appendChild(p);
    } else {
      var ul = document.createElement("ul");
      ul.className = "near-list";
      proches.forEach(function (x) { ul.appendChild(itemProche(x.o, x.d)); });
      nearbyEl.appendChild(ul);
    }
    nearbyEl.hidden = false;
  }

  function onPos(p) {
    moi = { lat: p.coords.latitude, lon: p.coords.longitude };
    if (moiMarker) map.removeLayer(moiMarker);
    moiMarker = L.marker([moi.lat, moi.lon], {
      icon: L.divIcon({ className: "cine-moi", html: "<span></span>",
                        iconSize: [22, 22], iconAnchor: [11, 11] }),
      zIndexOffset: 1000, keyboard: false,
    }).addTo(map).bindPopup("Vous êtes ici");
    map.setView([moi.lat, moi.lon], 11);
    statut("");
    if (btn) btn.disabled = false;
    listerProches();
  }

  function onErr(e) {
    if (btn) btn.disabled = false;
    statut(e && e.code === 1
      ? "Accès à la position refusé. Autorisez la géolocalisation pour voir les salles autour de vous."
      : "Position indisponible pour l'instant. Réessayez dans un moment.");
  }

  if (btn) {
    btn.addEventListener("click", function () {
      if (!navigator.geolocation) {
        statut("Votre navigateur ne permet pas la géolocalisation.");
        return;
      }
      btn.disabled = true;
      statut("Recherche de votre position…");
      navigator.geolocation.getCurrentPosition(onPos, onErr,
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    });
  }

  // Rejouer le filtre sur la carte ET sur la liste des proches.
  if (repOnly) {
    repOnly.addEventListener("change", function () {
      remplirClusters();
      listerProches();
    });
  }
})();
