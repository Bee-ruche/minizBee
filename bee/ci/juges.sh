#!/usr/bin/env bash
# Prépare les juges d'un job de la CI Bee : le dossier bee/ de la base de la PR, et le côté d'où le juge
# commun lit le greffon (bee/juge/projet.py).
#
# Usage : juges.sh <dossier_base> <dossier_pr> <base_sha>     (variable ETATS : dossier des états)
#
# Cas normal : la base contient bee/, rien ne change ; les juges sont ceux de la base, le greffon aussi
#   (<ETATS>/greffon.txt : « base »).
# Introduction du greffon : si la base a encore l'ancien juge isolé (bee/juge/juge.py) et pas de greffon,
#   et que la PR apporte bee/juge/projet.py, les juges restent ceux de la base (l'ancien juge isolé juge la
#   PR) et le juge commun prend le greffon de la PR (<ETATS>/greffon.txt : « pr »), comme à l'amorçage.
#   Ce cas ne se présente que pour une PR vers master tant que miniz-0032 n'y est pas fusionnée (bee-ci ne
#   juge que les PR vers master) ; ensuite master a toujours un greffon et la règle ne peut plus s'appliquer.
# Amorçage : si et seulement si <base_sha> vaut exactement BEE_COMMIT_AMORCAGE (master d'origine du
#   fork, avant tout outillage Bee), bee/ de la PR est copié dans la base. Les juges viennent alors
#   de la PR elle-même, le greffon aussi.
# À l'introduction et à l'amorçage, le journal le signale et <ETATS>/amorcage.txt le note pour verdict.json.
# Tout autre cas sans bee/ dans la base : échec (code 1). Une base sans juges n'est pas acceptée.
# Dans tous les cas, <ETATS>/juges.txt reçoit « succes » ou « echec » (étape « juges » du verdict).
# Une PR qui apporte un bee/juge/juge.py (l'ancien juge) n'a plus d'effet : la base le décide.
#
# Le workflow .github/workflows/bee-ci.yml contient une copie identique de la logique ci-dessous
# (variable BEE_JUGES, exécutée par l'étape « Juges » de chaque job), car à l'amorçage la base ne
# contient pas encore ce script. bee/ci/test_verdict.py vérifie que les deux copies sont identiques.
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "usage : $0 <dossier_base> <dossier_pr> <base_sha>" >&2
  exit 2
fi
base="$1"
pr="$2"
base_sha="$3"
etats="${ETATS:-etats}"
BEE_COMMIT_AMORCAGE="${BEE_COMMIT_AMORCAGE:-2948eebafc5b9f1c69bebed80333e403a09bd62d}"

# --- début de la logique recopiée dans bee-ci.yml ---
mkdir -p "$etats"
if [ -f "$base/bee/ci/etape.sh" ] && [ -f "$base/bee/juge/juge.py" ] && [ ! -e "$base/bee/juge/projet.py" ] && [ -f "$pr/bee/juge/projet.py" ]; then
  echo "::warning::INTRODUCTION DU GREFFON : la base $base_sha a l'ancien juge isolé et pas encore de greffon ; les juges restent ceux de la base (l'ancien juge isolé juge aussi la PR), le juge commun prend le greffon de la PR qui l'apporte (verdict.json : amorcage: true ; tâche d'outillage, relue par un gardien)."
  echo "pr" > "$etats/greffon.txt"
  echo "oui" > "$etats/amorcage.txt"
  echo "succes" > "$etats/juges.txt"
elif [ -f "$base/bee/ci/etape.sh" ]; then
  echo "Juges : bee/ de la base de la PR ($base_sha), greffon du juge commun compris."
  echo "base" > "$etats/greffon.txt"
  echo "succes" > "$etats/juges.txt"
elif [ "$base_sha" = "$BEE_COMMIT_AMORCAGE" ] && [ -f "$pr/bee/ci/etape.sh" ]; then
  echo "::warning::AMORÇAGE : la base $base_sha (commit d'amorçage épinglé) ne contient pas bee/ ; les juges viennent de la PR elle-même (verdict.json : amorcage: true)."
  rm -rf "$base/bee"
  cp -a "$pr/bee" "$base/bee"
  mkdir -p "$base/.github/workflows"
  cp -a "$pr/.github/workflows/bee-ci.yml" "$base/.github/workflows/bee-ci.yml"
  echo "pr" > "$etats/greffon.txt"
  echo "oui" > "$etats/amorcage.txt"
  echo "succes" > "$etats/juges.txt"
else
  echo "echec" > "$etats/juges.txt"
  echo "::error::La base de la PR ($base_sha) ne contient pas bee/ : pas de juges, CI refusée (seul le commit d'amorçage $BEE_COMMIT_AMORCAGE est accepté sans juges)." >&2
  exit 1
fi
# --- fin de la logique recopiée dans bee-ci.yml ---
