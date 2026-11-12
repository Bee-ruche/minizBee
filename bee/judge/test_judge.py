#!/usr/bin/env python3
"""Tests of minizBee's plugin for the Bee common judge (bee/judge/project.py, build.sh, execution.c).

  python3 bee/judge/test_judge.py                   unit tests (without Docker)
  BEE_JUDGE_INTEGRATION=1 python3 bee/judge/test_judge.py
                                                    + meta-tests: the common judge, with THIS plugin, against honest
                                                      and MALICIOUS variants of miniz (Docker required)
  BEE_COMMON_JUDGE=<registry>/tools/judge           the common judge, at the commit pinned by
                                                    .github/workflows/bee-ci.yml (judge-v4); by default,
                                                    ../registre/tools/judge next to this repository
  BEE_JUDGE_NETWORK=host                            network of « docker build » (machines without a Docker bridge)
  bee/sandbox/sans-docker.sh env BEE_HARNESS_SANDBOX=1 python3 bee/judge/test_judge.py
                                                    + the harness built by build.sh and run here, without
                                                      Docker: ONLY in the sandbox (it also checks it has no network
                                                      interface but lo); never on the CI machine

The plugin and the harness tested are THIS repository's (the PR's, when the CI runs these tests); the common judge is
the registry's. The malicious variants are written here, as transformations of the text of miniz.c, and are compiled
and run only INSIDE the judge's container. Each one targets a way of fooling a judge that would run the PR's code in
its own process:
  sortie_anticipee   the program exits « successfully » in the middle of the tests
  faux_chronos       the code replaces clock_gettime to report flattering times, and it is slower
  table_precalculee  the compressor works only on the inputs it knows in advance (the corpus)
  requete_valgrind   the code suspends Valgrind's instruction count during its own work
  faux_resume        the code writes a fake « I refs » summary on standard error
  travail_deplace    the code does its initialization in mz_compressBound, which the harness calls before the
                     compressions (adversarial review of 27/10: +1.7 to +27% instructions « gained » as long as only
                     a zone of the harness was counted)
  mesure_devinee     the code guesses from its own calls that it is measured (its first mz_compress2 is not at
                     level 0), and then compresses at level 1 whatever level it is given: faster and worse, yet
                     still correct, with sortie_compressee=peut_changer (juge-v3 on: refused, because a verification
                     input mixed into n6 or n9 must give its verification output, byte for byte)
  honnete            miniz as it is: accepted, nothing suspicious, identical counts for A and B
"""

import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(os.path.dirname(ICI))
JUGE_COMMUN = os.path.abspath(os.environ.get("BEE_COMMON_JUDGE") or os.path.join(os.path.dirname(RACINE), "registre", "tools", "judge"))
if not os.path.isfile(os.path.join(JUGE_COMMUN, "judge.py")):
    sys.exit(f"common judge not found in {JUGE_COMMUN}: BEE_COMMON_JUDGE=<registry>/tools/judge "
             "(at the commit pinned by .github/workflows/bee-ci.yml)")
sys.path.insert(0, JUGE_COMMUN)
import judge as juge_commun  # noqa: E402
import lecture  # noqa: E402
from entrees import Entree  # noqa: E402

_spec = importlib.util.spec_from_file_location("greffon_minizbee", os.path.join(ICI, "project.py"))
greffon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(greffon)

# Empreinte des entrées que le juge isolé de miniz-0031 (juge v2, bee/juge/juge.py jusqu'à miniz-0032) tirait
# de la graine 00320000b5e0c0de0032b5e0c0de2026 sur le petit corpus de TestIdentiqueAuJugeV2 : vérification
# (aléatoires et flux zlib), une répétition perturbée, puis les entrées du décompte d'instructions (préfixe de
# 1000 octets), avec ZlibFactice à la place de la zlib de l'hôte dans les deux juges. Calculée avec le juge v2
# sous Python 3.11, 3.12 et 3.13 (identique).
EMPREINTE_JUGE_V2 = "1fd4df9a7777b1f5cfacdb01da69e36d94329ff08a20eac0d57652e9b9335073"


class ZlibFactice:
    """zlib déterministe et portable, pour l'empreinte seulement. Les flux de la vraie zlib changent avec sa
    version (la CI de miniz-0032 l'a montré), et la longueur d'un flux décide des tirages suivants
    (randrange) : avec elle, l'empreinte ne vaudrait que sur une machine. Avec celle-ci, elle ne dépend que
    de la graine et de l'ordre des tirages, ce qui est exactement ce qu'on veut comparer au juge v2."""
    Z_DEFAULT_STRATEGY, Z_FILTERED, Z_HUFFMAN_ONLY, Z_RLE, Z_FIXED = 0, 1, 2, 3, 4
    DEFLATED = 8
    Z_NO_FLUSH, Z_SYNC_FLUSH, Z_FULL_FLUSH, Z_FINISH = 0, 2, 3, 4
    error = zlib.error

    @staticmethod
    def octets(etiquette, parametres, donnees):
        h = hashlib.sha256(repr((etiquette, parametres)).encode() + donnees).digest()
        return h[:4 + len(donnees) % 29]

    def compress(self, donnees, niveau=-1):
        return b"\x78" + self.octets("c", niveau, donnees)

    def compressobj(self, *parametres):
        octets = self.octets

        class Flux:
            def compress(self, donnees):
                return octets("o", parametres, donnees)

            def flush(self, mode=4):
                return octets("f", (parametres, mode), b"")
        return Flux()


