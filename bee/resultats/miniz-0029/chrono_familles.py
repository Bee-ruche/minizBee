#!/usr/bin/env python3
"""Chronomètre du banc par scénario et par famille, sur les mêmes entrées que cachegrind.py (128 premiers
Kio de chaque fichier), pour rapprocher temps et instructions : nanosecondes par octet et par instruction
(miniz-0029).

Le banc garde la meilleure de --passes passes (bee/README.md). Les nanosecondes par instruction
divisent ce temps par le décompte de Cachegrind des mêmes passes (donnees/cachegrind.json) : c'est un
CPI apparent (× 2,1 pour des cycles sur la machine de référence), qui grandit quand le temps dépend
d'autre chose que du nombre d'instructions (défauts de cache, branches mal prédites, dépendances).
Machine partagée : quelques % de bruit d'une exécution à l'autre ; --repetitions relance le tout et
garde la médiane.

Usage (depuis la racine du dépôt, dans la sandbox, après cachegrind.py) :
  bee/sandbox/sans-docker.sh python3 bee/resultats/miniz-0029/chrono_familles.py \
      --cachegrind bee/resultats/miniz-0029/donnees/cachegrind.json \
      --json bee/resultats/miniz-0029/donnees/chrono_familles.json
"""

import argparse
import json
import os
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commun  # noqa: E402

CLES = {"n1": "debit_compression_n1", "n6": "debit_compression_n6", "n9": "debit_compression_n9",
        "decompression": "debit_decompression"}


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--scenarios", default="n1,n6,n9,decompression")
    a.add_argument("--familles", default="tout," + ",".join(commun.FAMILLES))
    a.add_argument("--passes", type=int, default=15)
    a.add_argument("--repetitions", type=int, default=3)
    a.add_argument("--cachegrind", required=True)
    a.add_argument("--json", required=True)
    args = a.parse_args()

    commun.verifier_sources()
    subprocess.run(["make", "-s", "-C", commun.BEE, "banc"], check=True)
    with open(args.cachegrind, encoding="utf-8") as f:
        cg = json.load(f)
    resultat = {"commit_sources": commun.COMMIT, "prefixe": cg["prefixe"], "passes": args.passes,
                "repetitions": args.repetitions, "mesures": {}}
    for s in args.scenarios.split(","):
        for fam in args.familles.split(","):
            debits = []
            for _ in range(args.repetitions):
                r = subprocess.run([commun.BANC, "--corpus", commun.corpus_de(fam), "--scenario", s, "--passes",
                                    str(args.passes), "--prefixe", str(cg["prefixe"]), "--sans-memoire"],
                                   capture_output=True, text=True, check=True)
                debits.append(json.loads(r.stdout)[CLES[s]])
            mesure = cg["mesures"][s][fam]
            octets, ir = mesure["octets"], mesure["total"]["Ir"]
            debit = statistics.median(debits)  # Mo/s, Mo = 10^6 octets
            ns_octet = 1e3 / debit
            resultat["mesures"].setdefault(s, {})[fam] = {
                "debits_mo_s": debits, "debit_median_mo_s": debit, "ns_par_octet": ns_octet,
                "instructions_par_octet": ir / octets, "ns_par_instruction": ns_octet * octets / ir}
            print(f"{s:14} {fam:10} {debit:9.2f} Mo/s  {ns_octet:7.2f} ns/octet  {ir / octets:7.1f} instr/octet  "
                  f"{ns_octet * octets / ir:.3f} ns/instr", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
