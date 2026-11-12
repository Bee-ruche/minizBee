#!/usr/bin/env python3
"""Unit tests of bee/ci/verdict.py (« ci », failed step, gain on the task's metric, verdict.json in English) and of the
CI steps of .github/workflows/bee-ci.yml (judges, plugin, the judge-v4 pin and the juge-v3 transition, manifest).

Usage: python3 bee/ci/test_verdict.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
VERDICT = os.path.join(ICI, "verdict.py")
JUGES = os.path.join(ICI, "juges.sh")
WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(ICI)), ".github", "workflows", "bee-ci.yml")
COMMIT_AMORCAGE = "2948eebafc5b9f1c69bebed80333e403a09bd62d"
# juge_isole n'a pas de fichier d'état : verdict.py la tire du code du juge commun (sortie du job judge).
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "differentiel_x86_64",
          "differentiel_arm64", "fuzzing", "greffon_juge", "meta_juge", "outillage_pr"]
DEPART, BASE = "d" * 40, "b" * 40
# The greffon job's outputs keep the values bee-ci.yml writes (regle: base_de_la_pr); verdict.json says them in English.
GREFFON_OK = {"result": "success", "outputs": {"base_juge": BASE, "regle": "base_de_la_pr", "depart": DEPART}}
JOBS_OK = {"manifeste": {"result": "success"}, "greffon": GREFFON_OK,
           "compilation-et-tests": {"result": "success"}, "fuzzing": {"result": "success"},
           "judge": {"result": "success", "outputs": {"code": "0"}},
           "meta-juge": {"result": "success"}, "outillage-pr": {"result": "success"}}
# Copie de la tâche par défaut des tests du verdict (miniz-0049 : en CI, sans copie lisible de la tâche, le verdict est
# rouge) : metric: null, donc gain null, comme sans tâche auparavant ; tache=None pour un verdict sans copie.
TACHE_SANS_METRIQUE = "type: test\nmetric: null\n"
# verdict.json's keys, from the registry's tools/migration/names.yaml (family fork_verdict), written by hand here.
CLES_VERDICT = {"ci", "gain", "metric", "beyond_noise", "measurements", "instructions", "degradations", "changed_lines",
                "bootstrap", "judge_base", "judge", "steps", "details"}
METRIQUES_EN = ["compression_throughput_n1", "compression_throughput_n6", "compression_throughput_n9", "decompression_throughput",
                "ratio_n6", "max_memory_kb"]
ETAPES_VERDICT = ETAPES[:8] + ["juge_isole"] + ETAPES[8:]
CLES_ETAPES = ["judges", "manifest_and_size", "build_x86_64", "build_arm64", "differential_x86_64", "differential_arm64", "fuzzing",
               "judge_plugin", "common_judge", "plugin_meta_tests", "pr_tooling_tests"]
# Dossier où chaque job dépose ses fichiers d'état dans son artefact (bee-ci.yml), écrit à la main : les tests vérifient
# verdict.py, ils ne le recopient pas. Les autres états (juges, amorcage, juge_isole, meta_juge, outillage_pr) vont dans
# --etats, le dossier du job verdict.
DOSSIER_ETAT = {"manifeste_et_taille": "etat-manifeste/etats", "compilation_x86_64": "etat-tests-x86_64",
                "differentiel_x86_64": "etat-tests-x86_64", "compilation_arm64": "etat-tests-arm64",
                "differentiel_arm64": "etat-tests-arm64", "fuzzing": "etat-fuzzing", "greffon_juge": "etat-greffon"}


def ecrire_etats(d, etats):
    """Écrit chaque état là où son job le dépose ; renvoie (dossier des artefacts, dossier --etats)."""
    artefacts, propres = os.path.join(d, "artefacts"), os.path.join(d, "etats")
    os.makedirs(artefacts, exist_ok=True)
    os.makedirs(propres, exist_ok=True)
    for etape, valeur in etats.items():
        dossier = os.path.join(artefacts, DOSSIER_ETAT[etape]) if etape in DOSSIER_ETAT else propres
        os.makedirs(dossier, exist_ok=True)
        with open(os.path.join(dossier, etape + ".txt"), "w") as f:
            f.write(valeur + "\n")
    return artefacts, propres


def rapport_ab(gain_n6=0.03, signe_n6=True, degradation_n1=False):
    """A judge.json of judge-v4 (English keys, the English plugin's metric ids)."""
    metriques = {}
    for nom in METRIQUES_EN:
        metriques[nom] = {"gain": 0.0, "beyond_noise": False, "degradation_beyond_noise": False, "sign_test": {}}
    metriques["compression_throughput_n6"].update({"gain": gain_n6, "beyond_noise": signe_n6})
    if degradation_n1:
        metriques["compression_throughput_n1"].update({"gain": -0.04, "degradation_beyond_noise": True})
    return {"metrics": metriques, "measurements": {"A": {"compression_throughput_n6": 22.5}, "B": {"compression_throughput_n6": 23.2}},
            "instructions": {"instructions_n6": {"A": 100, "B": 97, "gain": 0.03, "beyond_noise": True}},
            "judge": {"version": 3, "common": "judge-v4", "project": "miniz", "plugin": "c0" * 32, "seed": "ab" * 16,
                      "verification": {"outputs_compared": 914}, "suspicious_constructs": []}}


class Verdict(unittest.TestCase):
    def executer(self, etats, jobs=None, ab=None, tache=TACHE_SANS_METRIQUE, nom_rapport="judge.json", code=None,
                 manifeste=None, base=BASE):
        with tempfile.TemporaryDirectory() as d:
            artefacts, propres = ecrire_etats(d, etats)
            commande = [sys.executable, VERDICT, "--artefacts", artefacts, "--etats", propres, "--sortie", os.path.join(d, "verdict.json")]
            if base is not None:
                commande += ["--base", base]
            if jobs is not None:
                with open(os.path.join(d, "jobs.json"), "w") as f:
                    json.dump(jobs, f)
                commande += ["--jobs", os.path.join(d, "jobs.json")]
            if ab is not None:
                # Le rapport du juge commun est dans l'artefact « judge » ; sous un autre nom, ailleurs (jamais lu).
                dossier = os.path.join(artefacts, "judge" if nom_rapport == "judge.json" else "x")
                os.makedirs(dossier, exist_ok=True)
                with open(os.path.join(dossier, nom_rapport), "w") as f:
                    json.dump(ab, f)
            if code is not None:
                os.makedirs(os.path.join(artefacts, "judge"), exist_ok=True)
                with open(os.path.join(artefacts, "judge", "code"), "w") as f:
                    f.write(code + "\n")
            for nom, contenu in (("tache.yaml", tache), ("CONTRIBUTION.yaml", manifeste)):
                if contenu is not None:
                    os.makedirs(os.path.join(artefacts, "etat-manifeste"), exist_ok=True)
                    with open(os.path.join(artefacts, "etat-manifeste", nom), "w") as f:
                        f.write(contenu)
            subprocess.run(commande, check=True, capture_output=True)
            with open(os.path.join(d, "verdict.json")) as f:
                return json.load(f)

    def test_tout_vert(self):
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), "metric: compression_throughput_n6\n")
        self.assertEqual(v["ci"], "green")
        self.assertNotIn("failed_step", v)
        self.assertAlmostEqual(v["gain"], 0.03)
        self.assertTrue(v["beyond_noise"])
        self.assertEqual(v["instructions"]["instructions_n6"]["B"], 97)
        self.assertEqual(set(v), CLES_VERDICT)
        self.assertEqual(v["steps"], {"judges": "passed", "manifest_and_size": "passed", "build_x86_64": "passed",
                                      "build_arm64": "passed", "differential_x86_64": "passed", "differential_arm64": "passed",
                                      "fuzzing": "passed", "judge_plugin": "passed", "common_judge": "passed",
                                      "plugin_meta_tests": "passed", "pr_tooling_tests": "passed"})

    def test_verdict_en_anglais(self):
        """verdict.json in English (names.yaml, family fork_verdict): keys, the ci domain, the details' keys; a red
        verdict names its failed step by its English label; a French metric id of the task is written in English."""
        etats = dict({e: "succes" for e in ETAPES}, fuzzing="echec")
        v = self.executer(etats, dict(JOBS_OK, fuzzing={"result": "failure"}), rapport_ab(), "metric: debit_compression_n6\n")
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Fuzzing (x86-64)", "compression_throughput_n6"))
        self.assertEqual(set(v), CLES_VERDICT | {"failed_step"})
        self.assertEqual(set(v["details"]), {"metric_origin", "manifest", "task", "base", "head", "jobs", "gains_by_metric",
                                             "sign_test", "method", "machine", "repetitions", "judge_code"})
        self.assertEqual(v["steps"]["fuzzing"], "failed")
        self.assertEqual(set(v["judge"]), {"version", "common", "project", "plugin", "seed", "outputs_compared", "suspicious_constructs"})
        self.assertEqual(set(v["measurements"]["A"]), {"compression_throughput_n6"})
        sans_rapport = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, None)
        self.assertEqual(set(sans_rapport["measurements"]["B"]), set(METRIQUES_EN))

    def test_premiere_etape_en_echec_explicite(self):
        etats = {e: "succes" for e in ETAPES}
        etats["differentiel_x86_64"] = "echec"
        del etats["compilation_arm64"]  # job ARM64 sans résultat, mais pas en échec explicite
        del etats["differentiel_arm64"]
        jobs = dict(JOBS_OK, **{"compilation-et-tests": {"result": "failure"}})
        v = self.executer(etats, jobs, rapport_ab())
        self.assertEqual(v["ci"], "red")
        self.assertEqual(v["failed_step"], "Differential tests and fingerprints (x86-64)")
        self.assertEqual((v["steps"]["build_x86_64"], v["steps"]["build_arm64"]), ("passed (job failure)", "absent"))

    def test_job_echoue_sans_fichier_etat(self):
        etats = {e: "succes" for e in ETAPES if e != "fuzzing"}
        v = self.executer(etats, dict(JOBS_OK, fuzzing={"result": "cancelled"}), rapport_ab())
        self.assertEqual(v["ci"], "red")
        self.assertEqual(v["failed_step"], "Fuzzing (x86-64) (no result)")

    def test_etat_succes_mais_job_en_echec(self):
        # Le code de la PR ne peut pas rendre la CI verte en écrivant « succes » : le résultat du job prime.
        v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, **{"judge": {"result": "failure"}}), rapport_ab())
        self.assertEqual(v["ci"], "red")

    def test_juge_commun_et_constructions_suspectes(self):
        rapport = rapport_ab()
        rapport["judge"] = {"version": 3, "common": "judge-v4", "project": "miniz", "plugin": "c0" * 32, "seed": "ab" * 16,
                            "verification": {"outputs_compared": 914, "sortie_compressee": "identique"},
                            "suspicious_constructs": [{"type": "instruction", "detail": "syscall: 1 occurrence(s)"}]}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, "metric: compression_throughput_n6\n", nom_rapport="judge.json")
        self.assertEqual(v["ci"], "green")
        self.assertEqual(v["steps"]["common_judge"], "passed")
        self.assertEqual((v["judge"]["version"], v["judge"]["common"], v["judge"]["project"], v["judge"]["plugin"]), (3, "judge-v4", "miniz", "c0" * 32))
        self.assertEqual(v["judge"]["outputs_compared"], 914)
        self.assertEqual(v["judge"]["suspicious_constructs"], [{"type": "instruction", "detail": "syscall: 1 occurrence(s)"}])
        self.assertAlmostEqual(v["gain"], 0.03)

    def test_champs_du_juge_valides(self):
        rapport = rapport_ab()
        rapport["judge"] = {"version": 3, "common": "judge-v4\n::error::x", "plugin": "pas une empreinte", "project": "x" * 100,
                            "verification": {"outputs_compared": 1}, "suspicious_constructs": []}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, nom_rapport="judge.json")
        self.assertEqual((v["judge"]["common"], v["judge"]["plugin"], len(v["judge"]["project"])), (None, None, 40))
        # judge.json is judge-v4's: « judge-vN » only; juge-v1 to juge-v3 wrote juge.json, in French.
        for commun, attendu in (("judge-v5", "judge-v5"), ("juge-v3", None), ("judge-v12345", None)):
            rapport["judge"]["common"] = commun
            self.assertEqual(self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport)["judge"]["common"], attendu, commun)

    def test_rapport_francais_jamais_lu(self):
        """A juge.json of juge-v3 (French keys) is not judge-v4's report: neither under its name nor as judge.json."""
        francais = {"metriques": {"compression_throughput_n6": {"gain": 0.5, "au_dela_du_bruit": True}},
                    "juge": {"version": 3, "commun": "juge-v3", "verification": {"sorties_comparees": 914}, "constructions_suspectes": []}}
        for nom in ("juge.json", "judge.json"):
            v = self.verdict_avec([("etat-manifeste/tache.yaml", "metric: compression_throughput_n6\n"),
                                   (f"judge/{nom}", json.dumps(francais))], JOBS_OK)
            self.assertEqual((v["ci"], v["gain"], v["judge"]), ("red", None, None), nom)

    def test_juge_commun_refuse(self):
        """Le job judge (judge.yml) réussit même quand le juge refuse B : c'est son code qui rend la CI rouge."""
        for code in ("1", "2"):
            with self.subTest(code=code):
                jobs = dict(JOBS_OK, judge={"result": "success", "outputs": {"code": code}})
                v = self.executer({e: "succes" for e in ETAPES}, jobs, rapport_ab(), code="0")
                self.assertEqual(v["ci"], "red")
                self.assertEqual(v["failed_step"], "Common judge (checking from the outside and measurements)")
                self.assertEqual(v["details"]["judge_code"], code)

    def test_juge_commun_sans_code(self):
        # Greffon en échec : le job judge est sauté, sans sortie « code ».
        etats = {e: "succes" for e in ETAPES}
        etats["greffon_juge"] = "echec"
        jobs = dict(JOBS_OK, greffon={"result": "failure"}, judge={"result": "skipped", "outputs": {}})
        v = self.executer(etats, jobs, rapport_ab())
        self.assertEqual(v["ci"], "red")
        self.assertEqual(v["failed_step"], "Common judge plugin")
        self.assertEqual(v["steps"]["common_judge"], "absent")

    def test_code_du_juge_hors_ci(self):
        """Simulation locale (sans --jobs) : le fichier code de l'artefact « judge »."""
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), code="0")
        self.assertEqual(v["ci"], "green")
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), code="1")
        self.assertEqual(v["ci"], "red")

    def test_un_etat_juge_isole_ne_suffit_pas(self):
        """Un fichier juge_isole.txt « succes » ne remplace pas le code du juge commun."""
        etats = dict({e: "succes" for e in ETAPES}, juge_isole="succes")
        v = self.executer(etats, dict(JOBS_OK, judge={"result": "success", "outputs": {"code": "1"}}), rapport_ab())
        self.assertEqual(v["ci"], "red")
        v = self.executer(etats, dict(JOBS_OK, judge={"result": "success", "outputs": {}}), rapport_ab())
        self.assertEqual(v["steps"]["common_judge"], "absent")  # en CI, sans code : sans résultat
        self.assertEqual(v["ci"], "red")
        etats["juge_isole"] = "echec"
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "red")  # un « echec » l'emporte toujours

    def test_plus_de_juge_ancien(self):
        """The old isolated judge's step is gone with juge-v3: its job and its state (the juge-v3 transition's) are not
        steps of this verdict, and the job « juge » (juge-v3's) is not the common judge's."""
        etats = dict({e: "succes" for e in ETAPES}, juge_ancien="echec")
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "green")
        self.assertNotIn("juge_ancien", v["steps"])
        jobs = {k: w for k, w in JOBS_OK.items() if k != "judge"}
        v = self.executer({e: "succes" for e in ETAPES}, dict(jobs, juge={"result": "success", "outputs": {"code": "0"}}), rapport_ab())
        self.assertEqual((v["ci"], v["failed_step"]), ("red", "Common judge (checking from the outside and measurements) (no result)"))

    def test_jobs_qui_executent_la_pr_jugent_par_leur_resultat(self):
        """meta-juge et outillage-pr exécutent du code de la PR : un fichier d'état « succes » ne compte pas,
        seul le résultat du job compte."""
        for job, libelle in (("meta-juge", "Plugin meta-tests against the common judge"),
                             ("outillage-pr", "Tests of the PR's CI tooling")):
            with self.subTest(job=job):
                v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, **{job: {"result": "failure"}}), rapport_ab())
                self.assertEqual((v["ci"], v["failed_step"]), ("red", libelle))
        etats = {e: "succes" for e in ETAPES if e not in ("meta_juge", "outillage_pr")}
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "green")  # sans fichier d'état : le résultat du job suffit

    def test_donnees_lues_dans_leur_artefact(self):
        """La tâche (métrique) n'est lue que dans l'artefact de son job."""
        with tempfile.TemporaryDirectory() as d:
            artefacts, propres = ecrire_etats(d, {e: "succes" for e in ETAPES})
            fichiers = (("etat-aaa", "tache.yaml", "metric: ratio_n6\n"),
                        ("etat-manifeste", "tache.yaml", "metric: compression_throughput_n6\n"),
                        ("judge", "judge.json", json.dumps(rapport_ab())))
            for dossier, nom, contenu in fichiers:
                os.makedirs(os.path.join(artefacts, dossier), exist_ok=True)
                with open(os.path.join(artefacts, dossier, nom), "w") as f:
                    f.write(contenu)
            with open(os.path.join(d, "jobs.json"), "w") as f:
                json.dump(JOBS_OK, f)
            subprocess.run([sys.executable, VERDICT, "--artefacts", artefacts, "--etats", propres, "--jobs", os.path.join(d, "jobs.json"),
                            "--base", BASE, "--sortie", os.path.join(d, "v.json")], check=True, capture_output=True)
            with open(os.path.join(d, "v.json")) as f:
                v = json.load(f)
        self.assertEqual((v["ci"], v["metric"]), ("green", "compression_throughput_n6"))

    def verdict_avec(self, fichiers, jobs, etats=None, liens=()):
        """Verdict sur des artefacts : les états là où leurs jobs les déposent (tous « succes » par défaut), puis des
        fichiers aux chemins donnés, et des liens symboliques aux chemins donnés vers un fichier hors des artefacts."""
        with tempfile.TemporaryDirectory() as d:
            artefacts, propres = ecrire_etats(d, {e: "succes" for e in ETAPES} if etats is None else etats)
            for i, (chemin, contenu) in enumerate(list(fichiers) + list(liens)):
                cible = os.path.join(artefacts, chemin) if i < len(fichiers) else os.path.join(d, f"cible-{i}")
                os.makedirs(os.path.dirname(os.path.join(artefacts, chemin)), exist_ok=True)
                with open(cible, "w") as f:
                    f.write(contenu)
                if cible != os.path.join(artefacts, chemin):
                    os.symlink(cible, os.path.join(artefacts, chemin))
            commande = [sys.executable, VERDICT, "--artefacts", artefacts, "--etats", propres, "--sortie", os.path.join(d, "v.json")]
            if jobs is not None:
                with open(os.path.join(d, "jobs.json"), "w") as f:
                    json.dump(jobs, f)
                commande += ["--jobs", os.path.join(d, "jobs.json"), "--base", BASE]
            subprocess.run(commande, check=True, capture_output=True)
            with open(os.path.join(d, "v.json")) as f:
                return json.load(f)

    def test_chaque_fichier_lu_a_la_racine_de_son_artefact(self):
        """Chaque fichier n'est lu qu'à la racine de l'artefact du job qui le produit : déposé dans un autre artefact
        (même rangé avant) ou dans un sous-dossier du bon artefact (rangé avant la racine), il est ignoré."""
        faux_tache = "metric: ratio_n6\n"
        fichiers = [("etat-manifeste/tache.yaml", "metric: compression_throughput_n6\n"),
                    ("judge/judge.json", json.dumps(rapport_ab())),
                    ("etat-manifeste/etats/tache.yaml", faux_tache), ("etat-aaa/tache.yaml", faux_tache),
                    ("etat-manifeste/etats/CONTRIBUTION.yaml", MANIFESTE_FR), ("etat-aaa/CONTRIBUTION.yaml", MANIFESTE_FR)]
        v = self.verdict_avec(fichiers, JOBS_OK)
        self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", "compression_throughput_n6", 0.03))
        self.assertEqual(v["details"]["manifest"], "absent")
        # Seulement dans un sous-dossier ou un autre artefact : la copie de la tâche manque, rouge (jamais la fausse).
        v = self.verdict_avec([f for f in fichiers if f[0] != "etat-manifeste/tache.yaml"], JOBS_OK)
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))

    def test_aucun_rapport_cherche_dans_les_artefacts(self):
        """Le rapport vient de --ab ou de judge.json à la racine de l'artefact « judge » ; hors CI non plus, un ab.json
        ou un judge.json déposé dans un autre artefact (ou un sous-dossier de « judge ») n'est jamais lu."""
        faux = json.dumps(rapport_ab(gain_n6=0.5))
        fichiers = [("etat-manifeste/tache.yaml", "metric: compression_throughput_n6\n"), ("etat-aaa/ab.json", faux),
                    ("x/ab.json", faux), ("etat-manifeste/ab.json", faux), ("etat-aaa/judge.json", faux),
                    ("judge/etats/judge.json", faux), ("judge/ab.json", faux), ("juge/judge.json", faux), ("juge/juge.json", faux)]
        for jobs in (None, JOBS_OK):
            with self.subTest(ci=jobs is not None):
                v = self.verdict_avec(fichiers, jobs)
                self.assertEqual((v["ci"], v["metric"], v["gain"], v["judge"]), ("red", "compression_throughput_n6", None, None))
                self.assertIsNone(v["measurements"]["B"]["compression_throughput_n6"])
        v = self.verdict_avec(fichiers + [("judge/judge.json", json.dumps(rapport_ab())), ("judge/code", "0\n")], None)
        self.assertEqual((v["ci"], v["gain"]), ("green", 0.03))

    def test_etat_lu_seulement_dans_le_dossier_de_son_job(self):
        """Chaque <etape>.txt n'est lu que dans le dossier d'état du job qui l'écrit : un « succes » déposé dans
        « judge », dans un autre artefact, dans le dossier d'un autre job, à la racine ou dans un sous-dossier du bon
        artefact ne remplace pas un état manquant (rouge, sans résultat) ; un état qui est un lien symbolique non plus."""
        base = [("etat-manifeste/tache.yaml", TACHE_SANS_METRIQUE), ("judge/judge.json", json.dumps(rapport_ab()))]
        self.assertEqual(self.verdict_avec(base, JOBS_OK)["ci"], "green")  # le parcours honnête
        for manquante, proprietaire in DOSSIER_ETAT.items():
            autre = "etat-manifeste/etats" if proprietaire != "etat-manifeste/etats" else "etat-fuzzing"
            dossiers = ["judge", "etat-evil", "etat-evil/etats", "x/etats", "etat-juge-ancien/etats", autre, proprietaire + "/sous"]
            dossiers += [proprietaire.split("/")[0]] if "/" in proprietaire else []
            etats = {e: "succes" for e in ETAPES if e != manquante}
            cle = next(k for e, k in zip(ETAPES_VERDICT, CLES_ETAPES) if e == manquante)
            with self.subTest(manquante=manquante):
                v = self.verdict_avec(base + [(f"{d}/{manquante}.txt", "succes\n") for d in dossiers], JOBS_OK, etats)
                self.assertEqual((v["ci"], v["steps"][cle]), ("red", "absent"))
                v = self.verdict_avec(base, JOBS_OK, etats, liens=[(f"{proprietaire}/{manquante}.txt", "succes\n")])
                self.assertEqual((v["ci"], v["steps"][cle]), ("red", "absent"))
        # « juges » et « amorcage », écrits par chaque job, ne se lisent pas non plus hors des dossiers d'état des jobs.
        v = self.verdict_avec(base + [("judge/amorcage.txt", "oui\n"), ("etat-evil/amorcage.txt", "oui\n"),
                                      ("etat-juge-ancien/etats/amorcage.txt", "oui\n")], JOBS_OK)
        self.assertFalse(v["bootstrap"])
        v = self.verdict_avec(base + [("etat-fuzzing/amorcage.txt", "oui\n")], JOBS_OK)
        self.assertTrue(v["bootstrap"])

    def test_lien_symbolique_jamais_lu(self):
        """La copie de la tâche et le rapport du juge commun ne sont jamais lus à travers un lien symbolique, même à leur
        place et vers un contenu valide."""
        honnete = [("etat-manifeste/tache.yaml", "metric: compression_throughput_n6\n"), ("judge/judge.json", json.dumps(rapport_ab()))]
        v = self.verdict_avec(honnete, JOBS_OK)
        self.assertEqual((v["ci"], v["metric"]), ("green", "compression_throughput_n6"))
        for i, (chemin, contenu) in enumerate(honnete):
            with self.subTest(lien=chemin):
                v = self.verdict_avec(honnete[:i] + honnete[i + 1:], JOBS_OK, liens=[(chemin, contenu)])
                self.assertEqual(v["ci"], "red")
                self.assertEqual(v["failed_step"], "Manifest and size" if "tache" in chemin else
                                 "Common judge (checking from the outside and measurements)")

    def test_base_juge_publiee(self):
        """verdict.json publie le commit A du juge commun et la règle qui l'a choisi (revue adverse de miniz-0032), en
        anglais (names.yaml : judge_base, rule, start ; la règle base_de_la_pr du job greffon y est pr_base)."""
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "green")
        self.assertEqual(v["judge_base"], {"commit": BASE, "rule": "pr_base", "start": DEPART, "base": BASE})
        self.assertIsNone(self.executer({e: "succes" for e in ETAPES}, None, rapport_ab())["judge_base"])

    def test_jamais_vert_sans_a_verifiable(self):
        """Règle de refus, règle inconnue, règle de juge-v2 (point_de_depart, introduction : plus jamais acceptées),
        commit ou point de départ illisible, A qui n'est pas la base du verdict : rouge, même si tous les jobs et états
        disent succès (secondes revues adverses de miniz-0032, M-1)."""
        autre = "e" * 40
        for sorties, base in (({"base_juge": BASE, "regle": "refus_rebase", "depart": DEPART}, BASE),
                              ({"base_juge": BASE, "regle": "refus_point_de_depart", "depart": DEPART}, BASE),
                              ({"base_juge": BASE, "regle": "base", "depart": DEPART}, BASE),
                              ({"base_juge": BASE, "regle": "pr_base", "depart": DEPART}, BASE),
                              ({"base_juge": DEPART, "regle": "point_de_depart", "depart": DEPART}, BASE),
                              ({"base_juge": BASE, "regle": "introduction", "depart": DEPART}, BASE),
                              ({"base_juge": "HEAD", "regle": "base_de_la_pr", "depart": DEPART}, BASE),
                              ({"base_juge": autre, "regle": "base_de_la_pr", "depart": DEPART}, BASE),
                              ({"base_juge": DEPART, "regle": "base_de_la_pr", "depart": DEPART}, BASE),
                              ({"base_juge": BASE, "regle": "base_de_la_pr"}, BASE),
                              ({"base_juge": BASE, "regle": "base_de_la_pr", "depart": "HEAD"}, BASE),
                              ({"base_juge": BASE, "regle": "base_de_la_pr", "depart": DEPART}, None), ({}, BASE)):
            with self.subTest(sorties=sorties, base=base):
                v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, greffon={"result": "success", "outputs": sorties}),
                                  rapport_ab(), base=base)
                self.assertEqual((v["ci"], v["failed_step"]), ("red", "Common judge plugin"))
        # L'amorçage ne rend plus acceptable la règle d'introduction de juge-v2.
        jobs = dict(JOBS_OK, greffon={"result": "success", "outputs": {"base_juge": autre, "regle": "introduction", "depart": DEPART}})
        v = self.executer(dict({e: "succes" for e in ETAPES}, amorcage="oui"), jobs, rapport_ab())
        self.assertEqual((v["ci"], v["bootstrap"], v["judge_base"]["rule"]), ("red", True, None))

    def test_code_0_sans_jugement_rouge(self):
        """M-2 : un code 0 sans section judge, ou sans aucune sortie comparée, n'est pas un jugement."""
        sans_section = rapport_ab()
        del sans_section["judge"]
        zero = rapport_ab()
        zero["judge"]["verification"]["outputs_compared"] = 0
        for rapport in (sans_section, zero):
            with self.subTest(juge=rapport.get("judge")):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, "metric: compression_throughput_n6\n")
                self.assertEqual(v["ci"], "red")
                self.assertEqual(v["failed_step"], "Common judge (checking from the outside and measurements)")
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, None)
        self.assertEqual((v["ci"], v["judge"]), ("red", None))

    def test_sans_metrique_designee_gain_null(self):
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), "type: test\nmetric: null\n")
        self.assertIsNone(v["gain"])
        self.assertIsNone(v["metric"])
        self.assertFalse(v["beyond_noise"])

    def test_degradations(self):
        ab = rapport_ab(degradation_n1=True)
        ab["instructions"]["instructions_n1"] = {"A": 100, "B": 105, "gain": -0.05, "beyond_noise": True}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, ab, "metric: compression_throughput_n6\n")
        self.assertIn("compression_throughput_n1", v["degradations"])
        self.assertIn("instructions_n1", v["degradations"])
        self.assertNotIn("instructions_n6", v["degradations"])

    def test_amorcage_signale(self):
        etats = {e: "succes" for e in ETAPES}
        etats["amorcage"] = "oui"
        v = self.executer(etats, JOBS_OK, rapport_ab(), "metric: compression_throughput_n6\n")
        self.assertEqual(v["ci"], "green")
        self.assertTrue(v["bootstrap"])
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab())
        self.assertFalse(v["bootstrap"])

    def test_juges_en_echec_rend_rouge(self):
        etats = {e: "succes" for e in ETAPES}
        etats["juges"] = "echec"
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "red")
        self.assertEqual(v["failed_step"], "Judges (base without bee/)")