# ------------------------------------------------------------------ tests unitaires

class TestContrat(unittest.TestCase):
    def test_greffon_charge_par_le_juge_commun(self):
        projet, empreinte = juge_commun.load_plugin(RACINE, {})
        with open(os.path.join(ICI, "project.py"), "rb") as f:
            self.assertEqual(empreinte, hashlib.sha256(f.read()).hexdigest())
        self.assertIsInstance(projet, juge_commun.EnglishPlugin)  # the English contract (judge-v4, miniz-0050)
        self.assertEqual(projet.NAME, "miniz")
        self.assertEqual(projet.SCENARIOS, {"n1": "f", "n6": "f", "n9": "f", "decompression": "z", "memoire": "f"})
        self.assertEqual(projet.INSTRUCTIONS, ("n1", "n6", "n9", "decompression"))
        self.assertEqual(projet.METRICS,
                         [("compression_throughput_n1", "higher", "MB/s"), ("compression_throughput_n6", "higher", "MB/s"),
                          ("compression_throughput_n9", "higher", "MB/s"), ("decompression_throughput", "higher", "MB/s"),
                          ("ratio_n6", "higher", "ratio"), ("max_memory_kb", "lower", "KB")])
        self.assertEqual([d for _, d, _ in projet.METRIQUES], ["plus_haut"] * 5 + ["plus_bas"])  # as the judge reads them
        self.assertEqual(projet.VERIFICATION, {"sortie_compressee": "identique"})
        self.assertIn("timed outputs of scenario n6", projet.METHOD["ratio_n6"])
        self.assertEqual(set(projet.METHOD), {"max_memory_kb", "ratio_n6"})

    def test_options(self):
        projet, _ = juge_commun.load_plugin(RACINE, {"sortie_compressee": "peut_changer"})
        self.assertFalse(projet.identique)
        for options in ({"sortie_compressee": "parfois"}, {"inconnue": "1"}):
            with self.assertRaises(lecture.Erreur, msg=str(options)):
                juge_commun.load_plugin(RACINE, options)

    def test_sources_et_objets(self):
        """Seuls miniz.c, miniz_tdef.c et miniz_tinfl.c sont compilés : un objet chacun, miniz_zip.c n'est pas copié."""
        projet, _ = juge_commun.load_plugin(RACINE, {})
        destination = tempfile.mkdtemp()
        try:
            juge_commun.copy_sources(RACINE, destination, projet.SOURCES, projet.REQUIRED_SOURCES)
            self.assertEqual(juge_commun.expected_objects(destination), ({"miniz.o", "miniz_tdef.o", "miniz_tinfl.o"}, []))
            self.assertIn("miniz.h", os.listdir(destination))
            self.assertNotIn("miniz_zip.c", os.listdir(destination))
        finally:
            shutil.rmtree(destination)


class TestEntrees(unittest.TestCase):
    def test_graine_reproductible_et_imprevisible(self):
        corpus = [("k000", b"abc" * 1000)]
        a = greffon.entrees_aleatoires(random.Random(1), corpus)
        b = greffon.entrees_aleatoires(random.Random(1), corpus)
        c = greffon.entrees_aleatoires(random.Random(2), corpus)
        self.assertEqual(a, b)
        self.assertNotEqual([d for _, d in a], [d for _, d in c])
        self.assertIn(b"", [d for _, d in a])

    def test_flux_valides(self):
        originaux = [("x", b""), ("y", b"bonjour " * 5000), ("z", bytes(range(256)) * 50)]
        for nom, z, taille, original in greffon.flux_zlib(random.Random(3), originaux):
            if original is not None:
                self.assertEqual(greffon.decompresser_zlib(z), original, nom)
                self.assertEqual(taille, len(original))

    def test_decompresser_zlib_refuse_les_flux_incomplets(self):
        z = zlib.compress(b"x" * 1000)
        self.assertEqual(greffon.decompresser_zlib(z), b"x" * 1000)
        self.assertIsNone(greffon.decompresser_zlib(z[:-1]))
        self.assertIsNone(greffon.decompresser_zlib(z + b"\x00"))


