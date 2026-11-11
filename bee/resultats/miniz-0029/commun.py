"""Définitions communes aux mesures de miniz-0029 : chemins, familles du corpus, zones de code.

Les zones sont des plages de lignes des sources de miniz au commit a2f939a (master du 30/10/2026).
Elles ne valent que pour ces sources : verifier_sources() compare leurs SHA-256 à celles de ce
commit et arrête tout en cas d'écart (refaire alors les plages, ou extraire a2f939a).
"""

import hashlib
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
BEE = os.path.dirname(os.path.dirname(ICI))
RACINE = os.path.dirname(BEE)
CORPUS = os.path.join(BEE, "corpus", "donnees")
BANC = os.path.join(BEE, "construction", "banc", "banc")
CONSTR = os.path.join(BEE, "construction", "miniz-0029")

sys.path.insert(0, os.path.join(BEE, "bench"))
import profil  # noqa: E402  (bee/bench/profil.py, lu tel quel : repérage des fonctions dans le source)

COMMIT = "a2f939a"
SHA256_SOURCES = {
    "miniz_tdef.c": "7405df4afa761a96de81dfe1eebad0cdca7e240793d2e1f5dba7503d78df1127",
    "miniz_tinfl.c": "68aa4df214ed8a37bdc848e11c2a63193cb662e5a97e8d141facb1415665a147",
    "miniz.c": "29a0c08c4610d20ab18381cbf18190f91b4b41d05c242376364756061b631f1d",
}
SOURCES = list(SHA256_SOURCES)

# Familles du corpus (bee/README.md) ; « vide » (un fichier de 0 octet) est omise.
FAMILLES = ["texte", "code", "structure", "binaire", "repetitif", "petits"]
PREFIXE = 131072  # comme profil.py, ab.py --instructions et le juge commun : 128 premiers Kio par fichier

# Simulation de cache explicite, pour que les chiffres ne dépendent pas de la machine qui les
# rejoue : L1 de la machine de référence (Xeon 2,1 GHz virtualisé : L1i 32 Kio, L1d 48 Kio par cœur),
# et, comme dernier niveau, son L2 par cœur (2 Mio). Son L3 (260 Mio, partagé, virtualisé) ne
# ferait voir aucun défaut ; Cachegrind ne simule que deux niveaux.
OPTIONS_CACHE = ["--I1=32768,8,64", "--D1=49152,12,64", "--LL=2097152,16,64"]

# Zones (fichier, première ligne, dernière ligne, nom) à a2f939a. La fonction englobante est
# trouvée par profil.plages_de_fonctions ; une ligne hors de toute zone garde « (reste) ».
ZONES = {
    "miniz_tdef.c": [
        (482, 502, "lz_codes : entrée, boucle, drapeaux"),
        (503, 525, "lz_codes : correspondances (longueur, distance, bits supplémentaires)"),
        (526, 547, "lz_codes : littéraux (1 à 3 par tour)"),
        (548, 575, "lz_codes : écriture du tampon de bits, fin de bloc"),
        (862, 877, "find_match : entrée (état, c01)"),
        (878, 881, "find_match : budget de sondes (--num_probes_left)"),
        (882, 893, "find_match : sondes (m_next, distance, 2 octets de fin)"),
        (894, 895, "find_match : distance nulle"),
        (896, 932, "find_match : comparaison par mots de 64 bits"),
        (933, 942, "find_match : nouvelle meilleure correspondance"),
        (1172, 1187, "compress_normal : entrée, préparation de l'insertion"),
        (1188, 1217, "compress_normal : insertion dans les chaînes (cas courant)"),
        (1218, 1253, "compress_normal : insertion (bords de fenêtre, début)"),
        (1254, 1282, "compress_normal : fenêtre et préparation de la recherche"),
        (1283, 1284, "compress_normal : appel de tdefl_find_match"),
        (1285, 1288, "compress_normal : rejet (longueur 3 à 8 Kio et plus)"),
        (1289, 1326, "compress_normal : analyse paresseuse"),
        (1327, 1331, "compress_normal : avancement de la fenêtre"),
        (1332, 1347, "compress_normal : décision de vidage, sortie"),
    ],
    "miniz_tinfl.c": [
        (187, 242, "tinfl : entrée et en-tête zlib"),
        (243, 292, "tinfl : en-tête de bloc, blocs stockés"),
        (293, 421, "tinfl : construction des tables de Huffman"),
        (422, 426, "tinfl : boucle des symboles"),
        (427, 427, "tinfl : littéraux, test du chemin rapide (l. 427)"),
        (428, 437, "tinfl : littéraux, chemin lent (fin de tampon)"),
        (438, 512, "tinfl : littéraux, chemin rapide"),
        (513, 534, "tinfl : longueur et distance (macros)"),
        (535, 542, "tinfl : contrôle de distance, source"),
        (543, 543, "tinfl : copie, test de fin de tampon (l. 543)"),
        (544, 554, "tinfl : copie, chemin lent (fin de tampon)"),
        (555, 614, "tinfl : copie sans chevauchement (4 ou 8 octets)"),
        (615, 631, "tinfl : copie octet par octet (chevauchement, longueur 3)"),
        (632, 661, "tinfl : fin de flux, Adler-32 lu"),
        (662, 681, "tinfl : sortie commune (état sauvé)"),
        (682, 733, "tinfl : Adler-32 de la sortie"),
    ],
}


def verifier_sources(racine=RACINE):
    """Arrête le script si les sources de miniz ne sont pas celles de a2f939a."""
    for nom, attendu in SHA256_SOURCES.items():
        with open(os.path.join(racine, nom), "rb") as f:
            vu = hashlib.sha256(f.read()).hexdigest()
        if vu != attendu:
            sys.exit(f"{nom} n'est pas celui de {COMMIT} (SHA-256 {vu[:12]}…) : les zones de commun.py "
                     f"ne s'appliquent pas. Extrayez {COMMIT} ou refaites les plages.")


_PLAGES = None


def plages():
    global _PLAGES
    if _PLAGES is None:
        _PLAGES = {s: profil.plages_de_fonctions(os.path.join(RACINE, s)) for s in SOURCES}
    return _PLAGES


def fonction_de(fichier, ligne):
    """Nom de la fonction source qui contient la ligne (inline comprises), comme profil.py."""
    return profil.nom_de(plages()[fichier], ligne, fichier)


def zone_de(fichier, ligne):
    for debut, fin, nom in ZONES.get(fichier, []):
        if debut <= ligne <= fin:
            return nom
    return None


def corpus_de(famille):
    return CORPUS if famille == "tout" else os.path.join(CORPUS, famille)
