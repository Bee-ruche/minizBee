#!/usr/bin/env python3
"""Tableaux de miniz-0029 (TABLEAUX.md), calculés uniquement à partir des JSON de donnees/.

Usage : python3 bee/resultats/miniz-0029/tableaux.py > bee/resultats/miniz-0029/TABLEAUX.md
(n'exécute aucun code de miniz : lit les JSON produits dans la sandbox par cachegrind.py, juge_parts.py,
stats_lz.py et chrono_familles.py)
"""

import json
import os

ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.path.join(ICI, "donnees")
SCENARIOS = ["n1", "n6", "n9", "decompression"]
FAMILLES = ["tout", "texte", "code", "structure", "binaire", "repetitif", "petits"]


def charger(nom):
    with open(os.path.join(DONNEES, nom), encoding="utf-8") as f:
        return json.load(f)


def pc(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}".replace(".", ",")


def nb(x, d=1):
    return "—" if x is None else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def ent(x):
    return f"{x:,}".replace(",", " ")


def l1m(e):
    return e["D1mr"] + e["D1mw"] + e["I1mr"]


def llm(e):
    return e["DLmr"] + e["DLmw"] + e["ILmr"]


def bm(e):
    return e["Bcm"] + e["Bim"]


def cest(e):
    """Estimation de cycles de KCachegrind : Ir + 10 Bm + 10 L1m + 100 LLm (un modèle, pas une mesure)."""
    return e["Ir"] + 10 * bm(e) + 10 * l1m(e) + 100 * llm(e)


def table(entetes, lignes):
    out = ["| " + " | ".join(entetes) + " |", "| " + " | ".join("---" for _ in entetes) + " |"]
    out += ["| " + " | ".join(str(c) for c in l) + " |" for l in lignes]
    return "\n".join(out)


def ajuster(cg, ch):
    """Moindres carrés sans constante : ns/octet = a * instructions/octet + b * défauts L1/octet,
    sur n1, n6, n9 × familles (hors « petits », dominée par des memset comptés octet par octet)."""
    pts = []
    for s in ("n1", "n6", "n9"):
        for f in ("texte", "code", "structure", "binaire", "repetitif"):
            m = cg["mesures"][s][f]
            o = m["octets"]
            pts.append((m["total"]["Ir"] / o, l1m(m["total"]) / o, ch["mesures"][s][f]["ns_par_octet"]))
    sxx = sum(x * x for x, _, _ in pts); sxy = sum(x * y for x, y, _ in pts); syy = sum(y * y for _, y, _ in pts)
    sxz = sum(x * z for x, _, z in pts); syz = sum(y * z for _, y, z in pts)
    det = sxx * syy - sxy * sxy
    a, b = (sxz * syy - syz * sxy) / det, (syz * sxx - sxz * sxy) / det
    a0 = sxz / sxx
    moy = sum(z for _, _, z in pts) / len(pts)
    tot = sum((z - moy) ** 2 for _, _, z in pts)
    r2 = 1 - sum((z - a * x - b * y) ** 2 for x, y, z in pts) / tot
    r2_0 = 1 - sum((z - a0 * x) ** 2 for x, _, z in pts) / tot
    return a, b, r2, a0, r2_0


