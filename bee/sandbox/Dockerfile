# Sandbox Bee pour le fork miniz : compiler, tester, mesurer et fuzzer le code des contributions
# sans réseau ni secret. Fork indépendant, non affilié au projet miniz.
#
# Construction (une fois, avec le réseau) :
#   docker build -t bee-miniz bee/sandbox
# Utilisation (sans réseau ; seul le clone du fork est monté, en /travail) :
#   docker run --rm -it --network none -v "$PWD":/travail -w /travail bee-miniz bash
#
# Les outils correspondent à ceux de la CI (ubuntu-24.04) : gcc 13, clang 18 avec son runtime libFuzzer
# (libclang-rt-18-dev), valgrind, cmake, make, zlib1g-dev (la référence des tests différentiels),
# python3 avec PyYAML. Rien n'est téléchargé à l'exécution.
#
# Image de base : ubuntu:24.04, la version de la CI. Elle n'est PAS encore épinglée par digest :
# Docker Hub n'était pas joignable depuis l'environnement qui a écrit ce fichier, et un digest non
# vérifié serait pire que pas de digest. À faire par le premier mainteneur qui a le réseau :
#   docker buildx imagetools inspect ubuntu:24.04     (relever le « Digest: sha256:… » de l'index)
# puis écrire FROM ubuntu:24.04@sha256:<digest>, et justifier tout changement de digest en relecture.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake make git ca-certificates \
      clang-18 libclang-rt-18-dev \
      valgrind \
      zlib1g-dev \
      python3 python3-yaml \
 && ln -s /usr/bin/clang-18 /usr/local/bin/clang \
 && ln -s /usr/bin/clang++-18 /usr/local/bin/clang++ \
 && rm -rf /var/lib/apt/lists/*

# Utilisateur sans privilège. L'UID 1000 correspond au premier utilisateur de la plupart des postes
# Linux, ce qui garde les fichiers créés dans /travail lisibles hors du conteneur.
RUN userdel -r ubuntu 2>/dev/null || true \
 && useradd --create-home --uid 1000 --shell /bin/bash bee
USER bee
# Le dépôt monté appartient à l'hôte : git doit l'accepter (sinon « dubious ownership »).
RUN git config --global --add safe.directory /travail
ENV CC=gcc CLANG=clang PYTHONDONTWRITEBYTECODE=1
WORKDIR /travail
CMD ["bash"]
