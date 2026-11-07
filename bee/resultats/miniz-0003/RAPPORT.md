# miniz-0003 : bruit du banc A/B (test A/A), une machine partagée

Base mesurée contre elle-même : `b16e34e` (master du fork), `ab.py --base HEAD --candidate HEAD --repetitions 10`,
dans le conteneur `bee-miniz` (image construite depuis `bee/sandbox/Dockerfile`, `--network none`), 6 passages :
3 sans `--instructions` (`aa-sans-instructions-{1,2,3}.json`), 3 avec (`aa-instructions-{1,2,3}.json`), à la suite, le
2026-11-06 entre 21:05 et 21:30 (Paris). Aucun fichier du banc ni de miniz n'est modifié.

## Configuration

Intel Xeon 2,1 GHz virtualisé, 2 cœurs, Linux 6.18 (x86_64), gcc 13.3.0, Valgrind de l'image, 10 répétitions + 1 de
chauffe. **Machine non calme** : d'autres agents du même utilisateur y lançaient en parallèle des suites de tests
Python (2 processus à 25-35 % de CPU chacun par tranche, charge de 4,8 mesurée par `uptime` à la fin pour 2 cœurs).
Ce n'est donc pas le bruit d'une machine au repos, mais celui d'une machine de développement partagée : à lire comme
un majorant.

## Plus grand écart relatif de médiane A/A (le « gain » que rapporte ab.py), en valeur absolue

| Métrique | 3 passages sans --instructions | 3 passages avec --instructions | Les 6 |
| --- | --- | --- | --- |
| debit_compression_n1 | 13,12 % (−7,12 ; −13,12 ; −1,29) | 6,34 % (−2,93 ; −4,77 ; +6,34) | **13,12 %** |
| debit_compression_n6 | 3,72 % (+1,23 ; −2,93 ; +3,72) | 3,65 % (+3,63 ; +1,58 ; −3,65) | **3,72 %** |
| debit_compression_n9 | 2,04 % (+1,20 ; +2,04 ; −0,28) | 5,13 % (+3,03 ; −5,13 ; +3,73) | **5,13 %** |
| debit_decompression | 20,76 % (−6,73 ; +17,05 ; +20,76) | 12,24 % (−1,40 ; −12,24 ; −0,21) | **20,76 %** |
| ratio_n6 | 0 % | 0 % | **0 %** |
| memoire_max_ko | 0,34 % | 4,72 % (+4,72 ; −0,23 ; 0) | **4,72 %** |

Instructions (Cachegrind, 3 passages) : A = B exactement pour les quatre scénarios, écart 0 (170 765 561 en n1,
334 757 696 en n6, 482 752 478 en n9, 26 160 282 en décompression) ; aucun « au-delà du seuil ».

## Faux « au-delà du bruit »

0 sur 6 passages × 6 métriques de chronomètre/mémoire, gain comme dégradation, et 0 sur 4 métriques d'instructions
(calculés sur les JSON). Le test du signe a tenu malgré des médianes très écartées : il demande 9 paires gagnées sur 10, et
le plus fort déséquilibre observé est 8 contre 2 (n1 : A gagne 8 paires, passage 2 ; décompression : B 8 paires,
passage 2 et 7 paires, passage 3).

## Lecture

- Le **bruit des médianes dépasse 2 %** sur toutes les métriques de débit, jusqu'à 13 % en n1 et 21 % en décompression,
  mais à ce niveau de charge et sur 10 répétitions. Le « gain » de médiane que `ab.py` affiche ne dit donc rien tout
  seul sur cette machine ; seuls le test du signe et le décompte d'instructions (déterministe : 0 écart) ont été fiables.
- Ce rapport ne dit pas que le banc est mauvais à froid : le A/A de bee/README.md (−1,4 % à +0,5 %) a été fait sur une
  machine calme. Il dit que ce bruit-là n'est pas celui d'une machine partagée.
- Réglages à essayer (non testés ici) : refuser de mesurer ou le signaler quand la charge dépasse le nombre de cœurs
  (`os.getloadavg()` dans le JSON) ; médiane des rapports de paires B_i/A_i plutôt que rapport des médianes ; plus de
  répétitions (20) ; épingler le processus (`taskset`).