def main():
    cg, juge, ch = charger("cachegrind.json"), charger("juge_parts.json"), charger("chrono_familles.json")
    st, st128 = charger("stats_lz.json"), charger("stats_lz_128k.json")
    p = print
    p("# miniz-0029 : tableaux\n")
    p(f"Sources de miniz au commit {cg['commit_sources']} (master du 30/10/2026). Produits par `tableaux.py` à partir de "
      "`donnees/*.json` ; chaque section nomme le script qui a produit ses données (commandes : RAPPORT.md). "
      f"Cachegrind simule I1 {cg['options_cache'][0][5:]}, D1 {cg['options_cache'][1][5:]}, LL {cg['options_cache'][2][5:]} "
      "(taille, associativité, ligne). « CEst » : estimation de cycles de KCachegrind, Ir + 10 × branches mal prédites "
      "+ 10 × défauts L1 + 100 × défauts LL, un modèle et non une mesure.\n")

    # ---------------------------------------------------------------- 1. fonctions
    p("## 1. Coût par fonction, tout le corpus (cachegrind.py)\n")
    p(f"Passes chronométrées du banc seulement, {cg['prefixe']} premiers octets de chaque fichier (2 221 670 octets). "
      "« memcpy en ligne » : memcpy de taille fixe incorporé dans la fonction (_FORTIFY_SOURCE), que profil.py compte "
      "dans « hors miniz ».\n")
    for s in SCENARIOS:
        m = cg["mesures"][s]["tout"]
        T, tc = m["total"], cest(m["total"])
        lignes = []
        for nom, e in m["fonctions"].items():
            if e["Ir"] < 0.004 * T["Ir"]:
                continue
            lignes.append([nom, pc(e["Ir"] / T["Ir"]), pc(cest(e) / tc), ent(l1m(e)), nb(1000 * l1m(e) / e["Ir"], 2),
                           ent(llm(e)), ent(bm(e)), pc(bm(e) / max(1, e["Bc"] + e["Bi"]))])
        p(f"**{s}** : {ent(T['Ir'])} instructions, {ent(l1m(T))} défauts L1, {ent(bm(T))} branches mal prédites "
          f"({pc(bm(T) / (T['Bc'] + T['Bi']))} %), CEst / Ir = {nb(tc / T['Ir'], 3)}\n")
        p(table(["fonction", "Ir %", "CEst %", "défauts L1", "par 1000 Ir", "défauts LL", "mal prédites", "taux %"], lignes))
        p()

    # ---------------------------------------------------------------- 2. zones
    p("## 2. Zones de code, tout le corpus (cachegrind.py ; plages de lignes : commun.py)\n")
    zones_d = [z for z in cg["mesures"]["n6"]["tout"]["zones"] if not z.startswith("tinfl")]
    lignes = []
    for z in sorted(zones_d, key=lambda z: -cg["mesures"]["n9"]["tout"]["zones"].get(z, {"Ir": 0})["Ir"]):
        cells = [z]
        for s in ("n1", "n6", "n9"):
            m = cg["mesures"][s]["tout"]
            e = m["zones"].get(z)
            cells.append("—" if not e else pc(e["Ir"] / m["total"]["Ir"]))
        e9 = cg["mesures"]["n9"]["tout"]["zones"].get(z)
        e6 = cg["mesures"]["n6"]["tout"]["zones"].get(z)
        cells += [ent(l1m(e6)) if e6 else "—", ent(l1m(e9)) if e9 else "—",
                  ent(bm(e6)) if e6 else "—", pc(bm(e6) / max(1, e6["Bc"] + e6["Bi"])) if e6 else "—"]
        lignes.append(cells)
    p(table(["zone (compression)", "Ir % n1", "Ir % n6", "Ir % n9", "défauts L1 n6", "défauts L1 n9",
             "mal prédites n6", "taux n6 %"], lignes))
    p()
    m = cg["mesures"]["decompression"]["tout"]
    lignes = []
    for z, e in m["zones"].items():
        ej = juge["mesures"]["decompression"]["zones"].get(z)
        lignes.append([z, pc(e["Ir"] / m["total"]["Ir"]),
                       pc(ej["Ir"] / juge["mesures"]["decompression"]["total"]["Ir"]) if ej else "—",
                       ent(l1m(e)), ent(bm(e)), pc(bm(e) / max(1, e["Bc"] + e["Bi"]))])
    p(table(["zone (décompression)", "Ir % banc (flux miniz n6)", "Ir % juge (flux zlib n6)", "défauts L1", "mal prédites",
             "taux %"], lignes))
    p()

    # ---------------------------------------------------------------- 3. juge
    p("## 3. Parts dans le décompte d'instructions du juge (juge_parts.py)\n")
    p("Tout le processus de bee/juge/execution.c, 128 premiers Kio de chaque fichier, non perturbés ; décompression des "
      "flux zlib niveau 6 (zlib 1.3). C'est le dénominateur de R4 (instructions_n1, _n6, _n9, _decompression).\n")
    lignes = []
    noms = []
    for s in SCENARIOS:
        for n, e in juge["mesures"][s]["fonctions"].items():
            if e["Ir"] >= 0.01 * juge["mesures"][s]["total"]["Ir"] and n not in noms:
                noms.append(n)
    for n in noms:
        cells = [n]
        for s in SCENARIOS:
            e = juge["mesures"][s]["fonctions"].get(n)
            cells.append("—" if not e else pc(e["Ir"] / juge["mesures"][s]["total"]["Ir"], 2))
        lignes.append(cells)
    lignes.append(["**total (instructions)**"] + [ent(juge["mesures"][s]["total"]["Ir"]) for s in SCENARIOS])
    p(table(["fonction"] + SCENARIOS, lignes))
    p()
    hors = juge["mesures"]["n1"]["hors_miniz"]
    memset = sum(e["Ir"] for k, e in hors.items() if k.startswith("__memset"))
    p(f"Dont memset (n1) : {ent(memset)} instructions, {pc(memset / juge['mesures']['n1']['total']['Ir'], 2)} % : "
      "les remises à zéro de tdefl_init (m_hash 64 Kio, m_dict 33 Kio, 61 flux), que Valgrind compte à peu près une "
      "instruction par octet (rep stosb).\n")

    # ---------------------------------------------------------------- 4. familles
    p("## 4. Par famille du corpus (cachegrind.py, chrono_familles.py)\n")
    p(f"Chronomètre : médiane de {ch['repetitions']} exécutions du banc, chacune meilleure de {ch['passes']} passes, "
      "mêmes entrées que Cachegrind ; machine partagée (Xeon 2,1 GHz virtualisé, 2 cœurs, gcc 13.3).\n")
    for s in SCENARIOS:
        lignes = []
        for f in FAMILLES:
            m = cg["mesures"][s][f]
            T, o = m["total"], m["octets"]
            c = ch["mesures"][s][f]
            if s == "decompression":
                part = m["fonctions"].get("tinfl_decompress", {"Ir": 0})["Ir"] / T["Ir"]
            else:
                part = m["fonctions"].get("tdefl_find_match (l. 862)", {"Ir": 0})["Ir"] / T["Ir"]
            lignes.append([f, ent(o), nb(T["Ir"] / o), nb(1000 * l1m(T) / T["Ir"], 2), nb(1000 * bm(T) / T["Ir"], 2),
                           pc(part), nb(c["debit_median_mo_s"]), nb(c["ns_par_octet"], 2), nb(c["ns_par_instruction"], 3)])
        p(f"**{s}**\n")
        p(table(["famille", "octets", "Ir/octet", "défauts L1 / 1000 Ir", "mal prédites / 1000 Ir",
                 "tinfl_decompress %" if s == "decompression" else "find_match %", "Mo/s", "ns/octet", "ns/instruction"], lignes))
        p()
    a, b, r2, a0, r2_0 = ajuster(cg, ch)
    p(f"Ajustement (moindres carrés, n1/n6/n9 × 5 familles hors « petits ») : ns/octet ≈ {nb(a, 3)} × instructions/octet "
      f"+ {nb(b, 2)} × défauts L1/octet, R² {nb(r2, 3)} ; avec les instructions seules : {nb(a0, 3)} ns par instruction, "
      f"R² {nb(r2_0, 3)}. Part du temps attribuée aux défauts L1 par ce modèle :")
    parts = []
    for s in ("n1", "n6", "n9"):
        m = cg["mesures"][s]["tout"]
        o = m["octets"]
        x, y = m["total"]["Ir"] / o, l1m(m["total"]) / o
        parts.append(f"{s} {pc(b * y / (a * x + b * y))} %")
    p(", ".join(parts) + ". Un modèle à deux termes sur 15 points d'une machine virtualisée : un ordre de grandeur, à "
      "valider par des compteurs matériels.\n")

    # ---------------------------------------------------------------- 5. sondes
    p("## 5. Chaînes de sondes de tdefl_find_match (stats_lz.py)\n")
    p("« sondes » : lectures de m_next (exécutions de TDEFL_PROBE). Sorties : part des appels qui s'arrêtent sur le budget "
      "(--num_probes_left), une fin de chaîne (m_next nul), une position hors fenêtre (distance > max_dist) ou une "
      "correspondance de longueur maximale. « vaines » : comparaisons complètes qui n'améliorent pas la correspondance.\n")
    for titre, d in (("fichiers entiers (12 Mo)", st), ("128 premiers Kio par fichier (comme Cachegrind)", st128)):
        lignes = []
        for n in ("n1", "n6", "n9"):
            for f in FAMILLES:
                t = d["tdefl"][n].get(f)
                if not t or not t["appels"]:
                    continue
                so = t["sorties"]
                lignes.append([n, f, nb(t["appels_par_octet"], 3), nb(t["sondes_par_appel"], 2), t["sondes_mediane"],
                               t["sondes_p90"], t["sondes_p99"], pc(so["budget"]), pc(so["fin_chaine"]), pc(so["trop_loin"]),
                               pc(so["longueur_max"]), nb(t["candidats_par_sonde"], 3), nb(t["comparaisons_par_appel"], 2),
                               pc(t["part_comparaisons_vaines"]), t["rang_du_resultat_median"]])
        p(f"**{titre}**\n")
        p(table(["niveau", "famille", "appels/octet", "sondes/appel", "médiane", "p90", "p99", "budget %", "fin de chaîne %",
                 "hors fenêtre %", "longueur max %", "candidats/sonde", "comparaisons/appel", "vaines %",
                 "rang médian du résultat"], lignes))
        p()

    # ---------------------------------------------------------------- 6. correspondances
    p("## 6. Correspondances émises (stats_lz.py, fichiers entiers)\n")
    p("Symboles enregistrés par tdefl_record_match (avant le choix d'un bloc brut). Tranches de longueur et de distance "
      "en % des correspondances.\n")
    tl = list(st["tdefl"]["n6"]["tout"]["longueurs"])
    td = list(st["tdefl"]["n6"]["tout"]["distances"])
    lignes = []
    for n in ("n1", "n6", "n9"):
        for f in FAMILLES:
            t = st["tdefl"][n].get(f)
            if not t or not t["correspondances"]:
                continue
            lignes.append([n, f, ent(t["correspondances"]), ent(t["litteraux"]), nb(t["longueur_moyenne"], 2),
                           nb(t["distance_moyenne"], 0), pc(t["part_octets_en_correspondances"])]
                          + [pc(t["longueurs"][k]) for k in tl])
    p(table(["niveau", "famille", "correspondances", "littéraux", "longueur moy.", "distance moy.", "octets couverts %"]
            + [f"L {k}" for k in tl], lignes))
    p()
    lignes = []
    for n in ("n1", "n6", "n9"):
        for f in FAMILLES:
            t = st["tdefl"][n].get(f)
            if not t or not t["correspondances"]:
                continue
            lignes.append([n, f] + [pc(t["distances"][k]) for k in td] + [pc(t["part_chevauchantes"]), pc(t["part_dist1"])])
    p(table(["niveau", "famille"] + [f"D {k}" for k in td] + ["chevauchantes (D < L) %", "D = 1 %"], lignes))
    p()

    # ---------------------------------------------------------------- 7. longueur 3 loin
    p("## 7. Correspondances de longueur 3 à 8 Kio et plus, rejetées (miniz_tdef.c l. 1285 à a2f939a ; stats_lz.py)\n")
    p("Résultat de tdefl_find_match vu par tdefl_compress_normal, avant le rejet. « sondes » : part des sondes du niveau "
      "dépensées dans les appels dont le résultat est ainsi rejeté.\n")
    lignes = []
    for titre, d in (("entiers", st), ("128 Kio", st128)):
        for n in ("n1", "n6", "n9"):
            for f in FAMILLES:
                t = d["tdefl"][n].get(f)
                if not t or not t["appels"]:
                    continue
                lignes.append([titre, n, f, pc(t["trouvees_par_appel"]), pc(t["part_len3_parmi_trouvees"]),
                               pc(t["part_len3_loin_parmi_len3"]), pc(t["part_len3_loin_parmi_trouvees"]),
                               pc(t["part_sondes_des_appels_len3_loin"]), pc(t["part_sondes_des_appels_sans_resultat"])])
    p(table(["corpus", "niveau", "famille", "appels avec résultat %", "longueur 3 parmi les résultats %",
             "≥ 8 Kio parmi les longueurs 3 %", "≥ 8 Kio parmi les résultats %", "sondes de ces appels %",
             "sondes des appels sans résultat %"], lignes))
    p()

    # ---------------------------------------------------------------- 8. tinfl
    p("## 8. Décodage par tinfl_decompress (stats_lz.py)\n")
    p("« zlib6 » : flux de zlib 1.3 niveau 6, ceux du scénario de décompression du juge ; « miniz6 » : flux de mz_compress2 "
      "niveau 6, ceux du banc. Chemins de copie en % des correspondances : « 4 à 8 » et « 9 et plus » sans "
      "chevauchement (l. 587-613), « octet par octet » : longueur 3 ou chevauchement (l. 615-630).\n")
    lignes = []
    for titre, d in (("entiers", st), ("128 Kio", st128)):
        for flux in ("zlib6", "miniz6"):
            for f in FAMILLES:
                t = d["tinfl"][flux].get(f)
                if not t or not t["octets"]:
                    continue
                c = t["copies"]
                lignes.append([titre, flux, f, "/".join(str(x) for x in t["blocs"][:3]), pc(t["part_octets_litteraux"]),
                               nb(t["longueur_moyenne"], 2), pc(t["part_litteraux_par_arbre"], 2), pc(c["large_4_8"]),
                               pc(c["large_9_plus"]), pc(c["octets_len3"]), pc(c["octets_chevauchee"]),
                               pc(t["chevauchees_dist1"]), pc(t["chevauchees_dist_2_7"]),
                               pc(t["part_octets_copie_octet_par_octet"])])
    p(table(["corpus", "flux", "famille", "blocs stockés/fixes/dynamiques", "octets littéraux %", "longueur moy.",
             "littéraux par l'arbre %", "copie 4 à 8 %", "copie 9 et plus %", "octet par octet, longueur 3 %",
             "octet par octet, chevauchée %", "chevauchées D = 1 %", "chevauchées D 2 à 7 %",
             "octets copiés octet par octet %"], lignes))
    p()


if __name__ == "__main__":
    main()
