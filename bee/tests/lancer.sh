#!/usr/bin/env bash
# Bee's differential tests for miniz: corpus, build, miniz against zlib, streams, determinism,
# then edge cases of the zlib-compatible API (miniz's return codes compared with zlib's, api.c).
#
# Usage (from anywhere):
#   bee/tests/lancer.sh                         everything, the fingerprint check included
#   bee/tests/lancer.sh --sans-empreintes       skips determinism (task « compressed_output: may_change »)
#   bee/tests/lancer.sh --regenerer-empreintes  rewrites bee/tests/empreintes-reference.txt (base version only)
#   bee/tests/lancer.sh --rapide                1-byte streaming limited to files of 64 KiB at most
#   bee/tests/lancer.sh --source FOLDER         judges the miniz sources of another folder (used by the CI)
#   bee/tests/lancer.sh --sanitiseurs           builds with ASan and UBSan (slower)
# Variables: CC (compiler), BEE_CONSTR (build folder).
# Exit code: 0 if everything is identical, 1 at the slightest discrepancy, 2 if the environment is unsuitable.
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"
SOURCE="$RACINE"
CONSTR="${BEE_CONSTR:-$BEE/construction/tests}"
ARGS=()
ARGS_API=()
OPT_TESTS="-O2 -g"

while [ $# -gt 0 ]; do
  case "$1" in
    --sans-empreintes|--regenerer-empreintes|--rapide) ARGS+=("$1") ;;
    --verbeux) ARGS+=("$1"); ARGS_API+=("$1") ;;
    --source) SOURCE="$(cd "$2" && pwd)"; shift ;;
    --sanitiseurs) OPT_TESTS="-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all"
                   CONSTR="${CONSTR}-sanitiseurs" ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

for f in miniz.c miniz_tdef.c miniz_tinfl.c miniz.h; do
  [ -f "$SOURCE/$f" ] || { echo "error: $SOURCE/$f not found (--source must name a copy of miniz)" >&2; exit 2; }
done

echo "== 1/4 Reference corpus"
python3 "$BEE/corpus/generer.py" || { echo "FAILED: corpus not conforming to bee/corpus/SHA256SUMS" >&2; exit 1; }

echo "== 2/4 Build (sources: $SOURCE)"
make --no-print-directory -s -C "$BEE" SOURCE="$SOURCE" CONSTR="$CONSTR" OPT_TESTS="$OPT_TESTS" differentiel api \
  || { echo "FAILED: the build of the tests failed" >&2; exit 1; }

echo "== 3/4 Differential tests and fingerprints"
cd "$RACINE"
statut=0
"$CONSTR/differentiel" --corpus "$BEE/corpus/donnees" --empreintes "$ICI/empreintes-reference.txt" ${ARGS[@]+"${ARGS[@]}"} || statut=$?

echo "== 4/4 Edge cases of the zlib-compatible API (miniz against zlib)"
"$CONSTR/api" ${ARGS_API[@]+"${ARGS_API[@]}"} || { s=$?; [ "$statut" -ne 0 ] || statut=$s; }
exit "$statut"
