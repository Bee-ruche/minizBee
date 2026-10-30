#!/bin/sh
# Construction d'une variante (A = base, B = PR) pour le juge commun Bee, DANS le conteneur sans réseau.
# Lancé par le juge commun (registre : outils/juge/juge.py), d'après CONSTRUIRE de bee/juge/projet.py de
# la BASE ; aucune ligne de miniz n'est exécutée ici, on compile.
#
# Usage : construire.sh <sources_miniz> <outillage_base> <sortie>
#   <sources_miniz>   miniz.c, miniz_tdef.c, miniz_tinfl.c et miniz*.h de la variante (lecture seule)
#   <outillage_base>  copie de la BASE : bee/juge, bee/commun et ses propres en-têtes de miniz (base/)
#   <sortie>          dossier inscriptible : obj/ (un objet par fichier .c de la variante) et execution
#
# Le harnais (execution.c) est compilé avec les en-têtes de miniz de la BASE, pas avec ceux de la PR :
# une macro glissée dans miniz.h ne peut pas réécrire le harnais. Seuls miniz.c, miniz_tdef.c et
# miniz_tinfl.c de la variante sont compilés avec ses propres en-têtes (options de la construction
# « Release » de miniz, comme bee/Makefile). Le lanceur chrono et les relevés d'analyse (nm, objdump sur
# tous les objets de obj/) sont l'affaire du juge commun, pas de ce script.
set -eu
umask 000  # l'hôte doit pouvoir effacer ce que le conteneur écrit (autre utilisateur)

source_miniz="$1"
outillage="$2"
sortie="$3"

mkdir -p "$sortie/obj"
for f in miniz miniz_tdef miniz_tinfl; do
  cc -O3 -DNDEBUG -g -std=gnu90 -D_GNU_SOURCE -I"$source_miniz" -I"$outillage/bee/commun" \
    -c "$source_miniz/$f.c" -o "$sortie/obj/$f.o"
done
cc -O2 -g -std=gnu99 -D_GNU_SOURCE -Wall -Wextra -Wno-unused-parameter \
  -I"$outillage/base" -I"$outillage/bee/commun" \
  "$outillage/bee/juge/execution.c" "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" \
  -o "$sortie/execution"
echo "construction terminée"
