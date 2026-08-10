/* Séancéo — Worker « watchlist par pseudo »
   ==========================================

   Rôle : recevoir un pseudo Letterboxd et renvoyer sa watchlist PUBLIQUE en
   JSON, pour que le site croise cette liste avec `watchlist-index.json` sans
   demander au visiteur d'exporter le moindre fichier.

   Pourquoi un Worker et pas du JavaScript dans le navigateur ? Letterboxd ne
   renvoie PAS d'en-tête CORS : un `fetch()` direct depuis keenzzz.github.io est
   bloqué par le navigateur. Le Worker, lui, est un serveur : il n'est pas soumis
   au CORS quand IL appelle Letterboxd, et c'est nous qui ajoutons les en-têtes
   CORS sur SA réponse vers le site.

   Zone grise assumée (comme `scripts/fetch_letterboxd.py` pour les notes) :
   Letterboxd n'a pas d'API publique ouverte, on lit donc des pages publiques.
   Posture polie et honnête :
     - User-Agent qui nous identifie et pointe vers le site (transparence) ;
     - cache agressif par pseudo (12 h) : un visiteur qui recharge ne relance
       pas 22 requêtes chez Letterboxd ;
     - plafond de pages pour ne jamais marteler ;
     - concurrence modérée.

   Ce que le Worker NE fait PAS : aucune écriture (ajouter à la watchlist =
   API officielle uniquement), aucun stockage de données personnelles (il relaie,
   le cache ne contient que des titres de films publics). */

// —— Réglages ———————————————————————————————————————————————————————————————

// Origines autorisées à appeler le Worker (CORS). On reflète l'origine exacte
// plutôt que « * » : le jour où le Worker fera de l'authentifié, « * » serait à
// proscrire, autant prendre l'habitude tout de suite.
const ORIGINS_OK = [
  "https://keenzzz.github.io", // GitHub Pages (prod actuelle)
  "https://seanceo.fr",        // domaine prévu
  "https://www.seanceo.fr",
];
// En dev, on autorise localhost sur n'importe quel port.
const ORIGIN_LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;

const LB = "https://letterboxd.com";
// Index des séances de répertoire, servi par le site (détail par film). Sert au
// calendrier .ics. TODO(domaine) : passer sur https://seanceo.fr/... le jour venu.
const AGENDA_INDEX = "https://keenzzz.github.io/seanceo/agenda-index.json";
const PER_PAGE = 28;      // Letterboxd sert 28 affiches par page de watchlist
const MAX_PAGES = 40;     // garde-fou : au-delà (~1120 films) on tronque
const CONCURRENCY = 4;    // pages récupérées de front (poli mais pas lent)
const CACHE_TTL = 43200;  // 12 h, en secondes
const PAGE_TIMEOUT = 15000; // ms par requête vers Letterboxd

// UA transparent : on se nomme et on pointe vers le site. C'est la politesse
// minimale quand on lit des pages publiques sans API.
const UA =
  "SeanceoBot/1.0 (+https://keenzzz.github.io/seanceo/; " +
  "croisement de watchlist a la demande du visiteur)";

// Pseudos Letterboxd : lettres, chiffres, tirets et underscores. On borne la
// longueur pour ne pas accepter n'importe quelle chaîne dans une URL.
const USERNAME_RE = /^[a-zA-Z0-9_-]{1,40}$/;
// Slugs de liste Letterboxd : lettres, chiffres et tirets. Plus longs qu'un
// pseudo (les titres de liste sont slugifiés en entier).
const LIST_SLUG_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,140}$/;
const MAX_LIST_PAGES = 40; // listes : ~100 films/page, plafond ~4000

