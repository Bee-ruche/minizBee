#!/usr/bin/env python3
"""Tests du juge isolé (bee/juge/).

  python3 bee/juge/test_juge.py                     tests unitaires (sans Docker)
  BEE_JUGE_INTEGRATION=1 python3 bee/juge/test_juge.py
                                                    + méta-tests : le juge contre des variantes de miniz
                                                      honnête et MALVEILLANTES (Docker requis, quelques minutes)

Les variantes malveillantes sont écrites ici, comme des transformations du texte de miniz, et ne sont
compilées et exécutées que DANS le conteneur du juge. Chacune vise une façon de tromper l'ancien juge
(qui exécutait le code de la PR dans le processus qui le jugeait) :
  sortie_anticipee   le programme s'arrête « avec succès » au milieu des tests
  faux_chronos       le code remplace clock_gettime pour annoncer des temps flatteurs, et il est plus lent
  table_precalculee  le compresseur ne marche que sur les entrées qu'il connaît d'avance (le corpus)
  requete_valgrind   le code suspend le décompte d'instructions de Valgrind pendant son propre travail
  faux_resume        le code écrit un faux résumé « I refs » sur la sortie d'erreur
  travail_deplace    le code fait son initialisation dans mz_compressBound, appelée par le harnais avant les
                     compressions (revue adverse du 27/10 : +1,7 à +27 % d'instructions « gagnées » tant que
                     seule une zone du harnais était comptée)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(os.path.dirname(ICI))
sys.path.insert(0, ICI)
import analyse  # noqa: E402
import juge  # noqa: E402


# ------------------------------------------------------------------ tests unitaires

NM_A = """/s/obj/miniz.o: mz_compress2 T 0000000000000100 0000000000000080
/s/obj/miniz.o: memcpy U
/s/obj/miniz.o: tdefl_compress U
/s/obj/miniz_tdef.o: tdefl_compress T 0000000000000000 0000000000001000
/s/obj/miniz_tdef.o: .LC0 r 0
"""
SECTIONS_A = """
/s/obj/miniz.o:     file format elf64-x86-64

Sections:
Idx Name          Size      VMA               LMA               File off  Algn
  0 .text         00001000  0000000000000000  0000000000000000  00000040  2**4
  1 .rodata       00000100  0000000000000000  0000000000000000  00001040  2**5
"""
DESASSEMBLAGE_A = """0000000000000000 <mz_compress2>:
   0:\tendbr64
   4:\tpush   %rbp
   5:\tmov    %rsp,%rbp
