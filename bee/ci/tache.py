#!/usr/bin/env python3
"""Finds, in the Bee registry, the task that a PR's manifest names (manifests/<task>.yaml or manifestes/).

Le manifeste vient de la PR : c'est une donnée, lue avec yaml.safe_load et validée, jamais exécutée ; c'est un fichier
ordinaire (ni lien symbolique, ni dossier), vérifié avant d'être ouvert.
La tâche vient du registre (branche main) : c'est elle, et non la PR, qui fixe la métrique visée et
le droit de changer la sortie compressée.
Les deux vocabulaires du registre sont lus (bee/ci/vocabulaire.py) : tasks/ ou taches/, clés et valeurs anglaises
ou françaises, ramenées aux noms internes ; un manifeste ou une tâche qui les mêle est refusé.

Usage : python3 bee/ci/tache.py --manifeste pr/manifests/miniz-0012.yaml --registre registre [--sortie tache.yaml]
Sortie standard, une ligne par valeur, au format de $GITHUB_OUTPUT :
  tache=miniz-0012
  type=optimisation
  metrique=debit_compression_n6
  sortie_compressee=identique
Toutes les valeurs sont validées contre une liste fermée avant d'être écrites.
Code de sortie : 0 si la tâche est trouvée et lisible ; 1 sinon (message sur la sortie d'erreur) : tâche introuvable
ou trouvée deux fois, type ou métrique illisible, jamais une valeur par défaut.
"""

import argparse
import glob
import os
import re
import shutil
import stat
import sys

import yaml

from vocabulaire import Illisible, lire_manifeste, lire_tache

MOTIF_TACHE = re.compile(r"^miniz-[0-9]{4}$")


def echouer(message):
    print(f"tache.py: {message}", file=sys.stderr)
    print("sortie_compressee=identique")  # en cas de doute, le contrôle le plus strict s'applique
    sys.exit(1)


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--manifeste", required=True)
    analyseur.add_argument("--registre", required=True)
    analyseur.add_argument("--sortie", default="tache.yaml")
    args = analyseur.parse_args()

    # Un manifeste est un fichier ordinaire : ni lien symbolique (même cassé), ni dossier, vérifié avant toute lecture.
    if not os.path.lexists(args.manifeste):
        echouer("manifest missing: the PR must add manifests/<task>.yaml or manifestes/ (see the registry's AGENTS.md: bee manifest)")
    if not stat.S_ISREG(os.lstat(args.manifeste).st_mode):
        echouer(f"the manifest {os.path.basename(args.manifeste)} must be a regular file (neither a symbolic link nor a folder)")
    try:
        with open(args.manifeste, encoding="utf-8") as f:
            manifeste = yaml.safe_load(f)
    except yaml.YAMLError as e:
        echouer(f"unreadable manifest: {e}")
    try:
        tache = lire_manifeste(manifeste).get("tache")
    except Illisible as e:
        echouer(str(e))
    if not isinstance(tache, str) or not MOTIF_TACHE.match(tache):
        echouer("the manifest's key « task » (or « tache ») must be a miniz-NNNN id")
    nom = os.path.basename(args.manifeste)
    if nom != "CONTRIBUTION.yaml" and nom != tache + ".yaml":
        echouer(f"the manifest {nom} names the task {tache}: it must be named manifests/{tache}.yaml (or manifestes/)")

    candidats = sorted(c for dossier in ("tasks", "taches")
                       for c in glob.glob(os.path.join(args.registre, dossier, "**", tache + ".yaml"), recursive=True))
    if not candidats:
        echouer(f"task {tache} not found in the registry (neither in tasks/ nor in taches/)")
    if len(candidats) > 1:
        echouer(f"task {tache} found several times in the registry ({', '.join(candidats)}): which one?")
    try:
        with open(candidats[0], encoding="utf-8") as f:
            valeurs = lire_tache(yaml.safe_load(f))
    except (Illisible, yaml.YAMLError) as e:
        echouer(f"task {tache} unreadable: {e}")
    shutil.copyfile(candidats[0], args.sortie)
    print(f"tache={tache}")
    print(f"type={valeurs['type']}")
    print(f"metrique={valeurs['metrique'] or 'aucune'}")
    print(f"sortie_compressee={valeurs['sortie_compressee']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
