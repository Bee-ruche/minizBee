#!/usr/bin/env python3
"""Tests du greffon de minizBee pour le juge commun Bee (bee/juge/projet.py, construire.sh, execution.c).

  python3 bee/juge/test_juge.py                     tests unitaires (sans Docker)
  BEE_JUGE_INTEGRATION=1 python3 bee/juge/test_juge.py
                                                    + méta-tests : le juge commun, avec CE greffon, contre des
                                                      variantes de miniz honnête et MALVEILLANTES (Docker requis)
  BEE_JUGE_COMMUN=<registre>/outils/juge            le juge commun, à l'étiquette épinglée par
                                                    .github/workflows/bee-ci.yml (juge-v2) ; par défaut,
                                                    ../registre/outils/juge à côté de ce dépôt
  BEE_JUGE_RESEAU=host                              réseau de « docker build » (machines sans pont Docker)

Le greffon et le harnais testés sont ceux de CE dépôt (la PR, quand la CI lance ces tests) ; le juge
commun est celui du registre. Les variantes malveillantes sont écrites ici, comme des transformations du
texte de miniz.c, et ne sont compilées et exécutées que DANS le conteneur du juge. Chacune vise une façon
de tromper un juge qui exécuterait le code de la PR dans son propre processus :
  sortie_anticipee   le programme s'arrête « avec succès » au milieu des tests
  faux_chronos       le code remplace clock_gettime pour annoncer des temps flatteurs, et il est plus lent
  table_precalculee  le compresseur ne marche que sur les entrées qu'il connaît d'avance (le corpus)
  requete_valgrind   le code suspend le décompte d'instructions de Valgrind pendant son propre travail
  faux_resume        le code écrit un faux résumé « I refs » sur la sortie d'erreur
  travail_deplace    le code fait son initialisation dans mz_compressBound, appelée par le harnais avant les
                     compressions (revue adverse du 27/10 : +1,7 à +27 % d'instructions « gagnées » tant que
                     seule une zone du harnais était comptée)
  honnete            miniz tel quel : accepté, rien de suspect, décomptes de A et B identiques
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
JUGE_COMMUN = os.path.abspath(os.environ.get("BEE_JUGE_COMMUN") or os.path.join(os.path.dirname(RACINE), "registre", "outils", "juge"))
if not os.path.isfile(os.path.join(JUGE_COMMUN, "juge.py")):
    sys.exit(f"juge commun introuvable dans {JUGE_COMMUN} : BEE_JUGE_COMMUN=<registre>/outils/juge "
             "(à l'étiquette épinglée par .github/workflows/bee-ci.yml)")
sys.path.insert(0, JUGE_COMMUN)
import juge as juge_commun  # noqa: E402
import lecture  # noqa: E402
from entrees import Entree  # noqa: E402

_spec = importlib.util.spec_from_file_location("greffon_minizbee", os.path.join(ICI, "projet.py"))
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
        projet, empreinte = juge_commun.charger_greffon(RACINE, {})
        with open(os.path.join(ICI, "projet.py"), "rb") as f:
            self.assertEqual(empreinte, hashlib.sha256(f.read()).hexdigest())
        self.assertEqual(projet.NOM, "miniz")
        self.assertEqual(projet.SCENARIOS, {"n1": "f", "n6": "f", "n9": "f", "decompression": "z", "memoire": "f"})
        self.assertEqual(projet.INSTRUCTIONS, ("n1", "n6", "n9", "decompression"))
        self.assertEqual([m for m, _, _ in projet.METRIQUES],
                         ["debit_compression_n1", "debit_compression_n6", "debit_compression_n9",
                          "debit_decompression", "ratio_n6", "memoire_max_ko"])
        self.assertEqual(projet.VERIFICATION, {"sortie_compressee": "identique"})

    def test_options(self):
        projet, _ = juge_commun.charger_greffon(RACINE, {"sortie_compressee": "peut_changer"})
        self.assertFalse(projet.identique)
        for options in ({"sortie_compressee": "parfois"}, {"inconnue": "1"}):
            with self.assertRaises(lecture.Erreur, msg=str(options)):
                juge_commun.charger_greffon(RACINE, options)

    def test_sources_et_objets(self):
        """Seuls miniz.c, miniz_tdef.c et miniz_tinfl.c sont compilés : un objet chacun, miniz_zip.c n'est pas copié."""
        projet, _ = juge_commun.charger_greffon(RACINE, {})
        destination = tempfile.mkdtemp()
        try:
            juge_commun.copier_sources(RACINE, destination, projet.SOURCES, projet.SOURCES_REQUISES)
            self.assertEqual(juge_commun.objets_attendus(destination), ({"miniz.o", "miniz_tdef.o", "miniz_tinfl.o"}, []))
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
        projet = greffon.Projet({})
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
        projet = greffon.Projet({})
        for etape in (projet.repetition(random.Random(7), self.CORPUS), projet.instructions(random.Random(7), self.CORPUS, 1000)):
            fichiers = {e.nom: e.donnees for e in etape if e.cote == "f"}
            for e in etape:
                if e.cote == "z":
                    self.assertEqual(zlib.decompress(e.donnees), fichiers[e.nom])