class TestIdentiqueAuJugeV2(unittest.TestCase):
    """À graine égale, le greffon tire exactement les entrées du juge v2 (miniz-0031), dans le même ordre."""

    CORPUS = [("k000", b"abc" * 30000), ("k001", bytes(range(256)) * 400), ("k002", b""), ("k003", b"le juge commun " * 9000)]

    def test_memes_entrees(self):
        projet = greffon.Project({})
        rng = random.Random(int.from_bytes(bytes.fromhex("00320000b5e0c0de0032b5e0c0de2026"), "big"))
        h = hashlib.sha256()
        vraie_zlib, greffon.zlib = greffon.zlib, ZlibFactice()
        try:
            verification = projet.verification(rng, self.CORPUS)
            etapes = (projet.repetition(rng, self.CORPUS), projet.instructions(rng, self.CORPUS, 1000))
        finally:
            greffon.zlib = vraie_zlib
        for e in verification:
            if e.cote == "f":
                self.assertEqual((e.taille, e.attendu), (len(e.donnees), e.donnees))
                h.update(e.nom.encode() + len(e.donnees).to_bytes(8, "little") + e.donnees)
        for e in verification:
            if e.cote == "z":
                h.update(e.nom.encode() + len(e.donnees).to_bytes(8, "little") + e.donnees + e.taille.to_bytes(8, "little")
                         + (b"-" if e.attendu is None else hashlib.sha256(e.attendu).digest()))
        for etape in etapes:
            fichiers = [e for e in etape if e.cote == "f"]
            flux = [e for e in etape if e.cote == "z"]
            self.assertEqual([e.nom for e in fichiers], [e.nom for e in flux])
            for f, z in zip(fichiers, flux):
                self.assertEqual((z.attendu, z.taille), (f.donnees, len(f.donnees)))
                h.update(f.nom.encode() + f.donnees + z.donnees)
        self.assertEqual(h.hexdigest(), EMPREINTE_JUGE_V2)

    def test_flux_des_mesures(self):
        """Avec la vraie zlib, les flux des mesures redonnent les fichiers perturbés qu'ils accompagnent."""
        projet = greffon.Project({})
        for etape in (projet.repetition(random.Random(7), self.CORPUS), projet.instructions(random.Random(7), self.CORPUS, 1000)):
            fichiers = {e.nom: e.donnees for e in etape if e.cote == "f"}
            for e in etape:
                if e.cote == "z":
                    self.assertEqual(zlib.decompress(e.donnees), fichiers[e.nom])


def ecrire_sorties(dossier, fichiers):
    """Writes {(side, relative path): bytes} under dossier/<side>/; returns the Sorties view the plugin gets."""
    racines = {c: os.path.join(dossier, c) for c in "fz"}
    for (cote, relatif), octets in fichiers.items():
        chemin = os.path.join(racines[cote], relatif)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "wb") as f:
            f.write(octets)
    return lecture.Sorties(racines)


def sorties_de_verification(donnees):
    """Verification outputs for an input f « k000 » and a valid stream z « z000 » of `donnees` (bee/judge/execution.c)."""
    fichiers = {("f", f"c/k000.{niveau}"): zlib.compress(donnees, min(niveau, 9)) for niveau in greffon.NIVEAUX_UNIQUE}
    fichiers.update({("f", f"s/k000.{niveau}"): zlib.compress(donnees, niveau) for niveau in greffon.NIVEAUX_FLUX})
    fichiers[("f", "m/k000")] = zlib.compress(donnees, 6)
    n = len(donnees)
    fichiers.update({("z", "e/z000"): f"0 {n}\n".encode(), ("z", "d/z000"): donnees,
                     ("z", "es/z000"): f"1 {n}\n".encode(), ("z", "ds/z000"): donnees})
    return fichiers


class TestVerification(unittest.TestCase):
    """La règle de justesse, sur des sorties écrites à la main (sans Docker)."""

    DONNEES = b"le greffon ne croit que la base et la zlib de l'hote " * 300

    def setUp(self):
        self.travail = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.travail)

    def sorties(self, nom, modifier=None):
        """Sorties d'une variante pour une entrée f « k000 » et un flux z « z000 » (valide)."""
        fichiers = sorties_de_verification(self.DONNEES)
        if modifier:
            modifier(fichiers)
        return ecrire_sorties(os.path.join(self.travail, nom), fichiers)

    def entrees(self):
        return [Entree("f", "k000", self.DONNEES, len(self.DONNEES), self.DONNEES),
                Entree("z", "z000", zlib.compress(self.DONNEES), len(self.DONNEES), self.DONNEES)]

    def test_identique_accepte(self):
        b = self.sorties("B")
        self.assertEqual(greffon.Project({}).verify(self.sorties("A"), b, self.entrees()), 13)
        juge_commun.require_coverage(b, self.entrees(), "essai")

    def test_sortie_compressee_differente(self):
        autre = lambda f: f.__setitem__(("f", "c/k000.9"), zlib.compress(self.DONNEES, 0))  # noqa: E731 (juste, mais autre)
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).verify(self.sorties("A"), self.sorties("B", autre), self.entrees())
        # Si la tâche le permet, une autre sortie compressée qui redonne l'original est acceptée ; pas une fausse.
        peut_changer = greffon.Project({"sortie_compressee": "peut_changer"})
        self.assertEqual(peut_changer.verify(self.sorties("A2"), self.sorties("B2", autre), self.entrees()), 13)
        fausse = lambda f: f.__setitem__(("f", "c/k000.9"), zlib.compress(self.DONNEES[:-1], 9))  # noqa: E731
        with self.assertRaises(lecture.Refus):
            peut_changer.verify(self.sorties("A3"), self.sorties("B3", fausse), self.entrees())

    def test_decompression_differente_ou_absente(self):
        b = self.sorties("B", lambda f: f.__setitem__(("z", "ds/z000"), self.DONNEES[:-1] + b"?"))
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).verify(self.sorties("A"), b, self.entrees())
        b = self.sorties("B2", lambda f: f.pop(("z", "e/z000")))
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).verify(self.sorties("A2"), b, self.entrees())
        b = self.sorties("B3", lambda f: f.__setitem__(("z", "e/z000"), b"-3 0\n"))
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).verify(self.sorties("A3"), b, self.entrees())

    def test_base_fausse_est_une_erreur(self):
        a = self.sorties("A", lambda f: f.__setitem__(("f", "c/k000.6"), zlib.compress(b"autre chose", 6)))
        with self.assertRaises(lecture.Erreur):
            greffon.Project({}).verify(a, self.sorties("B"), self.entrees())

    def test_sortie_de_memoire_verifiee(self):
        """juge-v3: verification also writes m/NAME, as the memoire scenario does, and checks it."""
        b = self.sorties("B", lambda f: f.__setitem__(("f", "m/k000"), zlib.compress(self.DONNEES, 1)))
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).verify(self.sorties("A"), b, self.entrees())


