#!/usr/bin/env python3
"""Assemble verdict.json pour la CI Bee du fork miniz (job « verdict » de .github/workflows/bee-ci.yml).

Entrées :
  --jobs        résultats des jobs GitHub (toJSON(needs) : {"manifeste": {"result": "success", "outputs": {...}}, ...}).
                C'est la source de vérité de « ci » : le code de la PR ne peut pas les réécrire.
  --artefacts   dossier où les artefacts « etat-* » ont été téléchargés : fichiers d'état <etape>.txt
                (« succes » / « echec », écrits par bee/ci/etape.sh), rapport juge-ancien.json de l'ancien juge
                isolé (artefact etat-juge-ancien, transition), CONTRIBUTION.yaml de la PR et tache.yaml du registre
                (artefact etat-manifeste). Ce sont des DONNÉES : lues, jamais exécutées. Les jobs qui exécutent du
                code de la PR (meta-juge, outillage-pr) n'ont pas d'artefact : leur étape vient de leur résultat.
  --juge        dossier de l'artefact « juge » du juge commun (workflow juge.yml du registre) : juge.json (au
                format d'ab.py plus une section « juge ») et code (0 juste, 1 refusé, 2 environnement) ; défaut
                <artefacts>/juge. En CI, le code est celui de la sortie « code » du job juge (--jobs), qui prime.
  --depot, --base, --tete   pour compter les lignes modifiées (git diff --numstat).

Sortie (--sortie, défaut verdict.json), avec au minimum :
  ci                « verte » si tous les jobs ont réussi, sinon « rouge »
  etape_en_echec    première étape en échec dans l'ordre de la CI (si rouge)
  gain              gain relatif sur la métrique principale de la tâche (positif = mieux), ou null
  metrique          la métrique principale retenue, ou null
  au_dela_du_bruit  test du signe d'ab.py sur la métrique principale (false si aucune métrique)
  mesures           {"A": {6 métriques}, "B": {6 métriques}} : médianes du juge isolé (ou d'ab.py)
  instructions      décompte Cachegrind par scénario sur un sous-corpus : {"instructions_n6": {"A", "B", "gain"}, ...}
  degradations      métriques dégradées au-delà du bruit (test du signe ; instructions au-delà du seuil), avec leur gain
  lignes_modifiees  lignes modifiées hors bee/**, tests/**, manifestes/** et CONTRIBUTION.yaml (pour bee enregistrer-verdict)
  amorcage          true si les juges ou le greffon venaient de la PR elle-même (bee/ci/juges.sh)
  base_juge         le commit A réellement extrait par le juge commun (son greffon et ses sources), la règle qui
                    l'a choisi (point_de_depart, introduction, ou un refus) et le point de départ de la PR,
                    d'après les sorties du job greffon ; null hors CI
  juge              section du juge commun : version (3 depuis juge-v1), commun (« juge-vN »), projet, greffon
                    (SHA-256 de bee/juge/projet.py), graine, sorties comparées et constructions_suspectes
                    (liste vide si l'analyse des objets n'a rien trouvé) ; null si le juge n'a pas tourné
  etapes, details   pour les relecteurs (details.juge_ancien : l'ancien juge isolé, s'il a jugé)

Métrique principale, dans l'ordre : la clé « metrique » de la tâche du registre (tache.yaml), sinon une clé
« metrique » du manifeste, sinon la seule métrique de mesures.avant du manifeste. Faute de quoi, gain = null.

La CI ne tranche pas R4 et R5 (seuils de gain et d'effets de bord) : elle publie les mesures et les
dégradations, l'outil du registre applique les règles.

Usage local (simulation) : python3 bee/ci/verdict.py --etats DOSSIER --ab juge.json [--juge DOSSIER] [--manifeste F] [--tache F]
"""

import argparse
import fnmatch
import glob
import json
import os
import re
import subprocess
import sys

