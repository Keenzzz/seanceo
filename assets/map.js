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

  // Attribution exigée par Esri pour l'usage de ses fonds de carte.
  var TUILES_ATTRIB = 'Fonds de carte &copy; <a href="https://www.esri.com/">Esri</a>' +
    ' — Esri, HERE, Garmin, &copy; OpenStreetMap contributors';

  var map = L.map(el, { scrollWheelZoom: true, zoomControl: true })
    .setView([46.6, 2.4], 6); // centre de la France métropolitaine

  // Fond Esri « Light Gray Canvas » : clair et sobre, dans le même esprit que
  // le CartoDB Positron qu'il remplace (2026-09-30).
  //
  // ⚠️ POURQUOI ON A QUITTÉ CARTO : leur CDN de fonds de carte exige désormais
  // une clé. Il ne renvoie PAS d'erreur — il sert un 200, un vrai PNG, de la
  // bonne taille, portant le filigrane « API KEY REQUIRED ». La carte gardait
  // donc ses marqueurs, ses clusters et ses popups : rien dans la console, rien
  // dans les tests de lien, seul l'œil voyait la panne. Signe qui ne trompe pas
  // et qui sert de test : deux tuiles de coordonnées très éloignées revenaient
  // OCTET POUR OCTET identiques (Paris et le milieu de l'Atlantique, md5
  // 502fc5f6…). Un fond de carte qui rend la même image partout est mort.
  //
  // ⚠️ LES LABELS SONT UNE COUCHE À PART chez Esri, et ils ne sont pas
  // optionnels : le fond seul n'affiche AUCUN nom de ville. C'est exactement le
  // défaut de l'ancien dark_nolabels, qui rendait la carte impossible à lire.
  // Ne pas retirer la couche « Reference » en croyant économiser des requêtes.
  //
  // ⚠️ `maxNativeZoom` N'EST PAS DÉCORATIF. Esri s'arrête au zoom 16 ; au-delà
  // il sert une tuile « données indisponibles » (2 521 octets, la même à toutes
  // les coordonnées — le même piège que CARTO). Avec maxNativeZoom, Leaflet
  // agrandit la tuile 16 au lieu d'aller la chercher : c'est flou passé ce
  // niveau, mais on voit la rue. Sans, la carte devient blanche quand on zoome
  // sur une salle, ce qui est le geste le plus courant.
  //
  // Ni `{s}` ni `{r}` ici : Esri n'a pas de sous-domaines ni de tuiles retina.
  var ESRI_CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  var fondOpts = { attribution: TUILES_ATTRIB, maxNativeZoom: 16, maxZoom: 19 };
  L.tileLayer(ESRI_CANVAS + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", fondOpts)
    .addTo(map);
  L.tileLayer(ESRI_CANVAS + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
              { maxNativeZoom: 16, maxZoom: 19 }).addTo(map);

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
    return TF("{n} séance{s} de répertoire cette semaine", { n: n, s: PL(n) });
  }

  // Un marqueur par cinéma géolocalisé, gardé en mémoire pour filtrer et trier.
  var entrees = [];
  cinemas.forEach(function (c) {
    if (c.lat == null || c.lon == null) return;
    var isChain = !!c.chain;
    var kind = isChain ? esc(c.chain) : T("Cinéma indépendant");
    var rep = c.rep
      ? '<br><span class="pop-rep">🎞️ ' + repLabel(c.rep) + "</span>"
      : "";
    var popup =
      '<strong>' + esc(c.name) + "</strong><br>" +
      '<span class="pop-kind">' + kind + "</span><br>" +
      esc(c.city) + rep +
      '<br><a href="' + esc(c.url) + '">' + esc(T("Voir le programme →")) + "</a>";
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
    // Séparateur décimal selon la langue : « 3,4 km » / « 3.4 km ». Une
    // virgule décimale se lit comme un séparateur de milliers en anglais.
    if (d < 10) {
      var x = d.toFixed(1);
      return (document.documentElement.lang === "fr" ? x.replace(".", ",") : x) + " km";
    }
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
    meta.textContent = o.c.city
      + (o.c.chain ? " · " + o.c.chain : " · " + T("indépendant"));
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
      ? T("Salles de répertoire les plus proches")
      : T("Cinémas les plus proches");
    nearbyEl.appendChild(h);
    if (!proches.length) {
      var p = document.createElement("p");
      p.className = "meta";
      p.textContent = T("Aucune salle ne correspond. Décochez le filtre pour voir "
                      + "tous les cinémas.");
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
    }).addTo(map).bindPopup(esc(T("Vous êtes ici")));
    map.setView([moi.lat, moi.lon], 11);
    statut("");
    if (btn) btn.disabled = false;
    listerProches();
  }

  function onErr(e) {
    if (btn) btn.disabled = false;
    statut(e && e.code === 1
      ? T("Accès à la position refusé. Autorisez la géolocalisation pour voir "
        + "les salles autour de vous.")
      : T("Position indisponible pour l'instant. Réessayez dans un moment."));
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