class TestScenarios(unittest.TestCase):
    """juge-v3: each scenario checks every output of its side by the rule of verification, whatever the input (the
    common judge mixes verification inputs into the measured ones, invalid streams included), at the path where
    verification writes it; n6 computes ratio_n6 from its timed outputs. Outputs written by hand (without Docker)."""

    DONNEES = b"chaque sortie mesuree est verifiee " * 500
    MESURE = {"utilisateur_s": 0.5, "systeme_s": 0.5, "maxrss_ko": 1234}

    def setUp(self):
        self.travail = tempfile.mkdtemp()
        n = len(self.DONNEES)
        flux = zlib.compress(self.DONNEES)
        # e0000 measured (a perturbed file and its stream); e0001 a mixed-in verification stream, invalid (truncated).
        self.entrees = [Entree("f", "e0000", self.DONNEES, n, self.DONNEES), Entree("z", "e0000", flux, n, self.DONNEES),
                        Entree("z", "e0001", flux[:40], n, None)]
        self.fichiers = {("f", "c/e0000.1"): zlib.compress(self.DONNEES, 1), ("f", "c/e0000.6"): zlib.compress(self.DONNEES, 6),
                         ("f", "c/e0000.9"): zlib.compress(self.DONNEES, 9), ("f", "m/e0000"): zlib.compress(self.DONNEES, 6),
                         ("z", "d/e0000"): self.DONNEES, ("z", "e/e0000"): f"0 {n}\n".encode(),
                         ("z", "d/e0001"): b"", ("z", "e/e0001"): b"-3 0\n"}

    def tearDown(self):
        shutil.rmtree(self.travail)

    def sorties(self, nom, s, modifier=None):
        """Outputs of scenario s for one variant, under <side>/<s>/ as the common judge keeps them."""
        fichiers = dict(self.fichiers)
        if modifier:
            modifier(fichiers)
        return ecrire_sorties(os.path.join(self.travail, nom), {(c, f"{s}/{r}"): o for (c, r), o in fichiers.items()})

    def test_chaque_sortie_verifiee(self):
        projet = greffon.Project({})
        for s, cote in projet.SCENARIOS.items():
            with self.subTest(s=s):
                b = self.sorties(f"B-{s}", s)
                valeurs, comparees = projet.scenario(s, self.sorties(f"A-{s}", s), b, self.entrees, self.MESURE)
                self.assertEqual(comparees, len([e for e in self.entrees if e.cote == cote]))
                juge_commun.require_coverage(b, [e for e in self.entrees if e.cote == cote], s)
        self.assertEqual(valeurs, {"max_memory_kb": 1234})

    def test_ratio_n6_sur_les_sorties_chronometrees(self):
        valeurs, _ = greffon.Project({}).scenario("n6", self.sorties("A", "n6"), self.sorties("B", "n6"), self.entrees, self.MESURE)
        self.assertEqual(valeurs["ratio_n6"], len(self.DONNEES) / len(zlib.compress(self.DONNEES, 6)))
        self.assertEqual(valeurs["compression_throughput_n6"], len(self.DONNEES) / 1e6)

    def test_flux_invalide_mele_comme_en_verification(self):
        """A stream in error mixed into the decompression scenario: B must give A's status and bytes, as in
        verification (juge-v2's plugin compared measured outputs with the original only)."""
        projet = greffon.Project({})
        valeurs, _ = projet.scenario("decompression", self.sorties("A", "decompression"), self.sorties("B", "decompression"),
                                     self.entrees, self.MESURE)
        self.assertEqual(valeurs["decompression_throughput"], len(self.DONNEES) / 1e6)
        for modifier in (lambda f: f.__setitem__(("z", "e/e0001"), b"0 40\n"), lambda f: f.pop(("z", "e/e0001")),
                         lambda f: f.__setitem__(("z", "d/e0000"), self.DONNEES[:-1] + b"?")):
            with self.subTest(modifier=modifier), self.assertRaises(lecture.Refus):
                projet.scenario("decompression", self.sorties("A2", "decompression"), self.sorties("B2", "decompression", modifier),
                                self.entrees, self.MESURE)

    def test_compression_mesuree_differente(self):
        b = self.sorties("B", "n9", lambda f: f.__setitem__(("f", "c/e0000.9"), zlib.compress(self.DONNEES, 1)))
        with self.assertRaises(lecture.Refus):
            greffon.Project({}).scenario("n9", self.sorties("A", "n9"), b, self.entrees, self.MESURE)

    def test_scenario_lit_les_chemins_de_la_verification(self):
        """Each output a scenario reads sits at a path verification writes (bee/judge/execution.c), without its <s>/
        prefix: the common judge compares a mixed-in verification input there, byte for byte."""
        projet = greffon.Project({})
        verification = ecrire_sorties(os.path.join(self.travail, "V-B"), sorties_de_verification(self.DONNEES))
        projet.verify(ecrire_sorties(os.path.join(self.travail, "V-A"), sorties_de_verification(self.DONNEES)), verification,
                        [self.entrees[0]._replace(nom="k000"), self.entrees[1]._replace(nom="z000")])
        chemins = {(c, r.replace("k000", "NOM").replace("z000", "NOM")) for c, r in verification.lues}
        for s in projet.SCENARIOS:
            with self.subTest(s=s):
                vue = self.sorties(f"B-{s}", s)
                projet.scenario(s, self.sorties(f"A-{s}", s), vue, self.entrees[:2], self.MESURE)
                lues = {(c, r.split("/", 1)[1].replace("e0000", "NOM")) for c, r in vue.lues}
                self.assertTrue(lues and lues <= chemins, (s, lues - chemins))


