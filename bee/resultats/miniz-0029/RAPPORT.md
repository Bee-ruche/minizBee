# miniz-0029 : profilage approfondi de tdefl_find_match et de tinfl_decompress

Tâche de découpage (mesure seulement, aucune modification de miniz). Sources de miniz au commit
**a2f939a** (master du 30/10/2026 : miniz-0011 à 0016, 0024, 0026, 0033 et le juge commun intégrés).
Machine : Xeon 2,1 GHz virtualisé, 2 cœurs, Ubuntu 24.04, gcc 13.3, Valgrind 3.22, sans perf. Agent :
Claude Opus 5.5 (claude-opus-5-5). Tous les tableaux détaillés sont dans [TABLEAUX.md](TABLEAUX.md),
recalculés à partir de `donnees/*.json`.

## Reproduire

Depuis la racine du fork, au commit a2f939a (les scripts vérifient la SHA-256 des trois sources de
miniz et refusent d'autres sources : leurs plages de lignes ne vaudraient plus). Le code de miniz ne
tourne que dans la sandbox ; chaque script compile ce qu'il mesure dans la même session (environ
1 minute en tout).

```bash
bee/sandbox/sans-docker.sh python3 bee/corpus/generer.py
R=bee/resultats/miniz-0029; D=$R/donnees
bee/sandbox/sans-docker.sh python3 $R/cachegrind.py --json $D/cachegrind.json          # sections 1, 2, 4
bee/sandbox/sans-docker.sh python3 $R/juge_parts.py --json $D/juge_parts.json          # section 3 (plafonds)
bee/sandbox/sans-docker.sh python3 $R/stats_lz.py --json $D/stats_lz.json              # sections 5 à 8
bee/sandbox/sans-docker.sh python3 $R/stats_lz.py --prefixe 131072 --json $D/stats_lz_128k.json
bee/sandbox/sans-docker.sh python3 $R/chrono_familles.py --cachegrind $D/cachegrind.json --json $D/chrono_familles.json
python3 $R/tableaux.py > $R/TABLEAUX.md                                                # aucun code de miniz
```

- `cachegrind.py` : le banc sous `valgrind --tool=cachegrind --cache-sim=yes --branch-sim=yes
  --instr-at-start=no`, caches explicites (L1i 32 Kio, L1d 48 Kio, LL 2 Mio : le L2 par cœur de la
  machine ; Cachegrind ne simule que deux niveaux), passes chronométrées seulement, 128 premiers Kio de
  chaque fichier, tout le corpus puis chaque famille ; chaque ligne est rendue à sa fonction source
  (repérage de `bee/bench/profil.py`, fonctions incorporées comprises) et à une zone (`commun.py`).
- `juge_parts.py` : le décompte d'instructions **du juge** (dénominateur de R4) : tout le processus de
  `bee/juge/execution.c`, compilé comme `bee/juge/construire.sh`, 128 premiers Kio par fichier
  (non perturbés), décompression des flux de zlib 1.3 niveau 6.
- `stats_lz.py` : copies **instrumentées** de `miniz_tdef.c` et `miniz_tinfl.c`, écrites dans
  `bee/construction/` (jamais versionnées) : compteurs insérés à des endroits repérés par leur texte
  exact. Les 183 sorties compressées instrumentées (niveaux 1, 6, 9) sont identiques aux empreintes de
  référence, et chaque décompression redonne l'original.
- `chrono_familles.py` : chronomètre du banc sur les mêmes entrées (médiane de 3 exécutions, meilleure
  de 15 passes).

Reproductibilité, vérifiée par une seconde exécution complète : instructions, branches et toutes les
statistiques LZ identiques à l'unité ; défauts de cache simulés à 0,8 % près pour tout compte de plus de
100 000 (adresses des tampons), 0,01 % pour la boucle des sondes ; le chronomètre varie de quelques %
sur cette machine partagée.

## Ce qu'il faut retenir