def logique_juges(texte, marqueur_debut, marqueur_fin):
    return texte.split(marqueur_debut, 1)[1].split(marqueur_fin, 1)[0]


class Juges(unittest.TestCase):
    """bee/ci/juges.sh et sa copie dans bee-ci.yml : amorçage seulement pour le commit épinglé ; le greffon de la PR
    n'est jamais pris hors amorçage (l'introduction du greffon sous juge-v2, miniz-0032, n'existe plus)."""

    def preparer(self, d, base_avec_bee, pr_avec_bee=True):
        base, pr = os.path.join(d, "base"), os.path.join(d, "pr")
        for racine, avec in ((base, base_avec_bee), (pr, pr_avec_bee)):
            os.makedirs(racine)
            if avec:
                os.makedirs(os.path.join(racine, "bee", "ci"))
                with open(os.path.join(racine, "bee", "ci", "etape.sh"), "w") as f:
                    f.write("# " + racine + "\n")
                # Le workflow est lui aussi un juge : il arrive avec bee/ et part avec lui à l'amorçage.
                os.makedirs(os.path.join(racine, ".github", "workflows"))
                with open(os.path.join(racine, ".github", "workflows", "bee-ci.yml"), "w") as f:
                    f.write("# workflow de " + racine + "\n")
        return base, pr

    def lancer(self, d, base, pr, base_sha):
        env = dict(os.environ, ETATS=os.path.join(d, "etats"))
        return subprocess.run(["bash", JUGES, base, pr, base_sha], capture_output=True, text=True, env=env)

    def lire(self, d, nom):
        try:
            with open(os.path.join(d, "etats", nom)) as f:
                return f.read().strip()
        except OSError:
            return None

    def test_base_avec_juges(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=True)
            r = self.lancer(d, base, pr, "0" * 40)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.lire(d, "juges.txt"), "succes")
            self.assertEqual(self.lire(d, "greffon.txt"), "base")
            self.assertIsNone(self.lire(d, "amorcage.txt"))
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(base, f.read())  # les juges de la base sont gardés, pas ceux de la PR

    def test_amorcage_commit_epingle(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=False)
            r = self.lancer(d, base, pr, COMMIT_AMORCAGE)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("::warning::BOOTSTRAP:", r.stdout)
            self.assertEqual(self.lire(d, "amorcage.txt"), "oui")
            self.assertEqual(self.lire(d, "juges.txt"), "succes")
            self.assertEqual(self.lire(d, "greffon.txt"), "pr")
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(pr, f.read())  # juges copiés depuis la PR
            with open(os.path.join(base, ".github", "workflows", "bee-ci.yml")) as f:
                self.assertIn(pr, f.read())  # le workflow aussi

    def ajouter(self, racine, nom, dossier="juge"):
        os.makedirs(os.path.join(racine, "bee", dossier), exist_ok=True)
        with open(os.path.join(racine, "bee", dossier, nom), "w") as f:
            f.write("# " + nom + " de " + racine + "\n")

    def test_plus_d_introduction_du_greffon(self):
        """Base avec l'ancien juge isolé et sans greffon, PR qui apporte un greffon (la règle de miniz-0032, jugée sous
        juge-v2) : les juges et le greffon restent ceux de la base, sans amorçage."""
        for dossier, nom in (("juge", "projet.py"), ("judge", "project.py")):
            with self.subTest(greffon=nom), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=True)
                self.ajouter(base, "juge.py")
                self.ajouter(pr, nom, dossier)
                r = self.lancer(d, base, pr, "0" * 40)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("::warning::", r.stdout)
                self.assertIsNone(self.lire(d, "amorcage.txt"))
                self.assertEqual(self.lire(d, "greffon.txt"), "base")
                self.assertFalse(os.path.exists(os.path.join(base, "bee", dossier, nom)))

    def test_greffon_de_la_base_garde(self):
        """Dès que la base a un greffon, celui de la PR n'est jamais pris, même si la base garde un juge.py."""
        for ancien_dans_la_base, (dossier, nom) in ((False, ("judge", "project.py")), (True, ("judge", "project.py")),
                                                    (False, ("juge", "projet.py"))):
            with self.subTest(ancien_dans_la_base=ancien_dans_la_base, greffon=nom), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=True)
                self.ajouter(base, nom, dossier)
                if ancien_dans_la_base:
                    self.ajouter(base, "juge.py")
                self.ajouter(pr, nom, dossier)
                r = self.lancer(d, base, pr, "0" * 40)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.lire(d, "greffon.txt"), "base")
                self.assertIsNone(self.lire(d, "amorcage.txt"))

    def test_juge_isole_de_la_pr_ignore(self):
        """L'ancienne règle d'introduction du juge isolé n'existe plus : une PR qui apporte un bee/juge/juge.py
        dans une base qui n'en a plus (après miniz-0032) ne se juge pas elle-même."""
        for greffon_dans_la_pr in (False, True):
            with self.subTest(greffon_dans_la_pr=greffon_dans_la_pr), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=True)
                self.ajouter(base, "projet.py")
                self.ajouter(pr, "juge.py")
                if greffon_dans_la_pr:
                    self.ajouter(pr, "projet.py")
                r = self.lancer(d, base, pr, "0" * 40)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIsNone(self.lire(d, "amorcage.txt"))
                self.assertEqual(self.lire(d, "greffon.txt"), "base")
                self.assertFalse(os.path.exists(os.path.join(base, "bee", "juge", "juge.py")))
                with open(os.path.join(base, "bee", "juge", "projet.py")) as f:
                    self.assertIn(base, f.read())

    def test_autre_base_sans_juges_echoue(self):
        for sha in ("1" * 40, COMMIT_AMORCAGE[:-1] + "0", COMMIT_AMORCAGE[:12], COMMIT_AMORCAGE.upper(), ""):
            with self.subTest(sha=sha), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=False)
                r = self.lancer(d, base, pr, sha)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(self.lire(d, "juges.txt"), "echec")
                self.assertIsNone(self.lire(d, "amorcage.txt"))
                self.assertFalse(os.path.exists(os.path.join(base, "bee")))

    def test_amorcage_sans_juges_dans_la_pr_echoue(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=False, pr_avec_bee=False)
            r = self.lancer(d, base, pr, COMMIT_AMORCAGE)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(self.lire(d, "juges.txt"), "echec")

    def test_copie_du_workflow_identique(self):
        with open(JUGES, encoding="utf-8") as f:
            script = logique_juges(f.read(), "# --- start of the logic copied into bee-ci.yml ---\n",
                                   "# --- end of the logic copied into bee-ci.yml ---")
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        self.assertEqual(workflow["env"]["BEE_JUGES"], script)
        self.assertEqual(workflow["env"]["BEE_COMMIT_AMORCAGE"], COMMIT_AMORCAGE)
        for nom, job in workflow["jobs"].items():
            if "uses" in job:  # workflow réutilisable (juge commun) : il extrait lui-même ce qu'il juge
                continue
            if not any("base" in str(e.get("with", {}).get("path", "")) or "base/" in e.get("run", "") for e in job["steps"]):
                self.assertEqual(nom, "outillage-pr")  # le seul job sans la base : il ne lance que les tests de la PR
                continue
            etapes = [e.get("name", "") for e in job["steps"]]
            self.assertTrue(any(n.startswith("Judges") for n in etapes), f"job {nom} has no Judges step")
            # No step uses base/bee before the Judges step.
            i_juges = next(i for i, n in enumerate(etapes) if n.startswith("Judges"))
            for e in job["steps"][:i_juges]:
                self.assertNotIn("base/bee", e.get("run", ""), f"job {nom}: base/bee used before Judges")

    def charger_workflow(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_juge_commun_epingle(self):
        """The judge job calls the registry's judge.yml at the commit JUGE_COMMUN_SHA (judge-v4; never a tag nor a branch,
        which move), with its English inputs, and each checkout of the common judge (isoler.sh, image, meta-tests,
        report.py) is at that commit. Transition: the juge-v3 job, juge.yml at JUGE_V3_SHA, only for a base that pins it."""
        workflow = self.charger_workflow()
        sha, v3 = workflow["env"]["JUGE_COMMUN_SHA"], workflow["env"]["JUGE_V3_SHA"]
        self.assertEqual(sha, "7623c1288482673f48171bb7ed921f447ac272d9")
        self.assertEqual(v3, "3b21e97a89c25ddcfbb3c0d28d1086b801c991bc")
        self.assertNotIn("JUGE_V2_SHA", workflow["env"])
        self.assertNotIn("juge-v2", workflow["jobs"])
        juge = workflow["jobs"]["judge"]
        self.assertEqual(juge["uses"], f"Bee-ruche/registre/.github/workflows/judge.yml@{sha}")
        # The event's base and head (judge.yml refuses any other), under judge-v4's English input names.
        self.assertEqual(juge["with"], {"history": "2948eebafc5b9f1c69bebed80333e403a09bd62d",
                                        "base_sha": "${{ github.event.pull_request.base.sha }}",
                                        "head_sha": "${{ github.event.pull_request.head.sha }}",
                                        "options": "sortie_compressee=${{ needs.manifeste.outputs.sortie_compressee || 'identique' }}"})
        self.assertEqual(juge["if"], "always() && needs.greffon.result == 'success'")  # both contracts: old and new version
        transition = workflow["jobs"]["juge-v3"]
        self.assertEqual(transition["uses"], f"Bee-ruche/registre/.github/workflows/juge.yml@{v3}")
        self.assertIn("needs.greffon.outputs.contrat == 'juge-v3'", transition["if"])
        self.assertEqual(transition["with"], {"historique": juge["with"]["history"], "base_sha": juge["with"]["base_sha"],
                                              "tete_sha": juge["with"]["head_sha"], "options": juge["with"]["options"]})
        self.assertEqual(workflow["jobs"]["juge-ancien"]["if"], "always() && needs.greffon.outputs.contrat == 'juge-v3'")
        with open(WORKFLOW, encoding="utf-8") as f:
            texte = f.read()
        self.assertIn(f'  JUGE_COMMUN_SHA: "{sha}"  # judge-v4\n', texte)
        self.assertIn(f'  JUGE_V3_SHA: "{v3}"  # juge-v3\n', texte)
        self.assertIn(f"judge.yml@{sha} # judge-v4\n", texte)
        self.assertIn(f"juge.yml@{v3} # juge-v3\n", texte)
        self.assertNotIn("outils/juge", texte.replace("juge-v3/outils/juge/rapport.py", ""))
        # Le commit du corpus est déclaré à judge.yml (history), qui le récupère avant la PR : celui du greffon en est.
        with open(os.path.join(os.path.dirname(ICI), "judge", "project.py"), encoding="utf-8") as f:
            commit = re.search(r'^COMMIT_CORPUS = "([0-9a-f]{40})"$', f.read(), re.M).group(1)
        self.assertIn(commit, juge["with"]["history"].split())
        extractions = [e for job in workflow["jobs"].values() for e in job.get("steps", [])
                       if e.get("with", {}).get("path") == "juge-commun"]
        self.assertEqual(len(extractions), 4)  # build and tests, fuzzing, meta-tests, verdict (report.py)
        for e in extractions:
            self.assertEqual((e["with"]["repository"], e["with"]["ref"]), ("${{ env.REGISTRE }}", "${{ env.JUGE_COMMUN_SHA }}"))
        anciens = [e for job in workflow["jobs"].values() for e in job.get("steps", []) if e.get("with", {}).get("path") == "juge-v3"]
        self.assertEqual([(e["with"]["ref"], e["if"]) for e in anciens], [("${{ env.JUGE_V3_SHA }}", "needs.greffon.outputs.contrat == 'juge-v3'")])
        self.assertEqual(workflow["env"]["REGISTRE"], "Bee-ruche/registre")
        self.assertIn("juge-commun/tools/judge/judge.py --tooling \"$greffon\" --image-only", workflow["env"]["BEE_IMAGE"])
        self.assertIn("ISOLER=$GITHUB_WORKSPACE/juge-commun/tools/judge/isoler.sh", workflow["env"]["BEE_IMAGE"])
        verdict = workflow["jobs"]["verdict"]
        self.assertEqual(set(verdict["needs"]), set(workflow["jobs"]) - {"verdict"})

    def test_meta_tests_du_greffon_anglais(self):
        """meta-juge runs the PR's bee/judge/test_judge.py against judge-v4's tools/judge when the PR modifies the plugin
        (either path) or this workflow."""
        etape = self.charger_workflow()["jobs"]["meta-juge"]["steps"][-1]["run"]
        self.assertIn("-- bee/judge bee/juge .github/workflows/bee-ci.yml", etape)
        self.assertIn('BEE_COMMON_JUDGE="$GITHUB_WORKSPACE/juge-commun/tools/judge" python3 pr/bee/judge/test_judge.py', etape)
        self.assertIn("BEE_JUDGE_INTEGRATION=1", etape)

    def test_jobs_qui_executent_la_pr_isoles(self):
        """meta-juge et outillage-pr exécutent du code de la PR sur la machine de CI : lecture seule, aucun
        identifiant conservé, ni artefact ni sortie ; leur résultat est un « needs » du verdict."""
        workflow = self.charger_workflow()
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        for nom in ("meta-juge", "outillage-pr"):
            job = workflow["jobs"][nom]
            self.assertEqual(job.get("permissions"), {"contents": "read"}, nom)
            self.assertNotIn("outputs", job, nom)
            self.assertIn(nom, workflow["jobs"]["verdict"]["needs"])
            for e in job["steps"]:
                self.assertNotIn("upload-artifact", e.get("uses", ""), nom)
                self.assertNotIn("secrets.", json.dumps(e), nom)
                if "actions/checkout" in e.get("uses", ""):
                    self.assertIs(e["with"]["persist-credentials"], False, nom)
        etape = workflow["jobs"]["outillage-pr"]["steps"][-1]["run"]
        self.assertIn("-- bee/ci .github/workflows/bee-ci.yml", etape)
        self.assertIn("python3 pr/bee/ci/test_verdict.py", etape)

    def test_declenche_seulement_pour_les_pr_vers_master(self):
        workflow = self.charger_workflow()
        declencheurs = workflow.get("on", workflow.get(True))  # PyYAML lit la clé « on » comme True
        self.assertEqual(declencheurs, {"pull_request": {"branches": ["master"]}})

    def test_greffon_dans_ce_que_la_regle_rebasez_compare(self):
        """La règle « rebasez » du job greffon compare bee/ et miniz* entre le point de départ et la base : tout
        ce que le greffon lit dans A doit y être (SOURCES et BASE_HEADERS dans miniz*, TOOLING, BUILD
        et le corpus dans bee/), sinon elle ne suit plus."""
        import ast
        import fnmatch
        with open(os.path.join(os.path.dirname(ICI), "judge", "project.py"), encoding="utf-8") as f:
            arbre = ast.parse(f.read())
        classe = next(n for n in arbre.body if isinstance(n, ast.ClassDef) and n.name == "Project")
        valeurs = {c.targets[0].id: ast.literal_eval(c.value) for c in classe.body
                   if isinstance(c, ast.Assign) and isinstance(c.targets[0], ast.Name) and c.targets[0].id in
                   ("SOURCES", "REQUIRED_SOURCES", "BASE_HEADERS", "TOOLING", "BUILD")}
        self.assertEqual(len(valeurs), 5)
        for cle in ("SOURCES", "REQUIRED_SOURCES", "BASE_HEADERS"):
            for motif in valeurs[cle]:
                self.assertTrue(fnmatch.fnmatchcase(motif, "miniz*") and "/" not in motif, (cle, motif))
        for chemin in list(valeurs["TOOLING"]) + [valeurs["BUILD"]]:
            self.assertTrue(chemin.startswith("bee/") and ".." not in chemin, chemin)
        chaines = {n.value for n in ast.walk(classe) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue({"bee/corpus/generer.py", "bee/corpus/donnees"} <= chaines)
        etape = next(e for e in self.charger_workflow()["jobs"]["greffon"]["steps"] if e.get("id") == "greffon")
        self.assertIn("git -C pr diff --quiet \"$depart\" \"$BASE_SHA\" -- bee 'miniz*'", etape["run"])

    def test_tests_unitaires_sans_garde(self):
        """Revue adverse de miniz-0033 : un test de l'outillage ne se saute jamais sans bruit (if [ -f … ])."""
        workflow = self.charger_workflow()
        etape = next(e for e in workflow["jobs"]["manifeste"]["steps"] if e.get("name", "").startswith("Unit tests"))
        self.assertNotIn("if [", etape["run"])
        for test in ("base/bee/bench/test_ab.py", "base/bee/ci/test_verdict.py", "base/bee/bench/test_profil.py"):
            self.assertIn(f"python3 {test}\n", etape["run"])

    def test_copie_du_workflow_se_comporte_comme_le_script(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        for sha, attendu in ((COMMIT_AMORCAGE, 0), ("2" * 40, 1)):
            with self.subTest(sha=sha), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=False)
                env = dict(os.environ, BEE_JUGES=workflow["env"]["BEE_JUGES"],
                           BEE_COMMIT_AMORCAGE=workflow["env"]["BEE_COMMIT_AMORCAGE"])
                r = subprocess.run(["bash", "-e", "-c", f'export base="{base}" pr="{pr}" base_sha="{sha}" etats="{d}/etats"\neval "$BEE_JUGES"'],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, attendu, r.stdout + r.stderr)


class Greffon(unittest.TestCase):
    """Étape « Commit of the plugin and of A » du job greffon de bee-ci.yml, sur de petits dépôts git : le juge commun
    ne lit jamais le greffon dans la PR ; il juge la base de la PR, épinglée à judge-v4 ou, en transition, à juge-v3."""

    def setUp(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        etape = next(e for e in workflow["jobs"]["greffon"]["steps"] if e.get("id") == "greffon")
        self.script = etape["run"]
        self.d = tempfile.mkdtemp()
        self.pr = os.path.join(self.d, "pr")
        os.makedirs(self.pr)
        self.git("init", "-q", "-b", "master")
        self.ecrire("miniz.c", "int x;\n")
        self.ecrire("bee/judge/project.py", "# greffon\n")
        self.depart = self.commit("depart")
        self.env_workflow = {k: workflow["env"][k] for k in ("JUGE_COMMUN_SHA", "JUGE_V3_SHA")}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d)

    def git(self, *args):
        # Dates strictement croissantes, une seconde par appel : deux commits de même contenu faits dans la même
        # seconde auraient le même SHA (un cherry-pick sur C0 recréait exactement C1 : test instable, N-1).
        self.horloge = getattr(self, "horloge", 1_700_000_000) + 1
        date = f"{self.horloge} +0000"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(["git", "-C", self.pr] + list(args), capture_output=True, text=True, check=True, env=env).stdout.strip()

    def ecrire(self, chemin, texte):
        os.makedirs(os.path.dirname(os.path.join(self.pr, chemin)) or self.pr, exist_ok=True)
        with open(os.path.join(self.pr, chemin), "w") as f:
            f.write(texte)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def lancer(self, base, tete, cote, epingle="JUGE_COMMUN_SHA"):
        """The step, its base pinning `epingle` (a key of the workflow's env, or a SHA) in its own bee-ci.yml."""
        sha = self.env_workflow.get(epingle, epingle)
        os.makedirs(os.path.join(self.d, "base", ".github", "workflows"), exist_ok=True)
        with open(os.path.join(self.d, "base", ".github", "workflows", "bee-ci.yml"), "w") as f:
            f.write(f'env:\n  JUGE_COMMUN_SHA: "{sha}"  # juge-vN\n')
        etats = os.path.join(self.d, "etats")
        os.makedirs(etats, exist_ok=True)
        with open(os.path.join(etats, "greffon.txt"), "w") as f:
            f.write(cote + "\n")
        sortie = os.path.join(self.d, "sortie")
        open(sortie, "w").close()
        env = dict(os.environ, ETATS=etats, BASE_SHA=base, TETE_SHA=tete, GITHUB_OUTPUT=sortie, **self.env_workflow)
        r = subprocess.run(["bash", "-e", "-c", self.script], cwd=self.d, capture_output=True, text=True, env=env)
        with open(sortie) as f:
            self.sorties = dict(l.split("=", 1) for l in f.read().split())
        with open(os.path.join(etats, "greffon_juge.txt")) as f:
            return r.returncode, self.sorties.get("base_juge"), f.read().strip(), r.stdout + r.stderr

    def test_point_de_depart_si_ni_bee_ni_miniz_n_ont_change(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("readme.md", "doc\n")  # la base avance sans rien de ce que le juge lit dans A
        base = self.commit("base")
        # judge-v4: A is the event's base, whose bee/ and miniz* are the starting point's (the outputs keep the values
        # the base's verdict.py reads).
        self.assertEqual(self.lancer(base, tete, "base")[:3], (0, base, "succes"))
        self.assertEqual((self.sorties["regle"], self.sorties["depart"], self.sorties["contrat"]), ("base_de_la_pr", self.depart, "judge-v4"))
        # Transition, a base that still pins juge-v3: the same A, judged by juge-v3 and by judge-v4.
        self.assertEqual(self.lancer(base, tete, "base", "JUGE_V3_SHA")[:3], (0, base, "succes"))
        self.assertEqual((self.sorties["regle"], self.sorties["depart"], self.sorties["contrat"]), ("base_de_la_pr", self.depart, "juge-v3"))

    def test_rouge_si_la_base_n_epingle_ni_judge_v4_ni_juge_v3(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        # juge-v2's commit (dab13a6) is no longer a pin this workflow judges.
        for epingle in ("1" * 40, "", "dab13a6e769a19937def567ed896a05b534c61dc"):
            with self.subTest(epingle=epingle):
                code, base_juge, etat, sortie = self.lancer(self.depart, tete, "base", epingle)
                self.assertEqual((code, base_juge, etat, self.sorties.get("contrat")), (1, None, "echec", None))
                self.assertIn("::error::The base pins neither judge-v4 nor juge-v3", sortie)
        # The common judge always reads the base's plugin: a PR that brings its own (bootstrap) is not judged by it.
        for epingle in ("JUGE_COMMUN_SHA", "JUGE_V3_SHA"):
            code, base_juge, etat, sortie = self.lancer(self.depart, tete, "pr", epingle)
            self.assertEqual((code, base_juge, etat, self.sorties.get("contrat")), (1, None, "echec", None))
            self.assertIn("::error::The common judge reads the plugin of the PR's base only", sortie)

    def test_rouge_si_miniz_a_change_sur_la_base(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz_tdef.c", "int z;\n")
        base = self.commit("base")
        code, base_juge, etat, sortie = self.lancer(base, tete, "base")
        self.assertEqual((code, base_juge, etat, self.sorties["regle"]), (1, None, "echec", "refus_rebase"))
        self.assertIn("rebase it on master", sortie)

    def scenario_copie(self, mode):
        """Seconde revue adverse (B-1 a) : master passe de C0 à C1 (optimisation O1 d'un autre, bee/ inchangé) ;
        la PR part de C0, récupère O1 sans ascendance (squash ou cherry-pick) et ajoute une ligne. Avec A = C0,
        le gain d'O1 était attribué à la PR."""
        self.ecrire("miniz_tinfl.c", "lent\n")
        c0 = self.commit("C0")
        self.git("checkout", "-q", "-b", "pr")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz.c", "rapide\n")
        c1 = self.commit("C1 : optimisation O1, fusionnée")
        self.git("checkout", "-q", "pr")
        if mode == "squash":
            self.git("merge", "-q", "--squash", "master")
            self.git("commit", "-q", "-m", "squash de master")
        else:
            self.git("cherry-pick", "-x", c1)
        self.ecrire("miniz_tinfl.c", "lent\nligne de la PR\n")
        tete = self.commit("PR")
        self.assertNotIn(c1, self.git("rev-list", tete).split())  # la copie n'a pas l'ascendance de C1
        self.assertEqual(self.git("merge-base", c1, tete), c0)
        code, base_juge, etat, sortie = self.lancer(c1, tete, "base")
        self.assertEqual((code, base_juge, etat, self.sorties["regle"]), (1, None, "echec", "refus_rebase"))
        self.assertIn("rebase it on master", sortie)

    def test_rouge_si_optimisation_de_master_recopiee_par_squash(self):
        self.scenario_copie("squash")

    def test_rouge_si_optimisation_de_master_recopiee_par_cherry_pick(self):
        self.scenario_copie("cherry-pick")

    def test_rouge_si_plusieurs_points_de_depart(self):
        """Seconde revue adverse (B-1 b) : historique croisé, merge-base --all rend deux commits ; l'étape en
        retenait un arbitrairement."""
        self.git("checkout", "-q", "-b", "x")
        self.ecrire("miniz_tdef.c", "O1\n")
        x1 = self.commit("X1")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz.c", "O0\n")
        c0p = self.commit("C0'")
        self.git("merge", "-q", "--no-ff", "--no-edit", "x")
        m = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "pr", c0p)
        self.git("merge", "-q", "--no-ff", "--no-edit", x1)
        self.ecrire("miniz.c", "O0\nligne de la PR\n")
        tete = self.commit("PR")
        self.assertEqual(len(self.git("merge-base", "--all", m, tete).split()), 2)
        for cote in ("base", "pr"):
            with self.subTest(cote=cote):
                code, base_juge, etat, sortie = self.lancer(m, tete, cote)
                self.assertEqual((code, base_juge, etat, self.sorties["regle"]), (1, None, "echec", "refus_point_de_depart"))
                self.assertIn("does not have a single starting point on master", sortie)

    def test_rouge_sans_point_de_depart(self):
        self.git("checkout", "-q", "--orphan", "pr")
        self.ecrire("miniz.c", "autre histoire\n")
        tete = self.commit("PR sans ancêtre commun")
        code, base_juge, etat, _ = self.lancer(self.depart, tete, "base")
        self.assertEqual((code, base_juge, etat, self.sorties["regle"]), (1, None, "echec", "refus_point_de_depart"))

    def test_rouge_si_bee_a_change_sur_la_base(self):
        """Revue adverse de miniz-0032 (B1) : comparer la base (avec une « correction » coûteuse de miniz et un
        changement de bee/) à une tête qui n'a ni l'un ni l'autre fabriquait un gain. CI rouge : rebasez."""
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y; /* commentaire de la PR */\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz_tinfl.c", "int lent;\n")
        self.commit("M : correction coûteuse sur master")
        self.ecrire("bee/README.md", "note\n")
        base = self.commit("K : outillage sur master")
        for cote in ("base", "pr"):
            with self.subTest(cote=cote):
                code, base_juge, etat, sortie = self.lancer(base, tete, cote)
                self.assertEqual((code, base_juge, etat), (1, None, "echec"))
                self.assertEqual(self.sorties["regle"], "refus_rebase")
                self.assertIn("::error::bee/ or miniz has changed on master", sortie)
                self.assertIn("rebase it on master", sortie)
        # Rebasée sur la base, la même PR passe, avec A = la base (son point de départ).
        self.git("checkout", "-q", "pr")
        self.git("rebase", "-q", base)
        tete = self.git("rev-parse", "HEAD")
        self.assertEqual(self.lancer(base, tete, "base")[:3], (0, base, "succes"))

    def test_jamais_la_tete(self):
        """Never the PR's head, whatever plugin the PR brings: A is the base (the introduction of juge-v2 is gone)."""
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("bee/judge/project.py", "# greffon de la PR, qui accepte tout\n")
        tete = self.commit("pr")
        for epingle in ("JUGE_COMMUN_SHA", "JUGE_V3_SHA"):
            self.assertEqual(self.lancer(self.depart, tete, "base", epingle)[1], self.depart)
            self.assertEqual(self.sorties["regle"], "base_de_la_pr")


class JobVerdict(unittest.TestCase):
    """The verdict job's steps (judge-v4, and the juge-v3 transition), run from bee-ci.yml: each report checked against
    its judging job's outputs (report.py --verify, rapport.py --verifier: here stand-ins that record their arguments),
    the jobs and the artifact the base's verdict.py reads under each contract, and the last step, which reads either
    vocabulary of verdict.json."""

    def setUp(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            self.etapes = {e.get("name", ""): e for e in yaml.safe_load(f)["jobs"]["verdict"]["steps"]}
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d)

    def etape(self, debut):
        return next(e for n, e in self.etapes.items() if n.startswith(debut))

    def verifier_rapport(self, debut, script, code_rapport):
        """Runs a check step with a stand-in `script` that exits `code_rapport`; returns (its arguments, juge_isole.txt)."""
        os.makedirs(os.path.join(self.d, os.path.dirname(script)), exist_ok=True)
        with open(os.path.join(self.d, script), "w") as f:
            f.write("import json, sys\nopen('arguments.json', 'w').write(json.dumps(sys.argv[1:] + [open(sys.argv[3]).read()]))\n"
                    f"sys.exit({code_rapport})\n")
        etats = os.path.join(self.d, "etats")
        os.makedirs(etats, exist_ok=True)
        if os.path.exists(os.path.join(etats, "juge_isole.txt")):
            os.remove(os.path.join(etats, "juge_isole.txt"))
        env = dict(os.environ, SORTIES_JUGE='{"code": "0", "fingerprint": "ab"}', BASE_SHA="b" * 40, TETE_SHA="c" * 40, ETATS=etats)
        r = subprocess.run(["bash", "-e", "-c", self.etape(debut)["run"]], cwd=self.d, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.d, "arguments.json")) as f:
            arguments = json.load(f)
        etat = None
        if os.path.exists(os.path.join(etats, "juge_isole.txt")):
            with open(os.path.join(etats, "juge_isole.txt")) as f:
                etat = f.read().strip()
        return arguments, etat, r.stderr

    def test_rapport_verifie_contre_les_sorties_du_job_judge(self):
        etape = self.etape("Common judge's report checked")
        self.assertNotIn("if", etape)  # under both contracts: judge-v4 judges this PR too
        self.assertNotIn("if", self.etape("Common judge (registry, at the pinned commit of judge-v4"))
        self.assertEqual(etape["env"]["SORTIES_JUGE"], "${{ toJSON(needs.judge.outputs) }}")
        noms = list(self.etapes)
        self.assertLess(noms.index(etape["name"]), noms.index("Assemble verdict.json"))
        self.assertLess(noms.index(next(n for n in noms if n.startswith("The common judge's report"))), noms.index(etape["name"]))
        arguments, etat, _ = self.verifier_rapport("Common judge's report checked", "juge-commun/tools/judge/report.py", 0)
        self.assertEqual(arguments, ["artefacts/judge/judge.json", "--verify", "sorties-judge.json", "--base", "b" * 40,
                                     "--head", "c" * 40, '{"code": "0", "fingerprint": "ab"}'])
        self.assertIsNone(etat)
        for code in (1, 2):
            with self.subTest(code=code):
                _, etat, erreur = self.verifier_rapport("Common judge's report checked", "juge-commun/tools/judge/report.py", code)
                self.assertEqual(etat, "echec")
                self.assertIn("::error::The common judge's report is not the one its job published", erreur)

    def test_transition_rapport_de_juge_v3_verifie_aussi(self):
        etape = self.etape("juge-v3's report checked")
        self.assertEqual(etape["if"], "needs.greffon.outputs.contrat == 'juge-v3'")
        for debut in ("Common judge, juge-v3 (registry", "juge-v3's report (artifact"):
            self.assertEqual(self.etape(debut)["if"], etape["if"])
        self.assertEqual(etape["env"]["SORTIES_JUGE"], "${{ toJSON(needs.juge-v3.outputs) }}")
        arguments, etat, _ = self.verifier_rapport("juge-v3's report checked", "juge-v3/outils/juge/rapport.py", 0)
        self.assertEqual(arguments, ["artefacts/juge/juge.json", "--verifier", "sorties-juge.json", "--base", "b" * 40,
                                     "--tete", "c" * 40, '{"code": "0", "fingerprint": "ab"}'])
        self.assertIsNone(etat)
        _, etat, erreur = self.verifier_rapport("juge-v3's report checked", "juge-v3/outils/juge/rapport.py", 1)
        self.assertEqual(etat, "echec")
        self.assertIn("::error::juge-v3's report is not the one its job published", erreur)

    def test_rapport_refuse_rend_le_verdict_rouge(self):
        """A juge_isole « echec » in the verdict job's own states turns a code 0 red (verdict.py)."""
        etats = {e: "succes" for e in ETAPES}
        etats["juge_isole"] = "echec"
        v = Verdict().executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual((v["ci"], v["failed_step"]), ("red", "Common judge (checking from the outside and measurements)"))

    def assembler(self, jobs, contrat, greffon="base"):
        """Runs the step « Assemble verdict.json » with a stand-in base/bee/ci/verdict.py (and pr/'s) that records its
        arguments and the jobs it reads; returns (the script that ran, its arguments, the jobs)."""
        etape = self.etape("Assemble verdict.json")
        self.assertEqual(etape["env"]["CONTRAT"], "${{ needs.greffon.outputs.contrat }}")
        for cote in ("base", "pr"):
            os.makedirs(os.path.join(self.d, cote, "bee", "ci"), exist_ok=True)
            with open(os.path.join(self.d, cote, "bee", "ci", "verdict.py"), "w") as f:
                f.write("import json, sys\nargs = sys.argv[1:]\njobs = json.load(open(args[args.index('--jobs') + 1]))\n"
                        f"json.dump({{'cote': {cote!r}, 'args': args, 'jobs': jobs}}, open('verdict.json', 'w'))\n")
        etats = os.path.join(self.d, "etats")
        os.makedirs(etats, exist_ok=True)
        with open(os.path.join(etats, "greffon.txt"), "w") as f:
            f.write(greffon + "\n")
        r = subprocess.run(["bash", "-e", "-c", etape["run"]], cwd=self.d, capture_output=True, text=True,
                           env=dict(os.environ, RESULTATS_JOBS=json.dumps(jobs), CONTRAT=contrat, ETATS=etats,
                                    BASE_SHA="b" * 40, TETE_SHA="c" * 40))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.d, "verdict.json")) as f:
            sortie = json.load(f)
        args = sortie["args"]
        return sortie["cote"], dict(zip(args[::2], args[1::2])), sortie["jobs"]

    def test_transition_le_job_qui_a_juge_est_lu_comme_juge(self):
        v4 = {"result": "success", "outputs": {"code": "0", "fingerprint": "ab"}}
        v3 = {"result": "success", "outputs": {"code": "0", "empreinte": "cd"}}
        ancien = {"result": "success", "outputs": {}}
        sautes = {"result": "skipped", "outputs": {}}
        # Under juge-v3 (this PR): the base's verdict.py reads juge-v3's job as « juge » and its artifact « juge », and the
        # juge-ancien job; the judge job (judge-v4) stays among the jobs, so its failure turns the verdict red.
        cote, args, jobs = self.assembler(dict(JOBS_OK, judge=v4, **{"juge-v3": v3, "juge-ancien": ancien}), "juge-v3")
        self.assertEqual((cote, args["--juge"]), ("base", "artefacts/juge"))
        self.assertEqual(jobs, dict(JOBS_OK, judge=v4, juge=v3, **{"juge-ancien": ancien}))
        self.assertEqual((args["--artefacts"], args["--etats"], args["--jobs"], args["--base"], args["--tete"]),
                         ("artefacts", os.path.join(self.d, "etats"), "resultats-jobs.json", "b" * 40, "c" * 40))
        # judge-v4 (the PRs after the merge), or no contract (the greffon job failed): the skipped transition jobs are left out.
        for contrat in ("judge-v4", ""):
            with self.subTest(contrat=contrat):
                cote, args, jobs = self.assembler(dict(JOBS_OK, judge=v4, **{"juge-v3": sautes, "juge-ancien": sautes}), contrat)
                self.assertEqual((cote, args["--juge"], jobs), ("base", "artefacts/judge", dict(JOBS_OK, judge=v4)))
        # Bootstrap only: the PR's assembler.
        self.assertEqual(self.assembler(dict(JOBS_OK, judge=v4), "judge-v4", greffon="pr")[0], "pr")
        # The new verdict.py, on the jobs of judge-v4: green; a failed judge job: red.
        v = Verdict().executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, judge=v4), rapport_ab())
        self.assertEqual(v["ci"], "green")

    def test_ci_rouge_lit_les_deux_vocabulaires(self):
        """The last step reads the verdict the base's verdict.py wrote: French under juge-v3, English after the merge."""
        etape = self.etape("CI red if a step failed")["run"]
        for verdict, attendu in (({"ci": "verte"}, 0), ({"ci": "green"}, 0), ({"ci": "rouge", "etape_en_echec": "x"}, 1),
                                 ({"ci": "red", "failed_step": "Fuzzing (x86-64)"}, 1), ({"ci": "vert"}, 1)):
            with self.subTest(verdict=verdict):
                with open(os.path.join(self.d, "verdict.json"), "w") as f:
                    json.dump(verdict, f)
                r = subprocess.run(["bash", "-e", "-c", etape], cwd=self.d, capture_output=True, text=True)
                self.assertEqual(r.returncode, attendu, r.stdout + r.stderr)
                self.assertIn(verdict.get("failed_step", verdict.get("etape_en_echec", "")), r.stdout)

    def test_verdict_de_repli_en_anglais(self):
        etape = self.etape("Fallback verdict")
        self.assertEqual(etape["if"], "failure() && steps.juges.outcome == 'failure'")
        r = subprocess.run(["bash", "-e", "-c", etape["run"]], cwd=self.d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.d, "verdict.json")) as f:
            v = json.load(f)
        self.assertEqual((v["ci"], v["failed_step"], v["bootstrap"]), ("red", "Judges (base without bee/)", False))


