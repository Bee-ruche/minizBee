#!/usr/bin/env python3
"""Statistiques LZ de miniz sur le corpus (miniz-0029) : chaînes de sondes de tdefl_find_match,
longueurs et distances des correspondances, rejet des longueurs 3 à 8 Kio et plus, chemins de copie
de tinfl_decompress.

miniz n'est pas modifié : le script écrit des COPIES instrumentées de miniz_tdef.c et miniz_tinfl.c
dans bee/construction/miniz-0029/instr/ (compteurs de stats_lz.h insérés à des endroits repérés par
leur texte exact, chacun trouvé une seule fois), les compile avec stats_lz.c, puis lance ce harnais
sur le corpus. Les compteurs n'écrivent que dans leurs propres structures ; pour le prouver, le
script compare la SHA-256 de chaque sortie compressée (niveaux 1, 6 et 9, fichiers entiers) à
bee/tests/empreintes-reference.txt et s'arrête au moindre écart.

Usage (depuis la racine du dépôt, dans la sandbox) :
  bee/sandbox/sans-docker.sh python3 bee/resultats/miniz-0029/stats_lz.py \
      --json bee/resultats/miniz-0029/donnees/stats_lz.json                     # fichiers entiers
  bee/sandbox/sans-docker.sh python3 bee/resultats/miniz-0029/stats_lz.py --prefixe 131072 \
      --json bee/resultats/miniz-0029/donnees/stats_lz_128k.json                # comme Cachegrind
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commun  # noqa: E402

NOUVELLE_SONDE = r"""#define TDEFL_PROBE                                                                    \
    m29_d.cur_sondes++;                                                                \
    next_probe_pos = d->m_next[probe_pos];                                             \
    if (!next_probe_pos)                                                               \
    {                                                                                  \
        M29_SORTIE(M29_FIN_CHAINE);                                                    \
        return;                                                                        \
    }                                                                                  \
    if ((dist = (mz_uint16)(lookahead_pos - next_probe_pos)) > max_dist)               \
    {                                                                                  \
        M29_SORTIE(M29_TROP_LOIN);                                                     \
        return;                                                                        \
    }                                                                                  \
    probe_pos = next_probe_pos & TDEFL_LZ_DICT_SIZE_MASK;                              \
    memcpy(&w, pTail + probe_pos, sizeof(w));                                          \
    if (w == c01)                                                                      \
    {                                                                                  \
        m29_d.candidats++;                                                             \
        break;                                                                         \
    }
