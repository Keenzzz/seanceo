/* Génération d'un fichier .ics (agenda) ENTIÈREMENT côté client.

   Le visiteur télécharge un fichier que son navigateur a fabriqué : aucune
   séance ne transite par un serveur, et le site reste statique. Le fichier
   s'ouvre dans Google Agenda, Apple Calendrier ou Outlook, où chaque séance
   devient un événement daté avec le cinéma et le lien de réservation.

   Ce module était à l'origine enfermé dans cinematheque.js. Il est sorti ici
   le jour où « Dernière chance » a eu besoin du même bouton : deux copies du
   même générateur auraient divergé à la première correction. Il n'est chargé
   QUE par les deux pages qui l'utilisent, pas par tout le site.

   Un événement : { titre, start, lieu, url, booking }
   `start` est une heure locale sans fuseau (« 2026-08-16T20:00 »), la forme
   stockée partout dans le projet. */

(function () {
  "use strict";

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  // Échappement du format iCalendar (RFC 5545) : le point-virgule et la
  // virgule y séparent des champs, ils doivent être neutralisés dans un texte
  // libre — sans quoi un titre comme « Le Bon, la Brute… » casse la ligne.
  function esc(s) {
    return String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;")
      .replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  }

  function stampNow() {
    var d = new Date();
    return d.getUTCFullYear() + pad(d.getUTCMonth() + 1) + pad(d.getUTCDate()) + "T"
      + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + pad(d.getUTCSeconds()) + "Z";
  }

  // Fin d'événement = début + 2 h (durée par défaut d'une séance, la vraie
  // n'est pas toujours connue). Arithmétique en UTC pour ne pas dépendre du
  // fuseau de l'appareil : le résultat est réécrit sans suffixe de fuseau,
  // donc l'heure reste « flottante » et s'affiche à 20 h partout.
  function plus2h(start) {
    var d = start.slice(0, 10).split("-").map(Number);
    var t = start.slice(11, 16).split(":").map(Number);
    var dt = new Date(Date.UTC(d[0], d[1] - 1, d[2], t[0] + 2, t[1]));
    return dt.getUTCFullYear() + pad(dt.getUTCMonth() + 1) + pad(dt.getUTCDate()) + "T"
      + pad(dt.getUTCHours()) + pad(dt.getUTCMinutes()) + "00";
  }

  /* Construit le calendrier et déclenche son téléchargement.
     `nom` : titre du calendrier ET base du nom de fichier.
     `evenements` : voir l'en-tête du fichier. */
  function telecharger(nom, fichier, evenements) {
    var lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Seanceo//Agenda//FR",
      "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
      "X-WR-CALNAME:" + esc(nom),
      "X-WR-TIMEZONE:Europe/Paris"
    ];
    evenements.forEach(function (e, i) {
      var dtStart = e.start.replace(/[-:]/g, "").slice(0, 13) + "00"; // 2026-08-16T20:00 -> 20260816T200000
      // Vrai saut de ligne : c'est esc() qui le convertit en « \n » iCalendar.
      // L'écrire déjà échappé ici le ferait échapper une SECONDE fois par esc()
      // (« \\n »), et les agendas affichaient alors « \n » en toutes lettres au
      // milieu de la description. Bug d'origine de l'export cinémathèque,
      // corrigé pour les deux pages du même coup.
      var desc = (e.booking ? T("Réserver :") + " " + e.booking + "\n" : "")
        + (e.url ? T("Fiche :") + " " + e.url : "");
      lines.push("BEGIN:VEVENT",
        "UID:cine-" + i + "-" + dtStart + "@seanceo",
        "DTSTAMP:" + stampNow(),
        "DTSTART:" + dtStart,
        "DTEND:" + plus2h(e.start),
        "SUMMARY:" + esc("🎬 " + e.titre),
        "LOCATION:" + esc(e.lieu),
        "DESCRIPTION:" + esc(desc),
        "URL:" + (e.booking || e.url || ""),
        "END:VEVENT");
    });
    lines.push("END:VCALENDAR", "");
    // \r\n : la RFC l'impose comme fin de ligne, et Outlook refuse le reste.
    var blob = new Blob([lines.join("\r\n")], { type: "text/calendar;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = fichier + ".ics";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  window.ICS = { telecharger: telecharger };
})();