"""


def releves(nm=NM_A, sections=SECTIONS_A, desassemblage=DESASSEMBLAGE_A):
    return {"symboles": nm, "sections": sections, "desassemblage": desassemblage}


class TestAnalyse(unittest.TestCase):
    def test_base_contre_elle_meme(self):
        self.assertEqual(analyse.analyser(releves(), releves()), [])

    def test_appel_externe_hors_liste(self):
        b = releves(nm=NM_A + "/s/obj/miniz.o: execve U\n/s/obj/miniz.o: malloc U\n")
        details = [s["detail"] for s in analyse.analyser(releves(), b)]
        self.assertEqual(len(details), 1)
        self.assertIn("execve", details[0])

    def test_symbole_qui_remplace_la_libc(self):
        b = releves(nm=NM_A + "/s/obj/miniz.o: clock_gettime T 0000000000000300 0000000000000010\n"
                             "/s/obj/miniz.o: mz_nouvelle_fonction T 0000000000000400 0000000000000010\n")
        suspects = analyse.analyser(releves(), b)
        self.assertEqual([s["type"] for s in suspects], ["symbole_defini"])
        self.assertIn("clock_gettime", suspects[0]["detail"])

    def test_fonction_indirecte(self):
        b = releves(nm=NM_A + "/s/obj/miniz.o: mz_choisir i 0000000000000300 0000000000000010\n")
        self.assertEqual([s["type"] for s in analyse.analyser(releves(), b)], ["symbole"])

    def test_constructeur(self):
        b = releves(sections=SECTIONS_A + "  2 .init_array   00000008  0000000000000000  0000000000000000  00001140  2**3\n")
        suspects = analyse.analyser(releves(), b)
        self.assertEqual([s["type"] for s in suspects], ["section"])

    def test_sections_ordinaires_permises(self):
        b = releves(sections=SECTIONS_A + "  2 .rodata.cst32 00000020  0000000000000000  0000000000000000  00001140  2**5\n"
                                          "  3 .text.unlikely 00000020  0000000000000000  0000000000000000  00001160  2**4\n")
        self.assertEqual(analyse.analyser(releves(), b), [])

    def test_instructions_suspectes(self):
        b = releves(desassemblage=DESASSEMBLAGE_A + "   9:\tsyscall\n   b:\trdtsc\n  10:\trol    $0x3,%rdi\n"
                                                  "  14:\trol    $0xd,%rdi\n  18:\trol    $0x3d,%rdi\n  1c:\trol    $0x33,%rdi\n")
        types = sorted(s["detail"].split(" ")[0] for s in analyse.analyser(releves(), b))
        self.assertEqual(types, ["preambule_valgrind", "rdtsc", "syscall"])

    def test_instruction_deja_dans_la_base(self):
        a = releves(desassemblage=DESASSEMBLAGE_A + "   9:\tcpuid\n")
        b = releves(desassemblage=DESASSEMBLAGE_A + "   9:\tcpuid\n")
        self.assertEqual(analyse.analyser(a, b), [])

    def test_source(self):
        diff = "+++ b/miniz.c\n+    __asm__ volatile(\"\");\n+#include <unistd.h>\n+    x = getenv(\"A\");\n-    asm retiré\n+    int ordinaire = 1;\n"
        types = [s["detail"] for s in analyse.analyser(releves(), releves(), diff)]
        self.assertEqual(len(types), 3)


class TestLectureSure(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.racine, "c"))

    def tearDown(self):
        shutil.rmtree(self.racine)

    def test_fichier_ordinaire(self):
        with open(os.path.join(self.racine, "c", "x"), "wb") as f:
            f.write(b"abc")
        self.assertEqual(juge.lire_sortie(self.racine, "c/x"), b"abc")
        self.assertIsNone(juge.lire_sortie(self.racine, "c/absent"))

    def test_lien_symbolique_refuse(self):
        os.symlink("/etc/hostname", os.path.join(self.racine, "c", "x"))
        with self.assertRaises(juge.Refus):
            juge.lire_sortie(self.racine, "c/x")

    def test_dossier_lien_refuse(self):
        os.symlink("/etc", os.path.join(self.racine, "d"))
        with self.assertRaises(juge.Refus):
            juge.lire_sortie(self.racine, "d/hostname")

    def test_tube_refuse(self):
        os.mkfifo(os.path.join(self.racine, "c", "x"))
        with self.assertRaises(juge.Refus):
            juge.lire_sortie(self.racine, "c/x")

    def test_trop_gros(self):
        with open(os.path.join(self.racine, "c", "x"), "wb") as f:
            f.write(b"0" * 100)
        with self.assertRaises(juge.Refus):
            juge.lire_sortie(self.racine, "c/x", maximum=10)

    def test_statut(self):
        with open(os.path.join(self.racine, "c", "s"), "wb") as f:
            f.write(b"-3 12\n")
        self.assertEqual(juge.statut(self.racine, "c/s"), (-3, 12))
        with open(os.path.join(self.racine, "c", "s"), "wb") as f:
            f.write(b"0 12 ; rm -rf /\n")
        with self.assertRaises(juge.Refus):
            juge.statut(self.racine, "c/s")


class TestEntrees(unittest.TestCase):
    def test_graine_reproductible_et_imprevisible(self):
        import random
        corpus = [("k000", b"abc" * 1000)]
        a = juge.entrees_aleatoires(random.Random(1), corpus)
        b = juge.entrees_aleatoires(random.Random(1), corpus)
        c = juge.entrees_aleatoires(random.Random(2), corpus)
        self.assertEqual(a, b)
        self.assertNotEqual([d for _, d in a], [d for _, d in c])
        self.assertIn(b"", [d for _, d in a])

    def test_flux_valides(self):
        import random
        rng = random.Random(3)
        originaux = [("x", b""), ("y", b"bonjour " * 5000), ("z", bytes(range(256)) * 50)]
        for nom, z, taille, original in juge.flux_zlib(rng, originaux):
            if original is not None:
                self.assertEqual(juge.decompresser_zlib(z), original, nom)
                self.assertEqual(taille, len(original))

    def test_decompresser_zlib_refuse_les_flux_incomplets(self):
        z = zlib.compress(b"x" * 1000)
        self.assertEqual(juge.decompresser_zlib(z), b"x" * 1000)
        self.assertIsNone(juge.decompresser_zlib(z[:-1]))
        self.assertIsNone(juge.decompresser_zlib(z + b"\x00"))


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
    """Le juge complet, en conteneur, contre la base et des variantes malveillantes."""

    @classmethod
    def setUpClass(cls):
        cls.travail = tempfile.mkdtemp(prefix="bee-meta-")
        cls.corpus = juge.charger_corpus(RACINE)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.travail, ignore_errors=True)

    def juger(self, nom, transformation=None, sans_instructions=False):
        source_b = os.path.join(self.travail, nom)
        os.makedirs(source_b)
        for fichier in os.listdir(RACINE):
            if juge.MOTIF_SOURCE.fullmatch(fichier):
                shutil.copyfile(os.path.join(RACINE, fichier), os.path.join(source_b, fichier))
        if transformation:
            with open(os.path.join(source_b, "miniz.c"), encoding="utf-8") as f:
                texte = f.read()
            with open(os.path.join(source_b, "miniz.c"), "w", encoding="utf-8") as f:
                f.write(transformation(texte, self.corpus))
        commande = [sys.executable, os.path.join(ICI, "juge.py"), "--source-a", RACINE, "--source-b", source_b,
                    "--outillage", RACINE, "--repetitions", "2", "--chauffe", "0"]
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

    def test_honnete(self):
        code, rapport, _ = self.juger("honnete")
        self.assertEqual(code, 0)
        self.assertEqual(rapport["juge"]["constructions_suspectes"], [])
        for m in rapport["instructions"].values():
            self.assertEqual(m["A"], m["B"])

    def test_sortie_anticipee(self):
        code, _, sortie = self.juger("sortie_anticipee", sortie_anticipee, sans_instructions=True)
        self.assertEqual(code, 1)
        self.assertIn("REFUS", sortie)

    def test_faux_chronos(self):
        code, rapport, _ = self.juger("faux_chronos", faux_chronos, sans_instructions=True)
        self.assertEqual(code, 0)
        self.assertIn("symbole_defini", self.types_suspects(rapport))
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
        self.assertIn("preambule_valgrind", " ".join(s["detail"] for s in rapport["juge"]["constructions_suspectes"]))

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