# --- miniz-0050 : le registre en anglais (ses identifiants de métrique en français ou en anglais jusqu'à ruche-0149), les
# manifestes dans les deux vocabulaires (jusqu'au DATE_D de bee). Données écrites à la main dans chaque vocabulaire
# (docs/english-names.md du registre), jamais dérivées des cartes de bee/ci/vocabulaire.py : les tests vérifient les
# cartes, ils ne les recopient pas.
MANIFESTE = os.path.join(ICI, "manifeste.sh")
TACHE_EN = """id: miniz-0050
project: miniz
type: optimization
size: S
title: essai
metric: debit_decompression
compressed_output: may_change
status: reserved
"""
# La même tâche après ruche-0149 (identifiant de métrique anglais), et avant la bascule du registre (refusée désormais).
TACHE_EN_M2 = TACHE_EN.replace("debit_decompression", "decompression_throughput")
TACHE_FR = """id: miniz-0050
projet: miniz
type: optimisation
taille: S
titre: essai
metrique: debit_decompression
sortie_compressee: peut_changer
statut: reservee
"""
MANIFESTE_FR = """tache: miniz-0050
utilisateur: abeille
agent: {modele: m, client: c}
resume: r
changement: c
mesures: {machine: x, commande: y, repetitions: 3, avant: {debit_decompression: 400}, apres: {debit_decompression: 420}}
teste: [a]
non_teste: [b]
doutes: d
taille_reelle: S
"""
MANIFESTE_EN = """task: miniz-0050
user: abeille
agent: {model: m, client: c}
summary: r
change: c
measurements: {machine: x, command: y, repetitions: 3, before: {decompression_throughput: 400}, after: {decompression_throughput: 420}}
tested: [a]
untested: [b]
doubts: d
actual_size: S
"""
OPTIONS_EN = ("--task", "--base", "--head", "--repo", "--author")
# Faux outil du registre, construit avec argparse comme le vrai. Il note ses appels (hors --help) dans journal.jsonl.
FAUX_OUTIL = '''import argparse, json, os, sys
ici = os.path.dirname(os.path.abspath(__file__))
p = argparse.ArgumentParser(prog="bee")
p.add_argument("--registry")
sous = p.add_subparsers(dest="commande", metavar="commande")
s = sous.add_parser("check-fork")
for o in ("--task", "--base", "--head", "--repo", "--author"):
    s.add_argument(o, required=o in ("--task", "--base"))
a = p.parse_args()
with open(os.path.join(ici, "journal.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "BEE_REGISTRY": os.environ.get("BEE_REGISTRY")}) + "\\n")
sys.exit(int(open(os.path.join(ici, "code")).read()) if os.path.exists(os.path.join(ici, "code")) else 0)
'''


