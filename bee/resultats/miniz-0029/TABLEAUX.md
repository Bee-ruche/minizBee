# miniz-0029 : tableaux

Sources de miniz au commit a2f939a (master du 30/10/2026). Produits par `tableaux.py` à partir de `donnees/*.json` ; chaque section nomme le script qui a produit ses données (commandes : RAPPORT.md). Cachegrind simule I1 32768,8,64, D1 49152,12,64, LL 2097152,16,64 (taille, associativité, ligne). « CEst » : estimation de cycles de KCachegrind, Ir + 10 × branches mal prédites + 10 × défauts L1 + 100 × défauts LL, un modèle et non une mesure.

## 1. Coût par fonction, tout le corpus (cachegrind.py)

Passes chronométrées du banc seulement, 131072 premiers octets de chaque fichier (2 221 670 octets). « memcpy en ligne » : memcpy de taille fixe incorporé dans la fonction (_FORTIFY_SOURCE), que profil.py compte dans « hors miniz ».

**n1** : 170 765 561 instructions, 897 695 défauts L1, 1 212 430 branches mal prédites (5,0 %), CEst / Ir = 1,155

| fonction | Ir % | CEst % | défauts L1 | par 1000 Ir | défauts LL | mal prédites | taux % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tdefl_compress_normal | 51,0 | 50,5 | 435 202 | 5,00 | 36 816 | 446 385 | 4,5 |
| tdefl_find_match (l. 862) | 18,4 | 19,4 | 266 004 | 8,47 | 8 | 413 768 | 8,7 |
| tdefl_compress_lz_codes (l. 482) | 10,7 | 10,6 | 15 916 | 0,87 | 29 | 250 556 | 13,8 |
| mz_adler32 | 4,4 | 4,0 | 34 384 | 4,58 | 6 | 581 | 0,2 |
| tdefl_record_match | 3,9 | 3,6 | 11 892 | 1,78 | 356 | 25 070 | 12,7 |
| hors miniz | 3,6 | 3,9 | 97 545 | 15,83 | 5 716 | 364 | 0,0 |
| tdefl_record_literal | 2,7 | 2,6 | 5 846 | 1,29 | 1 355 | 41 198 | 12,7 |
| tdefl_flush_block | 2,0 | 1,8 | 4 304 | 1,24 | 47 | 381 | 0,1 |
| tdefl_compress_normal (memcpy en ligne) | 1,5 | 1,3 | 4 791 | 1,93 | 1 | 0 | 0,0 |
| tdefl_optimize_huffman_table | 0,7 | 0,7 | 935 | 0,79 | 47 | 14 940 | 7,3 |

**n6** : 334 757 696 instructions, 8 061 202 défauts L1, 2 276 784 branches mal prédites (3,5 %), CEst / Ir = 1,324

| fonction | Ir % | CEst % | défauts L1 | par 1000 Ir | défauts LL | mal prédites | taux % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tdefl_find_match (l. 862) | 58,5 | 62,8 | 6 786 426 | 34,65 | 8 | 1 454 741 | 3,3 |
| tdefl_compress_normal | 27,4 | 25,0 | 978 821 | 10,66 | 36 833 | 552 217 | 5,2 |
| tdefl_compress_lz_codes (l. 482) | 4,3 | 3,7 | 12 313 | 0,86 | 29 | 182 190 | 12,3 |
| mz_adler32 | 2,2 | 1,8 | 34 517 | 4,60 | 6 | 580 | 0,2 |
| hors miniz | 1,8 | 1,7 | 97 313 | 15,89 | 5 444 | 354 | 0,0 |
| tdefl_record_literal | 1,3 | 1,2 | 25 749 | 5,73 | 1 393 | 37 762 | 12,8 |
| tdefl_record_match | 1,3 | 1,2 | 69 301 | 15,75 | 450 | 17 006 | 12,8 |
| tdefl_compress_normal (memcpy en ligne) | 1,2 | 0,9 | 32 828 | 8,52 | 1 | 0 | 0,0 |
| tdefl_flush_block | 1,0 | 0,8 | 4 285 | 1,23 | 47 | 356 | 0,1 |

**n9** : 482 752 478 instructions, 16 126 442 défauts L1, 2 481 460 branches mal prédites (2,5 %), CEst / Ir = 1,396

| fonction | Ir % | CEst % | défauts L1 | par 1000 Ir | défauts LL | mal prédites | taux % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tdefl_find_match (l. 862) | 71,2 | 75,1 | 14 573 126 | 42,41 | 8 | 1 664 052 | 2,1 |
| tdefl_compress_normal | 18,9 | 16,6 | 1 131 450 | 12,37 | 36 844 | 548 914 | 5,2 |
| tdefl_compress_lz_codes (l. 482) | 3,0 | 2,4 | 12 238 | 0,86 | 28 | 181 083 | 12,3 |
| mz_adler32 | 1,6 | 1,2 | 34 518 | 4,60 | 6 | 580 | 0,2 |
| hors miniz | 1,3 | 1,1 | 97 304 | 15,89 | 5 439 | 355 | 0,0 |
| tdefl_compress_normal (memcpy en ligne) | 1,0 | 0,8 | 78 402 | 17,03 | 1 | 0 | 0,0 |
| tdefl_record_literal | 0,9 | 0,8 | 46 095 | 10,26 | 1 399 | 37 802 | 12,8 |
| tdefl_record_match | 0,9 | 0,9 | 129 469 | 29,80 | 420 | 16 768 | 12,8 |
| tdefl_flush_block | 0,7 | 0,5 | 4 284 | 1,23 | 47 | 358 | 0,1 |

**decompression** : 29 954 575 instructions, 78 700 défauts L1, 314 368 branches mal prédites (8,5 %), CEst / Ir = 1,170

| fonction | Ir % | CEst % | défauts L1 | par 1000 Ir | défauts LL | mal prédites | taux % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tinfl_decompress | 95,4 | 93,1 | 17 476 | 0,61 | 7 219 | 313 278 | 8,8 |
| tinfl_decompress (memcpy en ligne) | 4,0 | 5,1 | 56 189 | 47,09 | 126 | 443 | 1,1 |
| hors miniz | 0,5 | 1,8 | 4 862 | 30,08 | 4 280 | 472 | 0,4 |

