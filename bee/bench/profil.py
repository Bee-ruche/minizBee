#!/usr/bin/env python3
"""Profilage callgrind de miniz sur un sous-corpus, regroupé par fonction source.

Pour chaque scénario (n1, n6, n9, decompression), lance le banc sous
  valgrind --tool=callgrind --toggle-collect=bee_passe_compression|bee_passe_decompression
sur les --prefixe premiers octets de chaque fichier du corpus (131072 par défaut, soit 2,2 Mo),
puis attribue le coût exclusif (Ir) de chaque ligne de miniz à la fonction qui la contient dans le
source. Les fonctions inline (tdefl_find_match, tdefl_record_*) apparaissent ainsi séparément,
alors que callgrind les fond dans leur appelant (tdefl_compress_normal).

Usage : python3 bee/bench/profil.py [--prefixe 131072] [--scenarios n1,n6,n9,decompression]
                                    [--sortie bee/construction/profil] [--json profil.json]
Prérequis : valgrind (callgrind_annotate), le banc compilé (make -C bee banc).
"""

import argparse
import json
import os
import re
import subprocess
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
BEE = os.path.dirname(ICI)
RACINE = os.path.dirname(BEE)
SOURCES = ["miniz_tdef.c", "miniz_tinfl.c", "miniz.c"]
DEBUT_FONCTION = re.compile(r"^\s*(?:static\s+)?(?:MZ_FORCEINLINE\s+)?(?:MINIZ_EXPORT\s+)?"
                            r"(?:const\s+)?[A-Za-z_][A-Za-z0-9_ \*]*?\b([a-z_][a-z0-9_]*)\s*\([^;]*$")


def plages_de_fonctions(chemin):
    """(début, fin, nom) des définitions de fonctions, repérées par leur ligne d'en-tête et leurs accolades."""
    lignes = open(chemin, encoding="utf-8", errors="replace").read().split("\n")
    plages, i = [], 0
    while i < len(lignes):
        m = DEBUT_FONCTION.match(lignes[i])
        if m and not lignes[i].rstrip().endswith(";") and m.group(1) not in ("if", "while", "for", "switch", "return", "sizeof"):
            j = i
            while j < len(lignes) and "{" not in lignes[j] and not lignes[j].rstrip().endswith(";"):
                j += 1
            if j < len(lignes) and "{" in lignes[j]:
                profondeur, k = 0, j
                while k < len(lignes):
                    profondeur += lignes[k].count("{") - lignes[k].count("}")
                    if profondeur <= 0 and k >= j:
                        break
                    k += 1
                plages.append((i + 1, k + 1, m.group(1)))
                i = k
        i += 1
    return plages


def nom_de(plages, ligne, fichier):
    candidats = [p for p in plages if p[0] <= ligne <= p[1]]
    if not candidats:
        return f"{fichier} (hors fonction)"
    debut, fin, nom = max(candidats, key=lambda p: p[0])  # la plus interne
    doublons = [p for p in plages if p[2] == nom]
    if len(doublons) > 1:  # variantes sous #if (tdefl_find_match, tdefl_compress_lz_codes)
        return f"{nom} (l. {debut})"
    return nom


def couts_par_ligne(fichier_callgrind, sources):
    sortie = subprocess.run(["callgrind_annotate", "--inclusive=no", "--auto=yes", "--context=0", "--threshold=100",
                             fichier_callgrind] + sources, capture_output=True, text=True, check=True).stdout
    total = int(re.search(r"^\s*([\d,]+) \(100\.0%\)\s+PROGRAM TOTALS", sortie, re.M).group(1).replace(",", ""))
    couts, courant, ligne, vus = {}, None, None, set()
    for l in sortie.split("\n"):
        m = re.match(r"^-- (?:User|Auto)-annotated source: (.*)$", l)
        if m:
            nom = os.path.basename(m.group(1))
            # Un même source peut être annoté deux fois (section automatique et section demandée) : la
            # seconde section, si elle a des données, répète la première ; on ne compte que la première.
            courant = nom if (nom in SOURCES and nom not in vus) else None
            ligne = None
            continue
        if courant and l.startswith("-- line "):
            vus.add(courant)
        m = re.match(r"^-- line (\d+) -+$", l)
        if m:
            ligne = int(m.group(1))
            continue
        # « N (x%)  => fichier:fonction (k x) » : coût INCLUSIF d'un appel fait depuis cette ligne, déjà
        # compté dans la fonction appelée ; on l'ignore pour ne garder que le coût exclusif.
        if l.startswith("-----"):  # fin de section (puis résumé « events annotated ») : plus de source courant
            if ligne is not None:
                courant, ligne = None, None
            continue
        m = re.match(r"^\s*([\d,]+) \(\s*[\d.]+%\)\s+(.*)$", l)
        if m and courant and ligne is not None and not m.group(2).lstrip().startswith("=>"):
            couts[(courant, ligne)] = couts.get((courant, ligne), 0) + int(m.group(1).replace(",", ""))
    return couts, total, sortie


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--prefixe", type=int, default=131072)
    analyseur.add_argument("--scenarios", default="n1,n6,n9,decompression")
    analyseur.add_argument("--sortie", default=os.path.join(BEE, "construction", "profil"))
    analyseur.add_argument("--banc", default=os.path.join(BEE, "construction", "banc", "banc"))
    analyseur.add_argument("--corpus", default=os.path.join(BEE, "corpus", "donnees"))
    analyseur.add_argument("--json", help="écrit le résultat regroupé dans ce fichier")
    analyseur.add_argument("--reutiliser", action="store_true", help="réutilise les fichiers callgrind existants")
    args = analyseur.parse_args()

    os.makedirs(args.sortie, exist_ok=True)
    sources = [os.path.join(RACINE, s) for s in SOURCES]
    plages = {s: plages_de_fonctions(os.path.join(RACINE, s)) for s in SOURCES}
    resultat = {}
    for scenario in args.scenarios.split(","):
        fichier = os.path.join(args.sortie, f"callgrind.{scenario}")
        if not (args.reutiliser and os.path.exists(fichier)):
            cible = "bee_passe_decompression" if scenario == "decompression" else "bee_passe_compression"
            subprocess.run(["valgrind", "--tool=callgrind", f"--toggle-collect={cible}", f"--callgrind-out-file={fichier}",
                            args.banc, "--corpus", args.corpus, "--scenario", scenario, "--passes", "1",
                            "--prefixe", str(args.prefixe), "--sans-memoire"], check=True, capture_output=True)
        couts, total, _ = couts_par_ligne(fichier, sources)
        groupes = {}
        for (f, l), c in couts.items():
            n = nom_de(plages.get(f, []), l, f) if f in plages else f
            groupes[n] = groupes.get(n, 0) + c
        hors_miniz = total - sum(couts.values())
        if hors_miniz > 0:
            groupes["hors miniz (libc : memset, memcpy…)"] = hors_miniz
        classement = sorted(groupes.items(), key=lambda x: -x[1])
        resultat[scenario] = {"total_ir": total, "fonctions": [{"fonction": n, "ir": c, "part": c / total} for n, c in classement]}
        print(f"== {scenario} : {total:,} instructions (passes mesurées, {args.prefixe} premiers octets par fichier)")
        for n, c in classement[:10]:
            print(f"  {100 * c / total:6.2f} %  {c:>13,}  {n}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultat, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
