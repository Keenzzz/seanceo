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

// —— Point d'entrée ————————————————————————————————————————————————————————

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    // Préflight CORS (le navigateur envoie OPTIONS avant un GET cross-origin).
    if (request.method === "OPTIONS") {
      return corsPreflight(origin);
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
  // On tente de distinguer les deux via un marqueur texte pour que l'UI dise
  // « rends-la publique » plutôt que « elle est vide ». Les favoris, eux,
  // restent souvent lisibles même watchlist privée : on les renvoie quand même.
  if (films.length === 0) {
    return {
      ok: true, user, count: 0, total: 0,
      empty: true, private: isPrivate(first.html),
      favorites, films: [],
    };
  }

  // Combien de pages au total ? On fait confiance à `data-num-entries` s'il est
  // là, plafonné par MAX_PAGES ; sinon on s'arrête dès qu'une page est vide.
  const wanted = total ? Math.min(Math.ceil(total / PER_PAGE), MAX_PAGES) : MAX_PAGES;
  const truncated = total ? Math.ceil(total / PER_PAGE) > MAX_PAGES : false;

  // Pages 2..wanted, par lots de CONCURRENCY.
  const rest = await fetchPagesConcurrent(user, 2, wanted, total == null);
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

// Récupère les pages [from..to] avec une concurrence bornée. Si `stopOnEmpty`
// (cas où on ne connaît pas le total), on arrête le lot dès qu'une page ne
// renvoie aucun film — inutile d'insister au-delà de la fin de la liste.
async function fetchPagesConcurrent(user, from, to, stopOnEmpty) {
  const out = [];
  let page = from;
  let done = false;
  while (page <= to && !done) {
    const batch = [];
    for (let i = 0; i < CONCURRENCY && page <= to; i++, page++) {
      batch.push(fetchPage(user, page));
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

function fetchPage(user, page) {
  const path = page === 1
    ? `${LB}/${user}/watchlist/`
    : `${LB}/${user}/watchlist/page/${page}/`;
  return fetchHtml(path);
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

// Détection best-effort d'une watchlist privée (à affiner avec un vrai compte
// privé). Sans marqueur, on considère la liste simplement vide.
const PRIVATE_RE = /hidden (?:their|this member's) watchlist|watchlist is private|hidden from the public/i;
function isPrivate(html) {
  return PRIVATE_RE.test(html);
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
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (ok) headers["Access-Control-Allow-Origin"] = ok;
  return new Response(null, { status: 204, headers });
}