## 2. Zones de code, tout le corpus (cachegrind.py ; plages de lignes : commun.py)

| zone (compression) | Ir % n1 | Ir % n6 | Ir % n9 | défauts L1 n6 | défauts L1 n9 | mal prédites n6 | taux n6 % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| find_match : sondes (m_next, distance, 2 octets de fin) | 5,1 | 46,7 | 60,5 | 6 786 411 | 14 573 112 | 1 069 497 | 3,0 |
| compress_normal : insertion dans les chaînes (cas courant) | 19,0 | 9,8 | 6,8 | 965 003 | 1 098 590 | 242 913 | 7,9 |
| find_match : budget de sondes (--num_probes_left) | 1,3 | 3,0 | 3,5 | 0 | 0 | 49 585 | 1,1 |
| compress_normal : entrée, préparation de l'insertion | 8,9 | 4,9 | 3,4 | 25 | 5 657 | 800 | 0,0 |
| compress_normal : fenêtre et préparation de la recherche | 8,2 | 4,5 | 3,1 | 68 | 68 | 6 902 | 0,6 |
| find_match : comparaison par mots de 64 bits | 2,6 | 3,2 | 3,1 | 4 | 3 | 185 524 | 9,3 |
| find_match : entrée (état, c01) | 7,3 | 4,0 | 2,8 | 10 | 10 | 133 | 0,0 |
| compress_normal : décision de vidage, sortie | 4,9 | 2,7 | 1,9 | 70 | 7 758 | 714 | 0,0 |
| compress_normal : avancement de la fenêtre | 4,0 | 2,0 | 1,4 | 2 | 2 | 0 | 0,0 |
| compress_normal : analyse paresseuse | 2,7 | 1,8 | 1,2 | 427 | 5 142 | 213 968 | 16,9 |
| lz_codes : correspondances (longueur, distance, bits supplémentaires) | 5,0 | 1,8 | 1,2 | 5 629 | 5 552 | 83 666 | 20,4 |
| compress_normal : rejet (longueur 3 à 8 Kio et plus) | 2,8 | 1,5 | 1,1 | 2 | 2 | 85 245 | 4,9 |
| find_match : nouvelle meilleure correspondance | 1,8 | 1,3 | 1,0 | 1 | 1 | 149 950 | 16,6 |
| lz_codes : littéraux (1 à 3 par tour) | 2,4 | 1,1 | 0,8 | 2 317 | 2 348 | 62 636 | 26,3 |
| lz_codes : écriture du tampon de bits, fin de bloc | 2,0 | 0,8 | 0,6 | 65 | 63 | 339 | 0,1 |
| lz_codes : entrée, boucle, drapeaux | 1,3 | 0,5 | 0,4 | 4 302 | 4 275 | 35 549 | 6,4 |
| find_match : distance nulle | 0,3 | 0,4 | 0,4 | 0 | 0 | 52 | 0,0 |
| compress_normal : insertion (bords de fenêtre, début) | 0,5 | 0,2 | 0,2 | 13 223 | 14 230 | 1 675 | 1,9 |
| tdefl_compress_normal : (reste) | 0,0 | 0,0 | 0,0 | 1 | 1 | 0 | 0,0 |

| zone (décompression) | Ir % banc (flux miniz n6) | Ir % juge (flux zlib n6) | défauts L1 | mal prédites | taux % |
| --- | --- | --- | --- | --- | --- |
| tinfl : longueur et distance (macros) | 21,7 | 20,1 | 104 | 33 758 | 4,0 |
| tinfl : littéraux, chemin rapide | 19,4 | 18,8 | 8 904 | 175 166 | 16,2 |
| tinfl : Adler-32 de la sortie | 18,6 | 17,6 | 77 | 615 | 0,4 |
| tinfl : copie sans chevauchement (4 ou 8 octets) | 9,7 | 9,2 | 2 | 86 584 | 19,2 |
| tinfl : contrôle de distance, source | 6,2 | 5,7 | 2 | 26 | 0,0 |
| tinfl : copie octet par octet (chevauchement, longueur 3) | 5,7 | 5,2 | 7 942 | 2 057 | 1,5 |
| tinfl : littéraux, test du chemin rapide (l. 427) | 5,5 | 5,4 | 1 | 176 | 0,0 |
| tinfl : construction des tables de Huffman | 5,3 | 8,1 | 167 | 14 267 | 5,7 |
| tinfl : copie, test de fin de tampon (l. 543) | 3,1 | 2,9 | 0 | 224 | 0,2 |
| tinfl : entrée et en-tête zlib | 0,0 | 0,0 | 149 | 41 | 6,1 |
| tinfl : littéraux, chemin lent (fin de tampon) | 0,0 | 0,0 | 23 | 100 | 22,7 |
| tinfl : fin de flux, Adler-32 lu | 0,0 | 0,0 | 52 | 172 | 15,4 |
| tinfl : en-tête de bloc, blocs stockés | 0,0 | 0,0 | 28 | 90 | 11,7 |
| tinfl : sortie commune (état sauvé) | 0,0 | 0,0 | 25 | 2 | 3,3 |

## 3. Parts dans le décompte d'instructions du juge (juge_parts.py)

Tout le processus de bee/juge/execution.c, 128 premiers Kio de chaque fichier, non perturbés ; décompression des flux zlib niveau 6 (zlib 1.3). C'est le dénominateur de R4 (instructions_n1, _n6, _n9, _decompression).

| fonction | n1 | n6 | n9 | decompression |
| --- | --- | --- | --- | --- |
| tdefl_compress_normal | 50,74 | 27,37 | 18,92 | — |
| tdefl_find_match (l. 862) | 18,31 | 58,37 | 71,06 | — |
| tdefl_compress_lz_codes (l. 482) | 10,68 | 4,27 | 2,95 | — |
| mz_adler32 | 4,38 | 2,24 | 1,55 | — |
| hors miniz | 4,06 | 2,07 | 1,43 | 3,10 |
| tdefl_record_match | 3,90 | 1,31 | 0,90 | — |
| tdefl_record_literal | 2,65 | 1,34 | 0,93 | — |
| tdefl_flush_block | 2,03 | 1,04 | 0,72 | — |
| tdefl_compress_normal (memcpy en ligne) | 1,44 | 1,15 | 0,95 | — |
| tinfl_decompress | — | — | — | 93,03 |
| tinfl_decompress (memcpy en ligne) | — | — | — | 3,83 |
| **total (instructions)** | 171 579 677 | 335 572 066 | 483 566 690 | 31 745 071 |

