# Image du juge isolé Bee pour miniz (bee/README.md, section « Juge isolé »).
#
# Construite AVANT que le moindre fichier de la PR ne soit monté : c'est la seule étape avec réseau.
# Ensuite, tout ce qui touche au code de la PR (compilation, exécution, mesures) tourne dans des
# conteneurs de cette image, sans réseau, en lecture seule, sans privilège (bee/juge/juge.py).
#
# Image de base épinglée par empreinte (index multi-architecture : x86-64 et ARM64), tirée du miroir
# de Docker Hub tenu par Google (pas de limite de débit anonyme sur les machines de CI partagées).
FROM mirror.gcr.io/library/ubuntu@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c

# gcc et binutils : compilation et analyse des objets ; valgrind : décompte d'instructions ;
# zlib1g-dev : zlib de référence des tests différentiels ; cmake, g++ : tests d'origine de miniz ;
# python3-minimal, git : générateur du corpus (bee/corpus/generer.py lit des objets git) ;
# clang-18, libclang-rt-18-dev : fuzzing libFuzzer (bee/fuzz/lancer.sh).
RUN apt-get update -q \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
      gcc g++ make cmake binutils libc6-dev zlib1g-dev valgrind python3-minimal git clang-18 libclang-rt-18-dev \
 && rm -rf /var/lib/apt/lists/*

# Utilisateur sans privilège sous lequel tourne tout le reste (juge.py passe aussi --user).
USER 65534:65534
WORKDIR /
