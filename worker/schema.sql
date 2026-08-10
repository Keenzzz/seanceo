-- Schéma de la base « seanceo-alertes » (Cloudflare D1).
--
-- Appliquer :  cd worker && npx wrangler d1 execute seanceo-alertes --remote --file schema.sql
-- En local   :  … --local --file schema.sql
--
-- Deux tables seulement : ce que le visiteur a marqué, et ce qui l'attend.

-- « Préviens-moi quand CE film repasse dans CETTE ville. »
CREATE TABLE IF NOT EXISTS alertes (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,

  -- Le canal est là dès le premier jour alors que seul 'push' est câblé :
  -- l'email attend l'achat de seanceo.fr, et le prévoir maintenant évite
  -- une migration de la table le jour où il arrive.
  canal    TEXT NOT NULL DEFAULT 'push' CHECK (canal IN ('push', 'email')),
  -- Endpoint du service de push aujourd'hui, adresse email demain.
  cible    TEXT NOT NULL,
  -- Clés de chiffrement du push. Inutiles tant qu'on envoie des
  -- notifications SANS contenu, gardées pour ne pas avoir à redemander
  -- l'autorisation au visiteur si on passait un jour au push avec charge.
  p256dh   TEXT NOT NULL DEFAULT '',
  auth     TEXT NOT NULL DEFAULT '',

  -- Empreinte du film (la clé de watchlist-index.json), plus de quoi
  -- rédiger la notification sans relire l'index.
  film     TEXT NOT NULL,
  titre    TEXT NOT NULL,
  url      TEXT NOT NULL DEFAULT '',
  -- Ville stockée par son NOM, jamais par son rang dans `_v` : un index
  -- numérique ne survivrait pas à une reconstruction du fichier. On garde la
  -- graphie officielle du site (celle de `_v`) pour que la notification dise
  -- « à Nice » et non « à NICE ».
  ville    TEXT NOT NULL,
  -- ⚠️ C'est l'EMPREINTE de la ville qui porte l'unicité, pas son nom.
  -- Le balayage compare les villes par empreinte ; si l'unicité portait sur
  -- le texte brut, « NICE » et « Nice » cohabiteraient comme deux alertes et
  -- la même séance déclencherait deux notifications identiques.
  ville_clef TEXT NOT NULL,

  -- Séance la plus tardive déjà connue pour ce couple film/ville. C'est
  -- ELLE qui définit « repasse » : on ne prévient que d'une séance
  -- postérieure, sinon chaque passage du cron renotifierait la même.
  -- Vide = le film ne passait pas du tout dans cette ville au marquage.
  derniere_seance TEXT NOT NULL DEFAULT '',

  cree_le    TEXT NOT NULL,
  notifie_le TEXT,

  -- Un même visiteur ne peut pas marquer deux fois le même film/ville.
  UNIQUE (cible, film, ville_clef)
);

CREATE INDEX IF NOT EXISTS alertes_film ON alertes (film);

-- File d'attente lue par le service worker quand il est réveillé.
--
-- On envoie des notifications SANS contenu (le service de push d'Apple ou
-- de Google ne voit donc jamais ce que le visiteur suit) : le réveil ne
-- transporte rien, le service worker vient chercher ici de quoi afficher.
CREATE TABLE IF NOT EXISTS notifs (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  cible   TEXT NOT NULL,
  titre   TEXT NOT NULL,
  ville   TEXT NOT NULL,
  quand   TEXT NOT NULL,           -- date de la séance annoncée
  url     TEXT NOT NULL DEFAULT '',
  cree_le TEXT NOT NULL,
  lu      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS notifs_cible ON notifs (cible, lu);