Dont memset (n1) : 6 014 295 instructions, 3,51 % : les remises à zéro de tdefl_init (m_hash 64 Kio, m_dict 33 Kio, 61 flux), que Valgrind compte à peu près une instruction par octet (rep stosb).

## 4. Par famille du corpus (cachegrind.py, chrono_familles.py)

Chronomètre : médiane de 3 exécutions du banc, chacune meilleure de 15 passes, mêmes entrées que Cachegrind ; machine partagée (Xeon 2,1 GHz virtualisé, 2 cœurs, gcc 13.3).

**n1**

| famille | octets | Ir/octet | défauts L1 / 1000 Ir | mal prédites / 1000 Ir | find_match % | Mo/s | ns/octet | ns/instruction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tout | 2 221 670 | 76,9 | 5,26 | 7,10 | 18,4 | 111,3 | 8,98 | 0,117 |
| texte | 287 107 | 82,8 | 3,19 | 7,84 | 19,0 | 104,0 | 9,61 | 0,116 |
| code | 614 269 | 62,1 | 3,64 | 9,17 | 17,3 | 125,7 | 7,96 | 0,128 |
| structure | 393 216 | 62,2 | 2,50 | 7,92 | 18,2 | 147,2 | 6,79 | 0,109 |
| binaire | 393 216 | 174,1 | 7,08 | 6,76 | 21,9 | 47,1 | 21,24 | 0,122 |
| repetitif | 524 288 | 19,2 | 7,27 | 0,93 | 7,2 | 564,2 | 1,77 | 0,092 |
| petits | 9 574 | 600,6 | 10,93 | 3,15 | 3,1 | 33,0 | 30,27 | 0,050 |

**n6**

| famille | octets | Ir/octet | défauts L1 / 1000 Ir | mal prédites / 1000 Ir | find_match % | Mo/s | ns/octet | ns/instruction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tout | 2 221 670 | 150,7 | 24,08 | 6,80 | 58,5 | 32,0 | 31,25 | 0,207 |
| texte | 287 107 | 210,5 | 30,00 | 6,07 | 70,0 | 20,5 | 48,70 | 0,231 |
| code | 614 269 | 131,1 | 16,60 | 6,89 | 61,2 | 38,9 | 25,74 | 0,196 |
| structure | 393 216 | 160,3 | 31,63 | 8,28 | 68,4 | 25,7 | 38,88 | 0,243 |
| binaire | 393 216 | 292,4 | 24,27 | 7,07 | 52,4 | 16,9 | 59,27 | 0,203 |
| repetitif | 524 288 | 18,7 | 7,47 | 0,84 | 6,7 | 383,7 | 2,61 | 0,139 |
| petits | 9 574 | 614,0 | 10,70 | 3,47 | 4,6 | 20,7 | 48,32 | 0,079 |

**n9**

| famille | octets | Ir/octet | défauts L1 / 1000 Ir | mal prédites / 1000 Ir | find_match % | Mo/s | ns/octet | ns/instruction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tout | 2 221 670 | 217,3 | 33,41 | 5,14 | 71,2 | 19,7 | 50,84 | 0,234 |
| texte | 287 107 | 305,9 | 40,15 | 4,50 | 79,5 | 12,3 | 81,15 | 0,265 |
| code | 614 269 | 212,4 | 25,48 | 4,48 | 76,1 | 20,9 | 47,89 | 0,225 |
| structure | 393 216 | 270,6 | 58,19 | 6,19 | 80,9 | 13,0 | 76,70 | 0,283 |
| binaire | 393 216 | 361,5 | 20,90 | 5,77 | 61,5 | 13,7 | 73,19 | 0,202 |
| repetitif | 524 288 | 18,7 | 7,47 | 0,84 | 6,7 | 581,3 | 1,72 | 0,092 |
| petits | 9 574 | 625,0 | 10,50 | 3,51 | 6,1 | 28,6 | 34,92 | 0,056 |

**decompression**

| famille | octets | Ir/octet | défauts L1 / 1000 Ir | mal prédites / 1000 Ir | tinfl_decompress % | Mo/s | ns/octet | ns/instruction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tout | 2 221 670 | 13,5 | 2,63 | 10,49 | 95,4 | 501,2 | 2,00 | 0,148 |
| texte | 287 107 | 17,6 | 2,10 | 10,75 | 95,5 | 417,8 | 2,39 | 0,136 |
| code | 614 269 | 14,1 | 2,22 | 13,37 | 95,0 | 419,2 | 2,39 | 0,170 |
| structure | 393 216 | 13,7 | 2,74 | 13,61 | 94,8 | 481,0 | 2,08 | 0,152 |
| binaire | 393 216 | 17,9 | 2,54 | 9,07 | 96,6 | 416,9 | 2,40 | 0,134 |
| repetitif | 524 288 | 5,9 | 5,60 | 1,20 | 95,5 | 2 404,2 | 0,42 | 0,070 |
| petits | 9 574 | 70,9 | 0,77 | 8,98 | 93,3 | 141,9 | 7,05 | 0,099 |

Ajustement (moindres carrés, n1/n6/n9 × 5 familles hors « petits ») : ns/octet ≈ 0,138 × instructions/octet + 2,84 × défauts L1/octet, R² 0,989 ; avec les instructions seules : 0,223 ns par instruction, R² 0,913. Part du temps attribuée aux défauts L1 par ce modèle :
n1 9,8 %, n6 33,2 %, n9 40,8 %. Un modèle à deux termes sur 15 points d'une machine virtualisée : un ordre de grandeur, à valider par des compteurs matériels.

## 5. Chaînes de sondes de tdefl_find_match (stats_lz.py)

