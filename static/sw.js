/* Séancéo — service worker
   ==========================

   ⚠️ Il ne fait QUE des notifications. Il n'intercepte AUCUNE requête.

   C'est délibéré et il ne faut pas y toucher sans y réfléchir longuement : un
   service worker s'installe chez le visiteur et y reste. S'il mettait des
   pages en cache, un bug de cache servirait une version périmée du site
   pendant des semaines, sur des appareils qu'on ne contrôle pas — c'est le
   seul morceau du projet qu'un simple redéploiement ne corrige pas. Tant
   qu'il n'y a pas d'écouteur `fetch`, le navigateur va chercher le site
   normalement et le risque est nul.

   Servi depuis static/ à la racine du site, donc sur /seanceo/sw.js : sa
   portée est /seanceo/, exactement le site et rien d'autre de l'origine
   github.io.

   Les notifications arrivent SANS CONTENU (voir worker/src/index.js) : le
   réveil ne transporte rien, on vient chercher quoi afficher ici même. */

// URL du Worker. Répétée ici parce que ce fichier est copié tel quel, sans
// passer par le gabarit : il n'a pas accès à window.LB. À changer AUSSI dans
// assets/letterboxd.js le jour où le Worker déménage.
var WORKER = "https://seanceo-watchlist.keenzzz.workers.dev";

self.addEventListener("install", function () {
  // Pas de pré-cache : on veut juste que la nouvelle version prenne la main
  // sans attendre la fermeture de tous les onglets.
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  // `waitUntil` garde le service worker en vie le temps de l'aller-retour.
  event.waitUntil(afficher());
});

function afficher() {
  return self.registration.pushManager.getSubscription()
    .then(function (sub) {
      if (!sub) return [];
      return fetch(WORKER + "/alerte/attente", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: sub.endpoint }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) { return (d && d.notifs) || []; })
        .catch(function () { return []; });
    })
    .then(function (notifs) {
      if (!notifs.length) {
        // ⚠️ Il FAUT afficher quelque chose : un push reçu sans notification
        // fait afficher au navigateur son propre message (« ce site a été mis
        // à jour en arrière-plan »), ce qui est pire que notre repli. Cas
        // atteint si le réseau lâche entre le réveil et la lecture.
        return self.registration.showNotification("Séancéo", {
          body: "Un film que tu suis repasse près de chez toi.",
          tag: "seanceo-repli",
        });
      }
      return Promise.all(notifs.map(function (n) {
        return self.registration.showNotification(n.titre + " repasse à " + n.ville, {
          body: quand(n.quand),
          // `tag` distinct par film/ville : deux alertes différentes doivent
          // rester deux notifications, pas s'écraser l'une l'autre.
          tag: "seanceo-" + n.titre + "-" + n.ville,
          data: { url: n.url || "" },
        });
      }));
    });
}

// « 2026-08-12T14:15 » → « mercredi 12 août à 14:15 ». Les dates arrivent en
// heure locale française sans fuseau (convention de tout le projet) : on les
// découpe, on ne les passe SURTOUT pas à `new Date()` sur un appareil réglé
// sur un autre fuseau, qui les décalerait.
var JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
var MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre"];

function quand(s) {
  var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})$/.exec(s || "");
  if (!m) return "Une séance t'attend.";
  var d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return JOURS[d.getDay()] + " " + Number(m[3]) + " " + MOIS[Number(m[2]) - 1] +
         " à " + m[4];
}

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var cible = (event.notification.data && event.notification.data.url) || "/seanceo/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then(function (fenetres) {
        // Un onglet du site est déjà ouvert : on le réutilise plutôt que d'en
        // empiler un de plus à chaque notification.
        for (var i = 0; i < fenetres.length; i++) {
          if (fenetres[i].url.indexOf(cible) !== -1 && "focus" in fenetres[i]) {
            return fenetres[i].focus();
          }
        }
        return self.clients.openWindow(cible);
      }),
  );
});