class TestVerification(unittest.TestCase):
    """La règle de justesse, sur des sorties écrites à la main (sans Docker)."""

    DONNEES = b"le greffon ne croit que la base et la zlib de l'hote " * 300

    def setUp(self):
        self.travail = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.travail)

    def sorties(self, nom, modifier=None):
        """Sorties d'une variante pour une entrée f « k000 » et un flux z « z000 » (valide)."""
        racines = {c: os.path.join(self.travail, nom, c) for c in "fz"}
        fichiers = {}
        for niveau in greffon.NIVEAUX_UNIQUE:
            fichiers[("f", f"c/k000.{niveau}")] = zlib.compress(self.DONNEES, min(niveau, 9))
        for niveau in greffon.NIVEAUX_FLUX:
            fichiers[("f", f"s/k000.{niveau}")] = zlib.compress(self.DONNEES, niveau)
        n = len(self.DONNEES)
        fichiers.update({("z", "e/z000"): f"0 {n}\n".encode(), ("z", "d/z000"): self.DONNEES,
                         ("z", "es/z000"): f"1 {n}\n".encode(), ("z", "ds/z000"): self.DONNEES})
        if modifier:
            modifier(fichiers)
        for (cote, relatif), octets in fichiers.items():
            chemin = os.path.join(racines[cote], relatif)
            os.makedirs(os.path.dirname(chemin), exist_ok=True)
            with open(chemin, "wb") as f:
                f.write(octets)
        return lecture.Sorties(racines)

    def entrees(self):
        return [Entree("f", "k000", self.DONNEES, len(self.DONNEES), self.DONNEES),
                Entree("z", "z000", zlib.compress(self.DONNEES), len(self.DONNEES), self.DONNEES)]

    def test_identique_accepte(self):
        b = self.sorties("B")
        self.assertEqual(greffon.Projet({}).verifier(self.sorties("A"), b, self.entrees()), 12)
        juge_commun.exiger_couverture(b, self.entrees(), "essai")

    def test_sortie_compressee_differente(self):
        autre = lambda f: f.__setitem__(("f", "c/k000.9"), zlib.compress(self.DONNEES, 0))  # noqa: E731 (juste, mais autre)
        with self.assertRaises(lecture.Refus):
            greffon.Projet({}).verifier(self.sorties("A"), self.sorties("B", autre), self.entrees())
        # Si la tâche le permet, une autre sortie compressée qui redonne l'original est acceptée ; pas une fausse.
        peut_changer = greffon.Projet({"sortie_compressee": "peut_changer"})
        self.assertEqual(peut_changer.verifier(self.sorties("A2"), self.sorties("B2", autre), self.entrees()), 12)
        fausse = lambda f: f.__setitem__(("f", "c/k000.9"), zlib.compress(self.DONNEES[:-1], 9))  # noqa: E731
        with self.assertRaises(lecture.Refus):
            peut_changer.verifier(self.sorties("A3"), self.sorties("B3", fausse), self.entrees())

    def test_decompression_differente_ou_absente(self):
        b = self.sorties("B", lambda f: f.__setitem__(("z", "ds/z000"), self.DONNEES[:-1] + b"?"))
        with self.assertRaises(lecture.Refus):
            greffon.Projet({}).verifier(self.sorties("A"), b, self.entrees())
        b = self.sorties("B2", lambda f: f.pop(("z", "e/z000")))
        with self.assertRaises(lecture.Refus):
            greffon.Projet({}).verifier(self.sorties("A2"), b, self.entrees())
        b = self.sorties("B3", lambda f: f.__setitem__(("z", "e/z000"), b"-3 0\n"))
        with self.assertRaises(lecture.Refus):
            greffon.Projet({}).verifier(self.sorties("A3"), b, self.entrees())

    def test_base_fausse_est_une_erreur(self):
        a = self.sorties("A", lambda f: f.__setitem__(("f", "c/k000.6"), zlib.compress(b"autre chose", 6)))
        with self.assertRaises(lecture.Erreur):
            greffon.Projet({}).verifier(a, self.sorties("B"), self.entrees())


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
        raise AssertionError(f"marqueur introuvable ou ambigu dans miniz.c : {ancien[:60]!r}")
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


