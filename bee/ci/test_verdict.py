#!/usr/bin/env python3
"""Tests unitaires de bee/ci/verdict.py : « ci », étape en échec, gain sur la métrique de la tâche.

Usage : python3 bee/ci/test_verdict.py
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
# juge_isole n'a pas de fichier d'état : verdict.py la tire du code du juge commun (sortie du job juge).
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "differentiel_x86_64",
          "differentiel_arm64", "fuzzing", "greffon_juge", "juge_ancien", "meta_juge", "outillage_pr"]
DEPART = "d" * 40
GREFFON_OK = {"result": "success", "outputs": {"base_juge": DEPART, "regle": "point_de_depart", "depart": DEPART}}
JOBS_OK = {"manifeste": {"result": "success"}, "greffon": GREFFON_OK,
           "compilation-et-tests": {"result": "success"}, "fuzzing": {"result": "success"},
           "juge": {"result": "success", "outputs": {"code": "0"}}, "juge-ancien": {"result": "success"},
           "meta-juge": {"result": "success"}, "outillage-pr": {"result": "success"}}
# Copie de la tâche par défaut des tests du verdict (miniz-0049 : en CI, sans copie lisible de la tâche, le verdict est
# rouge) : metrique: null, donc gain null, comme sans tâche auparavant ; tache=None pour un verdict sans copie.
TACHE_SANS_METRIQUE = "type: test\nmetrique: null\n"
# Dossier où chaque job dépose ses fichiers d'état dans son artefact (bee-ci.yml), écrit à la main : les tests vérifient
# verdict.py, ils ne le recopient pas. Les autres états (juges, amorcage, juge_isole, meta_juge, outillage_pr) vont dans
# --etats, le dossier du job verdict.
DOSSIER_ETAT = {"manifeste_et_taille": "etat-manifeste/etats", "compilation_x86_64": "etat-tests-x86_64",
                "differentiel_x86_64": "etat-tests-x86_64", "compilation_arm64": "etat-tests-arm64",
                "differentiel_arm64": "etat-tests-arm64", "fuzzing": "etat-fuzzing", "greffon_juge": "etat-greffon",
                "juge_ancien": "etat-juge-ancien/etats"}


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
    metriques = {}
    for nom in ["debit_compression_n1", "debit_compression_n6", "debit_compression_n9", "debit_decompression",
                "ratio_n6", "memoire_max_ko"]:
        metriques[nom] = {"gain": 0.0, "au_dela_du_bruit": False, "degradation_au_dela_du_bruit": False, "test_du_signe": {}}
    metriques["debit_compression_n6"].update({"gain": gain_n6, "au_dela_du_bruit": signe_n6})
    if degradation_n1:
        metriques["debit_compression_n1"].update({"gain": -0.04, "degradation_au_dela_du_bruit": True})
    return {"metriques": metriques, "mesures": {"A": {"debit_compression_n6": 22.5}, "B": {"debit_compression_n6": 23.2}},
            "instructions": {"instructions_n6": {"A": 100, "B": 97, "gain": 0.03, "au_dela_du_bruit": True}},
            "juge": {"version": 3, "commun": "juge-v1", "projet": "miniz", "greffon": "c0" * 32, "graine": "ab" * 16,
                     "verification": {"sorties_comparees": 914}, "constructions_suspectes": []}}


class Verdict(unittest.TestCase):
    def executer(self, etats, jobs=None, ab=None, tache=TACHE_SANS_METRIQUE, nom_rapport="juge.json", code=None, ancien=None,
                 manifeste=None):
        with tempfile.TemporaryDirectory() as d:
            artefacts, propres = ecrire_etats(d, etats)
            commande = [sys.executable, VERDICT, "--artefacts", artefacts, "--etats", propres, "--sortie", os.path.join(d, "verdict.json")]
            if jobs is not None:
                with open(os.path.join(d, "jobs.json"), "w") as f:
                    json.dump(jobs, f)
                commande += ["--jobs", os.path.join(d, "jobs.json")]
            if ab is not None:
                # Le rapport du juge commun est dans l'artefact « juge » ; sous un autre nom, ailleurs (jamais lu).
                dossier = os.path.join(artefacts, "juge" if nom_rapport == "juge.json" else "x")
                os.makedirs(dossier, exist_ok=True)
                with open(os.path.join(dossier, nom_rapport), "w") as f:
                    json.dump(ab, f)
            if code is not None:
                os.makedirs(os.path.join(artefacts, "juge"), exist_ok=True)
                with open(os.path.join(artefacts, "juge", "code"), "w") as f:
                    f.write(code + "\n")
            if ancien is not None:
                os.makedirs(os.path.join(artefacts, "etat-juge-ancien"), exist_ok=True)
                with open(os.path.join(artefacts, "etat-juge-ancien", "juge-ancien.json"), "w") as f:
                    json.dump(ancien, f)
            for nom, contenu in (("tache.yaml", tache), ("CONTRIBUTION.yaml", manifeste)):
                if contenu is not None:
                    os.makedirs(os.path.join(artefacts, "etat-manifeste"), exist_ok=True)
                    with open(os.path.join(artefacts, "etat-manifeste", nom), "w") as f:
                        f.write(contenu)
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

    def test_jobs_qui_executent_la_pr_jugent_par_leur_resultat(self):
        """meta-juge et outillage-pr exécutent du code de la PR : un fichier d'état « succes » ne compte pas,
        seul le résultat du job compte."""
        for job, libelle in (("meta-juge", "Méta-tests du greffon contre le juge commun"),
                             ("outillage-pr", "Tests de l'outillage de CI de la PR")):
            with self.subTest(job=job):
                v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, **{job: {"result": "failure"}}), rapport_ab())
                self.assertEqual((v["ci"], v["etape_en_echec"]), ("rouge", libelle))
        etats = {e: "succes" for e in ETAPES if e not in ("meta_juge", "outillage_pr")}
        v = self.executer(etats, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "verte")  # sans fichier d'état : le résultat du job suffit

    def test_donnees_lues_dans_leur_artefact(self):
        """La tâche (métrique) et le rapport de l'ancien juge ne sont lus que dans l'artefact de leur job."""
        with tempfile.TemporaryDirectory() as d:
            artefacts, propres = ecrire_etats(d, {e: "succes" for e in ETAPES})
            fichiers = (("etat-aaa", "tache.yaml", "metrique: ratio_n6\n"),
                        ("etat-aaa", "juge-ancien.json", json.dumps({"juge": {"version": 99}})),
                        ("etat-manifeste", "tache.yaml", "metrique: debit_compression_n6\n"),
                        ("juge", "juge.json", json.dumps(rapport_ab())))
            for dossier, nom, contenu in fichiers:
                os.makedirs(os.path.join(artefacts, dossier), exist_ok=True)
                if nom:
                    with open(os.path.join(artefacts, dossier, nom), "w") as f:
                        f.write(contenu)
            with open(os.path.join(d, "jobs.json"), "w") as f:
                json.dump(JOBS_OK, f)
            subprocess.run([sys.executable, VERDICT, "--artefacts", artefacts, "--etats", propres, "--jobs", os.path.join(d, "jobs.json"),
                            "--sortie", os.path.join(d, "v.json")], check=True, capture_output=True)
            with open(os.path.join(d, "v.json")) as f:
                v = json.load(f)
        self.assertEqual(v["metrique"], "debit_compression_n6")
        self.assertIsNone(v["details"]["juge_ancien"])

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
                commande += ["--jobs", os.path.join(d, "jobs.json")]
            subprocess.run(commande, check=True, capture_output=True)
            with open(os.path.join(d, "v.json")) as f:
                return json.load(f)

    def test_chaque_fichier_lu_a_la_racine_de_son_artefact(self):
        """Chaque fichier n'est lu qu'à la racine de l'artefact du job qui le produit : déposé dans un autre artefact
        (même rangé avant) ou dans un sous-dossier du bon artefact (rangé avant la racine), il est ignoré."""
        faux_tache, faux_ancien = "metrique: ratio_n6\n", json.dumps({"juge": {"version": 99}})
        fichiers = [("etat-manifeste/tache.yaml", "metrique: debit_compression_n6\n"),
                    ("etat-juge-ancien/juge-ancien.json", json.dumps({"juge": {"version": 2}})),
                    ("juge/juge.json", json.dumps(rapport_ab())),
                    ("etat-manifeste/etats/tache.yaml", faux_tache), ("etat-aaa/tache.yaml", faux_tache),
                    ("etat-juge-ancien/etats/juge-ancien.json", faux_ancien), ("etat-aaa/juge-ancien.json", faux_ancien),
                    ("etat-manifeste/etats/CONTRIBUTION.yaml", MANIFESTE_FR), ("etat-aaa/CONTRIBUTION.yaml", MANIFESTE_FR)]
        v = self.verdict_avec(fichiers, JOBS_OK)
        self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", "debit_compression_n6", 0.03))
        self.assertEqual(v["details"]["juge_ancien"]["juge"]["version"], 2)
        self.assertEqual(v["details"]["manifeste"], "absent")
        # Seulement dans un sous-dossier ou un autre artefact : la copie de la tâche manque, rouge (jamais la fausse).
        v = self.verdict_avec([f for f in fichiers if f[0] != "etat-manifeste/tache.yaml"], JOBS_OK)
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))

    def test_aucun_rapport_cherche_dans_les_artefacts(self):
        """Le rapport vient de --ab ou de juge.json à la racine de l'artefact « juge » ; hors CI non plus, un ab.json
        ou un juge.json déposé dans un autre artefact (ou un sous-dossier de « juge ») n'est jamais lu."""
        faux = json.dumps(rapport_ab(gain_n6=0.5))
        fichiers = [("etat-manifeste/tache.yaml", "metrique: debit_compression_n6\n"), ("etat-aaa/ab.json", faux),
                    ("x/ab.json", faux), ("etat-manifeste/ab.json", faux), ("etat-aaa/juge.json", faux),
                    ("juge/etats/juge.json", faux), ("juge/ab.json", faux)]
        for jobs in (None, JOBS_OK):
            with self.subTest(ci=jobs is not None):
                v = self.verdict_avec(fichiers, jobs)
                self.assertEqual((v["ci"], v["metrique"], v["gain"], v["juge"]), ("rouge", "debit_compression_n6", None, None))
                self.assertIsNone(v["mesures"]["B"]["debit_compression_n6"])
        v = self.verdict_avec(fichiers + [("juge/juge.json", json.dumps(rapport_ab())), ("juge/code", "0\n")], None)
        self.assertEqual((v["ci"], v["gain"]), ("verte", 0.03))

    def test_etat_lu_seulement_dans_le_dossier_de_son_job(self):
        """Chaque <etape>.txt n'est lu que dans le dossier d'état du job qui l'écrit : un « succes » déposé dans
        « juge », dans un autre artefact, dans le dossier d'un autre job, à la racine ou dans un sous-dossier du bon
        artefact ne remplace pas un état manquant (rouge, sans résultat) ; un état qui est un lien symbolique non plus."""
        base = [("etat-manifeste/tache.yaml", TACHE_SANS_METRIQUE), ("juge/juge.json", json.dumps(rapport_ab()))]
        self.assertEqual(self.verdict_avec(base, JOBS_OK)["ci"], "verte")  # le parcours honnête
        for manquante, proprietaire in DOSSIER_ETAT.items():
            autre = "etat-manifeste/etats" if proprietaire != "etat-manifeste/etats" else "etat-fuzzing"
            dossiers = ["juge", "etat-evil", "etat-evil/etats", "x/etats", autre, proprietaire + "/sous"]
            dossiers += [proprietaire.split("/")[0]] if "/" in proprietaire else []
            etats = {e: "succes" for e in ETAPES if e != manquante}
            with self.subTest(manquante=manquante):
                v = self.verdict_avec(base + [(f"{d}/{manquante}.txt", "succes\n") for d in dossiers], JOBS_OK, etats)
                self.assertEqual((v["ci"], v["etapes"][manquante]), ("rouge", "absent"))
                v = self.verdict_avec(base, JOBS_OK, etats, liens=[(f"{proprietaire}/{manquante}.txt", "succes\n")])
                self.assertEqual((v["ci"], v["etapes"][manquante]), ("rouge", "absent"))
        # « juges » et « amorcage », écrits par chaque job, ne se lisent pas non plus hors des dossiers d'état des jobs.
        v = self.verdict_avec(base + [("juge/amorcage.txt", "oui\n"), ("etat-evil/amorcage.txt", "oui\n")], JOBS_OK)
        self.assertFalse(v["amorcage"])
        v = self.verdict_avec(base + [("etat-fuzzing/amorcage.txt", "oui\n")], JOBS_OK)
        self.assertTrue(v["amorcage"])

    def test_lien_symbolique_jamais_lu(self):
        """La copie de la tâche, le rapport de l'ancien juge et celui du juge commun ne sont jamais lus à travers un
        lien symbolique, même à leur place et vers un contenu valide."""
        tache, ancien = "metrique: debit_compression_n6\n", json.dumps({"juge": {"version": 2}})
        honnete = [("etat-manifeste/tache.yaml", tache), ("etat-juge-ancien/juge-ancien.json", ancien),
                   ("juge/juge.json", json.dumps(rapport_ab()))]
        v = self.verdict_avec(honnete, JOBS_OK)
        self.assertEqual((v["ci"], v["metrique"], v["details"]["juge_ancien"]["juge"]["version"]), ("verte", "debit_compression_n6", 2))
        for i, (chemin, contenu) in enumerate(honnete):
            with self.subTest(lien=chemin):
                v = self.verdict_avec(honnete[:i] + honnete[i + 1:], JOBS_OK, liens=[(chemin, contenu)])
                if chemin == "etat-juge-ancien/juge-ancien.json":
                    self.assertIsNone(v["details"]["juge_ancien"])
                else:
                    self.assertEqual(v["ci"], "rouge")
                    self.assertEqual(v["etape_en_echec"], "Manifeste et taille" if "tache" in chemin else
                                     "Juge commun (vérification de l'extérieur et mesures)")

    def test_base_juge_publiee(self):
        """verdict.json publie le commit A du juge commun et la règle qui l'a choisi (revue adverse de miniz-0032)."""
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab())
        self.assertEqual(v["ci"], "verte")
        self.assertEqual(v["base_juge"], {"commit": DEPART, "regle": "point_de_depart", "depart": DEPART, "base": None})
        self.assertIsNone(self.executer({e: "succes" for e in ETAPES}, None, rapport_ab())["base_juge"])

    def test_jamais_vert_sans_a_verifiable(self):
        """Règle de refus, règle inconnue, commit ou point de départ illisible, point_de_depart dont A n'est pas le
        point de départ, introduction hors amorçage : rouge, même si tous les jobs et états disent succès
        (secondes revues adverses de miniz-0032, M-1)."""
        autre = "e" * 40
        for sorties in ({"base_juge": DEPART, "regle": "refus_rebase", "depart": DEPART},
                        {"base_juge": DEPART, "regle": "refus_point_de_depart", "depart": DEPART},
                        {"base_juge": DEPART, "regle": "base", "depart": DEPART},
                        {"base_juge": "HEAD", "regle": "point_de_depart", "depart": DEPART},
                        {"base_juge": autre, "regle": "point_de_depart", "depart": DEPART},
                        {"base_juge": autre, "regle": "point_de_depart"},
                        {"base_juge": DEPART, "regle": "point_de_depart", "depart": "HEAD"},
                        {"base_juge": autre, "regle": "introduction", "depart": DEPART}, {}):
            with self.subTest(sorties=sorties):
                v = self.executer({e: "succes" for e in ETAPES}, dict(JOBS_OK, greffon={"result": "success", "outputs": sorties}), rapport_ab())
                self.assertEqual(v["ci"], "rouge")
                self.assertEqual(v["etape_en_echec"], "Greffon du juge commun")

    def test_introduction_seulement_en_amorcage(self):
        autre = "e" * 40
        jobs = dict(JOBS_OK, greffon={"result": "success", "outputs": {"base_juge": autre, "regle": "introduction", "depart": DEPART}})
        v = self.executer(dict({e: "succes" for e in ETAPES}, amorcage="oui"), jobs, rapport_ab())
        self.assertEqual((v["ci"], v["amorcage"]), ("verte", True))

    def test_code_0_sans_jugement_rouge(self):
        """M-2 : un code 0 sans section juge, ou sans aucune sortie comparée, n'est pas un jugement."""
        sans_section = rapport_ab()
        del sans_section["juge"]
        zero = rapport_ab()
        zero["juge"]["verification"]["sorties_comparees"] = 0
        for rapport in (sans_section, zero):
            with self.subTest(juge=rapport.get("juge")):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport, "metrique: debit_compression_n6\n")
                self.assertEqual(v["ci"], "rouge")
                self.assertEqual(v["etape_en_echec"], "Juge commun (vérification de l'extérieur et mesures)")
        v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, None)
        self.assertEqual((v["ci"], v["juge"]), ("rouge", None))

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
            if not any("base" in str(e.get("with", {}).get("path", "")) or "base/" in e.get("run", "") for e in job["steps"]):
                self.assertEqual(nom, "outillage-pr")  # le seul job sans la base : il ne lance que les tests de la PR
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
        # Le commit du corpus est déclaré à juge.yml (juge-v2), qui le récupère avant la PR : celui du greffon en est
        # (l'ancien et le nouveau, le temps d'une PR qui le change, car le greffon qui juge est celui de la base).
        with open(os.path.join(os.path.dirname(ICI), "juge", "projet.py"), encoding="utf-8") as f:
            commit = re.search(r'^COMMIT_CORPUS = "([0-9a-f]{40})"$', f.read(), re.M).group(1)
        self.assertIn(commit, juge["with"]["historique"].split())
        extractions = [e for job in workflow["jobs"].values() for e in job.get("steps", [])
                       if e.get("with", {}).get("path") == "juge-commun"]
        self.assertEqual(len(extractions), 3)  # compilation et tests, fuzzing, méta-tests
        for e in extractions:
            self.assertEqual((e["with"]["repository"], e["with"]["ref"]), ("${{ env.REGISTRE }}", "${{ env.JUGE_COMMUN_SHA }}"))
        self.assertEqual(workflow["env"]["REGISTRE"], "Bee-ruche/registre")
        verdict = workflow["jobs"]["verdict"]
        self.assertEqual(set(verdict["needs"]), set(workflow["jobs"]) - {"verdict"})

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
        ce que le greffon lit dans A doit y être (SOURCES et EN_TETES_BASE dans miniz*, OUTILLAGE, CONSTRUIRE
        et le corpus dans bee/), sinon elle ne suit plus."""
        import ast
        import fnmatch
        with open(os.path.join(os.path.dirname(ICI), "juge", "projet.py"), encoding="utf-8") as f:
            arbre = ast.parse(f.read())
        classe = next(n for n in arbre.body if isinstance(n, ast.ClassDef) and n.name == "Projet")
        valeurs = {c.targets[0].id: ast.literal_eval(c.value) for c in classe.body
                   if isinstance(c, ast.Assign) and isinstance(c.targets[0], ast.Name) and c.targets[0].id in
                   ("SOURCES", "SOURCES_REQUISES", "EN_TETES_BASE", "OUTILLAGE", "CONSTRUIRE")}
        self.assertEqual(len(valeurs), 5)
        for cle in ("SOURCES", "SOURCES_REQUISES", "EN_TETES_BASE"):
            for motif in valeurs[cle]:
                self.assertTrue(fnmatch.fnmatchcase(motif, "miniz*") and "/" not in motif, (cle, motif))
        for chemin in list(valeurs["OUTILLAGE"]) + [valeurs["CONSTRUIRE"]]:
            self.assertTrue(chemin.startswith("bee/") and ".." not in chemin, chemin)
        chaines = {n.value for n in ast.walk(classe) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue({"bee/corpus/generer.py", "bee/corpus/donnees"} <= chaines)
        etape = next(e for e in self.charger_workflow()["jobs"]["greffon"]["steps"] if e.get("id") == "greffon")
        self.assertIn("git -C pr diff --quiet \"$depart\" \"$BASE_SHA\" -- bee 'miniz*'", etape["run"])

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

    def test_point_de_depart_si_ni_bee_ni_miniz_n_ont_change(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("readme.md", "doc\n")  # la base avance sans rien de ce que le juge lit dans A
        base = self.commit("base")
        self.assertEqual(self.lancer(base, tete, "base")[:3], (0, self.depart, "succes"))
        self.assertEqual((self.sorties["regle"], self.sorties["depart"]), ("point_de_depart", self.depart))

    def test_rouge_si_miniz_a_change_sur_la_base(self):
        self.git("checkout", "-q", "-b", "pr")
        self.ecrire("miniz.c", "int y;\n")
        tete = self.commit("pr")
        self.git("checkout", "-q", "master")
        self.ecrire("miniz_tdef.c", "int z;\n")
        base = self.commit("base")
        code, base_juge, etat, sortie = self.lancer(base, tete, "base")
        self.assertEqual((code, base_juge, etat, self.sorties["regle"]), (1, None, "echec", "refus_rebase"))
        self.assertIn("rebasez-la sur master", sortie)

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
        self.assertIn("rebasez-la sur master", sortie)

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
                self.assertIn("pas un seul point de départ", sortie)

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
                self.assertIn("::error::bee/ ou miniz a changé sur master", sortie)
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


# --- miniz-0049 : le registre et les manifestes dans les deux vocabulaires (français, anglais), avant la bascule. ---
# Données écrites à la main dans chaque vocabulaire (docs/english-names.md du registre), jamais dérivées des cartes de
# bee/ci/vocabulaire.py : les tests vérifient les cartes, ils ne les recopient pas.
MANIFESTE = os.path.join(ICI, "manifeste.sh")
TACHE_FR = """id: miniz-0050
projet: miniz
type: optimisation
taille: S
titre: essai
metrique: debit_decompression
sortie_compressee: peut_changer
statut: reservee
"""
TACHE_EN = """id: miniz-0050
project: miniz
type: optimization
size: S
title: essai
metric: debit_decompression
compressed_output: may_change
status: reserved
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
measurements: {machine: x, command: y, repetitions: 3, before: {debit_decompression: 400}, after: {debit_decompression: 420}}
tested: [a]
untested: [b]
doubts: d
actual_size: S
"""
OPTIONS_FR = ("--tache", "--base", "--tete", "--depot", "--auteur")
OPTIONS_EN = ("--task", "--base", "--head", "--repo", "--author")
# Faux outil du registre, construit avec argparse comme le vrai : son aide nomme aussi, dans ses textes, les noms de
# l'autre vocabulaire, que seule la ligne d'usage doit compter. Il note ses appels (hors --help) dans journal.jsonl.
FAUX_OUTIL = '''import argparse, json, os, sys
ici = os.path.dirname(os.path.abspath(__file__))
p = argparse.ArgumentParser(prog="bee", description="Outil (verifier-fork, check-fork, --tache, --task, --registre, --registry).")
p.add_argument("--version", action="version", version="bee 0")
p.add_argument(GLOBALE, help="chemin du registre (ancien nom : --registre ; nouveau : --registry ; $BEE_REGISTRE)")
sous = p.add_subparsers(dest="commande", metavar="commande")
sous.add_parser("lister", help="liste ; voir aussi verifier-fork et check-fork")
for nom, options in COMMANDES:
    s = sous.add_parser(nom, help="vérifie une branche (" + nom + ")", description="--tache --task --tete --head --depot --repo")
    for o in options or ():
        s.add_argument(o, required=o in ("--tache", "--task", "--base"), help="aussi --tache --task --auteur --author")
a = p.parse_args()
with open(os.path.join(ici, "journal.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "BEE_REGISTRE": os.environ.get("BEE_REGISTRE"),
                        "BEE_REGISTRY": os.environ.get("BEE_REGISTRY")}) + "\\n")
sys.exit(int(open(os.path.join(ici, "code")).read()) if os.path.exists(os.path.join(ici, "code")) else 0)
'''


def faux_outil(globale, commandes):
    return f"GLOBALE = {globale!r}\nCOMMANDES = {commandes!r}\n" + FAUX_OUTIL


OUTIL_FR = faux_outil("--registre", [("verifier-fork", OPTIONS_FR)])
OUTIL_EN = faux_outil("--registry", [("check-fork", OPTIONS_EN)])


def vocabulaire():
    sys.path.insert(0, ICI)
    try:
        import vocabulaire as module
    finally:
        sys.path.remove(ICI)
    return module


class Vocabulaire(unittest.TestCase):
    """bee/ci/vocabulaire.py : tâche et manifeste lus dans les deux vocabulaires, un seul par document."""

    def setUp(self):
        import yaml
        self.v = vocabulaire()
        self.yaml = yaml.safe_load

    def test_cartes_bijectives_et_disjointes(self):
        """Un nom n'est jamais des deux vocabulaires à la fois : sinon un document ne serait pas classable."""
        v = self.v
        for carte in (v.CLES_TACHE, v.CLES_MANIFESTE, v.CLES_AGENT, v.CLES_MESURES, v.SORTIES):
            self.assertEqual(len(set(carte.values())), len(carte))
            self.assertFalse(set(carte) & set(carte.values()), carte)
        types = dict(v.TYPES)
        self.assertEqual(types.pop("test"), "test")
        self.assertFalse(set(types) & set(types.values()))

    def test_tache_dans_les_deux_vocabulaires(self):
        attendu = {"type": "optimisation", "metrique": "debit_decompression", "sortie_compressee": "peut_changer"}
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_FR)), attendu)
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN)), attendu)
        for fr, en in (("optimisation", "optimization"), ("relecture", "review"), ("mesure", "measurement"),
                       ("test", "test"), ("decoupage", "split")):
            with self.subTest(type=en):
                self.assertEqual(self.v.lire_tache(self.yaml(TACHE_FR.replace("optimisation", fr)))["type"], fr)
                self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN.replace("optimization", en)))["type"], fr)
        sans_sortie = self.v.lire_tache(self.yaml(TACHE_EN.replace("compressed_output: may_change\n", "")))
        self.assertEqual(sans_sortie["sortie_compressee"], "identique")  # absente : le contrôle le plus strict
        for texte in (TACHE_EN.replace("metric: debit_decompression", "metric: null").replace("optimization", "test"),
                      TACHE_FR.replace("metrique: debit_decompression", "metrique: null").replace("optimisation", "mesure")):
            nulle = self.v.lire_tache(self.yaml(texte))
            self.assertIsNone(nulle["metrique"])  # la tâche dit explicitement qu'elle n'a pas de métrique

    def test_tache_melee_refusee(self):
        for texte in (TACHE_FR.replace("statut: reservee", "status: reserved"),
                      TACHE_FR + "metric: debit_decompression\n",
                      TACHE_EN.replace("compressed_output: may_change", "sortie_compressee: peut_changer"),
                      TACHE_EN.replace("type: optimization", "type: optimisation"),  # valeur de l'autre vocabulaire
                      TACHE_EN.replace("may_change", "peut_changer"),
                      TACHE_FR.replace("type: optimisation", "type: split")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte))

    def test_tache_type_ou_metrique_illisible(self):
        """Jamais une valeur par défaut : type absent ou inconnu, clé de métrique absente, métrique inconnue."""
        for texte in (TACHE_FR.replace("type: optimisation\n", ""), TACHE_EN.replace("optimization", "rapide"),
                      TACHE_FR.replace("metrique: debit_decompression\n", ""),
                      TACHE_EN.replace("metric: debit_decompression\n", ""),
                      TACHE_EN.replace("debit_decompression", "vitesse"), TACHE_FR.replace("debit_decompression", "[ratio_n6]"),
                      "id: miniz-0050\ntype: test\n", "- liste\n", "",
                      # revue adverse (M1) : une optimisation sans métrique n'a rien que R4 puisse juger
                      TACHE_EN.replace("metric: debit_decompression", "metric: null"),
                      TACHE_FR.replace("metrique: debit_decompression", "metrique: null")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte))
        with self.assertRaises(self.v.Illisible):
            self.v.metrique_de_la_tache(self.yaml("type: test\nstatus: open\n"))

    def test_manifeste_dans_les_deux_vocabulaires(self):
        fr, en = self.v.lire_manifeste(self.yaml(MANIFESTE_FR)), self.v.lire_manifeste(self.yaml(MANIFESTE_EN))
        self.assertEqual(fr, en)
        self.assertEqual(fr, self.yaml(MANIFESTE_FR))
        self.assertEqual(en["mesures"]["avant"], {"debit_decompression": 400})

    def test_manifeste_mele_refuse(self):
        """Un seul vocabulaire par manifeste, à tous ses niveaux (agent, mesures)."""
        for texte in (MANIFESTE_FR.replace("resume: r", "summary: r"), MANIFESTE_EN.replace("doubts: d", "doutes: d"),
                      MANIFESTE_FR.replace("avant:", "before:"), MANIFESTE_FR.replace("modele:", "model:"),
                      MANIFESTE_EN.replace("command:", "commande:"), MANIFESTE_FR + "measurements: {}\n"):
            with self.subTest(manifeste=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_manifeste(self.yaml(texte))


class JobManifeste(unittest.TestCase):
    """bee/ci/manifeste.sh de bout en bout (tache.py, verifier_fork.py), sur un petit dépôt git et un faux registre
    dans chaque disposition : tâches, outil, commande, options et manifeste lus dans les deux vocabulaires."""

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

    def lancer(self, manifestes, taches=(("taches", TACHE_FR),), outils=(("outils", OUTIL_FR),), liens=()):
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
                   BEE_SORTIE_TACHE=copie, BEE_REGISTRE="/ailleurs", BEE_REGISTRY="/ailleurs")
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

    def appel(self, globale, commande, options):
        valeurs = ("miniz-0050", self.base, self.tete, self.pr, "abeille")
        return [globale, self.registre, commande] + [x for paire in zip(options, valeurs) for x in paire]

    def test_registre_et_manifeste_francais(self):
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)])
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.journal, [{"argv": self.appel("--registre", "verifier-fork", OPTIONS_FR),
                                         "BEE_REGISTRE": self.registre, "BEE_REGISTRY": None}])
        self.assertEqual(self.sorties, {"tache": "miniz-0050", "type": "optimisation", "metrique": "debit_decompression",
                                        "sortie_compressee": "peut_changer", "manifeste": "manifestes/miniz-0050.yaml"})
        self.assertEqual(self.copie, TACHE_FR)  # la copie lue par verdict.py : la tâche telle quelle

    def test_registre_et_manifeste_anglais(self):
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], taches=(("tasks", TACHE_EN),),
                                   outils=(("tools", OUTIL_EN),))
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.journal, [{"argv": self.appel("--registry", "check-fork", OPTIONS_EN),
                                         "BEE_REGISTRE": None, "BEE_REGISTRY": self.registre}])
        # Valeurs ramenées aux noms internes (la CI les passe au juge commun épinglé, qui parle français).
        self.assertEqual(self.sorties, {"tache": "miniz-0050", "type": "optimisation", "metrique": "debit_decompression",
                                        "sortie_compressee": "peut_changer", "manifeste": "manifests/miniz-0050.yaml"})
        self.assertEqual(self.copie, TACHE_EN)

    def test_dossier_et_vocabulaire_du_manifeste_independants(self):
        for manifeste, taches, outils in ((("manifests/miniz-0050.yaml", MANIFESTE_FR), (("taches", TACHE_FR),), (("outils", OUTIL_FR),)),
                                          (("manifestes/miniz-0050.yaml", MANIFESTE_EN), (("tasks", TACHE_EN),), (("tools", OUTIL_EN),))):
            with self.subTest(manifeste=manifeste[0]):
                self.setUp()
                code, sortie = self.lancer([manifeste], taches, outils)
                self.assertEqual((code, len(self.journal), self.sorties["manifeste"]), (0, 1, manifeste[0]), sortie)

    def test_manifeste_mele_refuse(self):
        for texte in (MANIFESTE_EN.replace("summary: r", "resume: r"), MANIFESTE_FR.replace("avant:", "before:")):
            with self.subTest(manifeste=texte):
                self.setUp()
                code, sortie = self.lancer([("manifests/miniz-0050.yaml", texte)])
                self.assertEqual((code, self.journal, self.sorties["sortie_compressee"]), (1, [], "identique"), sortie)
                self.assertIn("mêle les deux vocabulaires", sortie)

    def test_tache_type_ou_metrique_illisible_echoue(self):
        """Le job échoue, sans appeler l'outil ni écrire la copie de la tâche : jamais un défaut."""
        for dossier, texte in (("tasks", TACHE_EN.replace("type: optimization\n", "")),
                               ("taches", TACHE_FR.replace("optimisation", "inconnu")),
                               ("tasks", TACHE_EN.replace("metric: debit_decompression\n", "")),
                               ("taches", TACHE_FR.replace("metrique: debit_decompression\n", "")),
                               ("tasks", TACHE_EN.replace("debit_decompression", "vitesse")),
                               ("tasks", TACHE_EN.replace("compressed_output: may_change", "sortie_compressee: peut_changer")),
                               ("taches", TACHE_FR.replace("optimisation", "optimization")), ("tasks", "- pas un objet\n"),
                               ("tasks", TACHE_EN.replace("metric: debit_decompression", "metric: null")),
                               ("taches", TACHE_FR.replace("metrique: debit_decompression", "metrique: null"))):
            with self.subTest(dossier=dossier, tache=texte):
                self.setUp()
                code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], taches=((dossier, texte),))
                self.assertEqual((code, self.journal, self.copie), (1, [], None), sortie)
                self.assertNotIn("metrique", self.sorties)

    def test_tache_introuvable_ou_dans_les_deux_dispositions(self):
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], taches=())
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("introuvable", sortie)
        self.setUp()
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], taches=(("taches", TACHE_FR), ("tasks", TACHE_EN)))
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("plusieurs fois", sortie)

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
                self.assertIn("doit être un fichier ordinaire", sortie)
        self.setUp()  # le parcours honnête, à côté : un fichier ordinaire passe
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, len(self.journal)), (0, 1), sortie)

    def test_tache_py_n_ouvre_qu_un_fichier_ordinaire(self):
        """tache.py, appelé seul, refuse lui aussi un lien symbolique (même vers un manifeste valide, même cassé) ou un
        dossier, sans trace d'exception ni copie de la tâche, avec le contrôle le plus strict en sortie."""
        self.ecrire(self.registre, "taches/miniz/miniz-0050.yaml", TACHE_FR)
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
                    self.assertIn("doit être un fichier ordinaire", r.stderr)
                    self.assertEqual(r.stdout, "sortie_compressee=identique\n")

    def test_deux_manifestes_refuses(self):
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN), ("manifestes/miniz-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("plusieurs manifestes", sortie)

    def test_un_seul_outil(self):
        for outils in ((("outils", OUTIL_FR), ("tools", OUTIL_EN)), ()):
            with self.subTest(outils=[o for o, _ in outils]):
                self.setUp()
                code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], outils=outils)
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("exactement un outil", sortie)

    def test_commande_et_options_demandees_a_l_aide(self):
        """Jamais deviné : une commande sans les options voulues (un relais qui refuse l'ancien nom, par exemple)
        est écartée ; deux commandes complètes, aucune, une option dans les deux noms ou absente : échec."""
        bascule = faux_outil("--registry", [("verifier-fork", None), ("check-fork", OPTIONS_EN)])
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], outils=(("tools", bascule),))
        self.assertEqual(code, 0, sortie)
        self.assertEqual([a["argv"] for a in self.journal], [self.appel("--registry", "check-fork", OPTIONS_EN)])
        melee = faux_outil("--registre", [("check-fork", ("--tache", "--base", "--head", "--depot", "--author"))])
        self.setUp()
        code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], outils=(("outils", melee),))
        self.assertEqual(code, 0, sortie)  # l'aide annonce ces noms-là : ce sont eux qu'on passe
        self.assertEqual([a["argv"] for a in self.journal],
                         [self.appel("--registre", "check-fork", ("--tache", "--base", "--head", "--depot", "--author"))])
        for outil in (faux_outil("--registre", [("verifier-fork", OPTIONS_FR), ("check-fork", OPTIONS_EN)]),
                      faux_outil("--registre", []),
                      faux_outil("--registre", [("check-fork", OPTIONS_EN + ("--tache",))]),
                      faux_outil("--registre", [("check-fork", OPTIONS_EN[:4])]),
                      faux_outil("--registre", [("verifier-fork", OPTIONS_FR[:2] + OPTIONS_FR[3:])]),
                      faux_outil("--chemin", [("verifier-fork", OPTIONS_FR)])):
            with self.subTest(outil=outil.splitlines()[:2]):
                self.setUp()
                code, sortie = self.lancer([("manifestes/miniz-0050.yaml", MANIFESTE_FR)], outils=(("outils", outil),))
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("::error::verifier_fork.py", sortie)

    def test_code_de_l_outil_rendu(self):
        self.ecrire(self.registre, "tools/code", "1\n")
        code, sortie = self.lancer([("manifests/miniz-0050.yaml", MANIFESTE_EN)], taches=(("tasks", TACHE_EN),),
                                   outils=(("tools", OUTIL_EN),))
        self.assertEqual((code, len(self.journal)), (1, 1), sortie)


