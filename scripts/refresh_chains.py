#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_chains.py — Rafraîchit les snapshots des chaînes qui bloquent le CI.

Pathé, CGR et Grand Écran répondent **403 aux IP de datacenter** : leur collecte
ne peut PAS tourner sur les serveurs GitHub (comme UGC et les indés le font). Elle
doit partir d'une IP **résidentielle**. Ce script est donc lancé DEPUIS LA MACHINE
de l'utilisateur (Planificateur de tâches Windows ou runner self-hosted), jamais
dans le CI cloud.

Ce qu'il fait, dans l'ordre :
  1. mémorise le volume actuel de chaque snapshot (avant collecte) ;
  2. relance la collecte complète de chaque chaîne (`--days 7`, sans limite) ;
  3. GARDE-FOU : ne garde une chaîne que si sa collecte est SAINE. Sinon il
     restaure le snapshot précédent (`git checkout`) et signale l'échec.
  4. committe les chaînes saines et pousse sur `main` (ce push redéclenche
     `deploy.yml`, qui rebuild et redéploie le site).

Pourquoi le garde-fou est vital : un connecteur best-effort qui échoue RESSEMBLE
à un connecteur bloqué (cf. le piège Webedia `theaterId` → HTTP 500 silencieux
qui avait figé CGR sans erreur visible). Sans ce contrôle, une collecte à moitié
cassée remplacerait de bonnes données par un snapshot rétréci, et personne ne le
verrait. On préfère GARDER l'ancien snapshot et lever un drapeau rouge.

Usage :
    python scripts/refresh_chains.py                 # collecte + commit + push
    python scripts/refresh_chains.py --dry-run       # collecte + garde-fou, RIEN d'écrit dans git
    python scripts/refresh_chains.py --no-push        # committe en local mais ne pousse pas
    python scripts/refresh_chains.py --min-ratio 0.6  # seuil de tolérance (défaut 0.5)
    python scripts/refresh_chains.py --only pathe cgr # sous-ensemble de chaînes

Code de sortie : 0 si toutes les chaînes visées sont saines, 1 si au moins une a
échoué (les chaînes saines sont quand même committées). Le déclencheur peut ainsi
détecter un problème et alerter, tout en gardant le site à jour pour le reste.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# La console Windows est en cp1252 par défaut. Sans ça, les flèches/coches des
# logs ci-dessous — et surtout les noms de cinémas accentués imprimés par les
# connecteurs enfants — feraient planter la tâche planifiée (UnicodeEncodeError).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Environnement des sous-process : PYTHONUTF8 met leur propre stdout en UTF-8,
# pour que fetch_pathe.py / fetch_webedia.py ne plantent pas non plus.
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

ROOT = Path(__file__).resolve().parent.parent          # racine du dépôt
PY = sys.executable                                     # le python courant

# Commande de collecte COMPLÈTE par chaîne (jamais de --theaters/--cinemas de
# test : ces options écrasent le snapshot avec un sous-ensemble).
CHAINS = {
    "pathe":      [PY, "scripts/fetch_pathe.py", "--cinemas", "0", "--days", "7"],
    "cgr":        [PY, "scripts/fetch_webedia.py", "--chain", "cgr", "--days", "7"],
    "grandecran": [PY, "scripts/fetch_webedia.py", "--chain", "grandecran", "--days", "7"],
}


