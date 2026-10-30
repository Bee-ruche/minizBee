#!/usr/bin/env python3
"""Cachegrind avec simulation de cache et de branches, par scénario, par famille du corpus, par
fonction et par zone de code (miniz-0029).

Pour chaque scénario (n1, n6, n9, decompression) et chaque famille (tout le corpus, puis chaque
sous-dossier de bee/corpus/donnees), lance le banc sous
  valgrind --tool=cachegrind --cache-sim=yes --branch-sim=yes --instr-at-start=no <caches explicites>
sur les --prefixe premiers octets de chaque fichier. Seules les passes chronométrées sont comptées
(le banc encadre bee_passe_* par des requêtes client Cachegrind ; --instr-at-start=no). Chaque ligne
de miniz est attribuée à la fonction source qui la contient (fonctions inline comprises, comme
bee/bench/profil.py) et à une zone (commun.ZONES, plages de a2f939a).

Le script compile d'abord le banc (make -C bee banc) : compiler et profiler dans la même session de
la sandbox évite les chemins de sources périmés.

Usage (depuis la racine du dépôt, dans la sandbox) :
  bee/sandbox/sans-docker.sh python3 bee/resultats/miniz-0029/cachegrind.py \
      --json bee/resultats/miniz-0029/donnees/cachegrind.json
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commun  # noqa: E402

EVENEMENTS = ["Ir", "I1mr", "ILmr", "Dr", "D1mr", "DLmr", "Dw", "D1mw", "DLmw", "Bc", "Bcm", "Bi", "Bim"]


def lire_cachegrind(chemin):
    """{(fichier, fonction, ligne): [compteurs]} et la liste des événements, lus dans cachegrind.out."""
    couts, evenements, fl, fn, resume = {}, None, None, None, None
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for l in f:
            l = l.rstrip("\n")
            if l.startswith("events:"):
                evenements = l.split()[1:]
            elif l.startswith("fl="):
                fl = l[3:]
            elif l.startswith("fn="):
                fn = l[3:]
            elif l.startswith("summary:"):
                resume = [int(x) for x in l.split()[1:]]
            elif l and l[0].isdigit():
                champs = [int(x) for x in l.split()]
                cle = (fl, fn, champs[0])
                valeurs = champs[1:] + [0] * (len(evenements) - len(champs) + 1)
                anc = couts.get(cle)
                couts[cle] = valeurs if anc is None else [a + b for a, b in zip(anc, valeurs)]
    if evenements != EVENEMENTS:
        sys.exit(f"{chemin} : événements inattendus {evenements} (il faut --cache-sim=yes --branch-sim=yes)")
    return couts, resume


def ajouter(groupes, nom, valeurs):
    anc = groupes.get(nom)
    groupes[nom] = list(valeurs) if anc is None else [a + b for a, b in zip(anc, valeurs)]


def regrouper(couts):
    fonctions, zones, hors = {}, {}, {}
    total = [0] * len(EVENEMENTS)
    for (fl, fn, ligne), v in couts.items():
        total = [a + b for a, b in zip(total, v)]
        base = os.path.basename(fl or "")
        if base in commun.SOURCES:
            nom = commun.fonction_de(base, ligne)
            ajouter(fonctions, nom, v)
            z = commun.zone_de(base, ligne)
            if z is None and nom in ("tdefl_find_match (l. 862)", "tdefl_compress_normal", "tinfl_decompress",
                                     "tdefl_compress_lz_codes (l. 482)"):
                z = f"{nom} : (reste)"
            if z:
                ajouter(zones, z, v)
        elif base == "string_fortified.h" and (fn or "").startswith(("tdefl_", "tinfl_", "mz_")):
            # memcpy de taille fixe incorporé dans une fonction de miniz (_FORTIFY_SOURCE d'Ubuntu) : la ligne
            # d'appel est perdue, la fonction reste. profil.py les range dans « hors miniz ».
            ajouter(fonctions, f"{fn.split('.')[0]} (memcpy en ligne)", v)
        else:
            ajouter(fonctions, "hors miniz", v)
            ajouter(hors, f"{fn} ({base})", v)
    return total, fonctions, zones, hors


def en_dict(v):
    return dict(zip(EVENEMENTS, v))


def octets_du_corpus(dossier, prefixe):
    n = 0
    for racine, _, fichiers in os.walk(dossier):
        for f in fichiers:
            t = os.path.getsize(os.path.join(racine, f))
            n += min(t, prefixe) if prefixe >= 0 else t
    return n


def une_mesure(scenario, famille, prefixe, sortie, reutiliser):
    fichier = os.path.join(sortie, f"cachegrind.{scenario}.{famille}")
    if not (reutiliser and os.path.exists(fichier)):
        cmd = (["valgrind", "--tool=cachegrind", "--cache-sim=yes", "--branch-sim=yes", "--instr-at-start=no"]
               + commun.OPTIONS_CACHE + [f"--cachegrind-out-file={fichier}", commun.BANC,
                                         "--corpus", commun.corpus_de(famille), "--scenario", scenario,
                                         "--passes", "1", "--sans-memoire"]
               + (["--prefixe", str(prefixe)] if prefixe >= 0 else []))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"échec de {' '.join(cmd)} :\n{r.stderr[-2000:]}")
    couts, resume = lire_cachegrind(fichier)
    total, fonctions, zones, hors = regrouper(couts)
    if resume is not None and resume != total:
        sys.exit(f"{fichier} : la somme des lignes ne redonne pas le résumé de Cachegrind")
    return scenario, famille, {
        "octets": octets_du_corpus(commun.corpus_de(famille), prefixe),
        "total": en_dict(total),
        "fonctions": {k: en_dict(v) for k, v in sorted(fonctions.items(), key=lambda x: -x[1][0])},
        "zones": {k: en_dict(v) for k, v in sorted(zones.items(), key=lambda x: -x[1][0])},
        "hors_miniz": {k: en_dict(v) for k, v in sorted(hors.items(), key=lambda x: -x[1][0]) if v[0] > 0},
    }


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--scenarios", default="n1,n6,n9,decompression")
    a.add_argument("--familles", default="tout," + ",".join(commun.FAMILLES))
    a.add_argument("--prefixe", type=int, default=commun.PREFIXE, help="-1 : fichiers entiers")
    a.add_argument("--sortie", default=os.path.join(commun.CONSTR, "cachegrind"))
    a.add_argument("--json", required=True)
    a.add_argument("--travaux", type=int, default=2)
    a.add_argument("--reutiliser", action="store_true", help="relit les fichiers cachegrind déjà produits")
    a.add_argument("--sans-compilation", action="store_true")
    args = a.parse_args()

    commun.verifier_sources()
    if not args.sans_compilation:
        subprocess.run(["make", "-s", "-C", commun.BEE, "banc"], check=True)
    os.makedirs(args.sortie, exist_ok=True)
    resultat = {"commit_sources": commun.COMMIT, "prefixe": args.prefixe, "options_cache": commun.OPTIONS_CACHE,
                "evenements": EVENEMENTS, "mesures": {}}
    taches = [(s, f) for s in args.scenarios.split(",") for f in args.familles.split(",")]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.travaux) as ex:
        futurs = [ex.submit(une_mesure, s, f, args.prefixe, args.sortie, args.reutiliser) for s, f in taches]
        for fu in futurs:
            s, f, r = fu.result()
            resultat["mesures"].setdefault(s, {})[f] = r
            t = r["total"]
            print(f"{s:14} {f:10} Ir {t['Ir']:>12,}  D1m {t['D1mr'] + t['D1mw']:>10,}  "
                  f"Bcm {t['Bcm']:>10,}", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