def vocabulaire():
    sys.path.insert(0, ICI)
    try:
        import vocabulaire as module
    finally:
        sys.path.remove(ICI)
    return module


class Vocabulaire(unittest.TestCase):
    """bee/ci/vocabulaire.py : la tâche en anglais, ses identifiants de métrique dans les deux vocabulaires (ramenés à
    l'anglais) ; le manifeste dans les deux vocabulaires, un seul par document."""

    def setUp(self):
        import yaml
        self.v = vocabulaire()
        self.yaml = yaml.safe_load

    def test_cartes_bijectives_et_disjointes(self):
        """Un nom n'est jamais des deux vocabulaires à la fois : sinon un document ne serait pas classable."""
        v = self.v
        for carte in (v.CLES_MANIFESTE, v.CLES_AGENT, v.CLES_MESURES, v.METRIQUES_FR):
            self.assertEqual(len(set(carte.values())), len(carte))
            self.assertFalse(set(carte) & set(carte.values()), carte)
        self.assertEqual(v.METRIQUES, ["compression_throughput_n1", "compression_throughput_n6", "compression_throughput_n9",
                                       "decompression_throughput", "ratio_n6", "max_memory_kb"])
        self.assertEqual(v.METRIQUES_FR, {"debit_compression_n1": "compression_throughput_n1", "debit_compression_n6": "compression_throughput_n6",
                                          "debit_compression_n9": "compression_throughput_n9", "debit_decompression": "decompression_throughput",
                                          "memoire_max_ko": "max_memory_kb"})

    def test_tache_en_anglais_metrique_dans_les_deux_vocabulaires(self):
        attendu = {"type": "optimization", "metric": "decompression_throughput", "compressed_output": "may_change"}
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN)), attendu)
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN_M2)), attendu)
        for en in ("optimization", "review", "measurement", "test", "split"):
            with self.subTest(type=en):
                self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN.replace("optimization", en)))["type"], en)
        sans_sortie = self.v.lire_tache(self.yaml(TACHE_EN.replace("compressed_output: may_change\n", "")))
        self.assertEqual(sans_sortie["compressed_output"], "identical")  # absente : le contrôle le plus strict
        nulle = self.v.lire_tache(self.yaml(TACHE_EN.replace("metric: debit_decompression", "metric: null").replace("optimization", "test")))
        self.assertIsNone(nulle["metric"])  # la tâche dit explicitement qu'elle n'a pas de métrique
        self.assertEqual(self.v.metrique_de_la_tache({"metric": "ratio_n6"}), "ratio_n6")

    def test_tache_illisible(self):
        """Jamais une valeur par défaut : la tâche française (avant la bascule du registre), un type ou une sortie de
        l'autre vocabulaire, type absent ou inconnu, clé de métrique absente, métrique inconnue."""
        for texte in (TACHE_FR, TACHE_EN.replace("type: optimization", "type: optimisation"),
                      TACHE_EN.replace("may_change", "peut_changer"), TACHE_EN.replace("type: optimization\n", ""),
                      TACHE_EN.replace("optimization", "rapide"), TACHE_EN.replace("metric: debit_decompression\n", ""),
                      TACHE_EN.replace("debit_decompression", "vitesse"), TACHE_EN.replace("debit_decompression", "[ratio_n6]"),
                      TACHE_EN.replace("debit_decompression", "instructions_n6"), "id: miniz-0050\ntype: test\n", "- liste\n", "",
                      # revue adverse (M1) : une optimisation sans métrique n'a rien que R4 puisse juger
                      TACHE_EN.replace("metric: debit_decompression", "metric: null")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte))
        with self.assertRaises(self.v.Illisible):
            self.v.metrique_de_la_tache(self.yaml("type: test\nstatus: open\n"))

    def test_manifeste_dans_les_deux_vocabulaires(self):
        fr, en = self.v.lire_manifeste(self.yaml(MANIFESTE_FR)), self.v.lire_manifeste(self.yaml(MANIFESTE_EN))
        self.assertEqual(fr, en)
        self.assertEqual(en, self.yaml(MANIFESTE_EN))
        self.assertEqual(fr["measurements"]["before"], {"decompression_throughput": 400})
        self.assertEqual(self.v.lire_manifeste({"metric": "debit_compression_n6"})["metric"], "compression_throughput_n6")

    def test_manifeste_mele_refuse(self):
        """Un seul vocabulaire par manifeste, à tous ses niveaux (agent, mesures), identifiants de métrique compris."""
        for texte in (MANIFESTE_FR.replace("resume: r", "summary: r"), MANIFESTE_EN.replace("doubts: d", "doutes: d"),
                      MANIFESTE_FR.replace("avant:", "before:"), MANIFESTE_FR.replace("modele:", "model:"),
                      MANIFESTE_EN.replace("command:", "commande:"), MANIFESTE_FR + "measurements: {}\n",
                      MANIFESTE_EN.replace("after: {decompression_throughput", "after: {debit_decompression"),
                      MANIFESTE_EN + "metric: debit_decompression\n"):
            with self.subTest(manifeste=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_manifeste(self.yaml(texte))


class JobManifeste(unittest.TestCase):
    """bee/ci/manifeste.sh de bout en bout (tache.py, verifier_fork.py), sur un petit dépôt git et un faux registre en
    anglais : tasks/, tools/bee.py check-fork et ses options anglaises ; le manifeste dans les deux vocabulaires."""

    def setUp(self):
        import shutil
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.pr, self.registre = os.path.join(self.d, "pr"), os.path.join(self.d, "registre")
        os.makedirs(self.pr)
        self.git("init", "-q", "-b", "master")
        self.ecrire(self.pr, "miniz.c", "int x;\n")
        self.base = self.commit()

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(["git", "-C", self.pr] + list(args), capture_output=True, text=True, check=True, env=env).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD")

    def ecrire(self, racine, chemin, texte):
        os.makedirs(os.path.dirname(os.path.join(racine, chemin)), exist_ok=True)
        with open(os.path.join(racine, chemin), "w", encoding="utf-8") as f:
            f.write(texte)

    def lancer(self, manifestes, taches=(("tasks", TACHE_EN),), outils=(("tools", FAUX_OUTIL),), liens=()):
        for dossier, texte in taches:
            self.ecrire(self.registre, f"{dossier}/miniz/miniz-0050.yaml", texte)
        for dossier, texte in outils:
            self.ecrire(self.registre, f"{dossier}/bee.py", texte)
        for chemin, texte in manifestes:
            self.ecrire(self.pr, chemin, texte)
        for chemin, cible in liens:
            os.makedirs(os.path.dirname(os.path.join(self.pr, chemin)) or self.pr, exist_ok=True)
            os.symlink(cible, os.path.join(self.pr, chemin))
        self.ecrire(self.pr, "miniz_tinfl.c", "int y;\n")
        tete = self.commit()
        sortie, copie = os.path.join(self.d, "sortie"), os.path.join(self.d, "copie.yaml")
        open(sortie, "w").close()
        env = dict(os.environ, BASE_SHA=self.base, TETE_SHA=tete, AUTEUR="abeille", GITHUB_OUTPUT=sortie,
                   BEE_SORTIE_TACHE=copie, BEE_REGISTRY="/ailleurs")
        r = subprocess.run(["bash", MANIFESTE, self.pr, self.registre, sys.executable], capture_output=True, text=True,
                           env=env, cwd=self.d)
        with open(sortie) as f:
            self.sorties = dict(l.split("=", 1) for l in f.read().split())
        self.copie = open(copie).read() if os.path.exists(copie) else None
        self.journal = []
        for dossier, _ in outils:
            chemin = os.path.join(self.registre, dossier, "journal.jsonl")
            if os.path.exists(chemin):
                self.journal += [json.loads(l) for l in open(chemin)]
        self.tete = tete
        return r.returncode, r.stdout + r.stderr

    def appel(self):
        valeurs = ("miniz-0050", self.base, self.tete, self.pr, "abeille")
        return ["--registry", self.registre, "check-fork"] + [x for paire in zip(OPTIONS_EN, valeurs) for x in paire]

    def test_registre_anglais_manifeste_dans_les_deux_vocabulaires(self):
        for chemin, manifeste in (("manifests/miniz-0050.yaml", MANIFESTE_EN), ("manifestes/miniz-0050.yaml", MANIFESTE_FR),
                                  ("manifests/miniz-0050.yaml", MANIFESTE_FR), ("manifestes/miniz-0050.yaml", MANIFESTE_EN)):
            with self.subTest(manifeste=chemin, francais=manifeste is MANIFESTE_FR):
                self.setUp()
                code, sortie = self.lancer([(chemin, manifeste)])
                self.assertEqual(code, 0, sortie)
                self.assertEqual(self.journal, [{"argv": self.appel(), "BEE_REGISTRY": self.registre}])
                # The metric in English (a French id of the task translated); sortie_compressee keeps the value the base's
                # judges take (the plugin's option, differentiel.sh).
                self.assertEqual(self.sorties, {"tache": "miniz-0050", "type": "optimization", "metrique": "decompression_throughput",
                                                "sortie_compressee": "peut_changer", "manifeste": chemin})
                self.assertEqual(self.copie, TACHE_EN)  # la copie lue par verdict.py : la tâche telle quelle

    def test_valeurs_ecrites(self):
        for tache, attendu in ((TACHE_EN_M2.replace("compressed_output: may_change\n", ""), ("decompression_throughput", "identique")),
                               (TACHE_EN.replace("may_change", "identical").replace("metric: debit_decompression", "metric: null")
                                .replace("optimization", "test"), ("none", "identique"))):
            with self.subTest(tache=tache):
                self.setUp()
                code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], taches=(("tasks", tache),))
                self.assertEqual((code, self.sorties["metrique"], self.sorties["sortie_compressee"]), (0,) + attendu, sortie)

    def test_manifeste_mele_refuse(self):
        for texte in (MANIFESTE_EN.replace("summary: r", "resume: r"), MANIFESTE_FR.replace("avant:", "before:")):
            with self.subTest(manifeste=texte):
                self.setUp()
                code, sortie = self.lancer([("manifests/miniz-0050.yaml", texte)])
                self.assertEqual((code, self.journal, self.sorties["sortie_compressee"]), (1, [], "identique"), sortie)
                self.assertIn("mixes both vocabularies", sortie)

    def test_tache_type_ou_metrique_illisible_echoue(self):
        """Le job échoue, sans appeler l'outil ni écrire la copie de la tâche : jamais un défaut."""
        for texte in (TACHE_EN.replace("type: optimization\n", ""), TACHE_EN.replace("optimization", "inconnu"),
                      TACHE_EN.replace("metric: debit_decompression\n", ""), TACHE_EN.replace("debit_decompression", "vitesse"),
                      TACHE_EN.replace("optimization", "optimisation"), "- pas un objet\n", TACHE_FR,
                      TACHE_EN.replace("metric: debit_decompression", "metric: null")):
            with self.subTest(tache=texte):
                self.setUp()
                code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], taches=(("tasks", texte),))
                self.assertEqual((code, self.journal, self.copie), (1, [], None), sortie)
                self.assertNotIn("metrique", self.sorties)

    def test_disposition_francaise_du_registre_refusee(self):
        """miniz-0049's fallbacks are gone: a registry with taches/ or outils/ only is not read."""
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], taches=(("taches", TACHE_EN),))
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("not found in the registry (tasks/miniz/miniz-0050.yaml)", sortie)
        self.setUp()
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], outils=(("outils", FAUX_OUTIL),))
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("the registry has no tools/bee.py", sortie)

    def test_manifeste_fichier_ordinaire(self):
        """Un manifeste est un fichier ordinaire : un lien symbolique (vers un manifeste valide du dépôt ou hors de lui,
        ou cassé) ou un dossier est refusé avant toute lecture : ni tâche lue, ni outil appelé, ni sortie écrite."""
        for manifestes, liens in (([("hors.yaml", MANIFESTE_FR)], [("manifestes/miniz-0050.yaml", "../hors.yaml")]),
                                  ([], [("manifests/miniz-0050.yaml", "DEHORS")]),
                                  ([], [("manifestes/miniz-0050.yaml", "absent.yaml")]),
                                  ([("hors.yaml", MANIFESTE_FR)], [("CONTRIBUTION.yaml", "hors.yaml")]),
                                  ([("CONTRIBUTION.yaml/x", "a\n")], [])):
            with self.subTest(manifestes=manifestes, liens=liens):
                self.setUp()
                self.ecrire(self.d, "dehors.yaml", MANIFESTE_EN)  # hors du dépôt
                liens = [(c, os.path.join(self.d, "dehors.yaml") if cible == "DEHORS" else cible) for c, cible in liens]
                code, sortie = self.lancer(manifestes, liens=liens)
                self.assertEqual((code, self.journal, self.copie, self.sorties), (1, [], None, {}), sortie)
                self.assertIn("must be a regular file", sortie)
        self.setUp()  # le parcours honnête, à côté : un fichier ordinaire passe
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, len(self.journal)), (0, 1), sortie)

    def test_tache_py_n_ouvre_qu_un_fichier_ordinaire(self):
        """tache.py, appelé seul, refuse lui aussi un lien symbolique (même vers un manifeste valide, même cassé) ou un
        dossier, sans trace d'exception ni copie de la tâche, avec le contrôle le plus strict en sortie."""
        self.ecrire(self.registre, "tasks/miniz/miniz-0050.yaml", TACHE_EN)
        self.ecrire(self.d, "vrai/miniz-0050.yaml", MANIFESTE_FR)
        os.makedirs(os.path.join(self.d, "lien"))
        os.symlink(os.path.join(self.d, "vrai", "miniz-0050.yaml"), os.path.join(self.d, "lien", "miniz-0050.yaml"))
        os.makedirs(os.path.join(self.d, "casse"))
        os.symlink("absent.yaml", os.path.join(self.d, "casse", "miniz-0050.yaml"))
        os.makedirs(os.path.join(self.d, "dossier", "miniz-0050.yaml"))
        for nom, attendu in (("vrai", 0), ("lien", 1), ("casse", 1), ("dossier", 1)):
            with self.subTest(manifeste=nom):
                copie = os.path.join(self.d, f"copie-{nom}.yaml")
                r = subprocess.run([sys.executable, os.path.join(ICI, "tache.py"), "--manifeste",
                                    os.path.join(self.d, nom, "miniz-0050.yaml"), "--registre", self.registre, "--sortie", copie],
                                   capture_output=True, text=True)
                self.assertEqual((r.returncode, os.path.exists(copie)), (attendu, attendu == 0), r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                if attendu:
                    self.assertIn("must be a regular file", r.stderr)
                    self.assertEqual(r.stdout, "sortie_compressee=identique\n")

    def test_deux_manifestes_refuses(self):
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN), ("manifestes/miniz-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("several manifests", sortie)

    def test_code_de_l_outil_rendu(self):
        self.ecrire(self.registre, "tools/code", "1\n")
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)])
        self.assertEqual((code, len(self.journal)), (1, 1), sortie)


