#!/usr/bin/env bash
# Étape « tests différentiels et empreintes » de la CI Bee.
#
# Les juges sont ceux de la base (le dossier bee/ qui contient ce script) : la PR ne peut pas assouplir
# les tests qui la jugent. Seules les sources de miniz viennent de la PR (--source).
# Si la PR modifie elle-même bee/ (tâches de type test ou mesure), son propre outillage doit aussi
# passer sur ses propres sources.
#
# Usage : bee/ci/differentiel.sh <clone_pr>
# Variables : SORTIE_COMPRESSEE (identique par défaut ; peut_changer saute le contrôle des empreintes,
#             seulement si la tâche du registre l'autorise), BASE_SHA et TETE_SHA (facultatifs).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
pr="$(cd "$1" && pwd)"

options=()
case "${SORTIE_COMPRESSEE:-identique}" in
  identique) ;;
  peut_changer) options+=(--sans-empreintes); echo "La tâche autorise une sortie compressée différente : empreintes non contrôlées." ;;
  *) echo "SORTIE_COMPRESSEE invalide : ${SORTIE_COMPRESSEE}" >&2; exit 2 ;;
esac

echo "== Outillage de la base, sources de la PR"
"$BEE/tests/lancer.sh" --source "$pr" ${options[@]+"${options[@]}"}

if [ -n "${BASE_SHA:-}" ] && [ -n "$(git -C "$pr" diff --name-only "${BASE_SHA}...${TETE_SHA:-HEAD}" -- bee/)" ]; then
  echo "== La PR modifie bee/ : son propre outillage, sur ses propres sources"
  BEE_CONSTR="$pr/bee/construction/tests-pr" "$pr/bee/tests/lancer.sh" ${options[@]+"${options[@]}"}
fi