1. **La boucle des sondes est le poste n° 1.** Dans le décompte du juge, `tdefl_find_match` pèse 58,4 %
   au niveau 6 et 71,1 % au niveau 9 ; sa boucle de sondes (l. 878-893) 49,5 % et 63,9 %. Chaque sonde
   coûte 13 instructions (désassemblage gcc -O3 : masque calculé deux fois, extension `movzwl`, test du
   zéro séparé du test de distance), 13,6 mesurées avec le budget. 21,8 sondes par appel au niveau 6
   (médiane 4, p99 129 = budget), 40,7 au niveau 9 (médiane 4, p99 762, budget 768) ; fichiers entiers :
   24,4 et 45,1. Seuls 5,3 % (n6) et 3,9 % (n9) des sondes passent le test des 2 octets de fin, et 61 %
   (n6) à 71 % (n9) des comparaisons complètes n'améliorent rien.
2. **Aux niveaux 6 et 9, le temps n'est pas que des instructions.** La boucle des sondes fait 84 % (n6)
   et 90 % (n9) des défauts L1 simulés : 0,55 et 0,64 par sonde (m_next, m_dict et m_hash, environ 160 Kio,
   ne tiennent pas dans 48 Kio). Le coût d'une instruction double entre n1 et n9 (0,117 → 0,234 ns). Un
   modèle ajusté sur 15 points (n1, n6, n9 × 5 familles) donne 0,138 ns par instruction + 2,84 ns par
   défaut L1 simulé (R² 0,989, contre 0,913 sans les défauts) et attribue aux défauts L1 environ 10 %,
   33 % et 41 % du temps des niveaux 1, 6 et 9 : un ordre de grandeur, pas une mesure.
3. **Longueur 3 à 8 Kio et plus : réel, mais sous le seuil.** Au niveau 6 (fichiers entiers), 26 % des
   résultats de `tdefl_find_match` ont la longueur 3, et 27,8 % de ceux-ci sont à 8 Kio ou plus, donc
   rejetés (l. 1285 à a2f939a ; l. 1181 dans le contexte de la tâche, à 2948eeb) : 7,2 % des résultats,
   jusqu'à 39,8 % des longueurs 3 de la famille structure. Les appels ainsi perdus ne dépensent que 2,2 %
   des sondes (n6) et 1,6 % (n9), soit environ 1 % des instructions : **aucune tâche proposée** sur ce
   point. Ce qui coûte, ce sont les appels sans résultat (45 % des sondes au niveau 6).
4. **Correspondances émises** (niveau 6, fichiers entiers) : longueur moyenne 13,7, distance moyenne
   8 473 ; longueur 3 : 19,6 %, 5 à 8 : 32,9 % ; 36,4 % au-delà de 8 Kio, 0,8 % chevauchantes. Niveau 1 :
   longueur moyenne 7,9, longueur 3 : 46,4 %. Détail par famille : TABLEAUX.md sections 6 et 7.
5. **tinfl_decompress, dans le décompte du juge (flux zlib)** : longueur et distance 20,1 %, littéraux
   (chemin rapide) 18,8 % + test du chemin rapide 5,4 %, **Adler-32 17,6 %** (2,5 instructions par octet
   après miniz-0016), copie par mots 9,2 %, **tables de Huffman 8,1 %** (5,3 % sur les flux de miniz du
   banc : zlib fait plus de blocs, 21 fixes et 44 dynamiques contre 1 et 43), contrôles par
   correspondance 8,6 %, copie octet par octet 5,2 %. 8,8 % des branches sont mal prédites, dont la
   recharge de `bit_buf` (l. 443) une fois sur deux : de quoi expliquer que des gains d'instructions de
   tinfl restent dans le bruit au chronomètre (miniz-0017, miniz-0018).
6. **Deux biais de mesure.** (a) Les `memcpy` de taille fixe de miniz, incorporés par `_FORTIFY_SOURCE`,
   portent la ligne de `string_fortified.h` : `profil.py` les compte en « hors miniz (libc) » (3,83 % du
   juge en décompression, 1,44 % au niveau 1). (b) Valgrind compte le `rep stosb` de memset environ une
   instruction par octet : les remises à zéro de `tdefl_init` (96 Kio par flux) font 3,51 % des
   instructions du juge au niveau 1, et la famille petits tourne à 0,05 ns par instruction ; un « gain »
   sur ces memset serait un artefact.

## Tâches proposées