# ------------------------------------------------------------------ méta-tests (Docker)

DEBUT_COMPRESS2 = """    int mz_compress2(unsigned char *pDest, mz_ulong *pDest_len, const unsigned char *pSource, mz_ulong source_len, int level)
    {
        int status;
        mz_stream stream;
        memset(&stream, 0, sizeof(stream));
"""
FIN_COMPRESS2 = """        *pDest_len = stream.total_out;
        return mz_deflateEnd(&stream);
    }

    int mz_compress("""
INCLUDE = '#include "miniz.h"\n'


def remplacer(texte, ancien, nouveau):
    if texte.count(ancien) != 1:
        raise AssertionError(f"marker missing or ambiguous in miniz.c: {ancien[:60]!r}")
    return texte.replace(ancien, nouveau)


def sortie_anticipee(texte, corpus):
    texte = remplacer(texte, INCLUDE, INCLUDE + "#include <stdlib.h>\nstatic int bee_appels = 0;\n")
    return remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 + "        if (++bee_appels > 3)\n            exit(0);\n")


def faux_chronos(texte, corpus):
    texte = remplacer(texte, INCLUDE, INCLUDE + "#include <time.h>\n"
                      "int clock_gettime(clockid_t c, struct timespec *t) { (void)c; t->tv_sec = 0; t->tv_nsec = 1; return 0; }\n")
    return remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 +
                     "        { volatile mz_uint64 bee_i; for (bee_i = 0; bee_i < (mz_uint64)source_len * 40; bee_i++) ; }\n")


def table_precalculee(texte, corpus):
    tailles = ", ".join(str(len(d)) for _, d in corpus)
    texte = remplacer(texte, INCLUDE, INCLUDE + f"static const unsigned long bee_connues[] = {{ {tailles} }};\n")
    return remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 +
                     "        { size_t bee_k; int bee_vu = 0;\n"
                     "          for (bee_k = 0; bee_k < sizeof(bee_connues) / sizeof(bee_connues[0]); bee_k++) bee_vu |= bee_connues[bee_k] == source_len;\n"
                     "          if (!bee_vu) { *pDest_len = 0; return MZ_OK; } }\n")


def requete_valgrind(texte, corpus):
    texte = remplacer(texte, INCLUDE, INCLUDE + "#include <valgrind/cachegrind.h>\n")
    texte = remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 + "        CACHEGRIND_STOP_INSTRUMENTATION;\n")
    return remplacer(texte, FIN_COMPRESS2, FIN_COMPRESS2.replace("        *pDest_len = stream.total_out;\n",
                                                                   "        *pDest_len = stream.total_out;\n        CACHEGRIND_START_INSTRUMENTATION;\n"))


def faux_resume(texte, corpus):
    texte = remplacer(texte, INCLUDE, INCLUDE + "#include <stdio.h>\n")
    return remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 + '        fputs("==1== I   refs:        1\\n", stderr);\n')


def mesure_devinee(texte, corpus):
    """Guesses the mode from its calls: verification starts with mz_compress2 at level 0, a measured scenario never."""
    texte = remplacer(texte, INCLUDE, INCLUDE + "static int bee_premier_niveau = -2;\n")
    return remplacer(texte, DEBUT_COMPRESS2, DEBUT_COMPRESS2 +
                     "        if (bee_premier_niveau == -2)\n            bee_premier_niveau = level;\n"
                     "        if (bee_premier_niveau != 0 && level > 1)\n            level = 1;\n")


def travail_deplace(texte, corpus):
    """Variante de la revue adverse du 27/10 : compresseurs initialisés d'avance dans mz_compressBound."""
    texte = remplacer(texte, """        return mz_deflateInit2(pStream, level, MZ_DEFLATED, MZ_DEFAULT_WINDOW_BITS, 9, MZ_DEFAULT_STRATEGY);
    }
""", """        return mz_deflateInit2(pStream, level, MZ_DEFLATED, MZ_DEFAULT_WINDOW_BITS, 9, MZ_DEFAULT_STRATEGY);
    }

    static tdefl_compressor **bee_pool = NULL;
    static size_t bee_cap = 0, bee_push = 0, bee_pop = 0;
""")
    texte = remplacer(texte, """        status = mz_deflateInit(&stream, level);
        if (status != MZ_OK)
            return status;
""", """        {
            tdefl_compressor *pComp = (bee_pool && bee_pop < bee_push) ? bee_pool[bee_pop++] : NULL;
            mz_uint comp_flags = TDEFL_COMPUTE_ADLER32 | tdefl_create_comp_flags_from_zip_params(level, MZ_DEFAULT_WINDOW_BITS, MZ_DEFAULT_STRATEGY);
            if (!pComp)
            {
                pComp = (tdefl_compressor *)malloc(sizeof(tdefl_compressor));
                if (!pComp)
                    return MZ_MEM_ERROR;
                tdefl_init(pComp, NULL, NULL, comp_flags);
            }
            else if (pComp->m_flags != comp_flags)
                tdefl_init(pComp, NULL, NULL, comp_flags);
            stream.adler = MZ_ADLER32_INIT;
            stream.zalloc = miniz_def_alloc_func;
            stream.zfree = miniz_def_free_func;
            stream.state = (struct mz_internal_state *)pComp;
        }
""")
    return remplacer(texte, """    mz_ulong mz_compressBound(mz_ulong source_len)
    {
""", """    mz_ulong mz_compressBound(mz_ulong source_len)
    {
        tdefl_compressor *bee_c = (tdefl_compressor *)malloc(sizeof(tdefl_compressor));
        if (bee_c)
            tdefl_init(bee_c, NULL, NULL, TDEFL_COMPUTE_ADLER32 | tdefl_create_comp_flags_from_zip_params(6, MZ_DEFAULT_WINDOW_BITS, MZ_DEFAULT_STRATEGY));
        if (bee_push == bee_cap)
        {
            bee_cap = bee_cap ? bee_cap * 2 : 64;
            bee_pool = (tdefl_compressor **)realloc(bee_pool, bee_cap * sizeof(*bee_pool));
        }
        bee_pool[bee_push++] = bee_c;
""")


