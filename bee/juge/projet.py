"""Greffon de minizBee pour le juge commun Bee (registre : outils/juge/, docs/juge-commun.md).

Le juge commun (isolement, lanceur chrono, lecture sûre, analyse des objets, graine, statistiques,
rapport) est lu dans le registre à une étiquette (juge-vN, épinglée dans .github/workflows/bee-ci.yml).
Ce fichier dit ce qui est propre à miniz : les sources, la construction (construire.sh), les entrées
(corpus, données tirées au hasard, flux zlib produits par l'hôte), la règle de justesse (sorties
identiques à la base, aller-retour par la zlib de l'hôte) et les scénarios mesurés. Il est lu depuis la
BASE de la PR, jamais depuis la PR (seule exception : la PR qui l'introduit, en amorçage, voir
bee/ci/juges.sh). Il ne voit les sorties du conteneur qu'à travers lecture.Sorties, n'exécute rien de ce
que le conteneur a produit et ne fait confiance qu'à la base (A) et à la zlib de l'hôte. Les fonctions
d'entrées sont celles du juge isolé de miniz-0031 (version 2), à l'identique : même graine, mêmes
entrées, mêmes vérifications, mêmes décomptes (bee/juge/test_juge.py le vérifie).
"""

import subprocess
import zlib

from entrees import Entree, charger_corpus, perturber
from lecture import Erreur, Refus

NIVEAUX_UNIQUE = (0, 1, 2, 3, 6, 9, 10)
NIVEAUX_FLUX = (1, 6, 9)
MZ_OK, MZ_STREAM_END = 0, 1
# bee/corpus/generer.py lit des sources de miniz figées à ce commit par leur identifiant d'objet git.
COMMIT_CORPUS = "2948eebafc5b9f1c69bebed80333e403a09bd62d"


def decompresser_zlib(donnees):
    """Décompression de référence (zlib de l'hôte) d'un flux zlib complet ; None s'il est invalide."""
    d = zlib.decompressobj()
    try:
        sortie = d.decompress(donnees) + d.flush()
    except zlib.error:
        return None
    return sortie if d.eof and not d.unused_data else None


def mots(rng, nombre):
    lettres = "etaoinshrdlucmfwypvbgkjqxz"
    poids = [12, 9, 8, 8, 7, 7, 6, 6, 6, 4, 4, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1]
    return ["".join(rng.choices(lettres, poids, k=rng.randint(1, 11))) for _ in range(nombre)]


