/* Séancéo — alertes « préviens-moi quand ce film repasse »
   ========================================================

   Deux écrans partagent ce fichier :
     - la fiche film  (#film-alerte) : marquer / retirer ce film ;
     - /mes-alertes/  (#mes-alertes) : la liste de ce qu'on suit.

   Le visiteur marque un FILM et une VILLE. Chaque nuit, le Worker regarde si
   ce film a gagné une séance là-bas et réveille le navigateur (voir
   worker/src/index.js et static/sw.js).

   Ce qui part d'ici : l'endpoint de push que le navigateur nous donne, la clé
   du film et le nom de la ville. Pas de compte, pas d'email, pas de pseudo
   Letterboxd — les alertes marchent pour un visiteur qui n'a rien connecté. */

(function () {
  "use strict";

  // Chemin de base du site (« …/seanceo »), déduit de l'URL de ce script.
  // Il sert à enregistrer le service worker au bon endroit : sa portée sera
  // /seanceo/, donc le site et rien d'autre de l'origine github.io.
  var MOI = document.currentScript;
  var BASE = MOI ? MOI.src.replace(/\/assets\/alertes\.js.*$/, "") : "";

  // Mémoire locale de ce qu'on suit : { empreinte du film: nom de ville }.
  // Elle sert uniquement à afficher tout de suite le bon état sur une fiche
  // film, sans interroger le Worker à chaque page vue. La liste qui fait foi
  // est celle du serveur, relue par /mes-alertes/.
  var CLE = "seanceo.alertes";

  function lues() {
    try { return JSON.parse(localStorage.getItem(CLE) || "{}"); }
    catch (e) { return {}; }
  }
  function ecrire(o) {
    try { localStorage.setItem(CLE, JSON.stringify(o)); } catch (e) {}
  }
  function noter(film, ville) { var o = lues(); o[film] = ville; ecrire(o); }
  function oublier(film) { var o = lues(); delete o[film]; ecrire(o); }

  // —— Capacités du navigateur ————————————————————————————————————————————————

  function supporte() {
    return "serviceWorker" in navigator &&
           "PushManager" in window &&
           typeof Notification !== "undefined";
  }

  // Sur iPhone, le push n'existe QUE si le site a été ajouté à l'écran
  // d'accueil : dans un onglet Safari, PushManager est tout simplement absent.
  // On distingue ce cas d'un navigateur trop vieux pour ne pas afficher un
  // message décourageant à quelqu'un qui n'a qu'un geste à faire.
  function estIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
           (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }
  function estInstalle() {
    return window.navigator.standalone === true ||
           (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  }

  // —— Dialogue avec le Worker ————————————————————————————————————————————————

  function worker() {
    return (window.LB && window.LB.WORKER_URL) || "";
  }

  function poste(route, corps) {
    return fetch(worker() + route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok || !d || d.error) throw (d && d.error) || "erreur";
        return d;
      });
    });
  }

  // La clé publique VAPID arrive du Worker plutôt que d'être écrite en dur
  // ici : une seule source de vérité (wrangler.toml), donc aucun risque de
  // désaccord entre le site et le service qui signe les notifications.
  function clePublique() {
    return fetch(worker() + "/alerte/cle")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.cle) throw "cle_absente";
        return d.cle;
      });
  }

  // base64url → Uint8Array, la forme exigée par `applicationServerKey`.
  function versOctets(b64) {
    var plat = (b64 + "=".repeat((4 - (b64.length % 4)) % 4))
      .replace(/-/g, "+").replace(/_/g, "/");
    var brut = atob(plat);
    var out = new Uint8Array(brut.length);
    for (var i = 0; i < brut.length; i++) out[i] = brut.charCodeAt(i);
    return out;
  }

  // Abonnement au push : on réutilise celui qui existe déjà si le visiteur a
  // marqué un autre film — un seul abonnement par navigateur, plusieurs
  // alertes dessus.
  function abonnement() {
    // La langue voyage dans l'URL du script : c'est le SEUL canal simple pour
    // la faire connaître au service worker, qui vit hors de la page et n'a
    // accès ni à <html lang> ni à window. Il la relit dans self.location.
    // Le `scope` reste inchangé, donc la portée d'installation ne bouge pas.
    var lang = document.documentElement.lang || "fr";
    return navigator.serviceWorker.register(BASE + "/sw.js?lang=" + lang,
                                            { scope: BASE + "/" })
      .then(function () { return navigator.serviceWorker.ready; })
      .then(function (reg) {
        return reg.pushManager.getSubscription().then(function (sub) {
          if (sub) return sub;
          return clePublique().then(function (cle) {
            return reg.pushManager.subscribe({
              // Obligatoire : on s'engage à afficher une notification visible
              // à chaque réveil. C'est ce que fait sw.js, repli compris.
              userVisibleOnly: true,
              applicationServerKey: versOctets(cle),
            });
          });
        });
      });
  }

  // —— Fiche film ————————————————————————————————————————————————————————————

  function fiche(bloc) {
    var film = bloc.dataset.film;
    var titre = bloc.dataset.titre || "";
    var url = bloc.dataset.url || "";
    if (!film || !worker()) return;

    // Navigateur sans push : sur iPhone hors écran d'accueil, ce n'est pas une
    // impasse mais un geste à faire, on le dit. Ailleurs on ne montre rien
    // plutôt que d'afficher un bouton qui ne marchera pas.
    if (!supporte()) {
      if (estIOS() && !estInstalle()) {
        // Ce n'est pas une limite de Séancéo : Safari n'expose le push qu'aux
        // sites posés sur l'écran d'accueil. Autant expliquer le geste exact
        // plutôt que d'afficher « non disponible » à quelqu'un qui est à deux
        // touches de l'avoir.
        bloc.innerHTML = '<p class="alerte-note alerte-ios">🔔 '
          + T("<strong>Être prévenu quand ce film repasse</strong><br>Sur iPhone, les "
            + "notifications demandent d'ajouter Séancéo à ton écran d'accueil : touche "
            + "<strong>Partager</strong> en bas de Safari, puis <strong>« Sur l'écran "
            + "d'accueil »</strong>. Rouvre ensuite cette page depuis l'icône.")
          + "</p>";
      }
      return;
    }

    var suivi = lues();
    if (Object.prototype.hasOwnProperty.call(suivi, film)) {
      montreActive(bloc, film, suivi[film]);
    } else {
      montreBouton(bloc, film, titre, url);
    }
  }

  function montreBouton(bloc, film, titre, url) {
    var ville = villeConnue();
    var b = document.createElement("button");
    b.type = "button";
    b.className = "bouton alerte-btn";
    b.textContent = ville
      ? TF("🔔 Préviens-moi quand il repasse à {ville}", { ville: ville })
      : T("🔔 Préviens-moi quand il repasse");
    b.addEventListener("click", function () {
      if (villeConnue()) return activer(bloc, film, titre, url, villeConnue(), b);
      // Pas encore de ville : on la demande sur place. Le cadrage par ville
      // est indispensable — « ce film repasse quelque part en France » n'est
      // pas une information actionnable.
      demandeVille(bloc, function (choisie) {
        activer(bloc, film, titre, url, choisie, null);
      });
    });
    bloc.innerHTML = "";
    bloc.appendChild(b);

    // L'abonné n'est identifié que par son endpoint de push, propre à CE
    // navigateur sur CET appareil : rien ne relie le PC au téléphone (pas de
    // compte, c'est le revers assumé du « zéro inscription »). S'abonner
    // depuis un ordinateur notifie l'ordinateur. Le visiteur n'a aucun moyen
    // de le deviner, d'où cette ligne.
    var note = document.createElement("p");
    note.className = "alerte-note alerte-appareil";
    note.textContent = T("L'alerte arrive sur l'appareil où tu l'actives.")
      + " " + T("Sur iPhone, ajoute d'abord Séancéo à ton écran d'accueil.");
    bloc.appendChild(note);
  }

  // Ville de cadrage déjà choisie par le visiteur (portail Letterboxd ou
  // /ma-watchlist/). On lit le nom brut du stockage : LB.city() résout contre
  // l'index et exigerait un loadIndex() préalable, inutile ici.
  function villeConnue() {
    try {
      var s = JSON.parse(localStorage.getItem("seanceo.lb") || "null");
      return (s && s.city) || "";
    } catch (e) { return ""; }
  }

  function demandeVille(bloc, suite) {
    bloc.innerHTML = '<p class="alerte-note">'
      + T("Dans quelle ville veux-tu être prévenu ?") + "</p>";
    var form = document.createElement("form");
    form.className = "alerte-ville";
    var champ = document.createElement("input");
    champ.type = "text";
    champ.autocomplete = "off";
    var ok = document.createElement("button");
    ok.type = "submit";
    ok.className = "bouton";
    ok.textContent = T("Valider");
    form.appendChild(champ);
    form.appendChild(ok);
    bloc.appendChild(form);

    function valide(nom) {
      nom = (nom || "").trim();
      if (!nom) return;
      if (window.LB && window.LB.setCity) window.LB.setCity(nom);
      suite(nom);
    }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      valide(champ.value);
    });

    // Suggestions maison partagées avec le reste du site (jamais de
    // <datalist>, qui déroule les 257 villes au clic et invite à parcourir
    // une liste alors que la bonne action est de taper). Elles ont besoin de
    // la table des villes, donc de l'index.
    var core = document.getElementById("lb-core");
    var indexUrl = core && core.dataset.index ? core.dataset.index : "";
    if (window.LB && window.LB.loadIndex && window.LB.autoVille && indexUrl) {
      window.LB.loadIndex(indexUrl).then(function () {
        window.LB.autoVille(champ, function (nom) { valide(nom); });
      }).catch(function () { champ.placeholder = T("Ta ville…"); });
    } else {
      champ.placeholder = T("Ta ville…");
    }
    champ.focus();
  }

  function activer(bloc, film, titre, url, ville, bouton) {
    if (bouton) {
      bouton.disabled = true;
      bouton.textContent = "…";
    }
    // La permission se demande APRÈS le clic, jamais au chargement : une
    // demande d'autorisation surgie sans raison se solde par un refus
    // définitif, et un refus ne se rattrape pas sans passer par les réglages.
    Notification.requestPermission()
      .then(function (etat) {
        if (etat !== "granted") throw "refus";
        return abonnement();
      })
      .then(function (sub) {
        return poste("/alerte/ajouter", {
          endpoint: sub.endpoint,
          p256dh: cle(sub, "p256dh"),
          auth: cle(sub, "auth"),
          film: film,
          titre: titre,
          url: url,
          ville: ville,
        });
      })
      .then(function (d) {
        noter(film, d.ville || ville);
        montreActive(bloc, film, d.ville || ville, d.deja);
      })
      .catch(function (err) {
        bloc.innerHTML = '<p class="alerte-note alerte-ko">' +
          (err === "refus"
            ? T("Tu as refusé les notifications. Réactive-les dans les réglages du "
              + "navigateur pour ce site.")
            : T("L'alerte n'a pas pu être enregistrée. Réessaie plus tard.")) +
          "</p>";
      });
  }

  function cle(sub, nom) {
    try {
      var b = sub.getKey(nom);
      if (!b) return "";
      var o = new Uint8Array(b), s = "";
      for (var i = 0; i < o.length; i++) s += String.fromCharCode(o[i]);
      return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    } catch (e) { return ""; }
  }

  function montreActive(bloc, film, ville, deja) {
    // `deja` : nombre de séances déjà programmées dans cette ville au moment
    // du marquage. Le dire évite de laisser croire qu'il n'y a rien à voir
    // alors que le film passe justement chez lui cette semaine.
    var sup = "";
    if (deja) {
      sup = " " + (deja > 1
        ? TF("Il y est déjà à l'affiche ({n} salles).", { n: deja })
        : T("Il y est déjà à l'affiche."));
    }
    bloc.innerHTML = "";
    var p = document.createElement("p");
    p.className = "alerte-note alerte-ok";
    p.textContent = TF("🔔 Tu seras prévenu quand ce film repassera à {ville}.",
                       { ville: ville }) + sup;
    var retirer = document.createElement("button");
    retirer.type = "button";
    retirer.className = "lien-bouton";
    retirer.textContent = T("Ne plus me prévenir");
    retirer.addEventListener("click", function () {
      retirer.disabled = true;
      navigator.serviceWorker.ready
        .then(function (reg) { return reg.pushManager.getSubscription(); })
        .then(function (sub) {
          if (!sub) throw "pas_d_abonnement";
          return poste("/alerte/retirer", { endpoint: sub.endpoint, film: film, ville: ville });
        })
        .then(function () {
          oublier(film);
          montreBouton(bloc, film, bloc.dataset.titre || "", bloc.dataset.url || "");
        })
        .catch(function () {
          // Même si le serveur n'a pas répondu, on retire localement : le
          // visiteur a dit non, l'interface doit lui obéir tout de suite.
          oublier(film);
          montreBouton(bloc, film, bloc.dataset.titre || "", bloc.dataset.url || "");
        });
    });
    p.appendChild(document.createTextNode(" "));
    p.appendChild(retirer);
    // Seul chemin d'accès à /mes-alertes/ : la page n'est ni dans le menu ni
    // dans le sitemap (rien à y indexer), elle ne concerne que qui suit déjà
    // un film. C'est ici, juste après la confirmation, qu'on en a besoin.
    p.appendChild(document.createTextNode(" · "));
    var vers = document.createElement("a");
    vers.href = BASE + "/mes-alertes/";
    vers.textContent = T("Mes alertes");
    p.appendChild(vers);
    bloc.appendChild(p);
  }

  // —— Page /mes-alertes/ ————————————————————————————————————————————————————

  function pageListe(hote) {
    if (!supporte() || !worker()) {
      hote.innerHTML = '<p class="alerte-note">'
        + T("Ce navigateur ne peut pas recevoir de notifications")
        + (estIOS() && !estInstalle()
          ? " " + T("tant que Séancéo n'est pas ajouté à ton écran d'accueil.") : ".")
        + "</p>";
      return;
    }
    hote.innerHTML = '<p class="alerte-note">' + T("Chargement…") + "</p>";
    navigator.serviceWorker.getRegistration(BASE + "/")
      .then(function (reg) { return reg ? reg.pushManager.getSubscription() : null; })
      .then(function (sub) {
        if (!sub) {
          hote.innerHTML = '<p class="alerte-note">'
            + T("Tu ne suis aucun film pour le moment. Sur la fiche d'un film, le "
              + "bouton « Préviens-moi quand il repasse » te préviendra dès qu'une "
              + "séance est programmée dans ta ville.") + "</p>";
          return;
        }
        return poste("/alerte/liste", { endpoint: sub.endpoint }).then(function (d) {
          affiche(hote, d.alertes || [], sub);
        });
      })
      .catch(function () {
        hote.innerHTML = '<p class="alerte-note alerte-ko">'
          + T("La liste n'a pas pu être chargée. Réessaie plus tard.") + "</p>";
      });
  }

  function affiche(hote, liste, sub) {
    if (!liste.length) {
      hote.innerHTML = '<p class="alerte-note">'
        + T("Tu ne suis aucun film pour le moment.") + "</p>";
      return;
    }
    hote.innerHTML = "";
    // La liste du serveur fait foi : on réaligne la mémoire locale dessus,
    // sinon une fiche film continuerait d'afficher « alerte active » pour un
    // marqueur retiré depuis un autre appareil.
    var local = {};
    var ul = document.createElement("ul");
    ul.className = "alerte-liste";
    liste.forEach(function (a) {
      local[a.film] = a.ville;
      var li = document.createElement("li");
      var titre = document.createElement("a");
      titre.href = a.url || "#";
      titre.textContent = a.titre;
      li.appendChild(titre);
      li.appendChild(document.createTextNode(
        " " + TF("à {ville}", { ville: a.ville }) + " "));
      var x = document.createElement("button");
      x.type = "button";
      x.className = "lien-bouton";
      x.textContent = T("retirer");
      x.addEventListener("click", function () {
        x.disabled = true;
        poste("/alerte/retirer", { endpoint: sub.endpoint, film: a.film, ville: a.ville })
          .then(function () {
            oublier(a.film);
            li.parentNode.removeChild(li);
            if (!ul.children.length) {
              hote.innerHTML = '<p class="alerte-note">Tu ne suis plus aucun film.</p>';
            }
          })
          .catch(function () { x.disabled = false; });
      });
      li.appendChild(x);
      ul.appendChild(li);
    });
    ecrire(local);
    hote.appendChild(ul);
  }

  // —— Démarrage —————————————————————————————————————————————————————————————

  document.addEventListener("DOMContentLoaded", function () {
    var bloc = document.getElementById("film-alerte");
    if (bloc) fiche(bloc);
    var liste = document.getElementById("mes-alertes");
    if (liste) pageListe(liste);
  });
})();
