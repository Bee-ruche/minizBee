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
# juge_isole n'a pas de fichier d'état : verdict.py la tire du code du juge commun (sortie du job juge).
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "differentiel_x86_64",
          "differentiel_arm64", "fuzzing", "greffon_juge", "juge_ancien", "meta_juge"]
DEPART = "d" * 40
GREFFON_OK = {"result": "success", "outputs": {"base_juge": DEPART, "regle": "point_de_depart", "depart": DEPART}}
JOBS_OK = {"manifeste": {"result": "success"}, "greffon": GREFFON_OK,
           "compilation-et-tests": {"result": "success"}, "fuzzing": {"result": "success"},
           "juge": {"result": "success", "outputs": {"code": "0"}}, "juge-ancien": {"result": "success"},
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
    def executer(self, etats, jobs=None, ab=None, tache=None, nom_rapport="ab.json", code=None, ancien=None):
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
                # Le rapport du juge commun est dans l'artefact « juge » ; ab.json (simulation) n'importe où.
                dossier = os.path.join(artefacts, "juge" if nom_rapport == "juge.json" else "x")
                os.makedirs(dossier, exist_ok=True)
                with open(os.path.join(dossier, nom_rapport), "w") as f:
                    json.dump(ab, f)
            if code is not None:
                os.makedirs(os.path.join(artefacts, "juge"), exist_ok=True)
                with open(os.path.join(artefacts, "juge", "code"), "w") as f:
                    f.write(code + "\n")
            if ancien is not None:
                with open(os.path.join(artefacts, "x", "juge-ancien.json"), "w") as f:
                    json.dump(ancien, f)
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

    def test_juge_commun_et_constructions_suspectes(self):
        rapport = rapport_ab()
        rapport["juge"] = {"version": 3, "commun": "juge-v1", "projet": "miniz", "greffon": "c0" * 32, "graine": "ab" * 16,
                           "verification": {"sorties_comparees": 914, "sortie_compressee": "identique"},
                           "constructions_suspectes": [{"type": "instruction", "detail": "syscall : 1 occurrence(s)"}]}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, "metrique: debit_compression_n6\n", nom_rapport="juge.json")
        self.assertEqual(v["ci"], "verte")
        self.assertEqual(v["etapes"]["juge_isole"], "succes")
        self.assertEqual((v["juge"]["version"], v["juge"]["commun"], v["juge"]["projet"], v["juge"]["greffon"]), (3, "juge-v1", "miniz", "c0" * 32))
        self.assertEqual(v["juge"]["sorties_comparees"], 914)
        self.assertEqual(v["juge"]["constructions_suspectes"], [{"type": "instruction", "detail": "syscall : 1 occurrence(s)"}])
        self.assertAlmostEqual(v["gain"], 0.03)

    def test_champs_du_juge_valides(self):
        rapport = rapport_ab()
        rapport["juge"] = {"version": 3, "commun": "juge-v1\n::error::x", "greffon": "pas une empreinte", "projet": "x" * 100,
                           "verification": {"sorties_comparees": 1}, "constructions_suspectes": []}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, nom_rapport="juge.json")
        self.assertEqual((v["juge"]["commun"], v["juge"]["greffon"], len(v["juge"]["projet"])), (None, None, 40))

    def test_juge_commun_refuse(self):
        """Le job juge (juge.yml) réussit même quand le juge refuse B : c'est son code qui rend la CI rouge."""
        for code in ("1", "2"):
            with self.subTest(code=code):
                jobs = dict(JOBS_OK, juge={"result": "success", "outputs": {"code": code}})
                v = self.executer({e: "succes" for e in ETAPES}, jobs, rapport_ab(), code="0")
                self.assertEqual(v["ci"], "rouge")
                self.assertEqual(v["etape_en_echec"], "Juge commun (vérification de l'extérieur et mesures)")
                self.assertEqual(v["details"]["code_juge"], code)

    def test_juge_commun_sans_code(self):
        # Greffon en échec : le job juge est sauté, sans sortie « code ».
        etats = {e: "succes" for e in ETAPES}
        etats["greffon_juge"] = "echec"
        jobs = dict(JOBS_OK, greffon={"result": "failure"}, juge={"result": "skipped", "outputs": {}})
        v = self.executer(etats, jobs, rapport_ab())
        self.assertEqual(v["ci"], "rouge")
        self.assertEqual(v["etape_en_echec"], "Greffon du juge commun")
        self.assertEqual(v["etapes"]["juge_isole"], "absent")

    def test_code_du_juge_hors_ci(self):
        """Simulation locale (sans --jobs) : le fichier code de l'artefact « juge »."""
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), code="0")
        self.assertEqual(v["ci"], "verte")
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), code="1")
        self.assertEqual(v["ci"], "rouge")

    def test_un_etat_juge_isole_ne_suffit_pas(self):
        """Un fichier juge_isole.txt « succes » ne remplace pas le code du juge commun."""
        etats = dict({e: "succes" for e in ETAPES}, juge_isole="succes")
        v = self.executer(etats, dict(JOBS_OK, juge={"result": "success", "outputs": {"code": "1"}}), rapport_ab())
        self.assertEqual(v["ci"], "rouge")
        v = self.executer(etats, dict(JOBS_OK, juge={"result": "success", "outputs": {}}), rapport_ab())
        self.assertEqual(v["etapes"]["juge_isole"], "absent")  # en CI, sans code : sans résultat
        self.assertEqual(v["ci"], "rouge")
        etats["juge_isole"] = "echec"
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "rouge")  # un « echec » l'emporte toujours

    def test_juge_ancien_dans_les_details(self):
        ancien = {"juge": {"version": 2, "graine": "cd" * 16, "verification": {"sorties_comparees": 2988}, "constructions_suspectes": []},
                  "instructions": {"instructions_n6": {"A": 10, "B": 9, "gain": 0.1}}}
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), ancien=ancien)
        self.assertEqual(v["details"]["juge_ancien"]["juge"]["version"], 2)
        self.assertEqual(v["details"]["juge_ancien"]["instructions"], {"instructions_n6": {"A": 10, "B": 9}})
        etats = dict({e: "succes" for e in ETAPES}, juge_ancien="echec")
        v = self.executer(etats, dict(JOBS_OK, **{"juge-ancien": {"result": "failure"}}), rapport_ab())
        self.assertEqual(v["etape_en_echec"], "Ancien juge isolé de la base (transition)")

    def test_base_juge_publiee(self):
        """verdict.json publie le commit A du juge commun et la règle qui l'a choisi (revue adverse de miniz-0032)."""
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "verte")
        self.assertEqual(v["base_juge"], {"commit": DEPART, "regle": "point_de_depart", "depart": DEPART, "base": None})
        self.assertIsNone(self.executer({e: "succes" for e in ETAPES}, None, rapport_ab())["base_juge"])

    def test_jamais_vert_sans_a_verifiable(self):
        """Règle de refus, règle inconnue ou commit illisible : rouge, même si tous les jobs et états disent succès."""
        for sorties in ({"base_juge": DEPART, "regle": "refus_bee_modifie", "depart": DEPART},
                        {"base_juge": DEPART, "regle": "base", "depart": DEPART},
                        {"base_juge": "HEAD", "regle": "point_de_depart", "depart": DEPART}, {}):
            with self.subTest(sorties=sorties):
                v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, greffon={"result": "success", "outputs": sorties}), rapport_ab())
                self.assertEqual(v["ci"], "rouge")
                self.assertEqual(v["etape_en_echec"], "Greffon du juge commun")

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
    """bee/ci/juges.sh et sa copie dans bee-ci.yml : amorçage seulement pour le commit épinglé, greffon de la
    PR seulement quand elle l'introduit dans une base qui a encore l'ancien juge isolé."""

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
            self.assertIn("AMORÇAGE", r.stdout)
            self.assertEqual(self.lire(d, "amorcage.txt"), "oui")
            self.assertEqual(self.lire(d, "juges.txt"), "succes")
            self.assertEqual(self.lire(d, "greffon.txt"), "pr")
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(pr, f.read())  # juges copiés depuis la PR
            with open(os.path.join(base, ".github", "workflows", "bee-ci.yml")) as f:
                self.assertIn(pr, f.read())  # le workflow aussi

    def ajouter(self, racine, nom):
        os.makedirs(os.path.join(racine, "bee", "juge"), exist_ok=True)
        with open(os.path.join(racine, "bee", "juge", nom), "w") as f:
            f.write("# " + nom + " de " + racine + "\n")

    def test_introduction_du_greffon(self):
        """Base avec l'ancien juge isolé et sans greffon, PR qui apporte le greffon (miniz-0032)."""
        with tempfile.TemporaryDirectory() as d:
            base, pr = self.preparer(d, base_avec_bee=True)
            self.ajouter(base, "juge.py")
            self.ajouter(pr, "projet.py")
            r = self.lancer(d, base, pr, "0" * 40)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("INTRODUCTION DU GREFFON", r.stdout)
            self.assertEqual(self.lire(d, "amorcage.txt"), "oui")
            self.assertEqual(self.lire(d, "greffon.txt"), "pr")
            # Les juges restent ceux de la base : l'ancien juge isolé juge aussi la PR.
            with open(os.path.join(base, "bee", "ci", "etape.sh")) as f:
                self.assertIn(base, f.read())
            self.assertFalse(os.path.exists(os.path.join(base, "bee", "juge", "projet.py")))

    def test_greffon_de_la_base_garde(self):
        """Dès que la base a un greffon, celui de la PR n'est jamais pris, même si la base garde un juge.py."""
        for ancien_dans_la_base in (False, True):
            with self.subTest(ancien_dans_la_base=ancien_dans_la_base), tempfile.TemporaryDirectory() as d:
                base, pr = self.preparer(d, base_avec_bee=True)
                self.ajouter(base, "projet.py")
                if ancien_dans_la_base:
                    self.ajouter(base, "juge.py")
                self.ajouter(pr, "projet.py")
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
            script = logique_juges(f.read(), "# --- début de la logique recopiée dans bee-ci.yml ---\n",
                                   "# --- fin de la logique recopiée dans bee-ci.yml ---")
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        self.assertEqual(workflow["env"]["BEE_JUGES"], script)
        self.assertEqual(workflow["env"]["BEE_COMMIT_AMORCAGE"], COMMIT_AMORCAGE)
        for nom, job in workflow["jobs"].items():
            if "uses" in job:  # workflow réutilisable (juge commun) : il extrait lui-même ce qu'il juge
                continue
            etapes = [e.get("name", "") for e in job["steps"]]
            self.assertTrue(any(n.startswith("Juges") for n in etapes), f"job {nom} sans étape Juges")
            # Aucune étape n'utilise base/bee avant l'étape Juges.
            i_juges = next(i for i, n in enumerate(etapes) if n.startswith("Juges"))
            for e in job["steps"][:i_juges]:
                self.assertNotIn("base/bee", e.get("run", ""), f"job {nom} : base/bee utilisé avant Juges")

    def charger_workflow(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_juge_commun_epingle(self):
        """Le job juge appelle juge.yml du registre au commit JUGE_COMMUN_SHA (jamais une étiquette ni une branche,
        qui se déplacent), et chaque extraction du juge commun (isoler.sh, image, méta-tests) se fait à ce commit."""
        workflow = self.charger_workflow()
        sha = workflow["env"]["JUGE_COMMUN_SHA"]
        self.assertRegex(sha, r"^[0-9a-f]{40}$")
        self.assertNotIn("JUGE_COMMUN_REF", workflow["env"])
        juge = workflow["jobs"]["juge"]
        self.assertEqual(juge["uses"], f"Bee-ruche/registre/.github/workflows/juge.yml@{sha}")
        # Greffon lu dans la base : le commit vient du job greffon, jamais de la tête de la PR directement.
        self.assertEqual(juge["with"]["base_sha"], "${{ needs.greffon.outputs.base_juge }}")
        self.assertIn("greffon", juge["needs"])
        extractions = [e for job in workflow["jobs"].values() for e in job.get("steps", [])
                       if e.get("with", {}).get("path") == "juge-commun"]
        self.assertEqual(len(extractions), 3)  # compilation et tests, fuzzing, méta-tests
        for e in extractions:
            self.assertEqual((e["with"]["repository"], e["with"]["ref"]), ("${{ env.REGISTRE }}", "${{ env.JUGE_COMMUN_SHA }}"))
        self.assertEqual(workflow["env"]["REGISTRE"], "Bee-ruche/registre")
        verdict = workflow["jobs"]["verdict"]
        self.assertEqual(set(verdict["needs"]), set(workflow["jobs"]) - {"verdict"})

    def test_tests_unitaires_sans_garde(self):
        """Revue adverse de miniz-0033 : un test de l'outillage ne se saute jamais sans bruit (if [ -f … ])."""
        workflow = self.charger_workflow()
        etape = next(e for e in workflow["jobs"]["manifeste"]["steps"] if e.get("name", "").startswith("Tests unitaires"))
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
    """Étape « Commit du greffon et de A » du job greffon de bee-ci.yml, sur de petits dépôts git : le juge
    commun ne lit jamais le greffon dans la PR, sauf à son introduction, et alors sans changement de miniz."""

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
        self.ecrire("bee/juge/projet.py", "# greffon\n")
        self.depart = self.commit("depart")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d)

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(["git", "-C", self.pr] + list(args), capture_output=True, text=True, check=True, env=env).stdout.strip()

    def ecrire(self, chemin, texte):
        os.makedirs(os.path.dirname(os.path.join(self.pr, chemin)) or self.pr, exist_ok=True)
        with open(os.path.join(self.pr, chemin), "w") as f:
            f.write(texte)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def lancer(self, base, tete, cote):
        etats = os.path.join(self.d, "etats")
        os.makedirs(etats, exist_ok=True)
        with open(os.path.join(etats, "greffon.txt"), "w") as f:
            f.write(cote + "\n")
        sortie = os.path.join(self.d, "sortie")
        open(sortie, "w").close()
        env = dict(os.environ, ETATS=etats, BASE_SHA=base, TETE_SHA=tete, GITHUB_OUTPUT=sortie)
        r = subprocess.run(["bash", "-e", "-c", self.script], cwd=self.d, capture_output=True, text=True, env=env)
        with open(sortie) as f:
            self.sorties = dict(l.split("=", 1) for l in f.read().split())
        with open(os.path.join(etats, "greffon_juge.txt")) as f:
            return r.returncode, self.sorties.get("base_juge"), f.read().strip(), r.stdout + r.stderr

    def test_point_de_depart_si_bee_inchange(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz_tdef.c", "int z;\n")  # la base avance, sans toucher bee/
        base = self.commit("base")
        self.assertEqual(self.lancer(base, tete, "base")[:3], (0, self.depart, "succes"))
        self.assertEqual((self.sorties["regle"], self.sorties["depart"]), ("point_de_depart", self.depart))

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
                self.assertEqual(self.sorties["regle"], "refus_bee_modifie")
                self.assertIn("::error::bee/ a changé sur master", sortie)
                self.assertIn("rebasez-la sur master", sortie)
        # Rebasée sur la base, la même PR passe, avec A = la base (son point de départ).
        self.git("checkout", "-q", "pr")
        self.git("rebase", "-q", base)
        tete = self.git("rev-parse", "HEAD")
        self.assertEqual(self.lancer(base, tete, "base")[:3], (0, base, "succes"))

    def test_jamais_la_tete_hors_introduction(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("bee/juge/projet.py", "# greffon de la PR, qui accepte tout\n")
        tete = self.commit("pr")
        self.assertEqual(self.lancer(self.depart, tete, "base")[1], self.depart)

    def test_introduction(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("bee/juge/projet.py", "# nouveau greffon\n")
        tete = self.commit("pr")
        self.assertEqual(self.lancer(self.depart, tete, "pr")[:3], (0, tete, "succes"))
        self.assertEqual(self.sorties["regle"], "introduction")
        self.ecrire("miniz_tinfl.c", "int w;\n")  # l'introduction ne doit pas toucher miniz
        tete = self.commit("pr + miniz")
        code, base_juge, etat, sortie = self.lancer(self.depart, tete, "pr")
        self.assertEqual((code, base_juge, etat), (1, None, "echec"))
        self.assertEqual(self.sorties["regle"], "refus_introduction_miniz")
        self.assertIn("::error::", sortie)


if __name__ == "__main__":
    unittest.main(verbosity=1)