def entrees_aleatoires(rng, corpus):
    """Entrées que personne ne connaît avant l'exécution : formes variées, tailles aux bornes des blocs."""
    e = []
    octets = lambda n: rng.randbytes(n)  # noqa: E731
    e += [b"", octets(1), octets(2)] + [octets(rng.randint(3, 300)) for _ in range(3)]
    e.append(octets(65536 + rng.randint(-3, 3)))
    vocabulaire = mots(rng, 600)
    for _ in range(2):
        cible = rng.randint(100_000, 900_000)
        morceaux, n = [], 0
        while n < cible:
            m = rng.choice(vocabulaire) + rng.choice(" " * 12 + "\n,.;")
            morceaux.append(m)
            n += len(m)
        e.append("".join(morceaux).encode()[:cible])
    for taille in (32767, 32768, 32769, 65535, 65536, 65537):
        base = rng.choice(corpus)[1] if corpus else b""
        debut = rng.randrange(max(1, len(base) - taille)) if len(base) > taille else 0
        bloc = bytearray((base[debut:debut + taille] or b"x") * (taille // max(1, len(base[debut:debut + taille])) + 1))[:taille]
        for _ in range(8):
            if bloc:
                bloc[rng.randrange(len(bloc))] = rng.randrange(256)
        e.append(bytes(bloc))
    sequences = bytearray()
    while len(sequences) < 500_000:
        longueur = rng.choice([rng.randint(1, 20), rng.randint(20, 300), rng.randint(258, 1000), rng.randint(30_000, 70_000)])
        sequences += bytes([rng.randrange(256)]) * longueur
    e.append(bytes(sequences[:500_000]))
    for periode in (rng.randint(1, 300), rng.randint(32_700, 32_800)):
        motif = octets(periode)
        bloc = bytearray((motif * (300_000 // periode + 2))[:300_000])
        for _ in range(200):
            bloc[rng.randrange(len(bloc))] = rng.randrange(256)
        e.append(bytes(bloc))
    structure = bytearray()
    valeur = rng.randrange(1 << 32)
    while len(structure) < 400_000:
        valeur = (valeur + rng.randint(-50, 50)) & 0xFFFFFFFF
        structure += valeur.to_bytes(4, "little") + bytes([rng.randrange(4)]) * 2
    e.append(bytes(structure))
    melange = bytearray()
    while corpus and len(melange) < 1_000_000:
        base = rng.choice(corpus)[1]
        if base:
            debut = rng.randrange(len(base))
            melange += base[debut:debut + rng.randint(1, 50_000)]
        if rng.random() < 0.3:
            melange += octets(rng.randint(1, 2000))
    e.append(bytes(melange))
    grand = bytearray()
    while len(grand) < 4_000_000:
        grand += (rng.choice(vocabulaire) + " ").encode() * rng.randint(1, 50) if rng.random() < 0.7 else octets(rng.randint(1, 5000))
    e.append(bytes(grand[:4_000_000]))
    return [(f"a{i:03d}", d) for i, d in enumerate(e)]


def flux_zlib(rng, originaux):
    """Flux zlib produits ICI (zlib de l'hôte), valides et invalides, avec la taille de tampon à donner.

    Renvoie [(nom, flux, taille_tampon, original_ou_None)] ; original None : comportement de la base."""
    strategies = [zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED]
    flux = []
    for i, (_, d) in enumerate(originaux):
        if i % 3 == 0:
            z = zlib.compress(d, (0, 1, 6, 9)[i % 4])
        elif i % 3 == 1:
            c = zlib.compressobj(rng.randint(0, 9), zlib.DEFLATED, rng.randint(9, 15), rng.randint(1, 9), rng.choice(strategies))
            z = c.compress(d) + c.flush()
        else:
            c = zlib.compressobj(rng.randint(1, 9))
            morceaux, pos = [], 0
            while pos < len(d):
                n = rng.randint(1, 100_000)
                morceaux.append(c.compress(d[pos:pos + n]))
                morceaux.append(c.flush(rng.choice([zlib.Z_SYNC_FLUSH, zlib.Z_FULL_FLUSH, zlib.Z_NO_FLUSH])))
                pos += n
            z = b"".join(morceaux) + c.flush()
        flux.append((z, len(d), d))
    valides = [f for f in flux if f[1] > 0]
    for k in range(min(14, len(valides))):
        z, taille, d = valides[(k * 7) % len(valides)]
        genre = k % 7
        if genre == 0 and len(z) > 2:
            flux.append((z[:rng.randrange(1, len(z))], taille, None))
        elif genre == 1 and len(z) > 6:
            b = bytearray(z)
            b[rng.randrange(2, len(z) - 4)] ^= 1 << rng.randrange(8)
            flux.append((bytes(b), taille, None))
        elif genre == 2:
            flux.append((z[:-4] + bytes(x ^ 0xFF for x in z[-4:]), taille, None))
        elif genre == 3:
            flux.append((z, max(0, taille - 1), None))
        elif genre == 4:
            flux.append((rng.randbytes(rng.randint(1, 1000)), 1000, None))
        elif genre == 5:
            flux.append((bytes([0x78, rng.choice([0x00, 0x9C ^ 1, 0xDA ^ 4])]) + z[2:], taille, None))
        else:
            flux.append((z + rng.randbytes(rng.randint(1, 50)), taille, None))
    return [(f"z{i:03d}", z, taille, d) for i, (z, taille, d) in enumerate(flux)]


def historique_du_corpus(outillage):
    """Vérifie que les objets git du commit COMMIT_CORPUS sont lisibles dans la copie de la base (outillage).

    Les sources figées que bee/corpus/generer.py lit par identifiant d'objet (miniz_tdef.c et miniz_tinfl.c
    d'origine, entre autres) viennent de ce commit. juge.yml (juge-v2, ruche-0024) le récupère avant la PR,
    parce que bee-ci.yml le déclare (historique) ; pendant le jugement, git n'a plus aucun transport. Aucun
    accès réseau ici : un commit absent est une erreur d'environnement (code 2)."""
    if subprocess.run(["git", "-C", outillage, "cat-file", "-e", COMMIT_CORPUS + "^{commit}"],
                      capture_output=True).returncode != 0:
        raise Erreur(f"corpus : commit {COMMIT_CORPUS} absent de la base ; déclarez-le à juge.yml (historique)")


class Projet:
    NOM = "miniz"
    # Paquets en plus de l'image commune : tests d'origine (g++, cmake), tests différentiels (zlib1g-dev),
    # générateur du corpus (git), fuzzing libFuzzer (clang-18, libclang-rt-18-dev), lancés par isoler.sh.
    PAQUETS = ["g++", "cmake", "zlib1g-dev", "git", "clang-18", "libclang-rt-18-dev"]
    # Fichiers compilés par construire.sh (miniz_zip.c ne l'est pas : il n'est ni copié, ni jugé) ; le diff
    # analysé est celui de ces fichiers, et chaque .c doit laisser son objet dans obj/.
    SOURCES = ["miniz.c", "miniz_tdef.c", "miniz_tinfl.c", "miniz*.h"]
    SOURCES_REQUISES = ["miniz.c", "miniz_tdef.c", "miniz_tinfl.c", "miniz.h"]
    OUTILLAGE = ["bee/juge", "bee/commun"]
    EN_TETES_BASE = ["miniz*.h"]
    CONSTRUIRE = "bee/juge/construire.sh"
    PREFIXES = ("mz_", "tdefl_", "tinfl_", "miniz_", "MZ_")
    PERMIS = ()
    # Les fichiers bruts (f) et les flux zlib (z) passent dans des conteneurs SÉPARÉS : une décompression ne
    # voit jamais les originaux (sinon elle pourrait les retrouver et les recopier au lieu de décompresser).
    COTES = ("f", "z")
    SCENARIOS = {"n1": "f", "n6": "f", "n9": "f", "decompression": "z", "memoire": "f"}
    INSTRUCTIONS = ("n1", "n6", "n9", "decompression")
    METRIQUES = [  # mêmes définitions que projets/miniz.yaml du registre et bee/bench/ab.py
        ("debit_compression_n1", "plus_haut", "Mo/s"),
        ("debit_compression_n6", "plus_haut", "Mo/s"),
        ("debit_compression_n9", "plus_haut", "Mo/s"),
        ("debit_decompression", "plus_haut", "Mo/s"),
        ("ratio_n6", "plus_haut", "ratio"),
        ("memoire_max_ko", "plus_bas", "Ko"),
    ]
    METHODE = {"memoire": "ru_maxrss du processus du scénario « memoire » (flux par blocs de 64 Kio), lu par wait4"}

    def __init__(self, options):
        sortie = options.pop("sortie_compressee", "identique")
        if sortie not in ("identique", "peut_changer"):
            raise Erreur(f"sortie_compressee : identique ou peut_changer, pas {sortie!r}")
        if options:
            raise Erreur("options inconnues : " + ", ".join(sorted(options)))
        self.identique = sortie == "identique"
        self.VERIFICATION = {"sortie_compressee": sortie}

    # -------------------------------------------------------------- entrées

    def corpus(self, outillage):
        historique_du_corpus(outillage)
        return charger_corpus(outillage, "bee/corpus/generer.py", "bee/corpus/donnees")

    @staticmethod
    def entrees(fichiers, flux):
        return [Entree("f", nom, d, len(d), d) for nom, d in fichiers] + \
               [Entree("z", nom, z, taille, original) for nom, z, taille, original in flux]

    def verification(self, rng, corpus):
        aleatoires = entrees_aleatoires(rng, corpus)
        fichiers = corpus + aleatoires
        flux = flux_zlib(rng, [f for f in aleatoires if len(f[1]) <= 2_000_000] + corpus[::max(1, len(corpus) // 12)])
        return self.entrees(fichiers, flux)

    def repetition(self, rng, corpus):
        perturbes = perturber(rng, corpus)
        return self.entrees(perturbes, [(nom, zlib.compress(d, 6), len(d), d) for nom, d in perturbes])

    def instructions(self, rng, corpus, prefixe):
        perturbes = perturber(rng, corpus, prefixe)
        return self.entrees(perturbes, [(nom, zlib.compress(d, 6), len(d), d) for nom, d in perturbes])

    # -------------------------------------------------------------- vérification

    def compressee(self, a, b, relatif, original):
        sortie_b = b.exiger("f", relatif)
        if self.identique:
            sortie_a = a.exiger("f", relatif)
            if sortie_a != sortie_b:
                raise Refus(f"sortie compressée différente de la base : {relatif} ({len(sortie_a)} contre {len(sortie_b)} octets)")
        elif decompresser_zlib(sortie_b) != original:
            raise Refus(f"la sortie compressée ne redonne pas l'original (zlib de l'hôte) : {relatif}")
        return len(sortie_b)

    def verifier(self, a, b, entrees):
        comparees = 0
        for e in entrees:
            if e.cote != "f":
                continue
            # Contrôle de bon sens sur la base elle-même (niveau 6) : il détecte un juge mal monté.
            if decompresser_zlib(a.exiger("f", f"c/{e.nom}.6")) != e.donnees:
                raise Erreur(f"la base ne redonne pas l'original pour {e.nom} : juge mal monté")
            for niveau in NIVEAUX_UNIQUE:
                self.compressee(a, b, f"c/{e.nom}.{niveau}", e.donnees)
                comparees += 1
            for niveau in NIVEAUX_FLUX:
                self.compressee(a, b, f"s/{e.nom}.{niveau}", e.donnees)
                comparees += 1
        for e in entrees:
            if e.cote != "z":
                continue
            for sortie, etat, unique in (("d", "e", True), ("ds", "es", False)):
                code_a, _ = a.statut("z", f"{etat}/{e.nom}")
                code_b, _ = b.statut("z", f"{etat}/{e.nom}")
                if code_a != code_b:
                    raise Refus(f"décompression ({'mz_uncompress' if unique else 'mz_inflate en flux'}) de {e.nom} : "
                                f"code {code_b}, la base donne {code_a}")
                sa, sb = a.exiger("z", f"{sortie}/{e.nom}"), b.exiger("z", f"{sortie}/{e.nom}")
                comparees += 1
                if code_a == (MZ_OK if unique else MZ_STREAM_END):
                    if sa != sb:
                        raise Refus(f"décompression de {e.nom} différente de la base ({sortie})")
                    if e.attendu is not None and sa != e.attendu:
                        raise Erreur(f"la base ne redonne pas l'original de {e.nom} ({sortie}) : juge mal monté")
                elif sa[:min(len(sa), len(sb))] != sb[:min(len(sa), len(sb))]:
                    raise Refus(f"décompression de {e.nom} en erreur : octets produits différents de la base ({sortie})")
        return comparees

    def fixes(self, sorties, corpus):
        total = sum(len(d) for _, d in corpus)
        compresse = sum(len(sorties.exiger("f", f"c/{nom}.6")) for nom, _ in corpus)
        return {"ratio_n6": total / compresse if compresse else None}

    def scenario(self, s, a, b, entrees, mesure):
        """Sorties d'un scénario mesuré ; renvoie ({métrique: valeur}, sorties comparées)."""
        traites = comparees = 0
        cpu = mesure["utilisateur_s"] + mesure["systeme_s"]
        if s in ("n1", "n6", "n9"):
            for e in entrees:
                if e.cote == "f":
                    self.compressee(a, b, f"{s}/c/{e.nom}", e.donnees)
                    traites += len(e.donnees)
                    comparees += 1
            return {f"debit_compression_{s}": traites / 1e6 / cpu if cpu > 0 else None}, comparees
        if s == "decompression":
            for e in entrees:
                if e.cote == "z":
                    if b.exiger("z", f"decompression/d/{e.nom}") != e.attendu:
                        raise Refus(f"décompression mesurée de {e.nom} différente de l'original")
                    traites += len(e.attendu)
                    comparees += 1
            return {"debit_decompression": traites / 1e6 / cpu if cpu > 0 else None}, comparees
        if s == "memoire":
            for e in entrees:
                if e.cote == "f":
                    self.compressee(a, b, f"memoire/m/{e.nom}", e.donnees)
                    comparees += 1
            return {"memoire_max_ko": mesure["maxrss_ko"]}, comparees
        raise Erreur(f"scénario inconnu : {s}")