// —— Point d'entrée ————————————————————————————————————————————————————————

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    // Préflight CORS (le navigateur envoie OPTIONS avant un GET cross-origin).
    if (request.method === "OPTIONS") {
      return corsPreflight(origin);
    }
    // Route : /alerte/... — « préviens-moi quand ce film repasse à Nancy ».
    // Tout est en POST sauf la clé publique, et ce n'est pas seulement parce
    // que ça écrit : l'identifiant du visiteur EST son endpoint de push, une
    // URL qu'on ne veut pas voir traîner dans un journal d'accès, un Referer
    // ou un historique de navigation.
    if (url.pathname === "/alerte/cle") {
      if (request.method !== "GET") {
        return withCors(json({ error: "method_not_allowed" }, 405), origin);
      }
      return withCors(json({ cle: env.VAPID_PUBLIC || "" }), origin);
    }
    if (url.pathname.startsWith("/alerte/")) {
      if (request.method !== "POST") {
        return withCors(json({ error: "method_not_allowed" }, 405), origin);
      }
      try {
        return withCors(await routeAlertes(url.pathname, request, env), origin);
      } catch (err) {
        console.log("alerte error", url.pathname, String(err));
        return withCors(json({ error: "erreur_interne" }, 500), origin);
      }
    }

    if (request.method !== "GET") {
      return withCors(json({ error: "method_not_allowed" }, 405), origin);
    }

    // Petit check de santé à la racine.
    if (url.pathname === "/" || url.pathname === "") {
      return withCors(
        json({ ok: true, service: "seanceo-watchlist", usage: "/watchlist/<pseudo>" }),
        origin,
      );
    }

    // Route : /calendar/<pseudo>.ics — abonnement Google Agenda / calendrier.
    // Google récupère cette URL côté serveur (pas de navigateur), toutes les
    // quelques heures ; on renvoie donc TOUJOURS un calendrier valide (même vide).
    const cal = url.pathname.match(/^\/calendar\/([^/]+?)\.ics$/);
    if (cal) {
      const cu = decodeURIComponent(cal[1]).trim().toLowerCase();
      if (!USERNAME_RE.test(cu)) {
        return withCors(json({ error: "invalid_username" }, 400), origin);
      }
      const near = parseNear(url.searchParams.get("near"));
      const km = Number(url.searchParams.get("km")) || 0;
      const ics = await buildCalendar(cu, near, km);
      const res = new Response(ics, {
        headers: {
          "Content-Type": "text/calendar; charset=utf-8",
          "Cache-Control": `max-age=${CACHE_TTL}`,
        },
      });
      return withCors(res, origin);
    }

    // Route : /list/<pseudo>/<slug> — une liste Letterboxd publique.
    // Même structure HTML (posters LazyPoster) que la watchlist ; on réutilise
    // donc tout le parsing. Différence : pas de `data-num-entries`, on pagine
    // jusqu'à tomber sur une page vide.
    const lm = url.pathname.match(/^\/list\/([^/]+)\/([^/]+)\/?$/);
    if (lm) {
      const luser = decodeURIComponent(lm[1]).trim();
      const lslug = decodeURIComponent(lm[2]).trim();
      if (!USERNAME_RE.test(luser) || !LIST_SLUG_RE.test(lslug)) {
        return withCors(json({ error: "invalid_list" }, 400), origin);
      }
      const fresh = url.searchParams.get("fresh") === "1";
      try {
        const { body, cacheStatus, status } = await getList(
          luser.toLowerCase(), lslug.toLowerCase(), fresh, ctx,
        );
        const res = new Response(body, {
          status,
          headers: { "Content-Type": "application/json; charset=utf-8" },
        });
        res.headers.set("X-Seanceo-Cache", cacheStatus);
        return withCors(res, origin);
      } catch (err) {
        console.log("list error", luser, lslug, String(err));
        return withCors(json({ error: "upstream_error" }, 502), origin);
      }
    }

    // Route : /watchlist/<pseudo>
    const m = url.pathname.match(/^\/watchlist\/([^/]+)\/?$/);
    if (!m) {
      return withCors(json({ error: "not_found" }, 404), origin);
    }

    const username = decodeURIComponent(m[1]).trim();
    if (!USERNAME_RE.test(username)) {
      return withCors(json({ error: "invalid_username" }, 400), origin);
    }
    const user = username.toLowerCase(); // les URLs Letterboxd sont en minuscules

    // `?fresh=1` court-circuite le cache (debug).
    const fresh = url.searchParams.get("fresh") === "1";

    try {
      const { body, cacheStatus, status } = await getWatchlist(user, fresh, ctx);
      const res = new Response(body, {
        status,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
      res.headers.set("X-Seanceo-Cache", cacheStatus);
      return withCors(res, origin);
    } catch (err) {
      // On ne divulgue pas l'erreur interne, on log côté Worker.
      console.log("watchlist error", user, String(err));
      return withCors(json({ error: "upstream_error" }, 502), origin);
    }
  },

  // Balayage quotidien des alertes (Cron Trigger, cf. wrangler.toml).
  // Il tourne après le build du site : on relit l'index des séances et on
  // réveille les visiteurs dont un film marqué a gagné une date.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      balayage(env)
        .then((bilan) => console.log("balayage", JSON.stringify(bilan)))
        .catch((err) => console.log("balayage KO", String(err))),
    );
  },
};

// —— Récupération + cache ——————————————————————————————————————————————————

async function getWatchlist(user, fresh, ctx) {
  const cache = caches.default;
  // Clé de cache stable et interne (jamais exposée). L'origine n'entre PAS dans
  // la clé : on ajoute les en-têtes CORS APRÈS, à la volée, selon le vrai
  // appelant — sinon on mettrait en cache une réponse liée à une seule origine.
  const cacheKey = new Request(`https://seanceo-cache/watchlist/${user}`);

  if (!fresh) {
    const hit = await cache.match(cacheKey);
    if (hit) return { body: await hit.text(), cacheStatus: "HIT", status: 200 };
  }

  const data = await buildWatchlist(user);
  const body = JSON.stringify(data);

  // On ne met en cache que les résultats exploitables (une watchlist trouvée).
  // Un « pseudo introuvable » ne doit pas rester figé 12 h : l'utilisateur peut
  // corriger sa faute de frappe et réessayer aussitôt.
  if (data.ok) {
    const toStore = new Response(body, {
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `max-age=${CACHE_TTL}`,
      },
    });
    ctx.waitUntil(cache.put(cacheKey, toStore));
  }

  return { body, cacheStatus: fresh ? "BYPASS" : "MISS", status: statusFor(data) };
}

