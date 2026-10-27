#!/usr/bin/env bash
# Tests différentiels Bee pour miniz : corpus, compilation, miniz contre zlib, flux, déterminisme.
#
# Usage (depuis n'importe où) :
#   bee/tests/lancer.sh                         tout, y compris le contrôle des empreintes
#   bee/tests/lancer.sh --sans-empreintes       saute le déterminisme (tâche « sortie_compressee: peut_changer »)
#   bee/tests/lancer.sh --regenerer-empreintes  réécrit bee/tests/empreintes-reference.txt (version de base seulement)
#   bee/tests/lancer.sh --rapide                flux à 1 octet limité aux fichiers de 64 Kio au plus
#   bee/tests/lancer.sh --source DOSSIER        juge les sources de miniz d'un autre dossier (utilisé par la CI)
#   bee/tests/lancer.sh --sanitiseurs           compile avec ASan et UBSan (plus lent)
# Variables : CC (compilateur), BEE_CONSTR (dossier de construction).
# Code de sortie : 0 si tout est identique, 1 au moindre écart, 2 si l'environnement ne convient pas.
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"
SOURCE="$RACINE"
CONSTR="${BEE_CONSTR:-$BEE/construction/tests}"
ARGS=()
OPT_TESTS="-O2 -g"

while [ $# -gt 0 ]; do
  case "$1" in
    --sans-empreintes|--regenerer-empreintes|--rapide|--verbeux) ARGS+=("$1") ;;
    --source) SOURCE="$(cd "$2" && pwd)"; shift ;;
    --sanitiseurs) OPT_TESTS="-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all"
                   CONSTR="${CONSTR}-sanitiseurs" ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "option inconnue : $1 (voir --help)" >&2; exit 2 ;;
  esac
  shift
done

for f in miniz.c miniz_tdef.c miniz_tinfl.c miniz.h; do
  [ -f "$SOURCE/$f" ] || { echo "erreur : $SOURCE/$f introuvable (--source doit désigner une copie de miniz)" >&2; exit 2; }
done

echo "== 1/3 Corpus de référence"
python3 "$BEE/corpus/generer.py" || { echo "ÉCHEC : corpus non conforme à bee/corpus/SHA256SUMS" >&2; exit 1; }

echo "== 2/3 Compilation (sources : $SOURCE)"
make --no-print-directory -s -C "$BEE" SOURCE="$SOURCE" CONSTR="$CONSTR" OPT_TESTS="$OPT_TESTS" differentiel \
  || { echo "ÉCHEC : la compilation des tests différentiels a échoué" >&2; exit 1; }

echo "== 3/3 Tests différentiels et empreintes"
cd "$RACINE"
"$CONSTR/differentiel" --corpus "$BEE/corpus/donnees" --empreintes "$ICI/empreintes-reference.txt" ${ARGS[@]+"${ARGS[@]}"}
