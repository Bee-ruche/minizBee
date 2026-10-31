#!/usr/bin/env python3
"""Compare deux JSON de profil.py (avant, après) : coût exclusif qui change d'attribution, par scénario.

Usage : python3 bee/resultats/miniz-0034/comparer.py profil-avant.json profil-apres.json > comparaison.txt
"""
import json
import sys

a, b = (json.load(open(chemin, encoding="utf-8")) for chemin in sys.argv[1:3])
print("Coût exclusif (Ir) qui change d'attribution entre profil.py de a2f939a (avant) et celui de miniz-0034 (après),")
print("mêmes fichiers callgrind (--reutiliser), même session de sandbox.")
for s in a:
    fa = {f["fonction"]: f["ir"] for f in a[s]["fonctions"]}
    fb = {f["fonction"]: f["ir"] for f in b[s]["fonctions"]}
    print(f"== {s} : total {a[s]['total_ir']:,} avant, {b[s]['total_ir']:,} après ; "
          f"somme des fonctions {sum(fa.values()):,} / {sum(fb.values()):,}")
    for n in sorted(set(fa) | set(fb)):
        if fa.get(n) != fb.get(n):
            print(f"   {n:30s} {fa.get(n, 0):>8,} -> {fb.get(n, 0):>8,}")