// Code HTTP correspondant à la réponse (le corps porte toujours le détail).
function statusFor(data) {
  if (data.ok) return 200;
  if (data.error === "not_found") return 404;
  if (data.error === "invalid_username") return 400;
  return 502;
}

async function buildWatchlist(user) {
  // On récupère EN PARALLÈLE la page 1 de la watchlist (existence du membre,
  // total d'entrées) et la page de profil (les 4 films préférés).
  const [first, profile] = await Promise.all([fetchPage(user, 1), fetchProfile(user)]);
  if (first.status === 404) {
    return { ok: false, error: "not_found", user };
  }
  if (first.status !== 200 || first.html == null) {
    return { ok: false, error: "upstream_error", user, status: first.status };
  }

  // Les 4 favoris affichés sur le profil (peuvent manquer si le membre n'en a
  // pas défini, ou si le profil est restreint → tableau vide, non bloquant).
  const favorites = profile.status === 200 ? parseFavorites(profile.html) : [];

  const total = readTotal(first.html); // null si l'attribut n'est pas là
  let films = parseFilms(first.html);

  // Watchlist vide OU privée : dans les deux cas la page ne liste aucun film.
  // On tranche par des signaux STRUCTURELS (voir isPrivate) pour que l'UI dise
  // « rends-la publique » plutôt que « elle est vide ». Les favoris, eux,
  // restent souvent lisibles même watchlist privée : on les renvoie quand même.
  if (films.length === 0) {
    return {
      ok: true, user, count: 0, total: 0,
      empty: true, private: isPrivate(first.html, total),
      favorites, films: [],
    };
  }

  // Combien de pages au total ? On fait confiance à `data-num-entries` s'il est
  // là, plafonné par MAX_PAGES ; sinon on s'arrête dès qu'une page est vide.
  const wanted = total ? Math.min(Math.ceil(total / PER_PAGE), MAX_PAGES) : MAX_PAGES;
  const truncated = total ? Math.ceil(total / PER_PAGE) > MAX_PAGES : false;

  // Pages 2..wanted, par lots de CONCURRENCY.
  const rest = await fetchPagesConcurrent(watchlistBase(user), 2, wanted, total == null);
  films = films.concat(rest);

  return {
    ok: true,
    user,
    count: films.length,
    total: total || films.length,
    truncated,
    favorites,
    generatedAt: new Date().toISOString(),
    films,
  };
}

// —— Listes Letterboxd —————————————————————————————————————————————————————

// Même cache 12 h que la watchlist, clé propre par (pseudo, slug de liste).
async function getList(user, slug, fresh, ctx) {
  const cache = caches.default;
  const cacheKey = new Request(`https://seanceo-cache/list/${user}/${slug}`);

  if (!fresh) {
    const hit = await cache.match(cacheKey);
    if (hit) return { body: await hit.text(), cacheStatus: "HIT", status: 200 };
  }

  const data = await buildList(user, slug);
  const body = JSON.stringify(data);
  if (data.ok) {
    const toStore = new Response(body, {
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `max-age=${CACHE_TTL}`,
      },
    });
    ctx.waitUntil(cache.put(cacheKey, toStore));
  }
  return { body, cacheStatus: fresh ? "BYPASS" : "MISS", status: statusFor(data) };
}

async function buildList(user, slug) {
  const base = `${LB}/${user}/list/${slug}/`;
  const first = await fetchPageAt(base, 1);
  if (first.status === 404) {
    return { ok: false, error: "not_found", user, slug };
  }
  if (first.status !== 200 || first.html == null) {
    return { ok: false, error: "upstream_error", user, slug, status: first.status };
  }

  const name = parseListName(first.html);
  let films = parseFilms(first.html);

  // Liste vide OU privée : la page ne liste aucun film. Les listes n'annoncent
  // pas de compteur `data-num-entries`, on ne peut donc pas distinguer les deux
  // aussi finement que pour la watchlist ; on renvoie un `empty` neutre.
  if (films.length === 0) {
    return { ok: true, user, slug, name, count: 0, empty: true, films: [] };
  }

  // Pas de total annoncé : on pagine en s'arrêtant à la première page vide.
  const rest = await fetchPagesConcurrent(base, 2, MAX_LIST_PAGES, true);
  films = films.concat(rest);
  const truncated = films.length >= MAX_LIST_PAGES * 100;

  return {
    ok: true, user, slug, name,
    count: films.length, truncated,
    generatedAt: new Date().toISOString(),
    films,
  };
}

// Nom lisible de la liste, depuis la balise Open Graph du <head>.
const OG_TITLE_RE = /<meta property="og:title" content="([^"]*)"/;
function parseListName(html) {
  const m = html.match(OG_TITLE_RE);
  return m ? decodeEntities(m[1]) : "";
}

