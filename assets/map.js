/* Carte nationale des cinémas Séancéo.
 * Lit les données injectées dans <script id="cinemas-data"> (pas de fetch :
 * robuste, aucun souci de chemin sous-dossier), plote des marqueurs groupés.
 * Anneau rouge = cinéma indépendant (la signature Séancéo) ; point bleu = chaîne.
 */
(function () {
  var el = document.getElementById("cine-map");
  var raw = document.getElementById("cinemas-data");
  if (!el || !raw || typeof L === "undefined") return;

  var cinemas = JSON.parse(raw.textContent);

  var map = L.map(el, { scrollWheelZoom: true, zoomControl: true })
    .setView([46.6, 2.4], 6); // centre de la France métropolitaine

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png", {
    attribution:
      '© OpenStreetMap contributors © <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  var clusters = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    iconCreateFunction: function (cluster) {
      return L.divIcon({
        className: "cine-cluster",
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

  cinemas.forEach(function (c) {
    if (c.lat == null || c.lon == null) return;
    var isChain = !!c.chain;
    var kind = isChain ? esc(c.chain) : "Cinéma indépendant";
    var popup =
      '<strong>' + esc(c.name) + "</strong><br>" +
      '<span class="pop-kind">' + kind + "</span><br>" +
      esc(c.city) +
      '<br><a href="' + esc(c.url) + '">Voir le programme →</a>';
    L.marker([c.lat, c.lon], { icon: pin(isChain) })
      .bindPopup(popup)
      .addTo(clusters);
  });

  map.addLayer(clusters);
})();