« sondes » : lectures de m_next (exécutions de TDEFL_PROBE). Sorties : part des appels qui s'arrêtent sur le budget (--num_probes_left), une fin de chaîne (m_next nul), une position hors fenêtre (distance > max_dist) ou une correspondance de longueur maximale. « vaines » : comparaisons complètes qui n'améliorent pas la correspondance.

**fichiers entiers (12 Mo)**

| niveau | famille | appels/octet | sondes/appel | médiane | p90 | p99 | budget % | fin de chaîne % | hors fenêtre % | longueur max % | candidats/sonde | comparaisons/appel | vaines % | rang médian du résultat |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n1 | tout | 0,260 | 1,54 | 1 | 3 | 3 | 62,7 | 5,2 | 31,9 | 0,2 | 0,340 | 0,52 | 15,7 | 1 |
| n1 | texte | 0,205 | 1,08 | 1 | 1 | 3 | 94,5 | 1,0 | 4,5 | 0,0 | 0,847 | 0,92 | 7,3 | 1 |
| n1 | code | 0,154 | 1,10 | 1 | 1 | 3 | 80,9 | 13,5 | 5,6 | 0,0 | 0,704 | 0,77 | 9,6 | 1 |
| n1 | structure | 0,156 | 1,04 | 1 | 1 | 3 | 96,3 | 0,7 | 3,0 | 0,0 | 0,913 | 0,95 | 3,1 | 1 |
| n1 | binaire | 0,778 | 1,96 | 2 | 3 | 3 | 35,4 | 7,3 | 57,3 | 0,0 | 0,087 | 0,17 | 62,8 | 1 |
| n1 | repetitif | 0,006 | 1,01 | 1 | 1 | 1 | 21,5 | 11,9 | 0,0 | 66,6 | 0,873 | 0,88 | 0,0 | 1 |
| n1 | petits | 0,509 | 0,99 | 1 | 1 | 1 | 8,9 | 89,8 | 0,0 | 0,3 | 0,092 | 0,09 | 2,9 | 1 |
| n6 | tout | 0,269 | 24,36 | 5 | 95 | 129 | 9,0 | 8,8 | 82,0 | 0,2 | 0,050 | 1,22 | 59,5 | 3 |
| n6 | texte | 0,204 | 40,89 | 23 | 123 | 129 | 12,3 | 4,3 | 83,4 | 0,0 | 0,039 | 1,58 | 41,5 | 4 |
| n6 | code | 0,173 | 33,32 | 12 | 125 | 129 | 14,4 | 34,2 | 51,4 | 0,0 | 0,036 | 1,20 | 43,5 | 1 |
| n6 | structure | 0,178 | 39,34 | 23 | 121 | 129 | 17,8 | 3,8 | 78,3 | 0,0 | 0,065 | 2,55 | 63,8 | 3 |
| n6 | binaire | 0,788 | 10,38 | 3 | 21 | 126 | 3,6 | 8,9 | 87,5 | 0,0 | 0,055 | 0,58 | 79,9 | 5 |
| n6 | repetitif | 0,005 | 1,02 | 1 | 1 | 2 | 0,0 | 15,2 | 0,0 | 84,8 | 0,841 | 0,86 | 0,0 | 1 |
| n6 | petits | 0,544 | 1,87 | 1 | 2 | 15 | 0,8 | 97,8 | 0,0 | 0,2 | 0,105 | 0,20 | 20,4 | 1 |
| n9 | tout | 0,268 | 45,14 | 5 | 109 | 760 | 2,3 | 9,1 | 88,4 | 0,2 | 0,039 | 1,77 | 71,9 | 4 |
| n9 | texte | 0,202 | 66,44 | 23 | 139 | 759 | 1,8 | 4,5 | 93,7 | 0,0 | 0,029 | 1,96 | 51,8 | 5 |
| n9 | code | 0,171 | 75,34 | 12 | 187 | 768 | 5,0 | 35,6 | 59,4 | 0,1 | 0,021 | 1,61 | 57,0 | 1 |
| n9 | structure | 0,177 | 90,76 | 23 | 284 | 766 | 5,7 | 4,4 | 90,0 | 0,0 | 0,053 | 4,80 | 80,6 | 3 |
| n9 | binaire | 0,787 | 15,30 | 3 | 21 | 154 | 0,9 | 8,9 | 90,1 | 0,0 | 0,041 | 0,62 | 81,0 | 5 |
| n9 | repetitif | 0,005 | 1,02 | 1 | 1 | 2 | 0,0 | 15,2 | 0,0 | 84,8 | 0,841 | 0,86 | 0,0 | 1 |
| n9 | petits | 0,542 | 2,68 | 1 | 2 | 16 | 0,2 | 98,4 | 0,0 | 0,3 | 0,129 | 0,35 | 36,3 | 1 |

**128 premiers Kio par fichier (comme Cachegrind)**