def en_sandbox():
    """The network namespace of bee/sandbox/sans-docker.sh: no interface but lo (a CI runner has others)."""
    try:
        with open("/proc/net/dev", encoding="ascii") as f:
            return {ligne.split(":")[0].strip() for ligne in f.read().splitlines()[2:]} == {"lo"}
    except OSError:
        return False


@unittest.skipUnless(os.environ.get("BEE_HARNESS_SANDBOX") == "1" and en_sandbox() and shutil.which("cc"),
                     "harness tests: inside bee/sandbox/sans-docker.sh, with BEE_HARNESS_SANDBOX=1 (they run miniz here)")
class TestHarnaisEnSandbox(unittest.TestCase):
    """The harness built as the common judge builds it (bee/judge/build.sh, the base's headers in base/), run in
    the sandbox, without Docker (juge-v3 contract, miniz-0048): malformed records exit 2; the judged code finds no
    arguments, no environment and nothing left on descriptor 0, and the same output folders, created up front, in
    every mode; each scenario's outputs are verification's, at the same paths."""

    MODES = ("verifier", "n1", "n6", "n9", "decompression", "memoire")
    DONNEES = b"le harnais efface ses parametres " * 2000

    @classmethod
    def setUpClass(cls):
        cls.travail = tempfile.mkdtemp(prefix="bee-harnais-")
        cls.sorties = os.path.join(cls.travail, "sorties")  # the same path at each run: the spy lists it
        cls.entrees = os.path.join(cls.travail, "entrees")
        os.makedirs(os.path.join(cls.entrees, "f"))
        os.makedirs(os.path.join(cls.entrees, "z"))
        flux = zlib.compress(cls.DONNEES, 6)
        fichiers = {("f", "e0000"): cls.DONNEES, ("f", "e0001"): b"", ("z", "e0002"): flux, ("z", "e0003"): flux[:30]}
        with open(os.path.join(cls.entrees, "liste"), "w", encoding="ascii") as liste:
            for (cote, nom), octets in fichiers.items():
                with open(os.path.join(cls.entrees, cote, nom), "wb") as f:
                    f.write(octets)
                liste.write(f"{cote} {nom} {len(cls.DONNEES) if cote == 'z' else len(octets)}\n")
        cls.honnete = cls.construire("honnete", None)
        cls.espion = cls.construire("espion", cls.espionner)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.travail, ignore_errors=True)

    @classmethod
    def espionner(cls, texte):
        """miniz.c whose first mz_deflateInit2 or mz_inflateInit2 (every mode reaches one) reports what it sees."""
        espion = f"""#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
extern char **environ;
static void bee_espion(void)
{{
    static int vu = 0;
    char b[4096], noms[256] = "";
    int fd, k, cmdline = 0, env = 0;
    ssize_t n;
    DIR *d;
    struct dirent *e;
    if (vu++)
        return;
    fd = open("/proc/self/cmdline", O_RDONLY);
    n = fd >= 0 ? read(fd, b, sizeof(b)) : -1;
    for (k = 0; k < n; k++)
        cmdline += b[k] != 0;
    while (environ && environ[env])
        env++;
    d = opendir("{cls.sorties}");
    while (d && (e = readdir(d)))
        if (e->d_name[0] != '.' && strlen(noms) + strlen(e->d_name) + 2 < sizeof(noms))
        {{
            strcat(noms, " ");
            strcat(noms, e->d_name);
        }}
    fprintf(stderr, "BEE_ESPION cmdline=%d environ=%d stdin=%zd dossiers=%s\\n", cmdline, env, read(0, b, sizeof(b)), noms);
}}
"""
        texte = remplacer(texte, INCLUDE, INCLUDE + espion)
        for signature in ("    int mz_deflateInit2(mz_streamp pStream, int level, int method, int window_bits, int mem_level, int strategy)\n    {\n",
                          "    int mz_inflateInit2(mz_streamp pStream, int window_bits)\n    {\n"):
            texte = remplacer(texte, signature, signature + "        bee_espion();\n")
        return texte

    @classmethod
    def construire(cls, nom, transformation):
        racine = os.path.join(cls.travail, nom)
        sources, outillage, sortie = (os.path.join(racine, d) for d in ("sources", "outillage", "sortie"))
        os.makedirs(sources)
        os.makedirs(os.path.join(outillage, "base"))
        for fichier in os.listdir(RACINE):
            if fichier.startswith("miniz") and fichier.endswith((".c", ".h")):
                shutil.copyfile(os.path.join(RACINE, fichier), os.path.join(sources, fichier))
                if fichier.endswith(".h"):
                    shutil.copyfile(os.path.join(RACINE, fichier), os.path.join(outillage, "base", fichier))
        for dossier in greffon.Project.TOOLING:
            shutil.copytree(os.path.join(RACINE, dossier), os.path.join(outillage, dossier))
        if transformation:
            with open(os.path.join(sources, "miniz.c"), encoding="utf-8") as f:
                texte = transformation(f.read())
            with open(os.path.join(sources, "miniz.c"), "w", encoding="utf-8") as f:
                f.write(texte)
        subprocess.run(["sh", os.path.join(outillage, greffon.Project.BUILD), sources, outillage, sortie], check=True,
                       capture_output=True)
        return os.path.join(sortie, "execution")

    def lancer(self, programme, mode=None, enregistrement=None, arguments=()):
        """Runs the harness in a fresh output folder, with the record on descriptor 0 and chrono's fixed environment."""
        shutil.rmtree(self.sorties, ignore_errors=True)
        os.makedirs(self.sorties)
        if enregistrement is None:
            enregistrement = f"{mode} {self.entrees} {self.sorties}".ljust(255).encode() + b"\n"
        return subprocess.run([programme, *arguments], input=enregistrement, capture_output=True,
                              env={"HOME": "/tmp", "LC_ALL": "C", "PATH": "/usr/bin:/bin"})

    def arbre(self):
        resultat = {}
        for racine, _, noms in os.walk(self.sorties):
            for nom in noms:
                with open(os.path.join(racine, nom), "rb") as f:
                    resultat[os.path.relpath(os.path.join(racine, nom), self.sorties)] = f.read()
        return resultat

    def test_enregistrements_mal_formes(self):
        bon = f"verifier {self.entrees} {self.sorties}"
        for enregistrement, arguments in ((f"{bon} en-trop".ljust(255).encode() + b"\n", ()),
                                          (f"inconnu {self.entrees} {self.sorties}".ljust(255).encode() + b"\n", ()),
                                          (b"", ()), (b"x" * 4096, ()), (bon.ljust(255).encode() + b"\n", ("verifier",))):
            with self.subTest(enregistrement=enregistrement[:40], arguments=arguments):
                r = self.lancer(self.honnete, enregistrement=enregistrement, arguments=arguments)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(b"execution: usage", r.stderr)
        self.assertEqual(self.lancer(self.honnete, "verifier").returncode, 0)

    def test_rien_ne_dit_le_mode(self):
        """After the erasure: /proc/self/cmdline empty, no environment, descriptor 0 at its end, and the same output
        folders, all created before the first call to miniz, whatever the mode."""
        vus = {}
        for mode in self.MODES:
            r = self.lancer(self.espion, mode)
            self.assertEqual(r.returncode, 0, (mode, r.stderr))
            vus[mode] = [l for l in r.stderr.decode().splitlines() if l.startswith("BEE_ESPION")]
        for mode in self.MODES:
            self.assertEqual(len(vus[mode]), 1, mode)
            self.assertEqual(sorted(vus[mode][0].split("dossiers=")[1].split()), ["c", "d", "ds", "e", "es", "m", "s"], mode)
            self.assertEqual(vus[mode][0].split(" dossiers=")[0], "BEE_ESPION cmdline=0 environ=0 stdin=0", mode)

    def test_scenarios_aux_chemins_de_la_verification(self):
        self.assertEqual(self.lancer(self.honnete, "verifier").returncode, 0)
        verification = self.arbre()
        self.assertEqual(len(verification), 2 * 11 + 2 * 4)
        for mode in self.MODES[1:]:
            with self.subTest(mode=mode):
                r = self.lancer(self.honnete, mode)
                self.assertEqual(r.returncode, 0, r.stderr)
                sorties = self.arbre()
                self.assertTrue(sorties)
                self.assertEqual(sorties, {p: verification[p] for p in sorties}, "same path, same bytes")
                self.assertEqual(sorted(os.listdir(self.sorties)), ["c", "d", "ds", "e", "es", "m", "s"])
        self.assertEqual(verification["e/e0003"], b"-3 0\n")  # a stream in error: its status, never a stop


