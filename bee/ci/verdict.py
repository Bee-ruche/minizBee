#!/usr/bin/env python3
"""Assemble verdict.json pour la CI Bee du fork miniz.

Entrées (dossier --etats) : un fichier <etape>.txt par étape de la CI, contenant « succes », « echec »
ou « saute », écrit par chaque job ; le rapport d'ab.py (--ab) ; le manifeste CONTRIBUTION.yaml de la
PR (--manifeste), lu comme une DONNÉE, jamais exécuté ; la tâche du registre Bee (--tache, optionnel).

Sortie : verdict.json, avec au minimum :
  ci                « verte » ou « rouge »
  etape_en_echec    nom de la première étape en échec, si rouge (sinon absent)
  gain              gain relatif sur la métrique principale de la tâche (positif = mieux), ou null
  metrique          la métrique principale retenue, ou null
  au_dela_du_bruit  booléen : test du signe d'ab.py sur la métrique principale (false si aucune)
  mesures           {"A": {...6 métriques...}, "B": {...}} (médianes d'ab.py)
  instructions      décompte Cachegrind par scénario (A, B, gain) sur un sous-corpus, ou null
  degradations      métriques dégradées au-delà du bruit (test du signe), avec leur gain : donnée pour R5
  lignes_modifiees  lignes modifiées hors chemins exclus (pour bee enregistrer-verdict)

La métrique principale vient, dans l'ordre : de la clé « metrique » de la tâche du registre si elle est
fournie (--tache), sinon d'une clé « metrique » du manifeste, sinon d'une métrique unique présente dans
mesures.avant du manifeste. Si aucune n'est désignée, gain vaut null.

La CI ne juge pas R4 et R5 (seuils de gain et d'effets de bord) : elle publie les mesures, le registre
applique les règles. « ci » ne dit que si les étapes de vérification ont réussi.

Dépendance : PyYAML, seulement pour lire le manifeste (python3-yaml ou pip install pyyaml) ; sans
PyYAML, gain vaut null et la raison est écrite dans le verdict.
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys

# Ordre des étapes de la CI : la première en échec est rapportée.
ETAPES = [
    ("manifeste_et_taille", "Manifeste et taille"),
    ("compilation_x86_64", "Compilation et tests d'origine (x86-64)"),
    ("compilation_arm64", "Compilation et tests d'origine (ARM64)"),
    ("differentiel_x86_64", "Tests différentiels et empreintes (x86-64)"),
    ("differentiel_arm64", "Tests différentiels et empreintes (ARM64)"),
    ("fuzzing", "Fuzzing (x86-64)"),
    ("banc_ab", "Banc A/B"),
]
METRIQUES = ["debit_compression_n1", "debit_compression_n6", "debit_compression_n9",
             "debit_decompression", "ratio_n6", "memoire_max_ko"]
# Repris de projets/miniz.yaml (chemins_hors_decompte) dans le registre Bee.
CHEMINS_HORS_DECOMPTE = ["bee/**", "tests/**", "CONTRIBUTION.yaml"]


def lire_etat(dossier, etape):
    chemin = os.path.join(dossier, etape + ".txt")
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip().lower() or "absent"
    except OSError:
        return "absent"


def charger_yaml(chemin):
    if not chemin or not os.path.exists(chemin):
        return None, "absent"
    try:
        import yaml
    except ImportError:
        return None, "PyYAML indisponible"
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = yaml.safe_load(f)
    except Exception as e:  # le manifeste vient de la PR : toute erreur de lecture est une donnée invalide
        return None, f"illisible ({type(e).__name__})"
    return (donnees if isinstance(donnees, dict) else None), ("ok" if isinstance(donnees, dict) else "pas un objet YAML")


def metrique_principale(tache, manifeste):
    if isinstance(tache, dict) and tache.get("metrique") in METRIQUES:
        return tache["metrique"], "tâche du registre"
    if isinstance(manifeste, dict):
        if manifeste.get("metrique") in METRIQUES:
            return manifeste["metrique"], "manifeste (clé metrique)"
        mesures = manifeste.get("mesures") if isinstance(manifeste.get("mesures"), dict) else {}
        avant = mesures.get("avant") if isinstance(mesures.get("avant"), dict) else {}
        connues = [m for m in avant if m in METRIQUES]
        if len(connues) == 1:
            return connues[0], "manifeste (seule métrique de mesures.avant)"
    return None, "aucune métrique désignée"


def lignes_modifiees(depot, base, tete):
    if not (depot and base and tete):
        return None
    try:
        sortie = subprocess.run(["git", "-C", depot, "diff", "--numstat", "--no-renames", f"{base}...{tete}"],
                                capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    total = 0
    for ligne in sortie.splitlines():
        ajoutees, retirees, chemin = ligne.split("\t", 2)
        if any(fnmatch.fnmatchcase(chemin, m) for m in CHEMINS_HORS_DECOMPTE) or ajoutees == "-":
            continue
        total += int(ajoutees) + int(retirees)
    return total


def main():
    analyseur = argparse.ArgumentParser(description="Assemble verdict.json pour la CI Bee du fork miniz.")
    analyseur.add_argument("--etats", required=True, help="dossier des fichiers <etape>.txt")
    analyseur.add_argument("--ab", help="rapport JSON d'ab.py")
    analyseur.add_argument("--manifeste", help="CONTRIBUTION.yaml de la PR (donnée)")
    analyseur.add_argument("--tache", help="fichier YAML de la tâche dans le registre (optionnel)")
    analyseur.add_argument("--depot", help="clone du fork, pour compter les lignes modifiées")
    analyseur.add_argument("--base", help="commit de base de la PR")
    analyseur.add_argument("--tete", help="commit de tête de la PR")
    analyseur.add_argument("--sortie", default="verdict.json")
    args = analyseur.parse_args()

    etats = {etape: lire_etat(args.etats, etape) for etape, _ in ETAPES}
    en_echec = next((libelle for etape, libelle in ETAPES if etats[etape] not in ("succes", "saute")), None)

    manifeste, etat_manifeste = charger_yaml(args.manifeste)
    tache, etat_tache = charger_yaml(args.tache)
    metrique, origine = metrique_principale(tache, manifeste)

    rapport = None
    if args.ab and os.path.exists(args.ab):
        try:
            with open(args.ab, encoding="utf-8") as f:
                rapport = json.load(f)
        except (OSError, ValueError):
            rapport = None

    verdict = {"ci": "rouge" if en_echec else "verte"}
    if en_echec:
        verdict["etape_en_echec"] = en_echec
    gain, bruit = None, False
    mesures = {"A": {m: None for m in METRIQUES}, "B": {m: None for m in METRIQUES}}
    if rapport:
        mesures = rapport.get("mesures", mesures)
        if metrique and metrique in rapport.get("metriques", {}):
            gain = rapport["metriques"][metrique].get("gain")
            bruit = bool(rapport["metriques"][metrique].get("au_dela_du_bruit"))
    metriques_ab = (rapport or {}).get("metriques", {})
    instructions = (rapport or {}).get("instructions")
    degradations = {m: v.get("gain") for m, v in metriques_ab.items() if v.get("degradation_au_dela_du_bruit")}
    for nom, v in (instructions or {}).items():
        if v.get("au_dela_du_bruit") and (v.get("gain") or 0) < 0:
            degradations[nom] = v.get("gain")
    verdict.update({
        "gain": gain,
        "metrique": metrique,
        "au_dela_du_bruit": bruit,
        "mesures": mesures,
        "instructions": ({nom: {"A": v.get("A"), "B": v.get("B"), "gain": v.get("gain")} for nom, v in instructions.items()}
                         if instructions else None),
        "degradations": degradations,
        "lignes_modifiees": lignes_modifiees(args.depot, args.base, args.tete),
        "etapes": etats,
        "details": {
            "origine_metrique": origine,
            "manifeste": etat_manifeste,
            "tache": etat_tache,
            "base": args.base,
            "tete": args.tete,
            "gains_par_metrique": {m: v.get("gain") for m, v in metriques_ab.items()},
            "test_du_signe": {m: v.get("test_du_signe") for m, v in metriques_ab.items()},
            "methode": (rapport or {}).get("methode"),
            "machine": (rapport or {}).get("machine"),
            "repetitions": (rapport or {}).get("repetitions"),
        },
    })
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: verdict[k] for k in ("ci", "etape_en_echec", "gain", "metrique", "au_dela_du_bruit", "degradations",
                                               "lignes_modifiees") if k in verdict}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
