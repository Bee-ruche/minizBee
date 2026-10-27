#!/usr/bin/env python3
"""Prépare les graines des deux harnais de fuzzing à partir du corpus de référence.

- fuzz_compression : préfixe de 3 octets (niveau, stratégie, tampons) + tranche d'un fichier du corpus.
- fuzz_inflate : préfixe de 2 octets (format, tampons) + flux zlib ou Deflate brut de la tranche,
  produit par le module zlib de Python (c'est la référence, pas miniz).
Déterministe (pas d'aléa). Les graines sont des fichiers produits : jamais versionnés.

Usage : python3 bee/fuzz/graines.py [--corpus bee/corpus/donnees] [--sortie bee/fuzz/corpus-graines]
"""

import argparse
import os
import zlib

ICI = os.path.dirname(os.path.abspath(__file__))
BEE = os.path.dirname(ICI)


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--corpus", default=os.path.join(BEE, "corpus", "donnees"))
    analyseur.add_argument("--sortie", default=os.path.join(ICI, "corpus-graines"))
    analyseur.add_argument("--taille-tranche", type=int, default=4096)
    args = analyseur.parse_args()

    fichiers = []
    for base, _, noms in os.walk(args.corpus):
        for nom in sorted(noms):
            fichiers.append(os.path.join(base, nom))
    fichiers.sort()
    if not fichiers:
        raise SystemExit("graines : corpus vide (python3 bee/corpus/generer.py)")

    dossiers = {h: os.path.join(args.sortie, h) for h in ("fuzz_inflate", "fuzz_compression")}
    for d in dossiers.values():
        os.makedirs(d, exist_ok=True)
    nombre = 0
    for i, chemin in enumerate(fichiers):
        with open(chemin, "rb") as f:
            tranche = f.read(args.taille_tranche)
        niveau = (0, 1, 6, 9, 10)[i % 5]
        with open(os.path.join(dossiers["fuzz_compression"], f"graine-{i:03d}"), "wb") as f:
            f.write(bytes([niveau, i % 5, i % 8]) + tranche)
        brut = i % 2
        compresseur = zlib.compressobj(niveau if niveau <= 9 else 9, zlib.DEFLATED, -15 if brut else 15)
        flux = compresseur.compress(tranche) + compresseur.flush()
        with open(os.path.join(dossiers["fuzz_inflate"], f"graine-{i:03d}"), "wb") as f:
            f.write(bytes([brut, i % 8]) + flux)
        nombre += 1
    print(f"graines : {nombre} par harnais dans {args.sortie}")


if __name__ == "__main__":
    main()
