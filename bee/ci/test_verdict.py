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

VERDICT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verdict.py")
ETAPES = ["manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "differentiel_x86_64",
          "differentiel_arm64", "fuzzing", "banc_ab"]
JOBS_OK = {"manifeste": {"result": "success"}, "compilation-et-tests": {"result": "success"},
           "fuzzing": {"result": "success"}, "banc-ab": {"result": "success"}}


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
    def executer(self, etats, jobs=None, ab=None, tache=None):
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
                with open(os.path.join(artefacts, "x", "ab.json"), "w") as f:
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
        v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, **{"banc-ab": {"result": "failure"}}), rapport_ab())
        self.assertEqual(v["ci"], "rouge")

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