// Récupère les pages [from..to] avec une concurrence bornée. Si `stopOnEmpty`
// (cas où on ne connaît pas le total), on arrête le lot dès qu'une page ne
// renvoie aucun film — inutile d'insister au-delà de la fin de la liste.
// `base` = URL du listing SANS le suffixe de page (watchlist ou liste).
async function fetchPagesConcurrent(base, from, to, stopOnEmpty) {
  const out = [];
  let page = from;
  let done = false;
  while (page <= to && !done) {
    const batch = [];
    for (let i = 0; i < CONCURRENCY && page <= to; i++, page++) {
      batch.push(fetchPageAt(base, page));
    }
    const results = await Promise.all(batch);
    for (const r of results) {
      if (r.status !== 200 || r.html == null) continue; // on tolère une page ratée
      const films = parseFilms(r.html);
      if (films.length === 0 && stopOnEmpty) { done = true; break; }
      out.push(...films);
    }
  }
  return out;
}

// Page 1 = l'URL de base telle quelle ; pages suivantes = « …/page/N/ ».
// Vaut pour les deux listings Letterboxd (watchlist et liste).
function fetchPageAt(base, page) {
  return fetchHtml(page === 1 ? base : `${base}page/${page}/`);
}

function watchlistBase(user) {
  return `${LB}/${user}/watchlist/`;
}

function fetchPage(user, page) {
  return fetchPageAt(watchlistBase(user), page);
}

// Page de profil : sert à récupérer les 4 films préférés.
function fetchProfile(user) {
  return fetchHtml(`${LB}/${user}/`);
}

async function fetchHtml(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PAGE_TIMEOUT);
  try {
    const r = await fetch(path, {
      headers: { "User-Agent": UA, "Accept": "text/html" },
      signal: controller.signal,
      // Cache de bord Cloudflare sur la requête sortante : deux visiteurs qui
      // demandent le même pseudo ne tapent Letterboxd qu'une fois.
      cf: { cacheTtl: CACHE_TTL, cacheEverything: true },
    });
    if (r.status !== 200) return { status: r.status, html: null };
    return { status: 200, html: await r.text() };
  } catch (_) {
    return { status: 0, html: null }; // timeout / réseau : traité comme page ratée
  } finally {
    clearTimeout(timer);
  }
}

// —— Parsing HTML —————————————————————————————————————————————————————————

// Chaque film est une balise <div class="react-component" data-component-class=
// "LazyPoster" …> qui porte TOUS ses attributs sur sa balise ouvrante. On
// capture chaque balise entière puis on lit ses attributs — robuste, contrairement
// à un zip de deux listes séparées qui se désaligne si un bloc manque un attribut.
const POSTER_TAG_RE =
  /<div class="react-component"[^>]*data-component-class="LazyPoster"[^>]*>/g;
const SLUG_RE = /data-item-slug="([^"]*)"/;
const NAME_RE = /data-item-full-display-name="([^"]*)"/;
// « Titre (2025) » -> nom + année. L'année est optionnelle (films à venir non datés).
const YEAR_RE = /^(.*?)\s*\((\d{4})\)\s*$/;

function parseFilms(html) {
  const films = [];
  const seen = new Set();
  const tags = html.match(POSTER_TAG_RE) || [];
  for (const tag of tags) {
    const slugM = tag.match(SLUG_RE);
    if (!slugM) continue;
    const slug = slugM[1];
    if (seen.has(slug)) continue;
    seen.add(slug);

    let name = "";
    let year = null;
    const nameM = tag.match(NAME_RE);
    if (nameM) {
      const raw = decodeEntities(nameM[1]);
      const ym = raw.match(YEAR_RE);
      if (ym) { name = ym[1]; year = ym[2]; }
      else { name = raw; }
    }
    films.push({ slug, name, year });
  }
  return films;
}

// Nombre total d'entrées de la watchlist, annoncé sur la page.
function readTotal(html) {
  const m = html.match(/data-num-entries="(\d+)"/);
  return m ? parseInt(m[1], 10) : null;
}

// Les 4 films préférés sont dans une section `id="favourites"` de la page de
// profil, avec les MÊMES posters LazyPoster que la watchlist. On borne la
// fenêtre à la section (les posters d'activité récente viennent après) et on
// plafonne à 4 par sécurité.
function parseFavorites(html) {
  const i = html.indexOf('id="favourites"');
  if (i < 0) return [];
  return parseFilms(html.slice(i, i + 7000)).slice(0, 4);
}

