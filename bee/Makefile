# Construction de l'outillage Bee pour miniz.
#
#   make -C bee differentiel     tests différentiels (assertions de miniz actives)
#   make -C bee banc             banc de mesure (options de compilation « Release » de miniz)
#   make -C bee fuzz-libfuzzer   harnais libFuzzer (clang complet requis)
#   make -C bee fuzz-gcc         mêmes harnais, pilote aléatoire + ASan/UBSan de gcc (repli local)
#
# Variables utiles :
#   SOURCE  dossier qui contient les sources de miniz à juger (défaut : la racine du dépôt).
#           ab.py et la CI s'en servent pour compiler l'outillage d'une révision contre la
#           bibliothèque d'une autre.
#   CONSTR  dossier de construction (défaut : bee/construction).
#   CC      compilateur C (défaut : cc, c'est-à-dire gcc sur Debian/Ubuntu).
#
# Seuls miniz.c, miniz_tdef.c et miniz_tinfl.c sont compilés : le périmètre v0 du fork exclut
# les archives ZIP (miniz_zip.c). zlib est liée statiquement (libz.a de zlib1g-dev) pour que la
# référence soit exactement celle dont on a les en-têtes, quelle que soit la libz.so chargée.

ICI     := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SOURCE  ?= $(abspath $(ICI)/..)
CONSTR  ?= $(ICI)/construction
CC      ?= cc
CLANG   ?= clang

MINIZ_C := $(SOURCE)/miniz.c $(SOURCE)/miniz_tdef.c $(SOURCE)/miniz_tinfl.c
MINIZ_H := $(wildcard $(SOURCE)/*.h)
COMMUN  := $(ICI)/commun/sha256.c $(ICI)/commun/corpus.c
COMMUN_H := $(wildcard $(ICI)/commun/*.h)

# -I$(SOURCE) d'abord : miniz.h trouve ses propres en-têtes ; commun/ fournit miniz_export.h.
INCLUDES := -I$(SOURCE) -I$(ICI)/commun
AVERTISSEMENTS := -Wall -Wextra -Wno-unused-parameter
ZLIB_STATIQUE := -Wl,-Bstatic -lz -Wl,-Bdynamic

# Banc : mêmes options que la construction CMake « Release » de miniz (-O3 -DNDEBUG, gnu90).
OPT_BANC  ?= -O3 -DNDEBUG
# Tests : -O2 avec assertions (MZ_ASSERT) actives, pour attraper une incohérence interne.
OPT_TESTS ?= -O2 -g

# Cachegrind : si l'en-tête de Valgrind est présent, le banc encadre la partie mesurée
# (option --instructions de ab.py) ; sinon le décompte inclut aussi la lecture du corpus.
CACHEGRIND := $(shell printf '\043include <valgrind/cachegrind.h>\nint main(void){return 0;}\n' | $(CC) -x c - -o /dev/null 2>/dev/null && echo -DBEE_AVEC_CACHEGRIND)

.PHONY: differentiel banc fuzz-libfuzzer fuzz-gcc tout nettoyer

tout: differentiel banc

differentiel: $(CONSTR)/differentiel
banc: $(CONSTR)/banc

$(CONSTR)/differentiel: $(ICI)/tests/differentiel.c $(COMMUN) $(COMMUN_H) $(MINIZ_C) $(MINIZ_H)
	@mkdir -p $(CONSTR)
	$(CC) $(OPT_TESTS) -std=gnu99 -D_GNU_SOURCE $(AVERTISSEMENTS) $(INCLUDES) \
	  $(ICI)/tests/differentiel.c $(COMMUN) $(MINIZ_C) $(ZLIB_STATIQUE) -o $@

$(CONSTR)/banc: $(ICI)/bench/banc.c $(COMMUN) $(COMMUN_H) $(MINIZ_C) $(MINIZ_H)
	@mkdir -p $(CONSTR)
	$(CC) $(OPT_BANC) -std=gnu90 -D_GNU_SOURCE -c $(INCLUDES) $(MINIZ_C)
	@mv miniz.o miniz_tdef.o miniz_tinfl.o $(CONSTR)/ 2>/dev/null || true
	$(CC) $(OPT_BANC) -std=gnu99 -D_GNU_SOURCE $(AVERTISSEMENTS) $(CACHEGRIND) $(INCLUDES) \
	  $(ICI)/bench/banc.c $(COMMUN) $(CONSTR)/miniz.o $(CONSTR)/miniz_tdef.o $(CONSTR)/miniz_tinfl.o -o $@

# ------------------------------------------------------------------ fuzzing
HARNAIS := fuzz_inflate fuzz_compression
FUZZ_DRAPEAUX := -g -O1 -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all

fuzz-libfuzzer: $(addprefix $(CONSTR)/libfuzzer-,$(HARNAIS))
fuzz-gcc: $(addprefix $(CONSTR)/gcc-,$(HARNAIS))

$(CONSTR)/libfuzzer-%: $(ICI)/fuzz/%.c $(MINIZ_C) $(MINIZ_H)
	@mkdir -p $(CONSTR)
	$(CLANG) $(FUZZ_DRAPEAUX) -fsanitize=fuzzer -std=gnu99 -D_GNU_SOURCE $(INCLUDES) \
	  $< $(MINIZ_C) $(ZLIB_STATIQUE) -o $@

$(CONSTR)/gcc-%: $(ICI)/fuzz/%.c $(ICI)/fuzz/pilote_aleatoire.c $(MINIZ_C) $(MINIZ_H)
	@mkdir -p $(CONSTR)
	$(CC) $(FUZZ_DRAPEAUX) -std=gnu99 -D_GNU_SOURCE $(INCLUDES) \
	  $< $(ICI)/fuzz/pilote_aleatoire.c $(MINIZ_C) $(ZLIB_STATIQUE) -o $@

nettoyer:
	rm -rf $(CONSTR)