class DeuxVocabulairesDansLeVerdict(unittest.TestCase):
    """verdict.py : la métrique de la copie de la tâche, en anglais ou en français ; illisible, jamais un défaut."""

    executer = Verdict.executer

    def test_metrique_de_la_tache_dans_les_deux_vocabulaires(self):
        for tache in (TACHE_EN, TACHE_FR):
            with self.subTest(tache=tache):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), tache.replace("debit_decompression", "debit_compression_n6"))
                self.assertEqual((v["ci"], v["metrique"], v["gain"], v["au_dela_du_bruit"]), ("verte", "debit_compression_n6", 0.03, True))
                self.assertEqual(v["details"]["origine_metrique"], "tâche du registre")

    def test_tache_illisible_rend_rouge(self):
        """Copie absente en CI, mêlée, sans clé de métrique, métrique inconnue, pas un objet : rouge, et la PR ne
        choisit pas la métrique (le manifeste en désigne une)."""
        for tache in (None, "type: test\n", "metric: vitesse\n", "metrique: debit_compression_n6\nmetric: debit_compression_n6\n",
                      "metric: debit_compression_n6\nstatut: ouverte\n", "- debit_compression_n6\n", "id: miniz-0050\ntype: test\n"):
            with self.subTest(tache=tache):
                v = self.executer({e: "succes" for e in ETAPES}, JOBS_OK, rapport_ab(), tache, manifeste=MANIFESTE_EN.replace("debit_decompression", "debit_compression_n6"))
                self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"], v["gain"]), ("rouge", "Manifeste et taille", None, None))
                self.assertTrue(v["details"]["origine_metrique"].startswith("illisible"))

    def test_metrique_null_jamais_celle_du_manifeste(self):
        manifeste = MANIFESTE_FR.replace("debit_decompression", "debit_compression_n6")
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                tache = TACHE_EN.replace("metric: debit_decompression", "metric: null").replace("optimization", "test")
                v = self.executer({e: "succes" for e in ETAPES}, jobs, rapport_ab(), tache, manifeste=manifeste, code=None if jobs else "0")
                self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", None, None))

    def test_simulation_sans_tache_lit_le_manifeste(self):
        """Hors CI seulement, sans copie de la tâche : le manifeste, dans un seul vocabulaire."""
        for manifeste in (MANIFESTE_EN, MANIFESTE_FR, "metric: debit_compression_n6\ntask: miniz-0050\n"):
            with self.subTest(manifeste=manifeste):
                v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), None, code="0",
                                  manifeste=manifeste.replace("debit_decompression", "debit_compression_n6"))
                self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", "debit_compression_n6", 0.03))
        v = self.executer({e: "succes" for e in ETAPES}, None, rapport_ab(), None, code="0", manifeste=MANIFESTE_EN.replace("before:", "avant:"))
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))

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
                self.assertEqual(json.load(f)["lignes_modifiees"], 2)


