# miniz-0034 : résultats

Machine : x86-64, 2 cœurs partagés, gcc 13.3, Valgrind de la distribution ; tout dans `bee/sandbox/sans-docker.sh`.
Base : master à a2f939a.

- `plages-avant.txt`, `plages-apres.txt`, `plages.diff` : fonctions repérées dans les trois sources, par
  `plages.py` avec le profil.py de la base puis celui de la tâche. 13 plages ajoutées, aucune retirée ni
  déplacée : `mz_deflateInit`, `mz_deflateInit2`, `mz_deflateReset`, `mz_deflateEnd`, `mz_deflateBound`,
  `mz_compressBound`, `mz_inflateInit2`, `mz_inflateInit`, `mz_inflateReset`, `mz_inflateEnd` (miniz.c) et
  `TDEFL_READ_UNALIGNED_WORD`, `…WORD2`, `…WORD32` (miniz_tdef.c, compilées seulement avec
  `MINIZ_UNALIGNED_USE_MEMCPY`, donc sans coût dans le banc). Bornes vérifiées à la main dans le source.
  Aucun appel de macro ni mot-clé n'apparaît.
- `profil-avant.*`, `profil-apres.*`, `comparaison.txt` : `profil.py` des deux versions sur les mêmes
  fichiers callgrind (`--reutiliser`). Totaux identiques ; « miniz.c (hors fonction) » passe de 4 514
  instructions à 0 dans chaque scénario de compression (vers `mz_deflateInit2` 3 782, `mz_deflateInit` 427,
  `mz_deflateEnd` 305), et de 1 403 à 0 en décompression (`mz_inflateInit2` 1 098, `mz_inflateEnd` 305).
- `regressions-semees.txt` : les nouveaux tests échouent sur le profil.py de la base et sur deux
  régressions semées (refus du mot-clé retiré ; type rendu facultatif), passent sur le candidat.
