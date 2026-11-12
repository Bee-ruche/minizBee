#!/usr/bin/env bash
# Prepares the judges of a Bee CI job: the bee/ folder of the PR's base, and the side the common judge reads the plugin
# from (bee/judge/project.py, or bee/juge/projet.py up to miniz-0050).
#
# Usage: juges.sh <base_folder> <pr_folder> <base_sha>     (variable ETATS: the states folder)
#
# Normal case: the base contains bee/, nothing changes; the judges are the base's, the plugin too
#   (<ETATS>/greffon.txt: « base »). A PR that brings its own plugin or an old isolated judge (bee/juge/juge.py) changes
#   nothing: the base decides (the introduction of the plugin, miniz-0032, judged under juge-v2, is gone).
# Bootstrap: if and only if <base_sha> is exactly BEE_COMMIT_AMORCAGE (the fork's original master, before any Bee
#   tooling), the PR's bee/ is copied into the base. The judges then come from the PR itself, the plugin too
#   (<ETATS>/greffon.txt: « pr »); the log says so and <ETATS>/amorcage.txt records it for verdict.json (bootstrap: true).
# Any other case without bee/ in the base: failure (code 1). A base without judges is not accepted.
# In every case, <ETATS>/juges.txt receives « succes » or « echec » (the verdict's step « juges »). These values and file
# names stay as they are: the workflow's copy comes from the PR, and the base's bee/ci/verdict.py reads them.
#
# The workflow .github/workflows/bee-ci.yml holds an identical copy of the logic below (variable BEE_JUGES, run by the
# « Judges » step of each job), because at bootstrap the base does not contain this script yet. The two copies must stay
# identical: bee/ci/test_verdict.py checks it.
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "usage: $0 <base_folder> <pr_folder> <base_sha>" >&2
  exit 2
fi
base="$1"
pr="$2"
base_sha="$3"
etats="${ETATS:-etats}"
BEE_COMMIT_AMORCAGE="${BEE_COMMIT_AMORCAGE:-2948eebafc5b9f1c69bebed80333e403a09bd62d}"

# --- start of the logic copied into bee-ci.yml ---
mkdir -p "$etats"
if [ -f "$base/bee/ci/etape.sh" ]; then
  echo "Judges: bee/ of the PR's base ($base_sha), the common judge's plugin included."
  echo "base" > "$etats/greffon.txt"
  echo "succes" > "$etats/juges.txt"
elif [ "$base_sha" = "$BEE_COMMIT_AMORCAGE" ] && [ -f "$pr/bee/ci/etape.sh" ]; then
  echo "::warning::BOOTSTRAP: the base $base_sha (pinned bootstrap commit) does not contain bee/; the judges come from the PR itself (verdict.json: bootstrap: true)."
  rm -rf "$base/bee"
  cp -a "$pr/bee" "$base/bee"
  mkdir -p "$base/.github/workflows"
  cp -a "$pr/.github/workflows/bee-ci.yml" "$base/.github/workflows/bee-ci.yml"
  echo "pr" > "$etats/greffon.txt"
  echo "oui" > "$etats/amorcage.txt"
  echo "succes" > "$etats/juges.txt"
else
  echo "echec" > "$etats/juges.txt"
  echo "::error::The PR's base ($base_sha) does not contain bee/: no judges, CI refused (only the bootstrap commit $BEE_COMMIT_AMORCAGE is accepted without judges)." >&2
  exit 1
fi
# --- end of the logic copied into bee-ci.yml ---