# (étape, libellé, job GitHub qui la porte), dans l'ordre de la CI. « juges » est écrite par
# bee/ci/juges.sh dans chaque job ; son job est None : elle compte dès qu'un job l'a écrite.
ETAPES = [
    ("juges", "Juges (base sans bee/)", None),
    ("manifeste_et_taille", "Manifeste et taille", "manifeste"),
    ("compilation_x86_64", "Compilation et tests d'origine (x86-64)", "compilation-et-tests"),
    ("compilation_arm64", "Compilation et tests d'origine (ARM64)", "compilation-et-tests"),
    ("differentiel_x86_64", "Tests différentiels et empreintes (x86-64)", "compilation-et-tests"),
    ("differentiel_arm64", "Tests différentiels et empreintes (ARM64)", "compilation-et-tests"),
    ("fuzzing", "Fuzzing (x86-64)", "fuzzing"),
    ("greffon_juge", "Greffon du juge commun", "greffon"),
    ("juge_isole", "Juge commun (vérification de l'extérieur et mesures)", "juge"),
    ("juge_ancien", "Ancien juge isolé de la base (transition)", "juge-ancien"),
    ("meta_juge", "Méta-tests du greffon contre le juge commun", "meta-juge"),
    ("outillage_pr", "Tests de l'outillage de CI de la PR", "outillage-pr"),
]
# Étapes dont le job exécute du code de la PR sur la machine de CI (méta-tests du greffon, tests de bee/ci/ de la
# PR) : en CI, leur état vient du seul résultat du job. Ces jobs ne publient ni artefact ni sortie : rien de ce
# que le code de la PR a pu écrire n'est lu ici.
ETAPES_RESULTAT_SEUL = {"meta_juge", "outillage_pr"}
METRIQUES = ["debit_compression_n1", "debit_compression_n6", "debit_compression_n9",
             "debit_decompression", "ratio_n6", "memoire_max_ko"]
# Repris de projets/miniz.yaml (chemins_hors_decompte) dans le registre Bee.
CHEMINS_HORS_DECOMPTE = ["bee/**", "tests/**", "CONTRIBUTION.yaml", "manifestes/**"]


