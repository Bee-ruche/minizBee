#!/usr/bin/env python3
"""Unit tests of ab.py's statistics (sign test, relative gain) and of its report's English names.

Usage: python3 bee/bench/test_ab.py
"""

import importlib.util
import os
import unittest

_CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab.py")
_SPEC = importlib.util.spec_from_file_location("ab", _CHEMIN)
ab = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ab)


class SeuilDuSigne(unittest.TestCase):
    def test_table_documentee(self):
        attendu = {6: 6, 7: 7, 8: 8, 9: 8, 10: 9, 11: 10, 12: 10, 13: 11, 14: 12, 15: 12, 16: 13, 17: 14, 18: 14, 19: 15, 20: 16}
        for n, k in attendu.items():
            self.assertEqual(ab.seuil_signe(n), k, f"N = {n}")

    def test_trop_peu_de_paires(self):
        for n in range(0, 6):
            self.assertIsNone(ab.seuil_signe(n), f"N = {n}")

    def test_p_valeur_n10_k9(self):
        self.assertAlmostEqual(ab.p_unilaterale(10, 9), 11 / 1024)


class TestDuSigne(unittest.TestCase):
    def test_toutes_egales_ni_gain_ni_degradation(self):
        r = ab.test_du_signe([3.5054] * 10, [3.5054] * 10, "higher")
        self.assertEqual(r["ties"], 10)
        self.assertEqual(r["useful_pairs"], 0)
        self.assertIsNone(r["threshold_k"])
        self.assertFalse(r["beyond_noise"])
        self.assertFalse(r["degradation_beyond_noise"])
        self.assertIsNone(r["p_improvement"])

    def test_egalites_ecartees_avant_le_seuil(self):
        # 9 égalités et 1 paire gagnée par B (cas de max_memory_kb) : N' = 1, aucune conclusion.
        r = ab.test_du_signe([1564] * 10, [1564] * 9 + [1548], "lower")
        self.assertEqual((r["b_wins"], r["a_wins"], r["ties"]), (1, 0, 9))
        self.assertFalse(r["beyond_noise"])
        # 4 égalités, 6 paires gagnées par B : N' = 6, k = 6, donc significatif.
        r = ab.test_du_signe([10] * 10, [10] * 4 + [11] * 6, "higher")
        self.assertEqual(r["threshold_k"], 6)
        self.assertTrue(r["beyond_noise"])
        # 4 égalités, 5 gagnées par B et 1 par A : N' = 6, k = 6, pas significatif.
        r = ab.test_du_signe([10] * 10, [10] * 4 + [11] * 5 + [9], "higher")
        self.assertFalse(r["beyond_noise"])
        self.assertFalse(r["degradation_beyond_noise"])

    def test_deterministe_qui_change(self):
        r = ab.test_du_signe([3.5054] * 10, [3.5100] * 10, "higher")
        self.assertTrue(r["beyond_noise"])
        r = ab.test_du_signe([3.5054] * 10, [3.5000] * 10, "higher")
        self.assertTrue(r["degradation_beyond_noise"])
        self.assertFalse(r["beyond_noise"])

    def test_sens_plus_bas(self):
        r = ab.test_du_signe([1600] * 10, [1500] * 10, "lower")
        self.assertTrue(r["beyond_noise"])
        r = ab.test_du_signe([1500] * 10, [1600] * 10, "lower")
        self.assertTrue(r["degradation_beyond_noise"])

    def test_neuf_sur_dix(self):
        a = [100.0] * 10
        b = [101.0] * 9 + [99.0]
        r = ab.test_du_signe(a, b, "higher")
        self.assertEqual(r["threshold_k"], 9)
        self.assertTrue(r["beyond_noise"])
        b = [101.0] * 8 + [99.0] * 2
        self.assertFalse(ab.test_du_signe(a, b, "higher")["beyond_noise"])

    def test_valeurs_absentes_ignorees(self):
        r = ab.test_du_signe([None] * 10, [None] * 10, "higher")
        self.assertEqual(r["pairs"], 0)
        self.assertFalse(r["beyond_noise"])


class NomsAnglais(unittest.TestCase):
    """The report's English names (names.yaml: ab_report, judge_report; domain metric_id), which bee record-measurement
    reads: the metric ids, their direction and unit, and the sign test's keys."""

    def test_metriques_en_anglais(self):
        self.assertEqual(ab.METRIQUES, [("compression_throughput_n1", "higher", "MB/s"), ("compression_throughput_n6", "higher", "MB/s"),
                                        ("compression_throughput_n9", "higher", "MB/s"), ("decompression_throughput", "higher", "MB/s"),
                                        ("ratio_n6", "higher", "ratio"), ("max_memory_kb", "lower", "KB")])

    def test_cles_du_test_du_signe(self):
        self.assertEqual(set(ab.test_du_signe([1.0] * 6, [2.0] * 6, "higher")),
                         {"pairs", "useful_pairs", "b_wins", "a_wins", "ties", "threshold_k", "p_improvement", "p_degradation",
                          "beyond_noise", "degradation_beyond_noise"})
        self.assertEqual(set(ab.resume([1.0, 2.0])), {"median", "min", "max", "values"})


class GainRelatif(unittest.TestCase):
    def test_sens(self):
        self.assertAlmostEqual(ab.gain_relatif(100.0, 103.0, "higher"), 0.03)
        self.assertAlmostEqual(ab.gain_relatif(1000.0, 970.0, "lower"), 0.03)
        self.assertIsNone(ab.gain_relatif(0, 1.0, "higher"))
        self.assertIsNone(ab.gain_relatif(None, 1.0, "higher"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
