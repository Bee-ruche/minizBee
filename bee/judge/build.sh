#!/bin/sh
# Build of a variant (A = base, B = PR) for the Bee common judge, INSIDE the container without network.
# Run by the common judge (registry: tools/judge/judge.py), as BUILD of the BASE's bee/judge/project.py says; no
# line of miniz runs here, it compiles.
#
# Usage: build.sh <miniz_sources> <base_tooling> <output>
#   <miniz_sources>   the variant's miniz.c, miniz_tdef.c, miniz_tinfl.c and miniz*.h (read-only)
#   <base_tooling>    copy of the BASE: bee/judge, bee/commun and its own miniz headers (base/)
#   <output>          writable folder: obj/ (one object per .c file of the variant) and execution
#
# The harness (execution.c) is compiled with the BASE's miniz headers, not the PR's: a macro slipped into miniz.h
# cannot rewrite the harness. Only the variant's miniz.c, miniz_tdef.c and miniz_tinfl.c are compiled with its own
# headers (the options of miniz's "Release" build, like bee/Makefile). The chrono launcher and the analysis surveys
# (nm, objdump on all the objects of obj/) are the common judge's business, not this script's.
set -eu
umask 000  # the host must be able to delete what the container writes (another user)

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
  "$outillage/bee/judge/execution.c" "$sortie/obj/miniz.o" "$sortie/obj/miniz_tdef.o" "$sortie/obj/miniz_tinfl.o" \
  -o "$sortie/execution"
echo "build done"
