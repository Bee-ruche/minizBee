#!/bin/sh
# Construction d'une variante (A = base, B = PR) pour le juge isolé, DANS le conteneur sans réseau.
# Lancé par bee/juge/juge.py ; aucune ligne de miniz n'est exécutée ici, on compile et on analyse.
#
# Usage : construire.sh <sources_miniz> <outillage_base> <sortie> [--chrono]
#   <sources_miniz>   miniz*.c et miniz*.h de la variante (lecture seule)
#   <outillage_base>  copie de la BASE : bee/juge, bee/commun et ses propres en-têtes de miniz (base/)
#   <sortie>          dossier inscriptible : obj/, execution, et les relevés d'analyse (texte)
#   --chrono          compile aussi le lanceur chrono (variante A seulement : il ne voit jamais la PR)
#
# Le harnais (execution.c) est compilé avec les en-têtes de miniz de la BASE, pas avec ceux de la PR :
# une macro glissée dans miniz.h ne peut pas réécrire le harnais. Seuls miniz.c, miniz_tdef.c et
# miniz_tinfl.c de la variante sont compilés avec ses propres en-têtes (options de la construction
# « Release » de miniz, comme bee/Makefile).
set -eu
umask 000  # l'hôte doit pouvoir effacer ce que le conteneur écrit (autre utilisateur)

source_miniz="$1"
outillage="$2"
sortie="$3"
chrono="${4:-}"

mkdir -p "$sortie/obj"
for f in miniz miniz_tdef miniz_tinfl; do
  cc -O3 -DNDEBUG -g -std=gnu90 -D_GNU_SOURCE -I"$source_miniz" -I"$outillage/bee/commun" \
    -c "$source_miniz/$f.c" -o "$sortie/obj/$f.o"
done
cc -O2 -g -std=gnu99 -D_GNU_SOURCE -Wall -Wextra -Wno-unused-parameter \
  -I"$outillage/base" -I"$outillage/bee/commun" \
  "$outillage/bee/juge/execution.c" "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" \
  -o "$sortie/execution"

if [ "$chrono" = "--chrono" ]; then
  cc -O2 -std=gnu99 -Wall -Wextra "$outillage/bee/juge/chrono.c" -o "$sortie/chrono"
fi

# Relevés pour l'analyse des objets (bee/juge/analyse.py, côté hôte) : symboles, sections, désassemblage.
nm -P -A "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" > "$sortie/symboles.txt"
objdump -h "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" > "$sortie/sections.txt"
objdump -d --no-show-raw-insn "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" \
  > "$sortie/desassemblage.txt"
echo "construction terminée"