class DeuxVocabulairesDansLeVerdict(unittest.TestCase):
    """verdict.py : la métrique de la copie de la tâche, son identifiant en anglais ou en français (jusqu'à ruche-0149),
    écrit en anglais ; illisible, jamais un défaut."""

    executer = Verdict.executer

    def test_metrique_de_la_tache_dans_les_deux_vocabulaires(self):
        for metrique in ("debit_compression_n6", "compression_throughput_n6"):
            with self.subTest(metrique=metrique):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), TACHE_EN.replace("debit_decompression", metrique))
                self.assertEqual((v["ci"], v["metric"], v["gain"], v["beyond_noise"]), ("green", "compression_throughput_n6", 0.03, True))
                self.assertEqual(v["details"]["metric_origin"], "registry task")

    def test_tache_illisible_rend_rouge(self):
        """Copie absente en CI, française, sans clé de métrique, métrique inconnue, pas un objet : rouge, et la PR ne
        choisit pas la métrique (le manifeste en désigne une)."""
        for tache in (None, "type: test\n", "metric: vitesse\n", TACHE_FR.replace("debit_decompression", "debit_compression_n6"),
                      "- debit_compression_n6\n", "id: miniz-0050\ntype: test\n"):
            with self.subTest(tache=tache):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), tache,
                                  manifeste=MANIFESTE_EN.replace("decompression_throughput", "compression_throughput_n6"))
                self.assertEqual((v["ci"], v["failed_step"], v["metric"], v["gain"]), ("red", "Manifest and size", None, None))
                self.assertTrue(v["details"]["metric_origin"].startswith("unreadable"))

    def test_metrique_null_jamais_celle_du_manifeste(self):
        manifeste = MANIFESTE_FR.replace("debit_decompression", "debit_compression_n6")
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                tache = TACHE_EN.replace("metric: debit_decompression", "metric: null").replace("optimization", "test")
                v = self.executer({e: "succes" for e in ETAPES}, jobs, rapport_ab(), tache, manifeste=manifeste, code=None if jobs else "0")
                self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", None, None))

    def test_simulation_sans_tache_lit_le_manifeste(self):
        """Hors CI seulement, sans copie de la tâche : le manifeste, dans un seul vocabulaire, ses identifiants en anglais."""
        for manifeste in (MANIFESTE_EN.replace("decompression_throughput", "compression_throughput_n6"),
                          MANIFESTE_FR.replace("debit_decompression", "debit_compression_n6"),
                          "metric: debit_compression_n6\ntask: miniz-0050\n", "metric: compression_throughput_n6\ntask: miniz-0050\n"):
            with self.subTest(manifeste=manifeste):
                v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), None, code="0", manifeste=manifeste)
                self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", "compression_throughput_n6", 0.03))
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), None, code="0", manifeste=MANIFESTE_EN.replace("before:", "avant:"))
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))

    def test_lignes_hors_manifestes_des_deux_dossiers(self):
        """R1 : manifests/** et manifestes/** hors décompte, comme bee/**, tests/** et CONTRIBUTION.yaml."""
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            git = lambda *a: subprocess.run(["git", "-C", d] + list(a), capture_output=True, text=True, check=True, env=env).stdout.strip()  # noqa: E731
            git("init", "-q", "-b", "master")
            open(os.path.join(d, "miniz.c"), "w").write("int x;\n")
            git("add", "-A"), git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            for chemin in ("manifests/miniz-0050.yaml", "manifestes/miniz-0051.yaml", "bee/x", "tests/y", "CONTRIBUTION.yaml"):
                os.makedirs(os.path.dirname(os.path.join(d, chemin)) or d, exist_ok=True)
                open(os.path.join(d, chemin), "w").write("a\nb\nc\nd\n")
            open(os.path.join(d, "miniz.c"), "w").write("int x;\nint y;\nint z;\n")
            git("add", "-A"), git("commit", "-q", "-m", "tete")
            sortie = os.path.join(d, "v.json")
            subprocess.run([sys.executable, VERDICT, "--depot", d, "--base", base, "--tete", git("rev-parse", "HEAD"),
                            "--tache", os.devnull, "--sortie", sortie], check=True, capture_output=True)
            with open(sortie) as f:
                self.assertEqual(json.load(f)["changed_lines"], 2)