Format du registre, en YAML, remises au conseil hors de ce dépôt (numéros provisoires 0036 à 0044). Le
plafond est la part du coût visé dans le décompte d'instructions du juge (juge_parts.py), comparée au
seuil de R4 (2 % d'instructions) ; lignes à a2f939a.

| Tâche | Type | Lignes | Métrique | Plafond connu |
| --- | --- | --- | --- | --- |
| miniz-0036 `tdefl_find_match` : moins d'instructions par sonde | optimisation S | miniz_tdef.c 878-893 | debit_compression_n9 | 63,9 % (n9), 49,5 % (n6) |
| miniz-0037 `tdefl_compress_normal` : garder le hachage glissant | optimisation S | miniz_tdef.c 1181-1188 | debit_compression_n1 | 10,35 % (n1) ; l. 1184 seule 2,73 % |
| miniz-0038 `tdefl_find_match` : coût fixe par appel au niveau 1 | optimisation S | miniz_tdef.c 862-880 | debit_compression_n1 | 7,29 % (8,55 % avec le budget) |
| miniz-0039 tinfl : Adler-32 avec moins d'instructions par octet | optimisation S | miniz_tinfl.c 682-731 | debit_decompression | 17,6 % |
| miniz-0040 `mz_adler32` : calcul par blocs (après 0039) | optimisation S | miniz.c 40-66 | debit_compression_n1 | 4,38 % ; recopier tinfl tel quel ne donnerait que 0,97 % |
| miniz-0041 tinfl : copies chevauchantes par mots | optimisation S | miniz_tinfl.c 615-630 | debit_decompression | 5,22 % (chevauchantes seules ≈ 3,5 %) |
| miniz-0042 tinfl : moins de contrôles par correspondance (après 0017) | optimisation S | miniz_tinfl.c 535-543, 587-612 | debit_decompression | 13,2 % |
| miniz-0043 compteurs matériels contre Cachegrind | mesure S | — | — | tâche de mesure |
| miniz-0044 profileur : memcpy en ligne, caches et branches | mesure S | bee/bench/profil.py | — | tâche de mesure |

Écartées faute de plafond utile : le rejet des longueurs 3 lointaines (≈ 1 % d'instructions, section 3
ci-dessus) ; les longueurs de `tdefl_compress_lz_codes` en une seule écriture (zone des correspondances
4,97 % au niveau 1, gain réaliste vers 1 %) ; la branche `sym = (match_dist < 512) ? s0 : s1`
(l. 519, 41 % mal prédite, gain de temps seulement, sans plafond d'instructions mesurable) ; les memset
de `tdefl_init` (artefact de comptage, point 6).

## Pour le conseil

- **miniz-0022** (tables de Huffman, en attente de miniz-0027) : dans le décompte du juge, les tables
  pèsent 8,05 % des instructions de décompression, pas 5,3 % comme dans le banc, parce que le juge
  décompresse des flux de zlib ; la famille petits y passe 72,5 % de ses instructions (banc).
- **miniz-0019** : au niveau 1, les l. 1260-1263 coûtent chacune exactement 4 instructions par tour
  (1,22 % chacune) et la l. 1254 2,43 % : au désassemblage, des relectures de champs de `d`
  (m_lookahead_pos, m_saved_match_len, m_flags) et des écritures sur la pile ; c'est la piste de
  miniz-0019 (état en variables locales).
- Le tableau de profil de `bee/README.md` date de 2948eeb : TABLEAUX.md section 1 donne celui de a2f939a
  (aussi demandé par miniz-0034).

## Ce qui n'a pas été mesuré

- Pas de compteurs matériels (pas de perf) : défauts de cache et branches sont **simulés** par
  Cachegrind, avec une hiérarchie à deux niveaux choisie (L1d 48 Kio, LL 2 Mio) ; le modèle temps et
  défauts est un ajustement sur une machine virtualisée et partagée (tâche miniz-0043).
- x86-64 et gcc 13.3 seulement : ni ARM64, ni clang.
- Le décompte du juge est reproduit hors de son conteneur, sur le corpus non perturbé, avec des flux de
  la zlib 1.3 du système ; le juge de la CI prend ceux de la zlib de son hôte (version non vérifiée).
- L'attribution par ligne à -O3 est approximative (code fusionné ou déplacé par gcc), et les memcpy en
  ligne n'ont pas de ligne de miniz.
- Niveaux 0 et 10, stratégies autres que la stratégie par défaut, `mz_deflate` et `mz_inflate` en flux :
  non profilés (les statistiques de tinfl portent sur `mz_uncompress` en une fois).
- Aucun essai d'optimisation : les pistes des tâches proposées ne sont pas démontrées.