@unittest.skipUnless(os.environ.get("BEE_JUGE_INTEGRATION") == "1" and shutil.which("docker"),
                     "méta-tests : BEE_JUGE_INTEGRATION=1 et Docker requis")
class TestJugeContreVariantes(unittest.TestCase):
    """Le juge commun complet, en conteneur, avec ce greffon, contre la base et des variantes malveillantes."""

    @classmethod
    def setUpClass(cls):
        cls.travail = tempfile.mkdtemp(prefix="bee-meta-")
        cls.corpus = greffon.Projet({}).corpus(RACINE)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.travail, ignore_errors=True)

    def juger(self, nom, transformation=None, sans_instructions=False):
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
        commande = [sys.executable, os.path.join(JUGE_COMMUN, "juge.py"), "--outillage", RACINE, "--source-a", RACINE,
                    "--source-b", source_b, "--repetitions", "2", "--chauffe", "0"]
        if sans_instructions:
            commande.append("--sans-instructions")
        if os.environ.get("BEE_JUGE_RESEAU"):
            commande += ["--reseau-construction", os.environ["BEE_JUGE_RESEAU"]]
        r = subprocess.run(commande, capture_output=True, text=True, timeout=3600)
        rapport = json.loads(r.stdout) if r.returncode == 0 else None
        print(f"\n[{nom}] code {r.returncode} : {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", file=sys.stderr)
        return r.returncode, rapport, r.stderr

    def types_suspects(self, rapport):
        return {s["type"] for s in rapport["juge"]["constructions_suspectes"]}

    def details(self, rapport):
        return " ".join(s["detail"] for s in rapport["juge"]["constructions_suspectes"])

    def test_honnete(self):
        code, rapport, _ = self.juger("honnete")
        self.assertEqual(code, 0)
        self.assertEqual(rapport["juge"]["constructions_suspectes"], [])
        self.assertEqual(rapport["juge"]["projet"], "miniz")
        self.assertEqual(rapport["juge"]["commun"], f"juge-v{juge_commun.VERSION_COMMUNE}")
        self.assertEqual(rapport["juge"]["greffon"], juge_commun.charger_greffon(RACINE, {})[1])
        self.assertGreater(rapport["juge"]["verification"]["sorties_comparees"], 900)
        self.assertEqual(set(rapport["instructions"]), {"instructions_n1", "instructions_n6", "instructions_n9", "instructions_decompression"})
        for m in rapport["instructions"].values():
            self.assertEqual(m["A"], m["B"])

    def test_sortie_anticipee(self):
        code, _, sortie = self.juger("sortie_anticipee", sortie_anticipee, sans_instructions=True)
        self.assertEqual(code, 1)
        self.assertIn("REFUS", sortie)

    def test_faux_chronos(self):
        code, rapport, _ = self.juger("faux_chronos", faux_chronos, sans_instructions=True)
        self.assertEqual(code, 0)
        self.assertIn("symbole_interdit", self.types_suspects(rapport))
        self.assertIn("clock_gettime", self.details(rapport))
        # Le temps est mesuré par le noyau, pas par clock_gettime : B est vu plus lent, pas plus rapide.
        n6 = rapport["metriques"]["debit_compression_n6"]
        self.assertLess(n6["B"]["mediane"], n6["A"]["mediane"])

    def test_table_precalculee(self):
        code, _, sortie = self.juger("table_precalculee", table_precalculee, sans_instructions=True)
        self.assertEqual(code, 1)
        self.assertIn("REFUS", sortie)

    def test_requete_valgrind(self):
        code, rapport, _ = self.juger("requete_valgrind", requete_valgrind)
        self.assertEqual(code, 0)
        self.assertIn("instruction", self.types_suspects(rapport))
        self.assertIn("preambule_valgrind", self.details(rapport))

    def test_travail_deplace(self):
        code, rapport, _ = self.juger("travail_deplace", travail_deplace)
        self.assertEqual(code, 0)
        self.assertEqual(rapport["juge"]["constructions_suspectes"], [])  # rien de visible : seul le décompte protège
        n6 = rapport["instructions"]["instructions_n6"]
        self.assertLess(n6["gain"], 0.002, "le travail déplacé hors des compressions doit rester compté")

    def test_faux_resume(self):
        code, rapport, _ = self.juger("faux_resume", faux_resume)
        self.assertEqual(code, 0)
        self.assertIn("appel_externe", self.types_suspects(rapport))
        n6 = rapport["instructions"]["instructions_n6"]
        self.assertGreater(n6["B"], 0.99 * n6["A"])  # le vrai décompte, pas « 1 »


if __name__ == "__main__":
    unittest.main(verbosity=2)