def lire_texte(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def etats_depuis(dossiers):
    """Renvoie (états des étapes, amorçage signalé par au moins un job)."""
    etats, amorcage = {}, False
    for dossier in dossiers:
        for chemin in glob.glob(os.path.join(dossier, "**", "*.txt"), recursive=True):
            nom = os.path.basename(chemin)[:-4]
            if nom == "amorcage":
                amorcage = amorcage or lire_texte(chemin) == "oui"
            elif any(nom == e for e, _, _ in ETAPES):
                valeur = lire_texte(chemin)
                # Un « echec » l'emporte toujours sur un « succes » du même nom.
                if valeur in ("succes", "echec") and etats.get(nom) != "echec":
                    etats[nom] = valeur
    return etats, amorcage


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
    except Exception as e:  # donnée de la PR : toute erreur de lecture rend simplement la donnée invalide
        return None, f"illisible ({type(e).__name__})"
    return (donnees, "ok") if isinstance(donnees, dict) else (None, "pas un objet YAML")


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
        if ajoutees == "-" or any(fnmatch.fnmatchcase(chemin, m) for m in CHEMINS_HORS_DECOMPTE):
            continue
        total += int(ajoutees) + int(retirees)
    return total


def section_juge(juge):
    """Ce que le registre garde du juge. Donnée produite par le juge commun (workflow juge.yml, greffon de la base)."""
    if not isinstance(juge, dict):
        return None
    commun, greffon = juge.get("commun"), juge.get("greffon")
    suspects = juge.get("constructions_suspectes")
    if not isinstance(suspects, list):
        suspects = [{"type": "illisible", "detail": "liste des constructions suspectes absente ou illisible"}]
    propres = []
    for s in suspects[:50]:
        if isinstance(s, dict):
            propres.append({"type": str(s.get("type", ""))[:40], "detail": str(s.get("detail", ""))[:300]})
    verification = juge.get("verification") if isinstance(juge.get("verification"), dict) else {}
    return {
        "version": juge.get("version") if isinstance(juge.get("version"), int) else None,
        "commun": commun if isinstance(commun, str) and re.fullmatch(r"juge-v\d{1,4}", commun) else None,
        "projet": str(juge.get("projet"))[:40] if juge.get("projet") is not None else None,
        "greffon": greffon if isinstance(greffon, str) and re.fullmatch(r"[0-9a-f]{64}", greffon) else None,
        "graine": str(juge.get("graine", ""))[:64],
        "sorties_comparees": verification.get("sorties_comparees") if isinstance(verification.get("sorties_comparees"), int) else None,
        "constructions_suspectes": propres,
    }


def code_du_juge(jobs, dossier_juge):
    """Code rendu par le juge commun : la sortie « code » du job juge (workflow juge.yml), que le code de la
    PR ne peut pas réécrire ; hors CI, le fichier code de l'artefact « juge ». None si inconnu."""
    if jobs:
        code = ((jobs.get("juge") or {}).get("outputs") or {}).get("code")
    else:
        code = lire_texte(os.path.join(dossier_juge, "code")) if dossier_juge else None
    return str(code).strip() if code is not None else None


REGLES_BASE_JUGE = {"point_de_depart", "introduction", "refus_point_de_depart", "refus_rebase", "refus_introduction_miniz"}
SHA = re.compile(r"[0-9a-f]{40}")


def base_juge(jobs, base):
    """Le commit A du juge commun, tel que le job greffon l'a choisi (sorties du job, que le code de la PR ne
    peut pas réécrire). Le registre peut ainsi vérifier que A est bien le point de départ de la PR."""
    if not jobs:
        return None
    sorties = (jobs.get("greffon") or {}).get("outputs") or {}
    commit, regle, depart = sorties.get("base_juge"), sorties.get("regle"), sorties.get("depart")
    return {
        "commit": commit if isinstance(commit, str) and SHA.fullmatch(commit) else None,
        "regle": regle if regle in REGLES_BASE_JUGE else None,
        "depart": depart if isinstance(depart, str) and SHA.fullmatch(depart) else None,
        "base": base,
    }


def base_juge_acceptee(a, amorcage):
    """A est-il celui que le job greffon a le droit de choisir ? point_de_depart : A est le point de départ
    lui-même ; introduction : seulement en amorçage (bee/ci/juges.sh) ; tout autre cas, ou un commit ou un
    point de départ illisible : non (revue adverse de miniz-0032)."""
    if a is None:
        return True  # hors CI : rien à vérifier
    if a["commit"] is None or a["depart"] is None:
        return False
    if a["regle"] == "point_de_depart":
        return a["commit"] == a["depart"]
    if a["regle"] == "introduction":
        return bool(amorcage)
    return False


def lire_json(chemin):
    if not chemin or not os.path.exists(chemin):
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = json.load(f)
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


def trouver_dans(artefacts, artefact, nom):
    """Fichier d'un artefact précis (etat-manifeste, etat-juge-ancien…) : jamais celui d'un autre job."""
    return trouver(os.path.join(artefacts, artefact), nom) if artefacts else None


def trouver(dossier, nom):
    if not dossier:
        return None
    trouves = sorted(glob.glob(os.path.join(dossier, "**", nom), recursive=True))
    return trouves[0] if trouves else None


def main():
    analyseur = argparse.ArgumentParser(description="Assemble verdict.json pour la CI Bee du fork miniz.")
    analyseur.add_argument("--jobs", help="toJSON(needs) du workflow : résultats des jobs (source de vérité de « ci »)")
    analyseur.add_argument("--artefacts", help="dossier des artefacts etat-* téléchargés")
    analyseur.add_argument("--etats", help="dossier des fichiers <etape>.txt (simulation locale)")
    analyseur.add_argument("--juge", help="dossier de l'artefact « juge » du juge commun (défaut : <artefacts>/juge)")
    analyseur.add_argument("--ab", help="rapport JSON du juge ou d'ab.py (défaut : juge.json de --juge, sinon ab.json dans --artefacts)")
    analyseur.add_argument("--manifeste", help="CONTRIBUTION.yaml de la PR (donnée)")
    analyseur.add_argument("--tache", help="tâche du registre (défaut : tache.yaml trouvé dans --artefacts)")
    analyseur.add_argument("--depot", help="clone du fork, pour compter les lignes modifiées")
    analyseur.add_argument("--base")
    analyseur.add_argument("--tete")
    analyseur.add_argument("--sortie", default="verdict.json")
    args = analyseur.parse_args()

    jobs = {}
    if args.jobs:
        with open(args.jobs, encoding="utf-8") as f:
            jobs = json.load(f) or {}
    etats, amorcage = etats_depuis([d for d in (args.etats, args.artefacts) if d])
    dossier_juge = args.juge or (os.path.join(args.artefacts, "juge") if args.artefacts else None)
    # Étape du juge commun : son job ne devient pas rouge à cause de B, c'est son code qui juge. En CI, rien
    # d'autre (aucun fichier d'état) ne la rend réussie : sans code, elle est sans résultat.
    code_juge = code_du_juge(jobs, dossier_juge)
    if code_juge is None and jobs:
        etats.pop("juge_isole", None)
    elif code_juge is not None:
        etats["juge_isole"] = "succes" if code_juge == "0" and etats.get("juge_isole") != "echec" else "echec"
    chemin_ab = args.ab or (os.path.join(dossier_juge, "juge.json") if dossier_juge and os.path.isfile(os.path.join(dossier_juge, "juge.json"))
                            else None) or (None if jobs else trouver(args.artefacts, "ab.json"))
    rapport = lire_json(chemin_ab)
    # Un code 0 sans section juge, ou sans aucune sortie comparée, n'est pas un jugement : rouge.
    section = section_juge((rapport or {}).get("juge"))
    if code_juge == "0" and not (section and isinstance(section["sorties_comparees"], int) and section["sorties_comparees"] > 0):
        etats["juge_isole"] = "echec"
    rapport_ancien = lire_json(trouver_dans(args.artefacts, "etat-juge-ancien", "juge-ancien.json"))
    # Le juge commun n'a jugé que si A est connu et choisi par une règle qui l'accepte : sinon, l'étape du
    # greffon est en échec, quoi que disent les fichiers d'état (jamais un verdict vert sans A vérifiable).
    a_juge = base_juge(jobs, args.base)
    if not base_juge_acceptee(a_juge, amorcage):
        etats["greffon_juge"] = "echec"
    chemin_manifeste = args.manifeste or trouver_dans(args.artefacts, "etat-manifeste", "CONTRIBUTION.yaml")
    chemin_tache = args.tache or trouver_dans(args.artefacts, "etat-manifeste", "tache.yaml")

    # Étape par étape : réussie seulement si son fichier d'état dit « succes » ET (en CI) si son job a réussi.
    resultat_etapes = {}
    for etape, _, job in ETAPES:
        etat = etats.get(etape, "absent")
        if job is None:  # « juges » : un seul « echec » suffit ; absente hors CI (simulation sans juges.sh)
            resultat_etapes[etape] = "echec" if etat == "echec" else ("succes" if etat == "succes" or not jobs else "absent")
            continue
        resultat_job = (jobs.get(job) or {}).get("result") if jobs else None
        if jobs and etape in ETAPES_RESULTAT_SEUL:
            resultat_etapes[etape] = {"success": "succes", "failure": "echec"}.get(resultat_job, "absent")
            continue
        if jobs and resultat_job != "success":
            # Job en échec : l'étape garde son propre état ; une étape « succes » d'un job en échec reste
            # suspecte (autre étape du même job en échec, ou job interrompu après coup).
            if etat == "echec":
                resultat_etapes[etape] = "echec"
            elif etat == "succes":
                resultat_etapes[etape] = f"succes (job {resultat_job})"
            else:
                resultat_etapes[etape] = "absent"
        else:
            resultat_etapes[etape] = "succes" if etat == "succes" else ("echec" if etat == "echec" else "absent")
    jobs_en_echec = [nom for nom, v in jobs.items() if (v or {}).get("result") != "success"]
    # D'abord la première étape explicitement en échec ; sinon la première sans résultat (job annulé,
    # délai dépassé, machine ARM64 indisponible…) ; sinon le job en échec.
    en_echec = next((libelle for etape, libelle, _ in ETAPES if resultat_etapes[etape].startswith("echec")), None)
    if en_echec is None:
        en_echec = next((libelle + " (sans résultat)" for etape, libelle, _ in ETAPES if resultat_etapes[etape] != "succes"), None)
    if en_echec is None and jobs_en_echec:
        en_echec = "job " + ", ".join(sorted(jobs_en_echec))

    manifeste, etat_manifeste = charger_yaml(chemin_manifeste)
    tache, etat_tache = charger_yaml(chemin_tache)
    metrique, origine = metrique_principale(tache, manifeste)

    metriques_ab = (rapport or {}).get("metriques", {})
    instructions = (rapport or {}).get("instructions")
    gain, bruit = None, False
    if metrique and metrique in metriques_ab:
        gain = metriques_ab[metrique].get("gain")
        bruit = bool(metriques_ab[metrique].get("au_dela_du_bruit"))
    degradations = {m: v.get("gain") for m, v in metriques_ab.items() if v.get("degradation_au_dela_du_bruit")}
    for nom, v in (instructions or {}).items():
        if v.get("au_dela_du_bruit") and (v.get("gain") or 0) < 0:
            degradations[nom] = v.get("gain")

    # « verte » exige que toutes les étapes aient réussi ET (en CI) que tous les jobs aient réussi.
    if en_echec is None and any(v != "succes" for v in resultat_etapes.values()):
        en_echec = "étape au résultat incohérent"
    verdict = {"ci": "rouge" if en_echec else "verte"}
    if en_echec:
        verdict["etape_en_echec"] = en_echec
    verdict.update({
        "gain": gain,
        "metrique": metrique,
        "au_dela_du_bruit": bruit,
        "mesures": (rapport or {}).get("mesures") or {"A": {m: None for m in METRIQUES}, "B": {m: None for m in METRIQUES}},
        "instructions": ({nom: {"A": v.get("A"), "B": v.get("B"), "gain": v.get("gain")} for nom, v in instructions.items()}
                         if instructions else None),
        "degradations": degradations,
        "lignes_modifiees": lignes_modifiees(args.depot, args.base, args.tete),
        "amorcage": amorcage,
        "base_juge": a_juge,
        "juge": section_juge((rapport or {}).get("juge")),
        "etapes": resultat_etapes,
        "details": {
            "origine_metrique": origine,
            "manifeste": etat_manifeste,
            "tache": etat_tache,
            "base": args.base,
            "tete": args.tete,
            "jobs": {nom: (v or {}).get("result") for nom, v in jobs.items()},
            "gains_par_metrique": {m: v.get("gain") for m, v in metriques_ab.items()},
            "test_du_signe": {m: v.get("test_du_signe") for m, v in metriques_ab.items()},
            "methode": (rapport or {}).get("methode"),
            "machine": (rapport or {}).get("machine"),
            "repetitions": (rapport or {}).get("repetitions"),
            "code_juge": code_juge,
            "juge_ancien": ({"juge": section_juge(rapport_ancien.get("juge")),
                             "instructions": {nom: {"A": v.get("A"), "B": v.get("B")} for nom, v in (rapport_ancien.get("instructions") or {}).items()
                                              if isinstance(v, dict)}}
                            if rapport_ancien else None),
        },
    })
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    resume = {k: verdict[k] for k in ("ci", "etape_en_echec", "gain", "metrique", "au_dela_du_bruit", "degradations",
                                      "lignes_modifiees", "amorcage") if k in verdict}
    if amorcage:
        print("AMORÇAGE : les juges de cette exécution venaient de la PR elle-même (amorcage: true).", file=sys.stderr)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