def log(msg):
    """Horodate chaque ligne pour que les logs du planificateur soient lisibles."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _count(path):
    """Nombre d'enregistrements d'un fichier JSON : longueur si tableau, nombre de
    clés si objet. Fichier absent ou illisible → 0 (traité comme 'vide')."""
    p = ROOT / path
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(data) if isinstance(data, (list, dict)) else 0


def counts(chain):
    """(nb de séances, nb de cinémas) pour une chaîne, lus sur le disque."""
    return (
        _count(f"data/{chain}_showtimes.json"),
        _count(f"data/{chain}_cinemas.json"),
    )


def tracked_files(chain):
    """Fichiers du snapshot RÉELLEMENT versionnés pour cette chaîne (via git),
    pour ne toucher qu'à eux lors d'un add ou d'un revert."""
    out = subprocess.run(
        ["git", "ls-files", f"data/{chain}_*.json"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    return [f for f in out.splitlines() if f]


def git(*args, check=True):
    """Petit wrapper git dans le dépôt."""
    return subprocess.run(["git", *args], cwd=ROOT, text=True,
                          capture_output=True, check=check)


def revert(chain):
    """Restaure le snapshot précédent (dernier commit) d'une chaîne."""
    files = tracked_files(chain)
    if files:
        git("checkout", "--", *files, check=False)


def collect(chain):
    """Lance la collecte d'une chaîne. Renvoie True si le process a réussi.
    La sortie du connecteur est laissée telle quelle (progression visible)."""
    log(f"→ collecte {chain} : {' '.join(CHAINS[chain][1:])}")
    res = subprocess.run(CHAINS[chain], cwd=ROOT, env=CHILD_ENV)
    return res.returncode == 0


def healthy(chain, before, after, min_ratio):
    """Décide si la nouvelle collecte est saine. Deux garde-fous :
      - le nombre de cinémas ne doit pas s'effondrer (très stable : 77/73/13) ;
      - le nombre de séances ne doit pas tomber sous `min_ratio` de l'ancien.
    Premier run (avant = 0) : on accepte dès qu'il y a du contenu non vide.
    Renvoie (ok: bool, raison: str)."""
    show_a, cine_a = after
    show_b, cine_b = before

    if show_a == 0 or cine_a == 0:
        return False, f"collecte vide (séances={show_a}, cinémas={cine_a})"

    if cine_b and cine_a < min_ratio * cine_b:
        return False, f"cinémas effondrés {cine_b} → {cine_a}"

    if show_b and show_a < min_ratio * show_b:
        return False, f"séances effondrées {show_b} → {show_a} (< {min_ratio:.0%})"

    return True, f"séances {show_b} → {show_a}, cinémas {cine_b} → {cine_a}"


def main():
    ap = argparse.ArgumentParser(description="Rafraîchit les snapshots Pathé/CGR/Grand Écran.")
    ap.add_argument("--dry-run", action="store_true",
                    help="collecte + garde-fou mais n'écrit rien dans git")
    ap.add_argument("--no-push", action="store_true",
                    help="committe en local mais ne pousse pas")
    ap.add_argument("--min-ratio", type=float, default=0.5,
                    help="seuil de tolérance sur la chute de volume (défaut 0.5)")
    ap.add_argument("--only", nargs="+", choices=list(CHAINS),
                    help="ne traiter que ces chaînes")
    args = ap.parse_args()

    chains = args.only or list(CHAINS)
    log(f"Rafraîchissement des chaînes : {', '.join(chains)} (min-ratio={args.min_ratio})")

    ok_chains, failed = [], []
    for chain in chains:
        before = counts(chain)
        success = collect(chain)
        after = counts(chain)

        if not success:
            # Le process lui-même a planté : on ne se fie pas aux fichiers.
            log(f"✗ {chain} : le connecteur a échoué (code de sortie ≠ 0) → snapshot restauré")
            revert(chain)
            failed.append(chain)
            continue

        ok, reason = healthy(chain, before, after, args.min_ratio)
        if ok:
            log(f"✓ {chain} : sain ({reason})")
            ok_chains.append(chain)
        else:
            log(f"✗ {chain} : SUSPECT ({reason}) → snapshot restauré, non committé")
            revert(chain)
            failed.append(chain)

    # —— Commit + push des chaînes saines ————————————————————————————————————
    if args.dry_run:
        log("--dry-run : aucun commit. Fin.")
    else:
        to_add = []
        for chain in ok_chains:
            to_add += tracked_files(chain)
        if to_add:
            git("add", *to_add)
            # Y a-t-il vraiment quelque chose à committer ? (données identiques =
            # pas de commit inutile.)
            staged = git("diff", "--cached", "--name-only").stdout.strip()
            if staged:
                today = f"{datetime.now():%Y-%m-%d}"
                summary = ", ".join(f"{c} {counts(c)[0]} séances" for c in ok_chains)
                git("commit", "-m",
                    f"data: rafraîchissement snapshots chaînes ({today})\n\n{summary}\n\n"
                    "Collecte locale automatisée (IP résidentielle, cf. refresh_chains.py).")
                log(f"Commit créé : {summary}")
                if args.no_push:
                    log("--no-push : commit local gardé, pas de push.")
                else:
                    push = git("push", "origin", "HEAD:main", check=False)
                    if push.returncode == 0:
                        log("Push OK → deploy.yml va rebuild et redéployer le site.")
                    else:
                        log(f"✗ ÉCHEC du push : {push.stderr.strip()}")
                        failed.append("push")
            else:
                log("Aucun changement de données (snapshots identiques) : rien à committer.")
        else:
            log("Aucune chaîne saine à committer.")

    # —— Bilan ————————————————————————————————————————————————————————————————
    log(f"Bilan : {len(ok_chains)} saine(s) [{', '.join(ok_chains) or '—'}] ; "
        f"{len(failed)} en échec [{', '.join(failed) or '—'}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