| niveau | famille | appels/octet | sondes/appel | médiane | p90 | p99 | budget % | fin de chaîne % | hors fenêtre % | longueur max % | candidats/sonde | comparaisons/appel | vaines % | rang médian du résultat |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n1 | tout | 0,235 | 1,41 | 1 | 3 | 3 | 56,6 | 27,7 | 15,3 | 0,4 | 0,356 | 0,50 | 20,3 | 1 |
| n1 | texte | 0,236 | 1,05 | 1 | 1 | 3 | 88,0 | 10,5 | 1,5 | 0,0 | 0,829 | 0,87 | 7,0 | 1 |
| n1 | code | 0,169 | 1,06 | 1 | 1 | 3 | 73,9 | 23,2 | 2,9 | 0,0 | 0,678 | 0,72 | 8,6 | 1 |
| n1 | structure | 0,161 | 1,02 | 1 | 1 | 2 | 92,8 | 5,6 | 1,6 | 0,0 | 0,901 | 0,92 | 2,4 | 1 |
| n1 | binaire | 0,707 | 1,73 | 1 | 3 | 3 | 35,5 | 37,6 | 26,9 | 0,0 | 0,139 | 0,24 | 61,9 | 1 |
| n1 | repetitif | 0,008 | 1,01 | 1 | 1 | 1 | 23,8 | 26,7 | 0,0 | 49,5 | 0,727 | 0,73 | 0,0 | 1 |
| n1 | petits | 0,509 | 0,99 | 1 | 1 | 1 | 8,9 | 89,8 | 0,0 | 0,3 | 0,092 | 0,09 | 2,9 | 1 |
| n6 | tout | 0,252 | 21,84 | 4 | 84 | 129 | 8,4 | 46,5 | 44,7 | 0,4 | 0,053 | 1,16 | 60,8 | 3 |
| n6 | texte | 0,262 | 36,97 | 17 | 122 | 129 | 11,7 | 41,2 | 47,1 | 0,0 | 0,039 | 1,45 | 41,0 | 4 |
| n6 | code | 0,193 | 26,61 | 7 | 111 | 129 | 11,5 | 60,2 | 28,3 | 0,0 | 0,039 | 1,05 | 40,3 | 1 |
| n6 | structure | 0,190 | 35,81 | 20 | 116 | 129 | 15,9 | 29,5 | 54,6 | 0,0 | 0,070 | 2,49 | 64,3 | 2 |
| n6 | binaire | 0,719 | 12,73 | 2 | 35 | 127 | 4,6 | 45,8 | 49,6 | 0,0 | 0,063 | 0,81 | 79,3 | 5 |
| n6 | repetitif | 0,006 | 1,03 | 1 | 1 | 2 | 0,0 | 34,9 | 0,0 | 65,0 | 0,649 | 0,67 | 0,0 | 1 |
| n6 | petits | 0,544 | 1,87 | 1 | 2 | 15 | 0,8 | 97,8 | 0,0 | 0,2 | 0,105 | 0,20 | 20,4 | 1 |
| n9 | tout | 0,251 | 40,73 | 4 | 98 | 762 | 2,3 | 47,8 | 49,5 | 0,4 | 0,039 | 1,58 | 70,9 | 3 |
| n9 | texte | 0,259 | 64,06 | 16 | 142 | 760 | 1,9 | 43,1 | 55,0 | 0,0 | 0,029 | 1,83 | 52,3 | 4 |
| n9 | code | 0,192 | 57,49 | 7 | 134 | 767 | 3,7 | 62,7 | 33,5 | 0,0 | 0,024 | 1,40 | 54,8 | 1 |
| n9 | structure | 0,188 | 75,26 | 20 | 205 | 711 | 4,2 | 32,2 | 63,6 | 0,0 | 0,060 | 4,48 | 80,1 | 3 |
| n9 | binaire | 0,718 | 19,70 | 2 | 37 | 192 | 1,3 | 46,1 | 52,6 | 0,0 | 0,044 | 0,87 | 80,4 | 5 |
| n9 | repetitif | 0,006 | 1,03 | 1 | 1 | 2 | 0,0 | 34,9 | 0,0 | 65,0 | 0,649 | 0,67 | 0,0 | 1 |
| n9 | petits | 0,542 | 2,68 | 1 | 2 | 16 | 0,2 | 98,4 | 0,0 | 0,3 | 0,129 | 0,35 | 36,3 | 1 |

## 6. Correspondances émises (stats_lz.py, fichiers entiers)

