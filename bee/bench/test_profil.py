#!/usr/bin/env python3
"""Tests unitaires du repérage des fonctions de profil.py (ni Valgrind, ni compilation).

Le fichier C d'exemple est écrit dans un dossier temporaire. Il reprend ce qui a trompé le repérage
(tâche miniz-0033) : une ligne de commentaire de bloc de la forme « mot (… » prise pour un en-tête de
fonction, et des accolades dans un commentaire ou une chaîne qui faussent leur compte.

Usage : python3 bee/bench/test_profil.py
"""

import importlib.util
import os
import tempfile
import unittest

_CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profil.py")
_SPEC = importlib.util.spec_from_file_location("profil", _CHEMIN)
profil = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(profil)

EXEMPLE = r"""/* Exemple pour bee/bench/test_profil.py. */
#include "miniz.h"

int exemple_public(void);

/* Comparaison par mots de 64 bits : la fin se fait
   octet par octet (mêmes correspondances choisies, sortie identique) et ne lit
   jamais au-delà du tampon. */
static int compte_non_nuls(const unsigned char *p, int n)
{
    int i, total = 0; // accolade dans un commentaire de ligne : {
    for (i = 0; i < n; i++)
        total += p[i] != 0;
    return total;
}

static const char *etat(int c)
{
    if (c == '}')
        return "fermante";
    return c ? "motif (64 bits) /* { trouvé" : "absent";
}

static MZ_FORCEINLINE int minimum(int a, int b)
{
    return a < b ? a : b;
}

#if TDEFL_FIND_MATCH_64BIT
static void cherche(const unsigned char *p,
                    int n)
{
    (void)p, (void)n;
}
#else
static void cherche(const unsigned char *p, int n)
{
    /* repli (octet par octet) */
    (void)compte_non_nuls(p, n);
}
#endif

int exemple_public(void)
{
    return minimum(1, 2) + (etat(0) != 0);
}
"""

# (début, fin, nom) attendus, lignes comptées à partir de 1 dans EXEMPLE.
ATTENDU = [
    (9, 15, "compte_non_nuls"),
    (17, 22, "etat"),
    (24, 27, "minimum"),
    (30, 34, "cherche"),
    (36, 40, "cherche"),
    (43, 46, "exemple_public"),
]


class Reperage(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = os.path.join(self.dossier.name, "exemple.c")
        with open(self.chemin, "w", encoding="utf-8") as f:
            f.write(EXEMPLE)

    def tearDown(self):
        self.dossier.cleanup()

    def test_plages_exactes(self):
        self.assertEqual(profil.plages_de_fonctions(self.chemin), ATTENDU)

    def test_attribution_des_lignes(self):
        plages = profil.plages_de_fonctions(self.chemin)
        attendu = {
            7: "exemple.c (hors fonction)",  # « octet par octet (… » dans le commentaire de bloc
            13: "compte_non_nuls",
            21: "etat",
            26: "minimum",
            33: "cherche (l. 30)",  # deux variantes sous #if : distinguées par leur première ligne
            39: "cherche (l. 36)",
            45: "exemple_public",
        }
        for ligne, nom in attendu.items():
            self.assertEqual(profil.nom_de(plages, ligne, "exemple.c"), nom, f"ligne {ligne}")


class SansCommentaires(unittest.TestCase):
    def test_lignes_conservees(self):
        nettoye = profil.sans_commentaires(EXEMPLE)
        self.assertEqual([len(l) for l in nettoye.split("\n")], [len(l) for l in EXEMPLE.split("\n")])
        self.assertEqual(nettoye.split("\n")[10].rstrip(), "    int i, total = 0;")
        self.assertEqual(nettoye.split("\n")[6].strip(), "")

    def test_morceaux(self):
        # (texte, gardé ?) : ce qui n'est pas gardé devient des espaces, sauts de ligne compris gardés.
        morceaux = [("a = ", True), ('"/* pas un commentaire {"', False), ("; b = ", True),
                    ("/* c \"d\n(e */", False), (" f = ", True), ("'\"'", False), ("; g = ", True),
                    ('"\\" { ("', False), ("; ", True), ("// h { (\\\n suite du commentaire", False),
                    ("\ni(\\\n);", True), (" '}'", False)]
        texte = "".join(m for m, _ in morceaux)
        attendu = "".join(m if garde else "".join(c if c == "\n" else " " for c in m) for m, garde in morceaux)
        self.assertEqual(profil.sans_commentaires(texte), attendu)


if __name__ == "__main__":
    unittest.main(verbosity=1)
