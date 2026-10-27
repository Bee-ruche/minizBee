#!/usr/bin/env bash
# Fuzzing Bee pour miniz : deux harnais, lancés en parallèle (un par cœur), chacun pendant <secondes>.
#
#   fuzz_inflate      inflate d'entrées arbitraires, miniz (une fois et en flux) contre zlib
#   fuzz_compression  compression miniz (niveau tiré de l'entrée) puis décompression zlib
#
# Usage :
#   bee/fuzz/lancer.sh <secondes> [--source DOSSIER] [--reference DOSSIER] [--moteur auto|libfuzzer|gcc] [--harnais NOM]
#   --source     sources de miniz à fuzzer (défaut : la racine du dépôt ; la CI passe les sources de la PR)
#   --reference  sources de miniz de référence (la CI passe la base de la PR) : chaque entrée fautive y
#                est rejouée. Si elle y échoue aussi, l'écart est PRÉEXISTANT : il est signalé mais ne
#                compte pas contre la PR. Sinon, ou sans --reference, c'est un écart NOUVEAU.
#   --moteur     libfuzzer : clang -fsanitize=fuzzer,address,undefined (exige le runtime de clang,
#                            paquet libclang-rt-18-dev sous Ubuntu 24.04) ;
#                gcc       : repli local, même harnais avec gcc ASan/UBSan et un pilote de mutations
#                            aléatoires sans retour de couverture (bee/fuzz/pilote_aleatoire.c) ;
#                auto      : libfuzzer si clang sait lier -fsanitize=fuzzer, sinon gcc (défaut).
#   --harnais    un seul des deux harnais.
# Variables : CLANG (défaut clang), CC (défaut cc), BEE_FUZZ_SORTIES (journaux et entrées fautives,
#             défaut bee/fuzz/sorties), BEE_CONSTR (dossier de construction),
#             BEE_FUZZ_DISCRET (1 : n'affiche ni journal ni trace, seulement l'empreinte des entrées
#             fautives ; vaut 1 par défaut sous GitHub Actions, dont les journaux sont publics).
# Code de sortie : 0 si aucun écart nouveau (les écarts préexistants sont seulement signalés),
#                  1 sinon (entrées fautives dans BEE_FUZZ_SORTIES, à garder pour soi : docs/securite.md).
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
    *) echo "option inconnue : $1" >&2; exit 2 ;;
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
    echo "lancer.sh : $CLANG ne sait pas lier -fsanitize=fuzzer (runtime libclang_rt absent) :"
    echo "            repli sur gcc + ASan/UBSan avec un pilote de mutations aléatoires (sans couverture)."
  fi
  rm -rf "$essai"
fi
case "$moteur" in
  libfuzzer) cible="fuzz-libfuzzer"; prefixe="libfuzzer" ;;
  gcc) cible="fuzz-gcc"; prefixe="gcc" ;;
  *) echo "moteur inconnu : $moteur" >&2; exit 2 ;;
esac
if [ "$moteur" = "gcc" ]; then
  # Par défaut, ASan et UBSan quittent par _exit(1) : le pilote de repli, qui ne sauve l'entrée fautive
  # que sur SIGABRT ou SIGSEGV, la perdait, et le classement nouveau / préexistant devenait impossible.
  # abort_on_error=1 fait passer toute erreur par abort(), donc par la sauvegarde.
  export ASAN_OPTIONS="abort_on_error=1${ASAN_OPTIONS:+:$ASAN_OPTIONS}"
  export UBSAN_OPTIONS="abort_on_error=1:halt_on_error=1${UBSAN_OPTIONS:+:$UBSAN_OPTIONS}"
fi

echo "== Corpus et graines"
python3 "$BEE/corpus/generer.py"
python3 "$ICI/graines.py" --sortie "$constr/graines"

echo "== Compilation ($moteur, sources : $source_miniz)"
make --no-print-directory -s -C "$BEE" SOURCE="$source_miniz" CONSTR="$constr" CLANG="$CLANG" "$cible"

echo "== Fuzzing : ${harnais[*]}, $duree s chacun, en parallèle"
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
    echo "-- $h : aucun écart. $(grep -E 'stat::number_of_executed_units|pilote : terminé' "$sorties/$h.log" | tail -1)"
    continue
  fi
  graine="$(grep -oE 'Seed: [0-9]+' "$sorties/$h.log" | head -1 | cut -d' ' -f2 || true)"
  echo "-- $h : le harnais a échoué${graine:+ (graine libFuzzer $graine)}."
  if [ "$discret" != "1" ]; then
    echo "   Fin du journal $sorties/$h.log :" >&2
    tail -40 "$sorties/$h.log" >&2
  fi
  mapfile -t fautives < <(find "$sorties/$h" -maxdepth 1 -type f \( -name 'crash-*' -o -name 'leak-*' -o -name 'timeout-*' -o -name 'oom-*' \) | sort)
  if [ "${#fautives[@]}" -eq 0 ]; then
    # Échec sans entrée fautive (compilation, erreur interne du moteur) : on ne peut pas le classer.
    nouveau=1
    signaler error "$h : échec sans entrée fautive (voir le journal en local) ; compté comme écart nouveau."
    continue
  fi
  if [ -n "$reference" ] && [ ! -x "$constr/reference/$prefixe-$h" ]; then
    echo "== Compilation du harnais $h sur la référence ($reference)"
    make --no-print-directory -s -C "$BEE" SOURCE="$reference" CONSTR="$constr/reference" CLANG="$CLANG" "$constr/reference/$prefixe-$h" >/dev/null
  fi
  for f in "${fautives[@]}"; do
    empreinte="$(sha256sum "$f" | cut -c1-16)"
    taille="$(stat -c %s "$f")"
    if [ -n "$reference" ] && rejouer_sur_reference "$h" "$f"; then
      signaler warning "$h : écart PRÉEXISTANT (l'entrée échoue aussi sur la référence), entrée sha256:$empreinte… ($taille octets). Il ne compte pas contre la PR ; à signaler en privé au conseil (docs/securite.md du registre)."
    else
      nouveau=1
      precision=""
      [ -n "$reference" ] && precision=" (l'entrée passe sur la référence)"
      signaler error "$h : écart NOUVEAU$precision, entrée sha256:$empreinte… ($taille octets). Reproduisez-le dans votre sandbox ; ne publiez ni l'entrée ni la trace (docs/securite.md du registre)."
    fi
  done
  if [ "$discret" = "1" ]; then
    echo "   Mode discret : ni journal, ni trace, ni entrée publiés. Entrées gardées dans $sorties/$h/ sur la machine qui a fuzzé."
  else
    echo "   Entrées fautives : ${fautives[*]}" >&2
  fi
done
exit "$nouveau"
