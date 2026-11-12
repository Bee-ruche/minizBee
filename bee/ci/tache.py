#!/usr/bin/env python3
"""Finds, in the Bee registry, the task that a PR's manifest names (manifests/<task>.yaml or manifestes/).

The manifest comes from the PR: it is data, read with yaml.safe_load and validated, never executed; it is a regular
file (neither a symbolic link nor a folder), checked before it is opened. The task comes from the registry (branch
main, tasks/miniz/): the registry, not the PR, sets the metric aimed at and the right to change the compressed output.
The registry is read in English (bee/ci/vocabulaire.py), its metric ids in French or in English until ruche-0149; the
manifest in either vocabulary until bee's DATE_D.

Usage: python3 bee/ci/tache.py --manifeste pr/manifests/miniz-0012.yaml --registre registre [--sortie tache.yaml]
Standard output, one line per value, in the format of $GITHUB_OUTPUT (the names stay those the workflow reads):
  tache=miniz-0012
  type=optimization
  metrique=compression_throughput_n6
  sortie_compressee=identique
The metric in its English name (« none » without one). sortie_compressee keeps the values the base's judges take
(identique, peut_changer: the plugin's option and bee/ci/differentiel.sh), whatever the registry calls them.
Every value is checked against a closed list before it is written.
Exit code: 0 if the task is found and readable; 1 otherwise (message on standard error): task not found, type or
metric unreadable, never a default value.
"""

import argparse
import os
import re
import shutil
import stat
import sys

import yaml

from vocabulaire import Illisible, lire_manifeste, lire_tache

MOTIF_TACHE = re.compile(r"^miniz-[0-9]{4}$")
# compressed_output (the registry's value) -> sortie_compressee (the value the base's judges take).
SORTIES_JUGES = {"identical": "identique", "may_change": "peut_changer"}


def echouer(message):
    print(f"tache.py: {message}", file=sys.stderr)
    print("sortie_compressee=identique")  # in doubt, the strictest check applies
    sys.exit(1)


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--manifeste", required=True)
    analyseur.add_argument("--registre", required=True)
    analyseur.add_argument("--sortie", default="tache.yaml")
    args = analyseur.parse_args()

    # A manifest is a regular file: neither a symbolic link (even a broken one) nor a folder, checked before any reading.
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
        tache = lire_manifeste(manifeste).get("task")
    except Illisible as e:
        echouer(str(e))
    if not isinstance(tache, str) or not MOTIF_TACHE.match(tache):
        echouer("the manifest's key « task » (or « tache ») must be a miniz-NNNN id")
    nom = os.path.basename(args.manifeste)
    if nom != "CONTRIBUTION.yaml" and nom != tache + ".yaml":
        echouer(f"the manifest {nom} names the task {tache}: it must be called manifests/{tache}.yaml (or manifestes/)")

    chemin = os.path.join(args.registre, "tasks", "miniz", tache + ".yaml")
    if not os.path.isfile(chemin):
        echouer(f"task {tache} not found in the registry (tasks/miniz/{tache}.yaml)")
    try:
        with open(chemin, encoding="utf-8") as f:
            valeurs = lire_tache(yaml.safe_load(f))
    except (Illisible, yaml.YAMLError) as e:
        echouer(f"task {tache} unreadable: {e}")
    shutil.copyfile(chemin, args.sortie)
    print(f"tache={tache}")
    print(f"type={valeurs['type']}")
    print(f"metrique={valeurs['metric'] or 'none'}")
    print(f"sortie_compressee={SORTIES_JUGES[valeurs['compressed_output']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
