#!/usr/bin/env python3
"""Liste les plages de fonctions que repère un profil.py donné, pour les trois sources de miniz.

Usage : python3 bee/resultats/miniz-0034/plages.py <chemin de profil.py> > plages.txt
Sert à comparer le repérage avant et après miniz-0034 (diff des deux listes).
"""

import importlib.util
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("profil", sys.argv[1])
profil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profil)
for source in profil.SOURCES:
    for debut, fin, nom in profil.plages_de_fonctions(os.path.join(RACINE, source)):
        print(f"{source}:{debut}-{fin} {nom}")
