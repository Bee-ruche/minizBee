#!/usr/bin/env python3
"""Tests unitaires de bee/ci/verdict.py : « ci », étape en échec, gain sur la métrique de la tâche.

Usage : python3 bee/ci/test_verdict.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
VERDICT = os.path.join(ICI, "verdict.py")
JUGES = os.path.join(ICI, "juges.sh")
WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(ICI)), ".github", "workflows", "bee-ci.yml")
COMMIT_AMORCAGE = "2948eebafc5b9f1c69bebed80333e403a09bd62d"
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "differentiel_x86_64",
          "differentiel_arm64", "fuzzing", "juge_isole", "meta_juge"]
JOBS_OK = {"manifeste": {"result": "success"}, "compilation-et-tests": {"result": "success"},
           "fuzzing": {"result": "success"}, "juge": {"result": "success"},
           "meta-juge": {"result": "success"}}


def rapport_ab(gain_n6=0.03, signe_n6=True, degradation_n1=False):
    metriques = {}
    for nom in ["debit_compression_n1", "debit_compression_n6", "debit_compression_n9", "debit_decompression",
                "ratio_n6", "memoire_max_ko"]:
        metriques[nom] = {"gain": 0.0, "au_dela_du_bruit": False, "degradation_au_dela_du_bruit": False, "test_du_signe": {}}
    metriques["debit_compression_n6"].update({"gain": gain_n6, "au_dela_du_bruit": signe_n6})
    if degradation_n1:
        metriques["debit_compression_n1"].update({"gain": -0.04, "degradation_au_dela_du_bruit": True})
    return {"metriques": metriques, "mesures": {"A": {"debit_compression_n6": 22.5}, "B": {"debit_compression_n6": 23.2}},
            "instructions": {"instructions_n6": {"A": 100, "B": 97, "gain": 0.03, "au_dela_du_bruit": True}}}


class Verdict(unittest.TestCase):
    def executer(self, etats, jobs=None, ab=None, tache=None, nom_rapport="ab.json"):
        with tempfile.TemporaryDirectory() as d:
            artefacts = os.path.join(d, "artefacts")
            os.makedirs(os.path.join(artefacts, "x", "etats"))
            for etape, valeur in etats.items():
                with open(os.path.join(artefacts, "x", "etats", etape + ".txt"), "w") as f:
                    f.write(valeur + "\n")
            commande = [sys.executable, VERDICT, "--artefacts", artefacts, "--sortie", os.path.join(d, "verdict.json")]
            if jobs is not None:
                with open(os.path.join(d, "jobs.json"), "w") as f:
                    json.dump(jobs, f)
                commande += ["--jobs", os.path.join(d, "jobs.json")]
            if ab is not None:
                with open(os.path.join(artefacts, "x", nom_rapport), "w") as f:
                    json.dump(ab, f)
            if tache is not None:
                with open(os.path.join(artefacts, "x", "tache.yaml"), "w") as f:
                    f.write(tache)
            subprocess.run(commande, check=True, capture_output=True)
            with open(os.path.join(d, "verdict.json")) as f:
                return json.load(f)

    def test_tout_vert(self):
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), "metrique: debit_compression_n6\n")
        self.assertEqual(v["ci"], "verte")
        self.assertNotIn("etape_en_echec", v)
        self.assertAlmostEqual(v["gain"], 0.03)
        self.assertTrue(v["au_dela_du_bruit"])
        self.assertEqual(v["instructions"]["instructions_n6"]["B"], 97)
        for cle in ("ci", "gain", "au_dela_du_bruit", "mesures"):
            self.assertIn(cle, v)

    def test_premiere_etape_en_echec_explicite(self):
        etats = {e: "succes" for e in ETAPES}
        etats["differentiel_x86_64"] = "echec"
        del etats["compilation_arm64"]  # job ARM64 sans résultat, mais pas en échec explicite
        del etats["differentiel_arm64"]
        jobs = dict(JOBS_OK, **{"compilation-et-tests": {"result": "failure"}})
        v = self.executer(etats, jobs, rapport_ab())
        self.assertEqual(v["ci"], "rouge")
        self.assertEqual(v["etape_en_echec"], "Tests différentiels et empreintes (x86-64)")

    def test_job_echoue_sans_fichier_etat(self):
        etats = {e: "succes" for e in ETAPES if e != "fuzzing"}
        v = self.executer(etats, dict(JOBS_OK, fuzzing={"result": "cancelled"}), rapport_ab())
        self.assertEqual(v["ci"], "rouge")
        self.assertEqual(v["etape_en_echec"], "Fuzzing (x86-64) (sans résultat)")

    def test_etat_succes_mais_job_en_echec(self):
        # Le code de la PR ne peut pas rendre la CI verte en écrivant « succes » : le résultat du job prime.
        v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, **{"juge": {"result": "failure"}}), rapport_ab())
        self.assertEqual(v["ci"], "rouge")

    def test_juge_isole_et_constructions_suspectes(self):
        rapport = rapport_ab()
        rapport["juge"] = {"version": 1, "graine": "ab" * 16, "verification": {"sorties_comparees": 914},
                           "constructions_suspectes": [{"type": "instruction", "detail": "syscall : 1 occurrence(s)"}]}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, "metrique: debit_compression_n6\n", nom_rapport="juge.json")
        self.assertEqual(v["ci"], "verte")
        self.assertEqual(v["juge"]["sorties_comparees"], 914)
        self.assertEqual(v["juge"]["constructions_suspectes"], [{"type": "instruction", "detail": "syscall : 1 occurrence(s)"}])

    def test_sans_juge_isole(self):
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), "metrique: debit_compression_n6\n")
        self.assertIsNone(v["juge"])

    def test_sans_metrique_designee_gain_null(self):
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), "type: test\nmetrique: null\n")
        self.assertIsNone(v["gain"])
        self.assertIsNone(v["metrique"])
        self.assertFalse(v["au_dela_du_bruit"])

    def test_degradations(self):
        ab = rapport_ab(degradation_n1=True)
        ab["instructions"]["instructions_n1"] = {"A": 100, "B": 105, "gain": -0.05, "au_dela_du_bruit": True}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, ab, "metrique: debit_compression_n6\n")
        self.assertIn("debit_compression_n1", v["degradations"])
        self.assertIn("instructions_n1", v["degradations"])
        self.assertNotIn("instructions_n6", v["degradations"])


    def test_amorcage_signale(self):
        etats = {e: "succes" for e in ETAPES}
        etats["amorcage"] = "oui"
        v = self.executer(etats, JOBS_OK, rapport_ab(), "metrique: debit_compression_n6\n")
        self.assertEqual(v["ci"], "verte")
        self.assertTrue(v["amorcage"])
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab())
        self.assertFalse(v["amorcage"])

    def test_juges_en_echec_rend_rouge(self):
        etats = {e: "succes" for e in ETAPES}
        etats["juges"] = "echec"
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "rouge")
        self.assertEqual(v["etape_en_echec"], "Juges (base sans bee/)")


def logique_juges(texte, marqueur_debut, marqueur_fin):
    return texte.split(marqueur_debut, 1)[1].split(marqueur_fin, 1)[0]


class Juges(unittest.TestCase):
    """bee/ci/juges.sh et sa copie dans bee-ci.yml : amorçage seulement pour le commit épinglé."""

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
            self.assertIsNone(self.lire(d, "amorcage.txt"))
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(base, f.read())  # les juges de la base sont gardés, pas ceux de la PR

    def test_amorcage_commit_epingle(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=False)
            r = self.lancer(d, base, pr, COMMIT_AMORCAGE)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("AMORÇAGE", r.stdout)
            self.assertEqual(self.lire(d, "amorcage.txt"), "oui")
            self.assertEqual(self.lire(d, "juges.txt"), "succes")
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(pr, f.read())  # juges copiés depuis la PR
            with open(os.path.join(base, ".github", "workflows", "bee-ci.yml")) as f:
                self.assertIn(pr, f.read())  # le workflow aussi

    def ajouter_juge(self, racine):
        os.makedirs(os.path.join(racine, "bee", "juge"), exist_ok=True)
        with open(os.path.join(racine, "bee", "juge", "juge.py"), "w") as f:
            f.write("# juge de " + racine + "\n")

    def test_introduction_du_juge_isole(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=True)
            self.ajouter_juge(pr)
            r = self.lancer(d, base, pr, "0" * 40)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("INTRODUCTION DU JUGE ISOLÉ", r.stdout)
            self.assertEqual(self.lire(d, "amorcage.txt"), "oui")
            with open(os.path.join(base, "bee", "juge", "juge.py")) as f:
                self.assertIn(pr, f.read())

    def test_juge_isole_de_la_base_garde(self):
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=True)
            self.ajouter_juge(base)
            self.ajouter_juge(pr)
            r = self.lancer(d, base, pr, "0" * 40)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIsNone(self.lire(d, "amorcage.txt"))
            with open(os.path.join(base, "bee", "juge", "juge.py")) as f:
                self.assertIn(base, f.read())  # une PR ne remplace jamais le juge de la base

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
            script = logique_juges(f.read(), "# --- début de la logique recopiée dans bee-ci.yml ---\n",
                                   "# --- fin de la logique recopiée dans bee-ci.yml ---")
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        self.assertEqual(workflow["env"]["BEE_JUGES"], script)
        self.assertEqual(workflow["env"]["BEE_COMMIT_AMORCAGE"], COMMIT_AMORCAGE)
        for nom, job in workflow["jobs"].items():
            etapes = [e.get("name", "") for e in job["steps"]]
            self.assertTrue(any(n.startswith("Juges") for n in etapes), f"job {nom} sans étape Juges")
            # Aucune étape n'utilise base/bee avant l'étape Juges.
            i_juges = next(i for i, n in enumerate(etapes) if n.startswith("Juges"))
            for e in job["steps"][:i_juges]:
                self.assertNotIn("base/bee", e.get("run", ""), f"job {nom} : base/bee utilisé avant Juges")

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
