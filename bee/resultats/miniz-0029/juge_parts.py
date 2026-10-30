#!/usr/bin/env python3
"""Parts des fonctions et des zones dans le décompte d'instructions DU JUGE commun (miniz-0029).

R4 juge l'ampleur d'un gain sur le décompte de Cachegrind du juge commun : tout le processus du
harnais bee/juge/execution.c (lecture des entrées, miniz, écriture des sorties), sur les 128 premiers
Kio de chaque fichier du corpus ; la décompression y lit des flux de la zlib de l'hôte (niveau 6),
pas ceux de miniz. Ce script reproduit ce décompte hors conteneur, sur le corpus NON perturbé (le
juge change quelques octets à chaque répétition : effet négligeable sur les parts) :
  - compile execution.c et miniz comme bee/juge/construire.sh (mêmes options) ;
  - écrit les entrées (fichiers tronqués à 128 Kio ; flux zlib niveau 6 produits par la libz.a liée,
    zlib 1.3 d'Ubuntu 24.04, par le harnais de stats_lz.py) ;
  - lance `execution n1|n6|n9|decompression` sous Cachegrind (cache et branches simulés, tout le
    processus) et regroupe par fonction et par zone comme cachegrind.py.

Usage (depuis la racine du dépôt, dans la sandbox) :
  bee/sandbox/sans-docker.sh python3 bee/resultats/miniz-0029/juge_parts.py \
      --json bee/resultats/miniz-0029/donnees/juge_parts.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cachegrind  # noqa: E402
import commun  # noqa: E402
import stats_lz  # noqa: E402


def construire(dossier):
    obj = os.path.join(dossier, "obj")
    os.makedirs(obj, exist_ok=True)
    objets = []
    for f in ("miniz", "miniz_tdef", "miniz_tinfl"):  # bee/juge/construire.sh, mêmes options
        o = os.path.join(obj, f + ".o")
        subprocess.run(["cc", "-O3", "-DNDEBUG", "-g", "-std=gnu90", "-D_GNU_SOURCE", "-I" + commun.RACINE,
                        "-I" + os.path.join(commun.BEE, "commun"), "-c", os.path.join(commun.RACINE, f + ".c"), "-o", o],
                       check=True)
        objets.append(o)
    execution = os.path.join(dossier, "execution")
    subprocess.run(["cc", "-O2", "-g", "-std=gnu99", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-I" + commun.RACINE, "-I" + os.path.join(commun.BEE, "commun"),
                    os.path.join(commun.BEE, "juge", "execution.c")] + objets + ["-o", execution], check=True)
    return execution


def preparer_entrees(dossier, prefixe):
    if os.path.exists(dossier):
        shutil.rmtree(dossier)
    for s in ("f", "z", "zlib6"):
        os.makedirs(os.path.join(dossier, s))
    harnais = stats_lz.construire()
    sortie = subprocess.run([harnais, "--corpus", commun.CORPUS, "--prefixe", str(prefixe), "--ecrire-zlib6",
                             os.path.join(dossier, "zlib6")], capture_output=True, text=True, check=True).stdout
    lignes = []
    for l in sortie.splitlines():
        _, i, taille, nom = l.split(" ", 3)
        nom_plat = nom.replace("/", "_")
        with open(os.path.join(commun.CORPUS, nom), "rb") as f:
            donnees = f.read()[:prefixe]
        with open(os.path.join(dossier, "f", nom_plat), "wb") as f:
            f.write(donnees)
        os.replace(os.path.join(dossier, "zlib6", f"{i}.z"), os.path.join(dossier, "z", nom_plat))
        lignes += [f"f {nom_plat} {len(donnees)}", f"z {nom_plat} {taille}"]
    with open(os.path.join(dossier, "liste"), "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    return len(lignes) // 2


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--scenarios", default="n1,n6,n9,decompression")
    a.add_argument("--prefixe", type=int, default=commun.PREFIXE)
    a.add_argument("--json", required=True)
    args = a.parse_args()

    commun.verifier_sources()
    base = os.path.join(commun.CONSTR, "juge")
    execution = construire(base)
    entrees = os.path.join(base, "entrees")
    n = preparer_entrees(entrees, args.prefixe)
    resultat = {"commit_sources": commun.COMMIT, "prefixe": args.prefixe, "fichiers": n,
                "options_cache": commun.OPTIONS_CACHE, "evenements": cachegrind.EVENEMENTS, "mesures": {}}
    for s in args.scenarios.split(","):
        sorties = os.path.join(base, "sorties-" + s)
        if os.path.exists(sorties):
            shutil.rmtree(sorties)
        os.makedirs(sorties)
        fichier = os.path.join(base, f"cachegrind.juge.{s}")
        subprocess.run(["valgrind", "--tool=cachegrind", "--cache-sim=yes", "--branch-sim=yes"] + commun.OPTIONS_CACHE
                       + [f"--cachegrind-out-file={fichier}", execution, s, entrees, sorties, "--prefixe", str(args.prefixe)],
                       check=True, capture_output=True)
        couts, resume = cachegrind.lire_cachegrind(fichier)
        total, fonctions, zones, hors = cachegrind.regrouper(couts)
        resultat["mesures"][s] = {
            "total": cachegrind.en_dict(total),
            "fonctions": {k: cachegrind.en_dict(v) for k, v in sorted(fonctions.items(), key=lambda x: -x[1][0])},
            "zones": {k: cachegrind.en_dict(v) for k, v in sorted(zones.items(), key=lambda x: -x[1][0])},
            "hors_miniz": {k: cachegrind.en_dict(v) for k, v in sorted(hors.items(), key=lambda x: -x[1][0])[:25]},
        }
        print(f"{s:14} Ir {total[0]:>12,} (tout le processus du harnais du juge)", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