class DependancesDeLOutil(unittest.TestCase):
    """Étape « Dependencies of the bee tool » du job manifeste : tools/requirements.txt du registre, sans repli sur outils/."""

    def test_le_fichier_du_registre_anglais(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        self.assertEqual([e["run"] for e in etapes if e.get("name", "").startswith("Dependencies of the bee tool")],
                         ["pip install -r registre/tools/requirements.txt"])


class ConserverLeManifeste(unittest.TestCase):
    """Étape « Keep the manifest, the task and the state » du job manifeste, extraite telle quelle : seul un manifeste
    au nom validé et qui est un fichier ordinaire est copié dans l'artefact etat-manifeste (ni lien, ni dossier)."""

    def test_seul_un_fichier_ordinaire_au_nom_valide_est_copie(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        scripts = [e["run"] for e in etapes if e.get("name", "").startswith("Keep the manifest")]
        self.assertEqual(len(scripts), 1)
        for chemin, forme, garde in (("manifests/miniz-0050.yaml", "fichier", True), ("manifestes/miniz-0050.yaml", "fichier", True),
                                     ("CONTRIBUTION.yaml", "fichier", True), ("manifests/miniz-50.yaml", "fichier", False),
                                     ("autre/miniz-0050.yaml", "fichier", False), ("manifests/../tache.yaml", "fichier", False),
                                     ("manifests/miniz-0050.yaml", "lien", False), ("CONTRIBUTION.yaml", "lien", False),
                                     ("manifestes/miniz-0050.yaml", "lien interne", False), ("CONTRIBUTION.yaml", "dossier", False)):
            with self.subTest(chemin=chemin, forme=forme), tempfile.TemporaryDirectory() as d:
                cible = os.path.join(d, "pr", chemin)
                os.makedirs(os.path.dirname(cible), exist_ok=True)
                with open(os.path.join(d, "dehors.yaml"), "w") as f:
                    f.write("tache: miniz-0050\n")
                if forme == "fichier":
                    with open(cible, "w") as f:
                        f.write("tache: miniz-0050\n")
                elif forme == "lien":
                    os.symlink(os.path.join(d, "dehors.yaml"), cible)
                elif forme == "lien interne":
                    with open(os.path.join(d, "pr", "hors.yaml"), "w") as f:
                        f.write("tache: miniz-0050\n")
                    os.symlink("../hors.yaml", cible)
                else:
                    os.makedirs(os.path.join(cible, "x"))
                env = dict(os.environ, MANIFESTE=chemin, ETATS=os.path.join(d, "etats"))
                r = subprocess.run(["bash", "-e", "-c", scripts[0]], cwd=d, capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                copie = os.path.join(d, "donnees", "CONTRIBUTION.yaml")
                self.assertEqual(os.path.lexists(copie), garde)
                if garde:
                    self.assertTrue(os.path.isfile(copie) and not os.path.islink(copie))


if __name__ == "__main__":
    unittest.main(verbosity=1)
