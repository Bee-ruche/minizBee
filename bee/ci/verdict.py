#!/usr/bin/env python3
"""Assembles verdict.json for the Bee CI of the miniz fork (job « verdict » of .github/workflows/bee-ci.yml).

Inputs:
  --jobs        the GitHub jobs' results (toJSON(needs): {"manifeste": {"result": "success", "outputs": {...}}, ...}).
                They are the source of truth for « ci »: the PR's code cannot rewrite them.
  --artefacts   folder where the « etat-* » artifacts were downloaded: state files <etape>.txt (« succes » / « echec »,
                written by bee/ci/etape.sh), the PR's CONTRIBUTION.yaml and the registry's tache.yaml (artifact
                etat-manifeste). They are DATA: read, never executed; each file is read only at the root of the
                artifact of the job that produces it (the common judge's report: --juge), each state file only in its
                job's state folder (DOSSIERS_ETATS); never a symbolic link. The jobs that run the PR's code (meta-juge,
                outillage-pr) have no artifact: their step comes from their result.
  --juge        folder of the common judge's artifact « judge » (the registry's workflow judge.yml, judge-v4):
                judge.json (in ab.py's format plus a « judge » section, its keys in English) and code (0 correct,
                1 refused, 2 environment); default <artefacts>/judge. In CI, the code is the output « code » of the job
                judge (--jobs), which prevails.
  --depot, --base, --tete   to count the changed lines (git diff --numstat).

Output (--sortie, default verdict.json), in English (the registry's tools/migration/names.yaml, family fork_verdict),
with at least:
  ci                « green » if every job passed, otherwise « red »
  failed_step       the first failed step in the CI's order (if red)
  gain              relative gain on the task's main metric (positive = better), or null
  metric            the main metric kept, or null
  beyond_noise      the sign test on the main metric (false without a metric)
  measurements      {"A": {6 metrics}, "B": {6 metrics}}: the common judge's medians (or ab.py's)
  instructions      Cachegrind count per scenario on a sub-corpus: {"instructions_n6": {"A", "B", "gain"}, ...}
  degradations      metrics degraded beyond noise (sign test; instructions beyond the threshold), with their gain
  changed_lines     lines changed outside bee/**, tests/**, manifests/**, manifestes/** and CONTRIBUTION.yaml (for
                    bee record-verdict)
  bootstrap         true if the judges or the plugin came from the PR itself (bee/ci/juges.sh)
  judge_base        the commit A the common judge really checked out (its plugin and its sources), the rule that
                    chose it (pr_base; or a refusal) and the PR's starting point, from the greffon job's outputs; null
                    outside CI
  judge             the common judge's section: version (3 since juge-v1), common (« judge-vN »), project, plugin
                    (SHA-256 of bee/judge/project.py), seed, outputs_compared and suspicious_constructs (an empty list if
                    the object analysis found nothing); null if the judge did not run
  steps, details    for the reviewers
Metric ids are written in English (compression_throughput_n1, _n6, _n9, decompression_throughput, ratio_n6,
max_memory_kb; instructions_n1, _n6, _n9, _decompression); bee reads them in either vocabulary until its DATE_D.

Main metric: « metric » of the task's copy (tache.yaml of etat-manifeste, bee/ci/vocabulaire.py; a French metric id is
read in English), null if it says null; missing in CI, unreadable, or an unknown metric: step « Manifest and size »
failed, never a metric chosen by the PR. Outside CI and without a copy only: the manifest's (metric, otherwise the only
metric of measurements.before; or in French). Failing that, gain = null.

The CI does not decide R4 and R5 (gain and side-effect thresholds): it publishes the measurements and the degradations,
the registry's tool applies the rules.

Local use (simulation): python3 bee/ci/verdict.py --etats FOLDER --ab judge.json [--juge FOLDER] [--manifeste F] [--tache F]
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys

from vocabulaire import METRIQUES, Illisible, lire_manifeste, metrique_de_la_tache

# (step, its key in verdict.json, label, GitHub job that carries it), in the CI's order. The step is the name of its state
# file (<etape>.txt, written by the workflow and the base's scripts); the key and the label are what verdict.json says.
# « juges » is written by bee/ci/juges.sh in each job; its job is None: it counts as soon as a job has written it. The
# common judge's job is « judge » (judge-v4); the old isolated judge's step (juge_ancien) is gone with juge-v3.
ETAPES = [
    ("juges", "judges", "Judges (base without bee/)", None),
    ("manifeste_et_taille", "manifest_and_size", "Manifest and size", "manifeste"),
    ("compilation_x86_64", "build_x86_64", "Build and original tests (x86-64)", "compilation-et-tests"),
    ("compilation_arm64", "build_arm64", "Build and original tests (ARM64)", "compilation-et-tests"),
    ("differentiel_x86_64", "differential_x86_64", "Differential tests and fingerprints (x86-64)", "compilation-et-tests"),
    ("differentiel_arm64", "differential_arm64", "Differential tests and fingerprints (ARM64)", "compilation-et-tests"),
    ("fuzzing", "fuzzing", "Fuzzing (x86-64)", "fuzzing"),
    ("greffon_juge", "judge_plugin", "Common judge plugin", "greffon"),
    ("juge_isole", "common_judge", "Common judge (checking from the outside and measurements)", "judge"),
    ("meta_juge", "plugin_meta_tests", "Plugin meta-tests against the common judge", "meta-juge"),
    ("outillage_pr", "pr_tooling_tests", "Tests of the PR's CI tooling", "outillage-pr"),
]
# A step's result in verdict.json; the state files keep « succes » and « echec » (bee/ci/etape.sh, juges.sh).
RESULTATS = {"succes": "passed", "echec": "failed", "absent": "absent"}
# Steps whose job runs the PR's code on the CI machine (the plugin's meta-tests, the PR's bee/ci/ tests): in CI, their
# state comes from the job's result alone. These jobs publish neither artifact nor output: nothing the PR's code may
# have written is read here.
ETAPES_RESULTAT_SEUL = {"meta_juge", "outillage_pr"}
# Each step's state folder in the artifacts: the one where the job that writes it puts it (bee-ci.yml: etats/ at the root
# of its artifact, or under etats/ when the artifact also carries its data). A step is read only there, never in another
# artifact (nor in « judge ») nor deeper; the steps without an artifact (meta_juge, outillage_pr: the job's result;
# juge_isole: the judge's code) are read only in --etats.
DOSSIERS_ETATS = {
    "manifeste_et_taille": "etat-manifeste/etats",
    "compilation_x86_64": "etat-tests-x86_64", "differentiel_x86_64": "etat-tests-x86_64",
    "compilation_arm64": "etat-tests-arm64", "differentiel_arm64": "etat-tests-arm64",
    "fuzzing": "etat-fuzzing",
    "greffon_juge": "etat-greffon",
}
# From projects/miniz.yaml (paths_not_counted) in the Bee registry, plus the manifest, in both its folders.
CHEMINS_HORS_DECOMPTE = ["bee/**", "tests/**", "CONTRIBUTION.yaml", "manifests/**", "manifestes/**"]


def lire_texte(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def ordinaire(chemin):
    """A regular file: neither a symbolic link nor a folder."""
    return bool(chemin) and os.path.isfile(chemin) and not os.path.islink(chemin)


def etats_depuis(dossier_etats, artefacts):
    """Returns (the steps' states, bootstrap reported by at least one job). In --etats (the verdict job's folder, or a
    simulation's), each <etape>.txt at its root; in the artifacts, each <etape>.txt only in the state folder of the job
    that writes it (DOSSIERS_ETATS), « juges » and « amorcage » in each of these folders."""
    noms = [e for e, _, _, _ in ETAPES] + ["amorcage"]
    chemins = [os.path.join(dossier_etats, nom + ".txt") for nom in noms] if dossier_etats else []
    for nom in noms if artefacts else []:
        if nom in ("juges", "amorcage"):
            dossiers = sorted(set(DOSSIERS_ETATS.values()))
        else:
            dossiers = [DOSSIERS_ETATS[nom]] if nom in DOSSIERS_ETATS else []
        chemins += [os.path.join(artefacts, dossier, nom + ".txt") for dossier in dossiers]
    etats, amorcage = {}, False
    for chemin in filter(ordinaire, chemins):
        nom, valeur = os.path.basename(chemin)[:-4], lire_texte(chemin)
        if nom == "amorcage":
            amorcage = amorcage or valeur == "oui"
        # An « echec » always prevails over a « succes » of the same name.
        elif valeur in ("succes", "echec") and etats.get(nom) != "echec":
            etats[nom] = valeur
    return etats, amorcage


def charger_yaml(chemin):
    if not chemin or not os.path.exists(chemin):
        return None, "absent"
    try:
        import yaml
    except ImportError:
        return None, "PyYAML unavailable"
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = yaml.safe_load(f)
    except Exception as e:  # PR data: any reading error simply makes the data invalid
        return None, f"unreadable ({type(e).__name__})"
    return (donnees, "ok") if isinstance(donnees, dict) else (None, "not a YAML object")


def metrique_principale(tache, etat_tache, manifeste, en_ci):
    """(metric in English or None, origin). Raises Illisible when the task does not say its metric readably."""
    if tache is not None:
        metrique = metrique_de_la_tache(tache)
        return metrique, "registry task" if metrique else "registry task (metric: null)"
    if en_ci or etat_tache != "absent":
        raise Illisible(f"copy of the registry's task {etat_tache}: metric unreadable")
    if manifeste is not None:
        manifeste = lire_manifeste(manifeste)
        if manifeste.get("metric") in METRIQUES:
            return manifeste["metric"], "manifest (key metric)"
        mesures = manifeste.get("measurements") if isinstance(manifeste.get("measurements"), dict) else {}
        avant = mesures.get("before") if isinstance(mesures.get("before"), dict) else {}
        connues = [m for m in avant if m in METRIQUES]
        if len(connues) == 1:
            return connues[0], "manifest (only metric of measurements.before)"
    return None, "no metric named"


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
    """What the registry keeps of the judge: judge.json's « judge » section (judge-v4, English keys). Data produced by the
    common judge (workflow judge.yml, the base's plugin). The construct types stay as the judge writes them."""
    if not isinstance(juge, dict):
        return None
    commun, greffon = juge.get("common"), juge.get("plugin")
    suspects = juge.get("suspicious_constructs")
    if not isinstance(suspects, list):
        suspects = [{"type": "illisible", "detail": "list of suspicious constructs missing or unreadable"}]
    propres = []
    for s in suspects[:50]:
        if isinstance(s, dict):
            propres.append({"type": str(s.get("type", ""))[:40], "detail": str(s.get("detail", ""))[:300]})
    verification = juge.get("verification") if isinstance(juge.get("verification"), dict) else {}
    comparees = verification.get("outputs_compared")
    return {
        "version": juge.get("version") if isinstance(juge.get("version"), int) else None,
        "common": commun if isinstance(commun, str) and re.fullmatch(r"judge-v\d{1,4}", commun) else None,
        "project": str(juge.get("project"))[:40] if juge.get("project") is not None else None,
        "plugin": greffon if isinstance(greffon, str) and re.fullmatch(r"[0-9a-f]{64}", greffon) else None,
        "seed": str(juge.get("seed", ""))[:64],
        "outputs_compared": comparees if isinstance(comparees, int) and not isinstance(comparees, bool) else None,
        "suspicious_constructs": propres,
    }


def code_du_juge(jobs, dossier_juge):
    """The code the common judge returned: the output « code » of the job judge (workflow judge.yml), which the PR's code
    cannot rewrite; outside CI, the file code of the artifact « judge ». None if unknown."""
    if jobs:
        code = ((jobs.get("judge") or {}).get("outputs") or {}).get("code")
    else:
        code = lire_texte(os.path.join(dossier_juge, "code")) if dossier_juge and ordinaire(os.path.join(dossier_juge, "code")) else None
    return str(code).strip() if code is not None else None


# The greffon job's rules (its output « regle », the value bee-ci.yml writes) -> their names in verdict.json
# (names.yaml, domain fork_judge_base_rule; pr_base is new with juge-v3). juge-v2's rules (point_de_depart,
# introduction, refus_introduction_miniz) are gone.
REGLES_BASE_JUGE = {"base_de_la_pr": "pr_base", "refus_point_de_depart": "refused_start_point", "refus_rebase": "refused_rebase"}
SHA = re.compile(r"[0-9a-f]{40}")


def base_juge(jobs, base):
    """The common judge's commit A, as the greffon job chose it (the job's outputs, which the PR's code cannot rewrite).
    The registry can thus check that A is the PR's base."""
    if not jobs:
        return None
    sorties = (jobs.get("greffon") or {}).get("outputs") or {}
    commit, regle, depart = sorties.get("base_juge"), sorties.get("regle"), sorties.get("depart")
    return {
        "commit": commit if isinstance(commit, str) and SHA.fullmatch(commit) else None,
        "rule": REGLES_BASE_JUGE.get(regle) if isinstance(regle, str) else None,
        "start": depart if isinstance(depart, str) and SHA.fullmatch(depart) else None,
        "base": base,
    }


def base_juge_acceptee(a):
    """Is A the one the greffon job may choose? pr_base (juge-v3 on): A is the PR's base, the event's, once the greffon
    job has checked that the starting point has the same bee/ and miniz*; any other case, or an unreadable commit or
    starting point: no (adversarial review of miniz-0032)."""
    if a is None:
        return True  # outside CI: nothing to check
    if a["commit"] is None or a["start"] is None:
        return False
    return a["rule"] == "pr_base" and a["commit"] == a["base"]


def resultat_en_anglais(resultat):
    """A step's result as verdict.json says it: « succes (job failure) » -> « passed (job failure) »."""
    mot, _, reste = resultat.partition(" ")
    return RESULTATS.get(mot, mot) + (" " + reste if reste else "")


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
    """The file `nom` at the root of the artifact of the job that produces it (etat-manifeste): never another job's or a
    subfolder's, and never a symbolic link."""
    chemin = os.path.join(artefacts, artefact, nom) if artefacts else None
    return chemin if ordinaire(chemin) else None


def main():
    analyseur = argparse.ArgumentParser(description="Assembles verdict.json for the Bee CI of the miniz fork.")
    analyseur.add_argument("--jobs", help="the workflow's toJSON(needs): the jobs' results (source of truth for « ci »)")
    analyseur.add_argument("--artefacts", help="folder of the downloaded etat-* artifacts")
    analyseur.add_argument("--etats", help="folder of the <etape>.txt files, at its root (the verdict job's, or a local simulation)")
    analyseur.add_argument("--juge", help="folder of the common judge's « judge » artifact (default: <artefacts>/judge)")
    analyseur.add_argument("--ab", help="JSON report of the judge or of ab.py (default: judge.json at the root of --juge)")
    analyseur.add_argument("--manifeste", help="the PR's CONTRIBUTION.yaml (data; default: the one in the etat-manifeste artifact)")
    analyseur.add_argument("--tache", help="the registry's task (default: tache.yaml of the etat-manifeste artifact)")
    analyseur.add_argument("--depot", help="clone of the fork, to count the changed lines")
    analyseur.add_argument("--base")
    analyseur.add_argument("--tete")
    analyseur.add_argument("--sortie", default="verdict.json")
    args = analyseur.parse_args()

    jobs = {}
    if args.jobs:
        with open(args.jobs, encoding="utf-8") as f:
            jobs = json.load(f) or {}
    etats, amorcage = etats_depuis(args.etats, args.artefacts)
    dossier_juge = args.juge or (os.path.join(args.artefacts, "judge") if args.artefacts else None)
    # The common judge's step: its job does not turn red because of B, its code judges. In CI, nothing else (no state
    # file) makes it pass: without a code, it has no result.
    code_juge = code_du_juge(jobs, dossier_juge)
    if code_juge is None and jobs:
        etats.pop("juge_isole", None)
    elif code_juge is not None:
        etats["juge_isole"] = "succes" if code_juge == "0" and etats.get("juge_isole") != "echec" else "echec"
    # The report comes from --ab, otherwise from judge.json at the root of the artifact « judge », the job that produces
    # it; in CI as in simulation, never from another artifact.
    chemin_ab = args.ab or (os.path.join(dossier_juge, "judge.json") if dossier_juge and ordinaire(os.path.join(dossier_juge, "judge.json"))
                            else None)
    rapport = lire_json(chemin_ab)
    # A code 0 without a judge section, or without any compared output, is not a judgement: red.
    section = section_juge((rapport or {}).get("judge"))
    if code_juge == "0" and not (section and isinstance(section["outputs_compared"], int) and section["outputs_compared"] > 0):
        etats["juge_isole"] = "echec"
    # The common judge judged only if A is known and chosen by a rule that accepts it: otherwise, the plugin's step fails,
    # whatever the state files say (never a green verdict without a checkable A).
    a_juge = base_juge(jobs, args.base)
    if not base_juge_acceptee(a_juge):
        etats["greffon_juge"] = "echec"
    chemin_manifeste = args.manifeste or trouver_dans(args.artefacts, "etat-manifeste", "CONTRIBUTION.yaml")
    chemin_tache = args.tache or trouver_dans(args.artefacts, "etat-manifeste", "tache.yaml")
    manifeste, etat_manifeste = charger_yaml(chemin_manifeste)
    tache, etat_tache = charger_yaml(chemin_tache)
    try:
        metrique, origine = metrique_principale(tache, etat_tache, manifeste, bool(jobs))
    except Illisible as e:
        # The task sets the metric, never the PR: without it, no green verdict (its copy comes from the manifeste job).
        metrique, origine = None, f"unreadable: {e}"
        etats["manifeste_et_taille"] = "echec"
        print(f"::error::verdict.py: {e}", file=sys.stderr)

    # Step by step: passed only if its state file says « succes » AND (in CI) its job passed.
    resultat_etapes = {}
    for etape, _, _, job in ETAPES:
        etat = etats.get(etape, "absent")
        if job is None:  # « juges »: one « echec » is enough; absent outside CI (simulation without juges.sh)
            resultat_etapes[etape] = "echec" if etat == "echec" else ("succes" if etat == "succes" or not jobs else "absent")
            continue
        resultat_job = (jobs.get(job) or {}).get("result") if jobs else None
        if jobs and etape in ETAPES_RESULTAT_SEUL:
            resultat_etapes[etape] = {"success": "succes", "failure": "echec"}.get(resultat_job, "absent")
            continue
        if jobs and resultat_job != "success":
            # A failed job: the step keeps its own state; a « succes » step of a failed job stays suspect (another
            # step of the same job failed, or the job was interrupted afterwards).
            if etat == "echec":
                resultat_etapes[etape] = "echec"
            elif etat == "succes":
                resultat_etapes[etape] = f"succes (job {resultat_job})"
            else:
                resultat_etapes[etape] = "absent"
        else:
            resultat_etapes[etape] = "succes" if etat == "succes" else ("echec" if etat == "echec" else "absent")
    jobs_en_echec = [nom for nom, v in jobs.items() if (v or {}).get("result") != "success"]
    # First the first step explicitly failed; otherwise the first without a result (job cancelled, timeout, ARM64
    # machine unavailable…); otherwise the failed job.
    en_echec = next((libelle for etape, _, libelle, _ in ETAPES if resultat_etapes[etape].startswith("echec")), None)
    if en_echec is None:
        en_echec = next((libelle + " (no result)" for etape, _, libelle, _ in ETAPES if resultat_etapes[etape] != "succes"), None)
    if en_echec is None and jobs_en_echec:
        en_echec = "job " + ", ".join(sorted(jobs_en_echec))

    # The common judge's report (judge.json, judge-v4), in English; its metric ids are the base's plugin's.
    metriques_ab = (rapport or {}).get("metrics", {})
    instructions = (rapport or {}).get("instructions")
    gain, bruit = None, False
    if metrique and metrique in metriques_ab:
        gain = metriques_ab[metrique].get("gain")
        bruit = bool(metriques_ab[metrique].get("beyond_noise"))
    degradations = {m: v.get("gain") for m, v in metriques_ab.items() if v.get("degradation_beyond_noise")}
    for nom, v in (instructions or {}).items():
        if v.get("beyond_noise") and (v.get("gain") or 0) < 0:
            degradations[nom] = v.get("gain")

    # « green » requires every step to have passed AND (in CI) every job to have passed.
    if en_echec is None and any(v != "succes" for v in resultat_etapes.values()):
        en_echec = "step with an inconsistent result"
    verdict = {"ci": "red" if en_echec else "green"}
    if en_echec:
        verdict["failed_step"] = en_echec
    verdict.update({
        "gain": gain,
        "metric": metrique,
        "beyond_noise": bruit,
        "measurements": (rapport or {}).get("measurements") or {"A": {m: None for m in METRIQUES}, "B": {m: None for m in METRIQUES}},
        "instructions": ({nom: {"A": v.get("A"), "B": v.get("B"), "gain": v.get("gain")} for nom, v in instructions.items()}
                         if instructions else None),
        "degradations": degradations,
        "changed_lines": lignes_modifiees(args.depot, args.base, args.tete),
        "bootstrap": amorcage,
        "judge_base": a_juge,
        "judge": section,
        "steps": {cle: resultat_en_anglais(resultat_etapes[etape]) for etape, cle, _, _ in ETAPES},
        "details": {
            "metric_origin": origine,
            "manifest": etat_manifeste,
            "task": etat_tache,
            "base": args.base,
            "head": args.tete,
            "jobs": {nom: (v or {}).get("result") for nom, v in jobs.items()},
            "gains_by_metric": {m: v.get("gain") for m, v in metriques_ab.items()},
            "sign_test": {m: v.get("sign_test") for m, v in metriques_ab.items()},
            "method": (rapport or {}).get("method"),
            "machine": (rapport or {}).get("machine"),
            "repetitions": (rapport or {}).get("repetitions"),
            "judge_code": code_juge,
        },
    })
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    resume = {k: verdict[k] for k in ("ci", "failed_step", "gain", "metric", "beyond_noise", "degradations",
                                      "changed_lines", "bootstrap") if k in verdict}
    if amorcage:
        print("BOOTSTRAP: the judges of this run came from the PR itself (bootstrap: true).", file=sys.stderr)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
