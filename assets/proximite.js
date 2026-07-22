/* « Autour de moi » sur l'accueil.
 *
 * Géolocalise le visiteur (position lue DANS le navigateur, rien n'est envoyé),
 * puis liste les villes les plus proches, en mettant en avant celles qui
 * programment du répertoire cette semaine. C'est le pendant, sur l'accueil, du
 * « Autour de moi » de la carte : répondre tout de suite à « qu'est-ce qui
 * passe près de chez moi ? » sans avoir à taper le nom de sa ville.
 *
 * Données injectées dans <script id="villes-geo"> : [{n, u, lat, lon, r}]
 * (nom, url, coords représentatives de la ville, nb de films de répertoire).
 */
(function () {
  "use strict";
  var btn = document.getElementById("proximite-btn");
  var raw = document.getElementById("villes-geo");
  var out = document.getElementById("proximite");
  var statutEl = document.getElementById("proximite-status");
  if (!btn || !raw || !out) return;

  var villes = JSON.parse(raw.textContent);
  var MAX = 6; // villes les plus proches affichées

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

  function repTxt(n) {
    return n + (n > 1 ? " films de répertoire" : " film de répertoire");
  }

  function lister(moi) {
    var proches = villes
      .map(function (v) { return { v: v, d: km(moi.lat, moi.lon, v.lat, v.lon) }; })
      .sort(function (a, b) { return a.d - b.d; })
      .slice(0, MAX);

    out.textContent = "";
    var titre = document.createElement("p");
    titre.className = "proximite-titre";
    titre.textContent = "Les villes les plus proches de vous :";
    out.appendChild(titre);

    var ul = document.createElement("ul");
    ul.className = "proximite-list";
    proches.forEach(function (x) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.className = "proximite-ville" + (x.v.r ? " has-rep" : "");
      a.href = x.v.u;

      var nom = document.createElement("span");
      nom.className = "proximite-nom";
      nom.textContent = x.v.n; // textContent : jamais d'injection HTML

      var meta = document.createElement("span");
      meta.className = "proximite-meta";
      meta.textContent = fmtKm(x.d) + (x.v.r ? " · " + repTxt(x.v.r) : "");

      a.appendChild(nom);
      a.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    out.appendChild(ul);
    out.hidden = false;
  }

  btn.addEventListener("click", function () {
    if (!navigator.geolocation) {
      statut("Votre navigateur ne permet pas la géolocalisation.");
      return;
    }
    btn.disabled = true;
    statut("Recherche de votre position…");
    navigator.geolocation.getCurrentPosition(
      function (p) {
        btn.disabled = false;
        statut("");
        lister({ lat: p.coords.latitude, lon: p.coords.longitude });
      },
      function (e) {
        btn.disabled = false;
        statut(e && e.code === 1
          ? "Accès à la position refusé. Autorisez la géolocalisation pour voir les villes autour de vous."
          : "Position indisponible pour l'instant. Réessayez dans un moment.");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });
})();