"""

# (première ligne, dernière ligne, [(ancien, nouveau)]) dans les sources de a2f939a. « ancien » est
# du texte exact (ou une expression rationnelle si c'est un objet re.Pattern), trouvé une seule fois
# dans la plage.
TDEF = [
    (862, 942, [  # tdefl_find_match, variante compilée (MINIZ_USE_UNALIGNED_LOADS_AND_STORES = 0)
        ("    memcpy(&c01, pTail + pos, sizeof(c01));\n    MZ_ASSERT(max_match_len <= TDEFL_MAX_MATCH_LEN);\n"
         "    if (max_match_len <= match_len)\n        return;\n",
         "    memcpy(&c01, pTail + pos, sizeof(c01));\n    M29_ENTREE(match_len);\n"
         "    MZ_ASSERT(max_match_len <= TDEFL_MAX_MATCH_LEN);\n"
         "    if (max_match_len <= match_len)\n    {\n        M29_SORTIE(M29_IMMEDIATE);\n        return;\n    }\n"),
        ("            if (--num_probes_left == 0)\n                return;\n",
         "            if (--num_probes_left == 0)\n            {\n                M29_SORTIE(M29_BUDGET);\n"
         "                return;\n            }\n"),
        (re.compile(r"#define TDEFL_PROBE .*?        break;\n", re.S), NOUVELLE_SONDE),
        ("        if (!dist)\n            break;\n",
         "        if (!dist)\n        {\n            M29_SORTIE(M29_DIST_NULLE);\n            break;\n        }\n"),
        ("        p = s;\n        q = d->m_dict + probe_pos;\n",
         "        m29_d.comparaisons++;\n        p = s;\n        q = d->m_dict + probe_pos;\n"),
        ("        if (probe_len > match_len)\n        {\n            *pMatch_dist = dist;\n"
         "            if ((*pMatch_len = match_len = probe_len) == max_match_len)\n                return;\n",
         "        m29_d.octets_compares += probe_len;\n        m29_d.comparaisons_vaines += (probe_len <= match_len);\n"
         "        if (probe_len > match_len)\n        {\n            *pMatch_dist = dist;\n"
         "            m29_d.ameliorations++;\n            m29_d.cur_prof = m29_d.cur_sondes;\n"
         "            if ((*pMatch_len = match_len = probe_len) == max_match_len)\n"
         "            {\n                M29_SORTIE(M29_LONGUEUR_MAX);\n                return;\n            }\n"),
    ]),
    (1130, 1141, [  # tdefl_record_literal
        ("        d->m_total_lz_bytes++;\n", "        m29_d.litteraux++;\n        d->m_total_lz_bytes++;\n"),
    ]),
    (1143, 1169, [  # tdefl_record_match
        ("(match_dist <= TDEFL_LZ_DICT_SIZE));\n",
         "(match_dist <= TDEFL_LZ_DICT_SIZE));\n        m29_correspondance_d(match_len, match_dist);\n"),
    ]),
    (1171, 1347, [  # tdefl_compress_normal : résultat de la recherche, avant le rejet de la l. 1285
        ("&cur_match_dist, &cur_match_len);\n",
         "&cur_match_dist, &cur_match_len);\n                m29_resultat(cur_match_len, cur_match_dist, cur_pos);\n"),
    ]),
]

TINFL = [
    (187, 733, [  # tinfl_decompress
        ("            r->m_type = r->m_final >> 1;\n",
         "            r->m_type = r->m_final >> 1;\n            m29_i.blocs[r->m_type & 3]++;\n"),
        ("                            *pOut_buf_cur++ = (mz_uint8)counter;\n",
         "                            m29_i.litteraux_lents++;\n                            *pOut_buf_cur++ = (mz_uint8)counter;\n"),
        ("                            mz_uint code_len;\n",
         "                            mz_uint code_len;\n                            m29_i.tours_rapides++;\n"),
        ("                            pOut_buf_cur[0] = (mz_uint8)counter;\n",
         "                            pOut_buf_cur[0] = (mz_uint8)counter;\n                            m29_i.litteraux_rapides++;\n"),
        ("                            pOut_buf_cur[1] = (mz_uint8)sym2;\n",
         "                            pOut_buf_cur[1] = (mz_uint8)sym2;\n                            m29_i.litteraux_rapides++;\n"),
        ("                    dist_from_out_buf_start = pOut_buf_cur - pOut_buf_start;\n",
         "                    m29_correspondance_i(counter, dist);\n"
         "                    dist_from_out_buf_start = pOut_buf_cur - pOut_buf_start;\n"),
        ("                    if ((MZ_MAX(pOut_buf_cur, pSrc) + counter) > pOut_buf_end)\n                    {\n",
         "                    if ((MZ_MAX(pOut_buf_cur, pSrc) + counter) > pOut_buf_end)\n                    {\n"
         "                        m29_i.copie_lente++;\n"),
        ("                        mz_uint8 *const pOut_match_end = pOut_buf_cur + counter;\n",
         "                        mz_uint8 *const pOut_match_end = pOut_buf_cur + counter;\n"
         "                        if (counter <= 8)\n                            m29_i.copie_large_4_8++;\n"
         "                        else\n                            m29_i.copie_large_9_plus++;\n"),
        ("                    while (counter > 2)\n",
         "                    m29_copie_octets(counter, dist);\n                    while (counter > 2)\n"),
    ]),
]
# Deux occurrences voulues : la recherche dans l'arbre des deux décodages du chemin rapide.
TINFL_ARBRE = ("                                code_len = TINFL_FAST_LOOKUP_BITS;\n",
               "                                m29_i.arbre_litt++;\n                                code_len = TINFL_FAST_LOOKUP_BITS;\n")


def remplacer_une_fois(texte, ancien, nouveau, ou):
    if isinstance(ancien, re.Pattern):
        trouves = ancien.findall(texte)
        if len(trouves) != 1:
            sys.exit(f"{ou} : motif {ancien.pattern!r} trouvé {len(trouves)} fois (1 attendu)")
        return ancien.sub(lambda m: nouveau, texte)
    n = texte.count(ancien)
    if n != 1:
        sys.exit(f"{ou} : texte {ancien[:60]!r}… trouvé {n} fois (1 attendu)")
    return texte.replace(ancien, nouveau)


def instrumenter(source, plages, sortie, supplement=None):
    with open(os.path.join(commun.RACINE, source), encoding="utf-8") as f:
        lignes = f.read().split("\n")
    for debut, fin, remplacements in sorted(plages, key=lambda p: -p[0]):
        bloc = "\n".join(lignes[debut - 1:fin]) + "\n"
        for ancien, nouveau in remplacements:
            bloc = remplacer_une_fois(bloc, ancien, nouveau, f"{source} l. {debut}-{fin}")
        if supplement and supplement[0] == (debut, fin):
            ancien, nouveau, nombre = supplement[1]
            if bloc.count(ancien) != nombre:
                sys.exit(f"{source} : {ancien.strip()!r} trouvé {bloc.count(ancien)} fois ({nombre} attendus)")
            bloc = bloc.replace(ancien, nouveau)
        lignes[debut - 1:fin] = bloc[:-1].split("\n")
    texte = "\n".join(lignes)
    texte = remplacer_une_fois(texte, '#include "miniz.h"\n', '#include "miniz.h"\n#include "stats_lz.h"\n', source)
    with open(sortie, "w", encoding="utf-8") as f:
        f.write(texte)


def construire():
    instr = os.path.join(commun.CONSTR, "instr")
    os.makedirs(instr, exist_ok=True)
    instrumenter("miniz_tdef.c", TDEF, os.path.join(instr, "miniz_tdef.c"))
    instrumenter("miniz_tinfl.c", TINFL, os.path.join(instr, "miniz_tinfl.c"), ((187, 733), (*TINFL_ARBRE, 2)))
    inc = ["-I" + commun.RACINE, "-I" + os.path.join(commun.BEE, "commun"), "-I" + commun.ICI]
    objets = []
    for src in (os.path.join(commun.RACINE, "miniz.c"), os.path.join(instr, "miniz_tdef.c"), os.path.join(instr, "miniz_tinfl.c")):
        obj = os.path.join(instr, os.path.basename(src)[:-2] + ".o")
        subprocess.run(["cc", "-O2", "-g", "-std=gnu90", "-D_GNU_SOURCE", "-Wno-unused-function"] + inc + ["-c", src, "-o", obj], check=True)
        objets.append(obj)
    harnais = os.path.join(instr, "stats_lz")
    subprocess.run(["cc", "-O2", "-g", "-std=gnu99", "-D_GNU_SOURCE", "-Wall", "-Wno-unused-function"] + inc
                   + [os.path.join(commun.ICI, "stats_lz.c"), os.path.join(commun.BEE, "commun", "sha256.c"),
                      os.path.join(commun.BEE, "commun", "corpus.c")] + objets
                   + ["-Wl,-Bstatic", "-lz", "-Wl,-Bdynamic", "-o", harnais], check=True)
    return harnais


def sommer(acc, enr):
    for k, v in enr.items():
        if isinstance(v, list):
            a = acc.setdefault(k, [])
            if len(a) < len(v):
                a.extend([0] * (len(v) - len(a)))
            for i, x in enumerate(v):
                a[i] += x
        else:
            acc[k] = acc.get(k, 0) + v


def quantile(hist, q):
    total, cumul = sum(hist), 0
    for i, n in enumerate(hist):
        cumul += n
        if total and cumul >= q * total:
            return i
    return None


# Tranches de distance, par codes de distance Deflate (code 0 : distance 1 ; 26 à 29 : 8193 à 32768).
TRANCHES_DIST = [("1", 0, 0), ("2-4", 1, 3), ("5-8", 4, 5), ("9-64", 6, 11), ("65-512", 12, 17),
                 ("513-4096", 18, 23), ("4097-8192", 24, 25), ("8193-32768", 26, 29)]
TRANCHES_LEN = [("3", 3, 3), ("4", 4, 4), ("5-8", 5, 8), ("9-16", 9, 16), ("17-32", 17, 32), ("33-64", 33, 64),
                ("65-128", 65, 128), ("129-257", 129, 257), ("258", 258, 258)]


def tranches(hist, definition):
    total = sum(hist)
    return {nom: (sum(hist[a:b + 1]) / total if total else None) for nom, a, b in definition}


def synthese_tdefl(s, octets):
    h = s.get("hist_sondes", [])
    sorties = s.get("sorties", []) + [0] * 6
    noms = ["immediate", "budget", "fin_chaine", "trop_loin", "dist_nulle", "longueur_max"]
    r = lambda a, b: a / b if b else None  # noqa: E731
    return {
        "octets": octets, "appels": s["appels"], "appels_par_octet": r(s["appels"], octets),
        "sondes": s["sondes"], "sondes_par_appel": r(s["sondes"], s["appels"]),
        "sondes_mediane": quantile(h, 0.5), "sondes_p90": quantile(h, 0.9), "sondes_p99": quantile(h, 0.99),
        "sondes_max": len(h) - 1 if h else None,
        "part_appels_sans_sonde": r(h[0] if h else 0, s["appels"]),
        "part_appels_paresseux": r(s["appels_paresseux"], s["appels"]),
        "sorties": {n: r(sorties[i], s["appels"]) for i, n in enumerate(noms)},
        "candidats_par_sonde": r(s["candidats"], s["sondes"]),
        "comparaisons_par_appel": r(s["comparaisons"], s["appels"]),
        "part_comparaisons_vaines": r(s["comparaisons_vaines"], s["comparaisons"]),
        "octets_compares_par_comparaison": r(s["octets_compares"], s["comparaisons"]),
        "rang_du_resultat_median": (lambda q: None if q is None else q + 1)(quantile(s.get("hist_prof", [0])[1:], 0.5)),
        "trouvees_par_appel": r(s["trouvees"], s["appels"]),
        "part_len3_parmi_trouvees": r(s["len3_trouvees"], s["trouvees"]),
        "part_len3_loin_parmi_len3": r(s["rejet_len3_loin"], s["len3_trouvees"]),
        "part_len3_loin_parmi_trouvees": r(s["rejet_len3_loin"], s["trouvees"]),
        "part_sondes_des_appels_len3_loin": r(s["sondes_rejet_len3_loin"], s["sondes"]),
        "part_sondes_des_appels_sans_resultat": r(s["sondes_sans_resultat"], s["sondes"]),
        "distances_len3_trouvees": tranches(s.get("hist_dcode_len3", []), TRANCHES_DIST),
        "rejets_cur_pos": s["rejet_pos"],
        "litteraux": s["litteraux"], "correspondances": s["correspondances"],
        "longueur_moyenne": r(s["octets_correspondances"], s["correspondances"]),
        "distance_moyenne": r(s["somme_distances"], s["correspondances"]),
        "part_octets_en_correspondances": r(s["octets_correspondances"], octets),
        "longueurs": tranches(s.get("hist_len", []), TRANCHES_LEN),
        "distances": tranches(s.get("hist_dcode", []), TRANCHES_DIST),
        "part_chevauchantes": r(s["chevauchantes"], s["correspondances"]),
        "part_dist1": r(s["dist1"], s["correspondances"]),
    }


def synthese_tinfl(s, octets):
    r = lambda a, b: a / b if b else None  # noqa: E731
    lit = s["litteraux_rapides"] + s["litteraux_lents"]
    corr = s["correspondances"]
    return {
        "octets": octets, "blocs": s.get("blocs", []), "litteraux": lit, "correspondances": corr,
        "part_octets_litteraux": r(lit, octets), "part_octets_correspondances": r(s["octets_correspondances"], octets),
        "longueur_moyenne": r(s["octets_correspondances"], corr),
        "distance_moyenne": r(s["somme_distances"], corr),
        "part_litteraux_lents": r(s["litteraux_lents"], lit),
        "part_litteraux_par_arbre": r(s["arbre_litt"], lit),
        "copies": {"lente": r(s["copie_lente"], corr), "large_4_8": r(s["copie_large_4_8"], corr),
                   "large_9_plus": r(s["copie_large_9_plus"], corr), "octets_len3": r(s["copie_octets_len3"], corr),
                   "octets_chevauchee": r(s["copie_octets_chevauchee"], corr)},
        "chevauchees_dist1": r(s["copie_octets_dist1"], s["copie_octets_chevauchee"]),
        "chevauchees_dist_2_7": r(s["copie_octets_dist_2_7"], s["copie_octets_chevauchee"]),
        "part_octets_copie_octet_par_octet": r(s["octets_copie_octets"], octets),
        "longueurs": tranches(s.get("hist_len", []), TRANCHES_LEN),
        "distances": tranches(s.get("hist_dcode", []), TRANCHES_DIST),
    }


def verifier_empreintes(enregistrements):
    attendu = {}
    with open(os.path.join(commun.BEE, "tests", "empreintes-reference.txt"), encoding="utf-8") as f:
        for l in f:
            if l.startswith("#") or not l.strip():
                continue
            niveau, taille, sha, nom = l.split(maxsplit=3)
            attendu[(niveau, nom.strip())] = (int(taille), sha)
    n = 0
    for e in enregistrements:
        if "niveau" not in e:
            continue
        cle = (str(e["niveau"]), e["fichier"])
        if cle not in attendu or attendu[cle] != (e["compresse"], e["sha256"]):
            sys.exit(f"sortie instrumentée différente de l'empreinte de référence : niveau {cle[0]}, {cle[1]}")
        n += 1
    return n


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--prefixe", type=int, default=-1, help="N premiers octets de chaque fichier (-1 : entiers)")
    a.add_argument("--niveaux", default="1,6,9")
    a.add_argument("--json", required=True)
    args = a.parse_args()

    commun.verifier_sources()
    harnais = construire()
    cmd = [harnais, "--corpus", commun.CORPUS, "--niveaux", args.niveaux] + (["--prefixe", str(args.prefixe)] if args.prefixe >= 0 else [])
    sortie = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    enregistrements = [json.loads(l) for l in sortie.splitlines() if l.strip()]
    verifiees = verifier_empreintes(enregistrements) if args.prefixe < 0 else 0
    if args.prefixe < 0:
        print(f"{verifiees} sorties compressées instrumentées identiques aux empreintes de référence")

    sommes, octets = {}, {}
    for e in enregistrements:
        famille = e["fichier"].split("/")[0]
        cle = ("d", e["niveau"]) if "niveau" in e else ("i", e["flux"])
        for f in (famille, "tout"):
            sommer(sommes.setdefault((f,) + cle, {}), e["d"] if "niveau" in e else e["i"])
            octets[(f,) + cle] = octets.get((f,) + cle, 0) + e["taille"]
    resultat = {"commit_sources": commun.COMMIT, "prefixe": args.prefixe, "empreintes_verifiees": verifiees,
                "tdefl": {}, "tinfl": {}, "brut": {}}
    for (f, genre, k), s in sorted(sommes.items(), key=lambda x: str(x[0])):
        if genre == "d":
            resultat["tdefl"].setdefault(f"n{k}", {})[f] = synthese_tdefl(s, octets[(f, genre, k)])
        else:
            resultat["tinfl"].setdefault(k, {})[f] = synthese_tinfl(s, octets[(f, genre, k)])
        resultat["brut"][f"{genre}:{k}:{f}"] = s
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, separators=(",", ":"))
    for niv in sorted(resultat["tdefl"]):
        t = resultat["tdefl"][niv]["tout"]
        print(f"{niv} : {t['sondes_par_appel']:.2f} sondes par appel, len 3 à 8 Kio et plus : "
              f"{100 * (t['part_len3_loin_parmi_len3'] or 0):.1f} % des len 3 trouvées")
    return 0


if __name__ == "__main__":
    sys.exit(main())