Symboles enregistrés par tdefl_record_match (avant le choix d'un bloc brut). Tranches de longueur et de distance en % des correspondances.

| niveau | famille | correspondances | littéraux | longueur moy. | distance moy. | octets couverts % | L 3 | L 4 | L 5-8 | L 9-16 | L 17-32 | L 33-64 | L 65-128 | L 129-257 | L 258 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n1 | tout | 1 295 894 | 1 827 393 | 7,87 | 2 275 | 84,8 | 46,4 | 15,4 | 21,2 | 7,9 | 6,6 | 1,8 | 0,2 | 0,1 | 0,5 |
| n1 | texte | 610 786 | 132 423 | 5,73 | 2 550 | 96,4 | 46,7 | 19,7 | 24,4 | 5,0 | 2,4 | 1,4 | 0,3 | 0,1 | 0,0 |
| n1 | code | 133 091 | 67 532 | 9,26 | 1 854 | 94,8 | 26,8 | 16,0 | 26,8 | 18,4 | 8,5 | 2,7 | 0,7 | 0,2 | 0,0 |
| n1 | structure | 450 170 | 82 723 | 7,39 | 2 094 | 97,6 | 46,1 | 11,4 | 19,0 | 9,9 | 11,6 | 2,1 | 0,0 | 0,0 | 0,0 |
| n1 | binaire | 93 379 | 1 539 186 | 5,98 | 2 129 | 26,6 | 75,1 | 7,1 | 4,6 | 3,6 | 7,3 | 2,3 | 0,0 | 0,0 | 0,0 |
| n1 | repetitif | 8 033 | 1 089 | 195,66 | 275 | 99,9 | 24,4 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 75,5 |
| n1 | petits | 435 | 4 440 | 11,80 | 121 | 53,6 | 48,0 | 19,8 | 12,2 | 6,4 | 7,6 | 2,1 | 2,5 | 0,5 | 0,9 |
| n6 | tout | 752 334 | 1 741 777 | 13,66 | 8 473 | 85,5 | 19,6 | 8,6 | 32,9 | 18,1 | 12,7 | 6,5 | 0,6 | 0,2 | 0,8 |
| n6 | texte | 304 237 | 134 682 | 11,50 | 10 291 | 96,3 | 5,3 | 9,7 | 49,0 | 22,1 | 7,2 | 5,6 | 0,8 | 0,3 | 0,0 |
| n6 | code | 82 732 | 59 498 | 15,00 | 4 981 | 95,4 | 10,7 | 11,8 | 26,4 | 23,6 | 18,2 | 6,9 | 1,8 | 0,4 | 0,1 |
| n6 | structure | 229 565 | 148 765 | 14,20 | 9 960 | 95,6 | 7,1 | 8,3 | 31,1 | 20,4 | 23,3 | 9,5 | 0,3 | 0,0 | 0,0 |
| n6 | binaire | 129 320 | 1 393 298 | 5,44 | 4 195 | 33,6 | 81,8 | 4,9 | 4,0 | 1,9 | 4,1 | 3,3 | 0,0 | 0,0 | 0,0 |
| n6 | repetitif | 6 097 | 1 088 | 257,79 | 348 | 99,9 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 99,9 |
| n6 | petits | 383 | 4 446 | 13,39 | 132 | 53,6 | 38,6 | 22,7 | 17,0 | 5,7 | 8,9 | 2,3 | 2,9 | 0,8 | 1,0 |
| n9 | tout | 740 763 | 1 746 846 | 13,87 | 8 815 | 85,5 | 19,8 | 8,6 | 31,8 | 18,6 | 12,8 | 6,7 | 0,6 | 0,2 | 0,8 |
| n9 | texte | 301 482 | 131 870 | 11,62 | 10 760 | 96,4 | 5,4 | 9,5 | 47,7 | 23,4 | 7,3 | 5,7 | 0,8 | 0,3 | 0,0 |
| n9 | code | 81 545 | 59 512 | 15,22 | 5 218 | 95,4 | 10,8 | 11,6 | 26,2 | 23,4 | 18,5 | 7,1 | 1,8 | 0,5 | 0,1 |
| n9 | structure | 222 436 | 156 869 | 14,62 | 10 399 | 95,4 | 7,3 | 8,5 | 29,4 | 20,7 | 23,6 | 10,1 | 0,4 | 0,0 | 0,0 |
| n9 | binaire | 128 826 | 1 393 061 | 5,47 | 4 231 | 33,6 | 82,0 | 5,0 | 4,0 | 1,7 | 3,9 | 3,4 | 0,0 | 0,0 | 0,0 |
| n9 | repetitif | 6 097 | 1 088 | 257,79 | 348 | 99,9 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | 99,9 |
| n9 | petits | 377 | 4 446 | 13,60 | 132 | 53,6 | 39,3 | 22,8 | 17,0 | 5,0 | 9,0 | 2,1 | 2,7 | 1,1 | 1,1 |

| niveau | famille | D 1 | D 2-4 | D 5-8 | D 9-64 | D 65-512 | D 513-4096 | D 4097-8192 | D 8193-32768 | chevauchantes (D < L) % | D = 1 % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n1 | tout | 0,6 | 1,6 | 0,8 | 11,9 | 30,5 | 38,8 | 9,6 | 6,1 | 1,5 | 0,6 |
| n1 | texte | 0,0 | 1,1 | 0,9 | 11,8 | 29,8 | 39,1 | 9,7 | 7,7 | 0,3 | 0,0 |
| n1 | code | 4,4 | 0,3 | 1,2 | 19,8 | 34,8 | 26,9 | 7,2 | 5,6 | 4,5 | 4,4 |
| n1 | structure | 0,0 | 0,6 | 0,6 | 11,4 | 32,4 | 40,2 | 9,9 | 5,0 | 0,0 | 0,0 |
| n1 | binaire | 0,0 | 10,1 | 1,1 | 5,0 | 20,3 | 48,7 | 12,0 | 2,9 | 8,5 | 0,0 |
| n1 | repetitif | 25,3 | 24,9 | 0,0 | 0,0 | 24,5 | 25,3 | 0,0 | 0,0 | 50,4 | 25,3 |
| n1 | petits | 6,0 | 3,2 | 3,2 | 37,0 | 48,3 | 2,3 | 0,0 | 0,0 | 8,7 | 6,0 |
| n6 | tout | 0,4 | 0,4 | 0,1 | 3,4 | 10,0 | 31,3 | 18,0 | 36,4 | 0,8 | 0,4 |
| n6 | texte | 0,0 | 0,1 | 0,1 | 1,9 | 6,9 | 26,8 | 17,4 | 46,9 | 0,1 | 0,0 |
| n6 | code | 0,9 | 0,2 | 0,4 | 10,7 | 26,5 | 29,2 | 11,2 | 20,9 | 1,1 | 0,9 |
| n6 | structure | 0,0 | 0,0 | 0,0 | 3,7 | 7,7 | 26,1 | 17,7 | 44,7 | 0,0 | 0,0 |
| n6 | binaire | 0,0 | 1,3 | 0,3 | 2,0 | 10,2 | 52,6 | 25,3 | 8,5 | 0,5 | 0,0 |
| n6 | repetitif | 33,3 | 16,7 | 0,0 | 0,0 | 16,7 | 33,3 | 0,0 | 0,0 | 66,7 | 33,3 |
| n6 | petits | 4,4 | 1,8 | 2,1 | 37,1 | 52,5 | 2,1 | 0,0 | 0,0 | 7,3 | 4,4 |
| n9 | tout | 0,3 | 0,3 | 0,1 | 3,3 | 9,6 | 30,5 | 17,8 | 38,1 | 0,7 | 0,3 |
| n9 | texte | 0,0 | 0,0 | 0,1 | 1,8 | 6,4 | 25,3 | 17,1 | 49,3 | 0,0 | 0,0 |
| n9 | code | 0,4 | 0,2 | 0,4 | 10,4 | 26,0 | 29,4 | 11,3 | 22,0 | 0,5 | 0,4 |
| n9 | structure | 0,0 | 0,0 | 0,0 | 3,7 | 7,3 | 24,8 | 17,3 | 47,0 | 0,0 | 0,0 |
| n9 | binaire | 0,0 | 0,9 | 0,3 | 2,0 | 10,0 | 53,1 | 25,3 | 8,5 | 0,1 | 0,0 |
| n9 | repetitif | 33,3 | 16,7 | 0,0 | 0,0 | 16,7 | 33,3 | 0,0 | 0,0 | 66,7 | 33,3 |
| n9 | petits | 2,9 | 1,9 | 2,1 | 37,7 | 53,6 | 1,9 | 0,0 | 0,0 | 5,8 | 2,9 |

## 7. Correspondances de longueur 3 à 8 Kio et plus, rejetées (miniz_tdef.c l. 1285 à a2f939a ; stats_lz.py)

Résultat de tdefl_find_match vu par tdefl_compress_normal, avant le rejet. « sondes » : part des sondes du niveau dépensées dans les appels dont le résultat est ainsi rejeté.

| corpus | niveau | famille | appels avec résultat % | longueur 3 parmi les résultats % | ≥ 8 Kio parmi les longueurs 3 % | ≥ 8 Kio parmi les résultats % | sondes de ces appels % | sondes des appels sans résultat % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| entiers | n1 | tout | 44,1 | 49,5 | 11,8 | 5,8 | 1,8 | 70,3 |
| entiers | n1 | texte | 85,2 | 48,6 | 7,3 | 3,6 | 3,0 | 19,3 |
| entiers | n1 | code | 69,9 | 30,5 | 16,6 | 5,1 | 3,4 | 35,5 |
| entiers | n1 | structure | 92,0 | 50,5 | 16,1 | 8,1 | 7,4 | 10,6 |
| entiers | n1 | binaire | 6,4 | 77,7 | 13,3 | 10,3 | 0,5 | 96,0 |
| entiers | n1 | repetitif | 88,1 | 24,4 | 0,0 | 0,0 | 0,0 | 12,0 |
| entiers | n1 | petits | 8,9 | 48,0 | 0,0 | 0,0 | 0,0 | 91,0 |
| entiers | n6 | tout | 31,2 | 26,0 | 27,8 | 7,2 | 2,2 | 45,0 |
| entiers | n6 | texte | 52,1 | 11,0 | 27,3 | 3,0 | 0,3 | 43,7 |
| entiers | n6 | code | 43,8 | 17,2 | 29,8 | 5,1 | 0,8 | 48,6 |
| entiers | n6 | structure | 58,4 | 17,7 | 39,8 | 7,1 | 1,1 | 49,0 |
| entiers | n6 | binaire | 10,0 | 85,1 | 22,4 | 19,1 | 7,5 | 40,2 |
| entiers | n6 | repetitif | 84,8 | 0,0 | 0,0 | 0,0 | 0,0 | 15,0 |
| entiers | n6 | petits | 8,0 | 38,5 | 0,0 | 0,0 | 0,0 | 68,8 |
| entiers | n9 | tout | 31,3 | 26,0 | 28,1 | 7,3 | 1,6 | 49,4 |
| entiers | n9 | texte | 52,0 | 10,9 | 28,0 | 3,0 | 0,2 | 41,9 |
| entiers | n9 | code | 43,8 | 17,3 | 29,8 | 5,2 | 0,7 | 53,4 |
| entiers | n9 | structure | 59,2 | 17,6 | 39,6 | 7,0 | 0,9 | 53,9 |
| entiers | n9 | binaire | 10,0 | 85,2 | 22,8 | 19,4 | 6,2 | 51,6 |
| entiers | n9 | repetitif | 84,8 | 0,0 | 0,0 | 0,0 | 0,0 | 15,0 |
| entiers | n9 | petits | 7,9 | 39,1 | 0,0 | 0,0 | 0,0 | 60,3 |
| 128 Kio | n1 | tout | 40,0 | 47,0 | 11,0 | 5,2 | 1,6 | 70,5 |
| 128 Kio | n1 | texte | 80,7 | 49,3 | 4,7 | 2,3 | 1,9 | 21,6 |
| 128 Kio | n1 | code | 65,8 | 31,5 | 14,7 | 4,6 | 3,0 | 37,3 |
| 128 Kio | n1 | structure | 89,9 | 50,9 | 14,3 | 7,3 | 6,5 | 11,3 |
| 128 Kio | n1 | binaire | 9,1 | 77,1 | 11,6 | 8,9 | 0,7 | 93,6 |
| 128 Kio | n1 | repetitif | 73,3 | 32,4 | 0,0 | 0,0 | 0,0 | 26,9 |
| 128 Kio | n1 | petits | 8,9 | 48,0 | 0,0 | 0,0 | 0,0 | 91,0 |
| 128 Kio | n6 | tout | 30,6 | 32,8 | 22,9 | 7,5 | 2,7 | 43,5 |
| 128 Kio | n6 | texte | 49,1 | 12,3 | 15,5 | 1,9 | 0,2 | 43,8 |
| 128 Kio | n6 | code | 41,3 | 19,0 | 24,3 | 4,6 | 0,6 | 48,2 |
| 128 Kio | n6 | structure | 57,2 | 18,8 | 34,9 | 6,5 | 0,7 | 49,1 |
| 128 Kio | n6 | binaire | 14,2 | 85,1 | 20,9 | 17,8 | 8,0 | 34,9 |
| 128 Kio | n6 | repetitif | 65,0 | 0,0 | 0,0 | 0,0 | 0,0 | 34,5 |
| 128 Kio | n6 | petits | 8,0 | 38,5 | 0,0 | 0,0 | 0,0 | 68,8 |
| 128 Kio | n9 | tout | 30,6 | 33,0 | 23,2 | 7,6 | 1,8 | 49,9 |
| 128 Kio | n9 | texte | 49,0 | 12,2 | 15,9 | 1,9 | 0,1 | 41,8 |
| 128 Kio | n9 | code | 41,3 | 19,2 | 24,4 | 4,7 | 0,5 | 53,0 |
| 128 Kio | n9 | structure | 57,8 | 18,8 | 34,8 | 6,5 | 0,5 | 53,7 |
| 128 Kio | n9 | binaire | 14,2 | 85,2 | 21,2 | 18,0 | 6,2 | 49,2 |
| 128 Kio | n9 | repetitif | 65,0 | 0,0 | 0,0 | 0,0 | 0,0 | 34,5 |
| 128 Kio | n9 | petits | 7,9 | 39,1 | 0,0 | 0,0 | 0,0 | 60,3 |

## 8. Décodage par tinfl_decompress (stats_lz.py)

« zlib6 » : flux de zlib 1.3 niveau 6, ceux du scénario de décompression du juge ; « miniz6 » : flux de mz_compress2 niveau 6, ceux du banc. Chemins de copie en % des correspondances : « 4 à 8 » et « 9 et plus » sans chevauchement (l. 587-613), « octet par octet » : longueur 3 ou chevauchement (l. 615-630).

| corpus | flux | famille | blocs stockés/fixes/dynamiques | octets littéraux % | longueur moy. | littéraux par l'arbre % | copie 4 à 8 % | copie 9 et plus % | octet par octet, longueur 3 % | octet par octet, chevauchée % | chevauchées D = 1 % | chevauchées D 2 à 7 % | octets copiés octet par octet % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| entiers | zlib6 | tout | 69/21/115 | 6,2 | 13,76 | 0,90 | 43,3 | 39,6 | 16,3 | 0,8 | 46,1 | 35,9 | 12,0 |
| entiers | zlib6 | texte | 0/0/29 | 3,8 | 11,50 | 2,50 | 59,4 | 36,1 | 4,4 | 0,1 | 11,9 | 72,4 | 1,3 |
| entiers | zlib6 | code | 0/0/16 | 4,7 | 14,98 | 1,55 | 38,2 | 51,7 | 9,0 | 1,1 | 85,0 | 9,9 | 3,0 |
| entiers | zlib6 | structure | 0/0/24 | 4,1 | 13,71 | 1,25 | 41,1 | 53,9 | 4,9 | 0,0 | 7,7 | 38,5 | 1,0 |
| entiers | zlib6 | binaire | 64/1/31 | 18,9 | 5,81 | 0,12 | 10,2 | 10,3 | 78,6 | 0,8 | 0,0 | 100,0 | 13,2 |
| entiers | zlib6 | repetitif | 0/0/4 | 0,1 | 257,79 | 1,47 | 0,0 | 33,3 | 0,0 | 66,7 | 50,0 | 25,0 | 66,7 |
| entiers | zlib6 | petits | 5/19/11 | 26,8 | 13,23 | 0,00 | 37,3 | 19,0 | 38,3 | 5,4 | 47,6 | 19,0 | 23,9 |
| entiers | miniz6 | tout | 52/1/83 | 5,8 | 13,67 | 0,99 | 41,4 | 38,3 | 19,5 | 0,8 | 47,9 | 32,8 | 12,7 |
| entiers | miniz6 | texte | 0/0/20 | 3,7 | 11,50 | 2,58 | 58,6 | 35,9 | 5,3 | 0,1 | 12,5 | 69,0 | 1,5 |
| entiers | miniz6 | code | 0/0/13 | 4,6 | 15,00 | 1,52 | 37,7 | 50,6 | 10,7 | 1,0 | 83,3 | 10,7 | 3,5 |
| entiers | miniz6 | structure | 0/0/16 | 4,4 | 14,20 | 1,14 | 39,4 | 53,5 | 7,1 | 0,0 | 8,3 | 41,7 | 1,4 |
| entiers | miniz6 | binaire | 34/0/13 | 16,5 | 5,45 | 0,21 | 8,8 | 8,9 | 81,8 | 0,5 | 0,0 | 100,0 | 15,5 |
| entiers | miniz6 | repetitif | 0/0/4 | 0,1 | 257,79 | 1,56 | 0,0 | 33,3 | 0,0 | 66,7 | 50,0 | 25,0 | 66,7 |
| entiers | miniz6 | petits | 18/0/17 | 24,6 | 13,42 | 0,00 | 37,4 | 16,8 | 38,5 | 7,3 | 60,7 | 14,3 | 30,8 |
| 128 Kio | zlib6 | tout | 13/21/44 | 7,9 | 14,71 | 0,73 | 37,9 | 36,5 | 23,7 | 1,8 | 40,8 | 36,9 | 22,6 |
| 128 Kio | zlib6 | texte | 0/0/5 | 5,6 | 9,15 | 2,33 | 64,0 | 28,8 | 7,2 | 0,1 | 12,5 | 79,2 | 2,3 |
| 128 Kio | zlib6 | code | 0/0/12 | 6,0 | 13,90 | 1,15 | 38,8 | 48,6 | 11,3 | 1,3 | 82,4 | 15,2 | 4,1 |
| 128 Kio | zlib6 | structure | 0/0/4 | 4,8 | 13,12 | 1,82 | 40,2 | 53,5 | 6,3 | 0,0 | 0,0 | 50,0 | 1,4 |
| 128 Kio | zlib6 | binaire | 8/1/8 | 25,4 | 5,81 | 0,13 | 9,5 | 10,4 | 79,2 | 0,9 | 0,0 | 100,0 | 17,7 |
| 128 Kio | zlib6 | repetitif | 0/0/4 | 0,2 | 257,35 | 0,00 | 0,0 | 24,8 | 0,0 | 75,1 | 33,3 | 33,4 | 75,0 |
| 128 Kio | zlib6 | petits | 5/19/11 | 26,8 | 13,23 | 0,00 | 37,3 | 19,0 | 38,3 | 5,4 | 47,6 | 19,0 | 23,9 |
| 128 Kio | miniz6 | tout | 23/1/43 | 7,3 | 14,47 | 0,79 | 36,1 | 34,8 | 27,4 | 1,7 | 41,0 | 35,4 | 23,4 |
| 128 Kio | miniz6 | texte | 0/0/4 | 5,5 | 9,13 | 2,25 | 63,2 | 28,7 | 8,0 | 0,1 | 12,5 | 79,2 | 2,6 |
| 128 Kio | miniz6 | code | 0/0/11 | 5,8 | 13,90 | 1,18 | 38,2 | 47,6 | 13,0 | 1,2 | 80,1 | 16,7 | 4,5 |
| 128 Kio | miniz6 | structure | 0/0/3 | 5,0 | 13,62 | 1,75 | 38,5 | 52,9 | 8,6 | 0,0 | 0,0 | 50,0 | 1,8 |
| 128 Kio | miniz6 | binaire | 5/0/4 | 22,4 | 5,46 | 0,18 | 8,2 | 9,0 | 82,2 | 0,6 | 0,0 | 100,0 | 20,6 |
| 128 Kio | miniz6 | repetitif | 0/0/4 | 0,2 | 257,35 | 0,00 | 0,0 | 24,8 | 0,0 | 75,1 | 33,3 | 33,4 | 75,0 |
| 128 Kio | miniz6 | petits | 18/0/17 | 24,6 | 13,42 | 0,00 | 37,4 | 16,8 | 38,5 | 7,3 | 60,7 | 14,3 | 30,8 |