class DependancesDeLOutil(unittest.TestCase):
    """Étape « Dépendances de l'outil bee » du job manifeste : le fichier d'exigences qui existe, un seul."""

    def lancer(self, fichiers):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        script = next(e["run"] for e in etapes if e.get("name", "").startswith("Dépendances de l'outil bee"))
        with tempfile.TemporaryDirectory() as d:
            for chemin in fichiers:
                os.makedirs(os.path.join(d, os.path.dirname(chemin)), exist_ok=True)
                open(os.path.join(d, chemin), "w").write("pyyaml>=6\n")
            os.makedirs(os.path.join(d, "bin"))
            with open(os.path.join(d, "bin", "pip"), "w") as f:
                f.write('#!/bin/sh\necho "$@" > "$(dirname "$0")/../appel"\n')
            os.chmod(os.path.join(d, "bin", "pip"), 0o755)
            env = dict(os.environ, PATH=os.path.join(d, "bin") + os.pathsep + os.environ["PATH"])
            r = subprocess.run(["bash", "-e", "-c", script], cwd=d, capture_output=True, text=True, env=env)
            appel = open(os.path.join(d, "appel")).read().strip() if os.path.exists(os.path.join(d, "appel")) else None
        return r.returncode, appel, r.stderr

    def test_le_fichier_qui_existe(self):
        self.assertEqual(self.lancer(["registre/outils/requirements.txt"])[:2], (0, "install -r registre/outils/requirements.txt"))
        self.assertEqual(self.lancer(["registre/tools/requirements.txt"])[:2], (0, "install -r registre/tools/requirements.txt"))

    def test_aucun_ou_deux_echoue(self):
        for fichiers in ([], ["registre/outils/requirements.txt", "registre/tools/requirements.txt"]):
            with self.subTest(fichiers=fichiers):
                code, appel, erreur = self.lancer(fichiers)
                self.assertEqual((code, appel), (1, None))
                self.assertIn("::error::", erreur)


class ConserverLeManifeste(unittest.TestCase):
    """Étape « Conserver le manifeste, la tâche et l'état » du job manifeste, extraite telle quelle : seul un manifeste
    au nom validé et qui est un fichier ordinaire est copié dans l'artefact etat-manifeste (ni lien, ni dossier)."""

    def test_seul_un_fichier_ordinaire_au_nom_valide_est_copie(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        scripts = [e["run"] for e in etapes if e.get("name", "").startswith("Conserver le manifeste")]
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