// Détection best-effort d'une watchlist privée, par signaux STRUCTURELS tirés du
// HTML réel de Letterboxd, dans l'ordre de fiabilité. La watchlist privée est
// une option payante (Pro/Patron), donc rare : le cas privé lui-même n'a pas pu
// être capturé lors de l'audit (2026-07-24), ces signaux restent à VALIDER sur
// un vrai compte privé — mais ils ne peuvent pas produire de faux positif sur
// une page publique (vérifié sur dave = publique pleine, davidehrlich = publique
// vide) :
//   1. `data-num-entries` > 0 alors qu'on ne parse AUCUN film : Letterboxd
//      annonce des films mais nous les cache = liste masquée. Signal le plus sûr
//      et indépendant de la langue. `num-entries="0"` = vraie liste vide (public).
//   2. Jeton de visibilité du chemin ESI différent de « public ». Le HTML public
//      porte toujours .../esi/watchlist/<id>/default/public:<n>/... ; une autre
//      valeur (ou un futur « friends »/« you ») signalerait une visibilité restreinte.
//   3. Repli : marqueur texte explicite. Volontairement étroit — « only visible
//      to you » est un libellé du widget de réglages présent sur TOUTES les pages,
//      on ne le matche donc surtout pas ici.
const PRIVATE_RE = /hidden (?:their|this member's) watchlist|watchlist is private|hidden from the public/i;
const ESI_POLICY_RE = /\/esi\/watchlist\/\d+\/default\/([a-z]+):/i;
function isPrivate(html, total) {
  if (total && total > 0) return true;                         // (1) compte annoncé, films masqués
  const pol = html.match(ESI_POLICY_RE);
  if (pol && pol[1].toLowerCase() !== "public") return true;   // (2) visibilité restreinte
  return PRIVATE_RE.test(html);                                // (3) repli texte étroit
}

// Décodeur d'entités minimal (les titres passent par là : &amp;, &#39;, accents…).
function decodeEntities(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0*39;|&apos;|&#x0*27;/gi, "'")
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)));
}

// —— Calendrier .ics ——————————————————————————————————————————————————————

// Empreinte IDENTIQUE à lb_slug_key() (Python) et à empreinte() (front) :
// NFKD → non-ASCII retiré → [a-z0-9]. Clé de croisement watchlist ↔ agenda.
function empreinte(s) {
  return (s || "").normalize("NFKD")
    .replace(/[^\x00-\x7F]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

async function fetchAgendaIndex() {
  const r = await fetch(AGENDA_INDEX, { cf: { cacheTtl: 3600, cacheEverything: true } });
  return r.ok ? r.json() : {};
}

// `near` = { lat, lon } optionnel ; `km` = rayon. Construit le VCALENDAR des
// séances de répertoire des films de la watchlist + favoris du membre.
async function buildCalendar(user, near, km) {
  const data = await buildWatchlist(user); // réutilise le cache watchlist (12 h)
  const wanted = data.ok ? [...(data.films || []), ...(data.favorites || [])] : [];
  const index = wanted.length ? await fetchAgendaIndex() : {};

  const events = [];
  const seen = new Set();
  const seenFilm = new Set();
  for (const f of wanted) {
    const e = empreinte(f.slug);
    if (seenFilm.has(e)) continue;
    seenFilm.add(e);
    const entry = index[e] || index[e.replace(/(19|20)\d\d$/, "")];
    if (!entry) continue;
    for (const s of entry.s) {
      // s = [start "YYYY-MM-DDTHH:MM", cinéma, ville, lat, lon, billetterie]
      if (near && km && !withinKm(near, s[3], s[4], km)) continue;
      const uid = `${e}-${s[0]}-${slugCin(s[1])}@seanceo`;
      if (seen.has(uid)) continue;
      seen.add(uid);
      events.push(vevent(entry, s, uid));
    }
  }
  return icsDoc(user, events);
}

function parseNear(v) {
  if (!v) return null;
  const [lat, lon] = v.split(",").map(Number);
  if (Number.isFinite(lat) && Number.isFinite(lon)) return { lat, lon };
  return null;
}

function withinKm(near, lat, lon, km) {
  if (lat == null || lon == null) return false; // sans coords, on ne peut pas filtrer
  const R = 6371, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat - near.lat), dLon = toRad(lon - near.lon);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(near.lat)) * Math.cos(toRad(lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a)) <= km;
}

// Un VEVENT par séance. Heure « flottante » (sans fuseau) + X-WR-TIMEZONE au
// niveau du calendrier : Google l'interprète en Europe/Paris. Durée par défaut 2 h.
function vevent(entry, s, uid) {
  const [start, cinema, city, , , booking] = s;
  const dtStart = start.replace(/[-:]/g, "") + "00";        // 2026-08-27T20:30 → 20260827T203000
  const dtEnd = plus2h(start);
  const loc = city ? `${cinema}, ${city}` : cinema;
  const desc = (booking ? `Réserver : ${booking}\\n` : "") +
    `Fiche : https://keenzzz.github.io${entry.u}`;
  return [
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${nowStamp()}`,
    `DTSTART:${dtStart}`,
    `DTEND:${dtEnd}`,
    `SUMMARY:${icsEsc("🎬 " + entry.t)}`,
    `LOCATION:${icsEsc(loc)}`,
    `DESCRIPTION:${icsEsc(desc)}`,
    `URL:${booking || "https://keenzzz.github.io" + entry.u}`,
    "END:VEVENT",
  ].join("\r\n");
}

function icsDoc(user, events) {
  const head = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Seanceo//Repertoire//FR",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:${icsEsc("Séancéo — " + user)}`,
    "X-WR-TIMEZONE:Europe/Paris",
    "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    "X-PUBLISHED-TTL:PT12H",
  ];
  return head.concat(events, ["END:VCALENDAR", ""]).join("\r\n");
}