@unittest.skipUnless(os.environ.get("BEE_JUDGE_INTEGRATION") == "1" and shutil.which("docker"),
                     "meta-tests: BEE_JUDGE_INTEGRATION=1 and Docker required")
class TestJugeContreVariantes(unittest.TestCase):
    """Le juge commun complet, en conteneur, avec ce greffon, contre la base et des variantes malveillantes."""

    @classmethod
    def setUpClass(cls):
        cls.travail = tempfile.mkdtemp(prefix="bee-meta-")
        cls.corpus = greffon.Project({}).corpus(RACINE)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.travail, ignore_errors=True)

    def juger(self, nom, transformation=None, sans_instructions=False, options=()):
        source_b = os.path.join(self.travail, nom)
        os.makedirs(source_b)
        for fichier in os.listdir(RACINE):
            if fichier.startswith("miniz") and fichier.endswith((".c", ".h")):
                shutil.copyfile(os.path.join(RACINE, fichier), os.path.join(source_b, fichier))
        if transformation:
            with open(os.path.join(source_b, "miniz.c"), encoding="utf-8") as f:
                texte = f.read()
            with open(os.path.join(source_b, "miniz.c"), "w", encoding="utf-8") as f:
                f.write(transformation(texte, self.corpus))
        commande = [sys.executable, os.path.join(JUGE_COMMUN, "judge.py"), "--tooling", RACINE, "--source-a", RACINE,
                    "--source-b", source_b, "--repetitions", "2", "--warmup", "0"]
        if sans_instructions:
            commande.append("--no-instructions")
        for option in options:
            commande += ["--option", option]
        if os.environ.get("BEE_JUDGE_NETWORK"):
            commande += ["--build-network", os.environ["BEE_JUDGE_NETWORK"]]
        r = subprocess.run(commande, capture_output=True, text=True, timeout=3600)
        rapport = json.loads(r.stdout) if r.returncode == 0 else None
        print(f"\n[{nom}] code {r.returncode}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", file=sys.stderr)
        return r.returncode, rapport, r.stderr

    def types_suspects(self, rapport):
        return {s["type"] for s in rapport["judge"]["suspicious_constructs"]}

    def details(self, rapport):
        return " ".join(s["detail"] for s in rapport["judge"]["suspicious_constructs"])

    def test_honnete(self):
        code, rapport, _ = self.juger("honnete")
        self.assertEqual(code, 0)
        self.assertEqual(rapport["judge"]["suspicious_constructs"], [])
        self.assertEqual(rapport["judge"]["project"], "miniz")
        self.assertEqual(rapport["judge"]["common"], juge_commun.common_tag())
        self.assertEqual(rapport["judge"]["common"], "judge-v4")
        self.assertEqual(rapport["judge"]["plugin"], juge_commun.load_plugin(RACINE, {})[1])
        self.assertGreater(rapport["judge"]["verification"]["outputs_compared"], 900)
        # juge-v3 on: verification inputs mixed into every measurement, and no fixed metric read on verification alone.
        self.assertGreater(rapport["judge"]["verification"]["inputs_mixed"], 0)
        self.assertEqual(rapport["judge"]["verification"]["fixed_without_measurement"], [])
        self.assertEqual(rapport["judge"]["verification"]["instructions_without_mixing"], [])
        self.assertFalse(rapport["metrics"]["ratio_n6"]["verification_only"])
        self.assertEqual(list(rapport["metrics"]), [m for m, _, _ in greffon.Project.METRICS])  # English metric ids
        self.assertEqual(set(rapport["instructions"]), {"instructions_n1", "instructions_n6", "instructions_n9", "instructions_decompression"})
        for m in rapport["instructions"].values():
            self.assertEqual(m["A"], m["B"])

    def test_sortie_anticipee(self):
        code, _, sortie = self.juger("sortie_anticipee", sortie_anticipee, sans_instructions=True)
        self.assertEqual(code, 1)
        self.assertIn("judge: REFUSAL: ", sortie)

    def test_faux_chronos(self):
        code, rapport, _ = self.juger("faux_chronos", faux_chronos, sans_instructions=True)
        self.assertEqual(code, 0)
        self.assertIn("symbole_interdit", self.types_suspects(rapport))
        self.assertIn("clock_gettime", self.details(rapport))
        # Le temps est mesuré par le noyau, pas par clock_gettime : B est vu plus lent, pas plus rapide.
        n6 = rapport["metrics"]["compression_throughput_n6"]
        self.assertLess(n6["B"]["median"], n6["A"]["median"])

    def test_table_precalculee(self):
        code, _, sortie = self.juger("table_precalculee", table_precalculee, sans_instructions=True)
        self.assertEqual(code, 1)
        self.assertIn("judge: REFUSAL: ", sortie)

    def test_requete_valgrind(self):
        code, rapport, _ = self.juger("requete_valgrind", requete_valgrind)
        self.assertEqual(code, 0)
        self.assertIn("instruction", self.types_suspects(rapport))
        self.assertIn("preambule_valgrind", self.details(rapport))

    def test_travail_deplace(self):
        code, rapport, _ = self.juger("travail_deplace", travail_deplace)
        self.assertEqual(code, 0)
        self.assertEqual(rapport["judge"]["suspicious_constructs"], [])  # rien de visible : seul le décompte protège
        n6 = rapport["instructions"]["instructions_n6"]
        self.assertLess(n6["gain"], 0.002, "work moved out of the compressions must stay counted")

    def test_mesure_devinee(self):
        code, _, sortie = self.juger("mesure_devinee", mesure_devinee, sans_instructions=True,
                                     options=["sortie_compressee=peut_changer"])
        self.assertEqual(code, 1)
        self.assertIn("judge: REFUSAL: ", sortie)

    def test_faux_resume(self):
        code, rapport, _ = self.juger("faux_resume", faux_resume)
        self.assertEqual(code, 0)
        self.assertIn("appel_externe", self.types_suspects(rapport))
        n6 = rapport["instructions"]["instructions_n6"]
        self.assertGreater(n6["B"], 0.99 * n6["A"])  # le vrai décompte, pas « 1 »


if __name__ == "__main__":
    unittest.main(verbosity=2)
