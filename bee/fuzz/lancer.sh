#!/usr/bin/env bash
# Bee's fuzzing for miniz: two harnesses, run in parallel (one per core), each for <seconds>.
#
#   fuzz_inflate      inflate of arbitrary inputs, miniz (one shot and streamed) against zlib
#   fuzz_compression  miniz compression (level drawn from the input) then zlib decompression
#
# Usage:
#   bee/fuzz/lancer.sh <seconds> [--source FOLDER] [--reference FOLDER] [--moteur auto|libfuzzer|gcc] [--harnais NAME]
#   --source     miniz sources to fuzz (default: the repository's root; the CI passes the PR's sources)
#   --reference  reference miniz sources (the CI passes the PR's base): each failing input is replayed
#                on them. If it fails there too, the discrepancy is PRE-EXISTING: it is reported but does
#                not count against the PR. Otherwise, or without --reference, it is a NEW discrepancy.
#   --moteur     libfuzzer: clang -fsanitize=fuzzer,address,undefined (needs clang's runtime,
#                           package libclang-rt-18-dev on Ubuntu 24.04);
#                gcc:       local fallback, same harnesses with gcc ASan/UBSan and a driver of random
#                           mutations without coverage feedback (bee/fuzz/pilote_aleatoire.c);
#                auto:      libfuzzer if clang can link -fsanitize=fuzzer, otherwise gcc (default).
#   --harnais    only one of the two harnesses.
# Variables: CLANG (default clang), CC (default cc), BEE_FUZZ_SORTIES (logs and failing inputs,
#            default bee/fuzz/sorties), BEE_CONSTR (build folder),
#            BEE_FUZZ_DISCRET (1: shows neither log nor trace, only the fingerprint of the failing
#            inputs; 1 by default under GitHub Actions, whose logs are public).
# Exit code: 0 if no new discrepancy (pre-existing discrepancies are only reported),
#            1 otherwise (failing inputs in BEE_FUZZ_SORTIES, to keep to yourself: docs/security.md).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"

if [ $# -lt 1 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  sed -n '2,25p' "$0"
  exit 2
fi
duree="$1"
shift
source_miniz="$RACINE"
reference=""
moteur="auto"
harnais=(fuzz_inflate fuzz_compression)
while [ $# -gt 0 ]; do
  case "$1" in
    --source) source_miniz="$(cd "$2" && pwd)"; shift ;;
    --reference) reference="$(cd "$2" && pwd)"; shift ;;
    --moteur) moteur="$2"; shift ;;
    --harnais) harnais=("$2"); shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

CLANG="${CLANG:-clang}"
sorties="${BEE_FUZZ_SORTIES:-$ICI/sorties}"
constr="${BEE_CONSTR:-$BEE/construction/fuzz}"
mkdir -p "$sorties" "$constr"
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then discret="${BEE_FUZZ_DISCRET:-1}"; else discret="${BEE_FUZZ_DISCRET:-0}"; fi

if [ "$moteur" = "auto" ]; then
  essai="$(mktemp -d)"
  printf '#include <stdint.h>\n#include <stddef.h>\nint LLVMFuzzerTestOneInput(const uint8_t *d, size_t n) { (void)d; (void)n; return 0; }\n' > "$essai/essai.c"
  if "$CLANG" -fsanitize=fuzzer,address,undefined "$essai/essai.c" -o "$essai/essai" >/dev/null 2>&1; then
    moteur="libfuzzer"
  else
    moteur="gcc"
    echo "lancer.sh: $CLANG cannot link -fsanitize=fuzzer (libclang_rt runtime missing):"
    echo "           falling back on gcc + ASan/UBSan with a driver of random mutations (without coverage)."
  fi
  rm -rf "$essai"
fi
case "$moteur" in
  libfuzzer) cible="fuzz-libfuzzer"; prefixe="libfuzzer" ;;
  gcc) cible="fuzz-gcc"; prefixe="gcc" ;;
  *) echo "unknown engine: $moteur" >&2; exit 2 ;;
esac
if [ "$moteur" = "gcc" ]; then
  # Par défaut, ASan et UBSan quittent par _exit(1) : le pilote de repli, qui ne sauve l'entrée fautive
  # que sur SIGABRT ou SIGSEGV, la perdait, et le classement nouveau / préexistant devenait impossible.
  # abort_on_error=1 fait passer toute erreur par abort(), donc par la sauvegarde.
  export ASAN_OPTIONS="abort_on_error=1${ASAN_OPTIONS:+:$ASAN_OPTIONS}"
  export UBSAN_OPTIONS="abort_on_error=1:halt_on_error=1${UBSAN_OPTIONS:+:$UBSAN_OPTIONS}"