function icsEsc(s) {
  return String(s)
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

function slugCin(name) {
  return empreinte(name).slice(0, 24);
}

function plus2h(start) {
  const [d, t] = start.split("T");
  const [Y, Mo, D] = d.split("-").map(Number);
  const [H, Mi] = t.split(":").map(Number);
  const dt = new Date(Date.UTC(Y, Mo - 1, D, H + 2, Mi)); // arithmétique en UTC = reste « flottant »
  const p = (n) => String(n).padStart(2, "0");
  return `${dt.getUTCFullYear()}${p(dt.getUTCMonth() + 1)}${p(dt.getUTCDate())}T${p(dt.getUTCHours())}${p(dt.getUTCMinutes())}00`;
}

function nowStamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
}

// —— Réponses & CORS ——————————————————————————————————————————————————————

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function allowOrigin(origin) {
  if (!origin) return null;
  if (ORIGINS_OK.includes(origin)) return origin;
  if (ORIGIN_LOCAL.test(origin)) return origin;
  return null;
}

function withCors(res, origin) {
  const ok = allowOrigin(origin);
  if (ok) {
    res.headers.set("Access-Control-Allow-Origin", ok);
    res.headers.set("Vary", "Origin");
  }
  return res;
}

function corsPreflight(origin) {
  const ok = allowOrigin(origin);
  const headers = {
    // POST et Content-Type sont là pour les routes /alerte/ (corps JSON).
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (ok) headers["Access-Control-Allow-Origin"] = ok;
  return new Response(null, { status: 204, headers });
}

// —— Alertes « préviens-moi quand ce film repasse » ———————————————————————————
//
// Le visiteur marque un film ET une ville. Chaque nuit, après le build du
// site, on relit l'index des séances : si le film a gagné une date dans cette
// ville, on le réveille.
//
// Les notifications sont envoyées SANS CONTENU. Le réveil ne transporte rien ;
// le service worker vient ensuite chercher de quoi afficher sur /alerte/attente.
// Deux bénéfices : le service de push d'Apple ou de Google ne voit jamais ce
// que le visiteur suit, et on n'a pas à implémenter le chiffrement aes128gcm
// de la charge utile — il ne reste qu'un jeton VAPID à signer, ce que Web
// Crypto fait nativement. Le Worker garde ainsi ses zéro dépendance npm.

// ⚠️ Seuls les vrais services de push sont acceptés comme destination.
// Sans cette liste, n'importe qui pourrait enregistrer une alerte pointant
// vers l'URL de son choix et se servir du balayage nocturne comme d'un
// émetteur de requêtes anonyme (le Worker deviendrait un relais d'abus).
const PUSH_HOSTS = [
  /^fcm\.googleapis\.com$/,                    // Chrome, Edge, Android
  /^[a-z0-9-]+\.push\.apple\.com$/,            // Safari, iOS
  /^updates\.push\.services\.mozilla\.com$/,   // Firefox
  /^[a-z0-9-]+\.notify\.windows\.com$/,        // Windows
];

const MAX_ALERTES = 60;   // par visiteur : au-delà c'est un script, pas un cinéphile
const MAX_TXT = 200;      // longueur max de ce qu'on accepte du client
const MAX_BALAYAGE = 2000; // alertes traitées par nuit (garde-fou de temps CPU)

function texte(v, max = MAX_TXT) {
  return String(v == null ? "" : v)
    .replace(/[\x00-\x1f\x7f]/g, "")  // pas de caractères de contrôle
    .trim()
    .slice(0, max);
}

function endpointValide(u) {
  let p;
  try {
    p = new URL(u);
  } catch {
    return false;
  }
  return p.protocol === "https:" && PUSH_HOSTS.some((re) => re.test(p.hostname));
}

function maintenant() {
  return new Date().toISOString();
}

async function routeAlertes(chemin, request, env) {
  const corps = await request.json().catch(() => null);
  if (!corps || typeof corps !== "object") {
    return json({ error: "corps_invalide" }, 400);
  }
  const cible = texte(corps.endpoint, 500);
  if (!endpointValide(cible)) return json({ error: "endpoint_invalide" }, 400);

  switch (chemin) {
    case "/alerte/ajouter":  return alerteAjouter(env, cible, corps);
    case "/alerte/retirer":  return alerteRetirer(env, cible, corps);
    case "/alerte/liste":    return alerteListe(env, cible);
    case "/alerte/attente":  return alerteAttente(env, cible);
    default:                 return json({ error: "not_found" }, 404);
  }
}

async function alerteAjouter(env, cible, corps) {
  const film = texte(corps.film, 80);
  const ville = texte(corps.ville, 80);
  if (!film || !ville) return json({ error: "champs_manquants" }, 400);

  const compte = await env.DB
    .prepare("SELECT COUNT(*) AS n FROM alertes WHERE cible = ?")
    .bind(cible).first();
  if (compte && compte.n >= MAX_ALERTES) {
    return json({ error: "trop_d_alertes", max: MAX_ALERTES }, 429);
  }

  // Point de départ : ce que le film joue DÉJÀ dans cette ville. Sans ce
  // repère, le balayage de la nuit même annoncerait comme une nouveauté la
  // séance que le visiteur avait sous les yeux en cliquant.
  let deja = [];
  let villeAff = ville;
  try {
    const index = await chargeIndexSeances(env);
    villeAff = villeCanonique(index, ville);
    deja = seancesDansVille(index, film, villeAff);
  } catch (err) {
    // Index injoignable : on enregistre quand même l'alerte, avec la graphie
    // du visiteur. `ville_clef` garantit qu'elle ne fera pas doublon.
    console.log("index indisponible à l'ajout", String(err));
  }
  const depart = deja.length ? deja[deja.length - 1] : "";

  // Le titre et l'URL sont facultatifs. À l'INSERT on se rabat sur la clé du
  // film faute de mieux ; à la mise à jour on ne remplace que si le client a
  // vraiment envoyé quelque chose — sinon un re-marquage sans titre écraserait
  // « Le Voyage de Chihiro » par « spiritedaway ». D'où deux jeux de valeurs :
  // `excluded` ne sait pas distinguer « absent » de « replié sur la clé ».
  const titreBrut = texte(corps.titre);
  const urlBrut = texte(corps.url, 300);

  await env.DB.prepare(
    `INSERT INTO alertes (canal, cible, p256dh, auth, film, titre, url, ville,
                          ville_clef, derniere_seance, cree_le)
     VALUES ('push', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (cible, film, ville_clef)
       DO UPDATE SET titre = COALESCE(NULLIF(?, ''), alertes.titre),
                     url   = COALESCE(NULLIF(?, ''), alertes.url),
                     ville = excluded.ville`,
  ).bind(
    cible,
    texte(corps.p256dh, 200),
    texte(corps.auth, 100),
    film,
    titreBrut || film,
    urlBrut,
    villeAff,
    empreinte(ville),
    depart,
    maintenant(),
    titreBrut,
    urlBrut,
  ).run();

  // On renvoie la ville TELLE QU'ELLE EST STOCKÉE (graphie du site), pas celle
  // tapée : le front affiche cette réponse, elle doit dire « Nice », pas « nIcE ».
  // `deja` lui permet d'annoncer « il passe déjà 2 fois chez toi » plutôt que
  // de laisser croire que le film ne joue nulle part.
  return json({ ok: true, film, ville: villeAff, deja: deja.length });
}

async function alerteRetirer(env, cible, corps) {
  const film = texte(corps.film, 80);
  const ville = texte(corps.ville, 80);
  if (!film) return json({ error: "champs_manquants" }, 400);
  // Sans ville, on retire le film pour toutes les villes de ce visiteur.
  const res = ville
    ? await env.DB.prepare(
        "DELETE FROM alertes WHERE cible = ? AND film = ? AND ville_clef = ?",
      ).bind(cible, film, empreinte(ville)).run()
    : await env.DB.prepare(
        "DELETE FROM alertes WHERE cible = ? AND film = ?",
      ).bind(cible, film).run();
  return json({ ok: true, retirees: res.meta ? res.meta.changes : 0 });
}

async function alerteListe(env, cible) {
  const { results } = await env.DB.prepare(
    `SELECT film, titre, url, ville, cree_le, notifie_le
       FROM alertes WHERE cible = ? ORDER BY cree_le DESC`,
  ).bind(cible).all();
  return json({ ok: true, alertes: results || [] });
}

// Appelé par le service worker quand il est réveillé : il vient chercher ce
// qu'il doit afficher, puisque le réveil lui-même ne transporte rien.
async function alerteAttente(env, cible) {
  const { results } = await env.DB.prepare(
    `SELECT id, titre, ville, quand, url
       FROM notifs WHERE cible = ? AND lu = 0 ORDER BY id`,
  ).bind(cible).all();
  const liste = results || [];
  if (liste.length) {
    await env.DB.prepare(
      `UPDATE notifs SET lu = 1
        WHERE cible = ? AND id <= ?`,
    ).bind(cible, liste[liste.length - 1].id).run();
  }
  return json({ ok: true, notifs: liste });
}

// —— Balayage nocturne ————————————————————————————————————————————————————————

// L'index des séances du site : pour chaque film à l'affiche, sa prochaine
// séance dans chaque salle. `_s` donne salle → ville, `_v` donne la ville.
async function chargeIndexSeances(env) {
  const r = await fetch(env.WATCHLIST_INDEX, {
    cf: { cacheTtl: 3600, cacheEverything: true },
  });
  if (!r.ok) throw new Error(`index ${r.status}`);
  return r.json();
}

// Graphie officielle d'une ville, celle que le site affiche. Le visiteur peut
// avoir tapé « NICE » ou « nice » ; on retrouve « Nice » dans `_v`, sinon on
// garde ce qu'il a écrit (la ville peut ne rien programmer aujourd'hui).
function villeCanonique(index, ville) {
  const cle = empreinte(ville);
  const trouvee = (index._v || []).find((v) => empreinte(v[0]) === cle);
  return trouvee ? trouvee[0] : ville;
}

// Séances d'un film dans une ville, triées, au format « 2026-08-12T14:15 ».
// La comparaison de ville passe par `empreinte` (la même fonction que partout
// ailleurs) : « Saint-Ouen-l'Aumône » et « saint ouen l aumone » se valent.
function seancesDansVille(index, film, ville) {
  const f = index[film];
  if (!f || !Array.isArray(f.k)) return [];
  const cherchee = empreinte(ville);
  const out = [];
  for (const k of f.k) {
    const salle = index._s && index._s[k[0]];
    if (!salle) continue;
    const v = index._v && index._v[salle[1]];
    if (!v || empreinte(v[0]) !== cherchee) continue;
    out.push(`${k[1]}T${k[2]}`);
  }
  return out.sort();
}

async function balayage(env) {
  const { results } = await env.DB.prepare(
    `SELECT id, cible, film, titre, url, ville, derniere_seance
       FROM alertes WHERE canal = 'push' LIMIT ${MAX_BALAYAGE}`,
  ).all();
  const alertes = results || [];
  if (!alertes.length) return { alertes: 0, notifiees: 0, mortes: 0 };

  const index = await chargeIndexSeances(env);
  let notifiees = 0;
  let mortes = 0;

  for (const a of alertes) {
    const seances = seancesDansVille(index, a.film, a.ville);
    if (!seances.length) continue;
    // « Repasse » = une séance POSTÉRIEURE à la dernière qu'on connaissait.
    const nouvelle = seances.find((s) => s > (a.derniere_seance || ""));
    if (!nouvelle) continue;

    // On dépose d'abord de quoi afficher, on réveille ensuite : si le push
    // échoue, l'information n'est pas perdue pour autant (le service worker
    // la trouvera au prochain réveil, et /alerte/liste la voit aussi).
    await env.DB.prepare(
      `INSERT INTO notifs (cible, titre, ville, quand, url, cree_le)
       VALUES (?, ?, ?, ?, ?, ?)`,
    ).bind(a.cible, a.titre, a.ville, nouvelle, a.url, maintenant()).run();

    await env.DB.prepare(
      "UPDATE alertes SET derniere_seance = ?, notifie_le = ? WHERE id = ?",
    ).bind(seances[seances.length - 1], maintenant(), a.id).run();

    const etat = await envoiePush(env, a.cible);
    if (etat === "morte") {
      // Le navigateur a désinstallé l'abonnement (désinscription, app
      // supprimée) : plus personne au bout du fil, on nettoie tout.
      await env.DB.prepare("DELETE FROM alertes WHERE cible = ?").bind(a.cible).run();
      await env.DB.prepare("DELETE FROM notifs WHERE cible = ?").bind(a.cible).run();
      mortes++;
    } else {
      notifiees++;
    }
  }
  return { alertes: alertes.length, notifiees, mortes };
}

// —— Web Push (VAPID, sans charge utile) ——————————————————————————————————————

async function envoiePush(env, endpoint) {
  let jeton;
  try {
    jeton = await jetonVapid(env, new URL(endpoint).origin);
  } catch (err) {
    console.log("VAPID KO", String(err));
    return "erreur";
  }
  const r = await fetch(endpoint, {
    method: "POST",
    headers: {
      // TTL est exigé par la spec : combien de temps le service de push
      // garde le réveil si l'appareil est éteint. 24 h ici — au-delà,
      // annoncer une séance devient inutile.
      "TTL": "86400",
      "Urgency": "normal",
      "Authorization": `vapid t=${jeton}, k=${env.VAPID_PUBLIC}`,
    },
  });
  // 404/410 = abonnement révoqué côté navigateur, définitif.
  if (r.status === 404 || r.status === 410) return "morte";
  if (!r.ok) {
    console.log("push refusé", r.status, await r.text().catch(() => ""));
    return "erreur";
  }
  return "ok";
}

// Jeton VAPID : un JWT ES256 qui prouve au service de push que l'envoi vient
// bien de nous (il est vérifié contre la clé publique que le navigateur a
// reçue à l'abonnement).
async function jetonVapid(env, aud) {
  const cle = await crypto.subtle.importKey(
    "jwk",
    JSON.parse(env.VAPID_PRIVATE_JWK),
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"],
  );
  const entete = b64urlTexte(JSON.stringify({ typ: "JWT", alg: "ES256" }));
  const charge = b64urlTexte(JSON.stringify({
    aud,
    exp: Math.floor(Date.now() / 1000) + 12 * 3600,  // la spec plafonne à 24 h
    sub: env.VAPID_SUBJECT,
  }));
  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    cle,
    new TextEncoder().encode(`${entete}.${charge}`),
  );
  // Web Crypto rend la signature ECDSA en r||s brut, exactement la forme
  // qu'attend ES256 — aucun ré-encodage DER à faire.
  return `${entete}.${charge}.${b64urlOctets(new Uint8Array(signature))}`;
}

function b64urlOctets(octets) {
  let s = "";
  for (const o of octets) s += String.fromCharCode(o);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlTexte(s) {
  return b64urlOctets(new TextEncoder().encode(s));
}