fi

echo "== Corpus and seeds"
python3 "$BEE/corpus/generer.py"
python3 "$ICI/graines.py" --sortie "$constr/graines"

echo "== Build ($moteur, sources: $source_miniz)"
make --no-print-directory -s -C "$BEE" SOURCE="$source_miniz" CONSTR="$constr" CLANG="$CLANG" "$cible"

echo "== Fuzzing: ${harnais[*]}, $duree s each, in parallel"
pids=()
for h in "${harnais[@]}"; do
  mkdir -p "$constr/corpus-$h" "$sorties/$h"
  journal="$sorties/$h.log"
  # -rss_limit_mb : 2 Go par harnais (la machine de CI a 7 Go et deux harnais tournent ensemble).
  "$constr/$prefixe-$h" -max_total_time="$duree" -rss_limit_mb=2048 -timeout=25 -print_final_stats=1 \
    -artifact_prefix="$sorties/$h/" "$constr/corpus-$h" "$constr/graines/$h" > "$journal" 2>&1 &
  pids+=("$!")
done

# Rejoue une entrée fautive sur les sources de référence : code 0 si elle y échoue aussi (préexistant).
rejouer_sur_reference() {
  local h="$1" entree="$2" bac
  bac="$(mktemp -d)"
  # -max_total_time=0 : le pilote gcc rejoue les fichiers puis s'arrête ; libFuzzer exécute un fichier donné une fois.
  if "$constr/reference/$prefixe-$h" -max_total_time=0 -rss_limit_mb=2048 -timeout=25 -artifact_prefix="$bac/" "$entree" >/dev/null 2>&1; then
    rm -rf "$bac"; return 1
  fi
  rm -rf "$bac"; return 0
}

signaler() {
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::$1::$2"; else echo "$2" >&2; fi
}

nouveau=0
for i in "${!harnais[@]}"; do
  h="${harnais[$i]}"
  if wait "${pids[$i]}"; then
    echo "-- $h: no discrepancy. $(grep -E 'stat::number_of_executed_units|pilote: done' "$sorties/$h.log" | tail -1)"
    continue
  fi
  graine="$(grep -oE 'Seed: [0-9]+' "$sorties/$h.log" | head -1 | cut -d' ' -f2 || true)"
  echo "-- $h: the harness failed${graine:+ (libFuzzer seed $graine)}."
  if [ "$discret" != "1" ]; then
    echo "   End of the log $sorties/$h.log:" >&2
    tail -40 "$sorties/$h.log" >&2
  fi
  mapfile -t fautives < <(find "$sorties/$h" -maxdepth 1 -type f \( -name 'crash-*' -o -name 'leak-*' -o -name 'timeout-*' -o -name 'oom-*' \) | sort)
  if [ "${#fautives[@]}" -eq 0 ]; then
    # Échec sans entrée fautive (compilation, erreur interne du moteur) : on ne peut pas le classer.
    nouveau=1
    signaler error "$h: failure without a failing input (see the log locally); counted as a new discrepancy."
    continue
  fi
  if [ -n "$reference" ] && [ ! -x "$constr/reference/$prefixe-$h" ]; then
    echo "== Build of the harness $h on the reference ($reference)"
    make --no-print-directory -s -C "$BEE" SOURCE="$reference" CONSTR="$constr/reference" CLANG="$CLANG" "$constr/reference/$prefixe-$h" >/dev/null
  fi
  for f in "${fautives[@]}"; do
    empreinte="$(sha256sum "$f" | cut -c1-16)"
    taille="$(stat -c %s "$f")"
    if [ -n "$reference" ] && rejouer_sur_reference "$h" "$f"; then
      signaler warning "$h: PRE-EXISTING discrepancy (the input also fails on the reference), input sha256:$empreinte… ($taille bytes). It does not count against the PR; report it privately to the council (the registry's docs/security.md)."
    else
      nouveau=1
      precision=""
      [ -n "$reference" ] && precision=" (the input passes on the reference)"
      signaler error "$h: NEW discrepancy$precision, input sha256:$empreinte… ($taille bytes). Reproduce it in your sandbox; publish neither the input nor the trace (the registry's docs/security.md)."
    fi
  done
  if [ "$discret" = "1" ]; then
    echo "   Discreet mode: no log, trace or input published. Inputs kept in $sorties/$h/ on the machine that fuzzed."
  else
    echo "   Failing inputs: ${fautives[*]}" >&2
  fi
done
exit "$nouveau"
