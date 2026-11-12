"""minizBee's plugin for the Bee common judge (registry: tools/judge/, docs/common-judge.md).

The common judge (isolation, chrono launcher, safe reading, object analysis, seed, statistics, report) is read in the
registry at a commit (judge-vN, pinned by SHA in .github/workflows/bee-ci.yml). This file says what is specific to
miniz: the sources, the build (build.sh), the inputs (corpus, randomly drawn data, zlib streams produced by the host),
the correctness rule (outputs identical to the base, round trip through the host's zlib) and the measured scenarios.
It is read from the PR's BASE, never from the PR. It sees the container's outputs only through lecture.Sorties, runs
nothing the container produced, and trusts only the base (A) and the host's zlib. The input functions are those of
miniz-0031's isolated judge (version 2), unchanged: same seed, same inputs, same checks, same counts
(bee/judge/test_judge.py checks it).

The English plugin contract (judge-v4, ruche-0148; miniz-0050): Project, NAME, PACKAGES, REQUIRED_SOURCES, TOOLING,
BASE_HEADERS, BUILD, ALLOWED, SIDES, METRICS (directions higher and lower), METHOD, verify() and fixed(). The metric
ids are the registry's English ones (compression_throughput_n1, ..., max_memory_kb).

juge-v3 contract (miniz-0048; the registry's docs/common-judge.md): the harness reads its parameters on its
descriptor 0 and writes an input's output at the same path in every mode (bee/judge/execution.c); the common judge
mixes verification inputs, invalid streams included, into the measured ones. So each scenario checks every output
of its side with the rule of verify(), and n6 also computes ratio_n6 from its timed outputs.
"""

import subprocess
import zlib

from entrees import Entree, charger_corpus, perturber
from lecture import Erreur, Refus

NIVEAUX_UNIQUE = (0, 1, 2, 3, 6, 9, 10)
NIVEAUX_FLUX = (1, 6, 9)
MZ_OK, MZ_STREAM_END = 0, 1
# bee/corpus/generer.py reads miniz sources frozen at this commit by their git object id.
COMMIT_CORPUS = "2948eebafc5b9f1c69bebed80333e403a09bd62d"


def decompresser_zlib(donnees):
    """Reference decompression (the host's zlib) of a complete zlib stream; None if it is invalid."""
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
    """Inputs nobody knows before the run: varied shapes, sizes at the bounds of the blocks."""
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
    """zlib streams produced HERE (the host's zlib), valid and invalid, with the buffer size to give.

    Returns [(name, stream, buffer_size, original_or_None)]; original None: the base's behavior."""
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
    """Checks that the git objects of the commit COMMIT_CORPUS are readable in the base's copy (outillage).

    The frozen sources that bee/corpus/generer.py reads by object id (the original miniz_tdef.c and miniz_tinfl.c,
    among others) come from this commit. judge.yml (since juge-v2, ruche-0024) fetches it before the PR, because
    bee-ci.yml declares it (history); during judging, git no longer has any transport. No network access here: a
    missing commit is an environment error (code 2)."""
    if subprocess.run(["git", "-C", outillage, "cat-file", "-e", COMMIT_CORPUS + "^{commit}"],
                      capture_output=True).returncode != 0:
        raise Erreur(f"corpus: commit {COMMIT_CORPUS} missing from the base; declare it to judge.yml (history), "
                     f"or, locally, git fetch --depth=1 origin {COMMIT_CORPUS}")


class Project:
    NAME = "miniz"
    # Packages on top of the common image: original tests (g++, cmake), differential tests (zlib1g-dev), corpus
    # generator (git), libFuzzer fuzzing (clang-18, libclang-rt-18-dev), run through isoler.sh.
    PACKAGES = ["g++", "cmake", "zlib1g-dev", "git", "clang-18", "libclang-rt-18-dev"]
    # Files compiled by build.sh (miniz_zip.c is not: it is neither copied nor judged); the judge analyzes these
    # files whole, and each .c must leave its object in obj/.
    SOURCES = ["miniz.c", "miniz_tdef.c", "miniz_tinfl.c", "miniz*.h"]
    REQUIRED_SOURCES = ["miniz.c", "miniz_tdef.c", "miniz_tinfl.c", "miniz.h"]
    TOOLING = ["bee/judge", "bee/commun"]
    BASE_HEADERS = ["miniz*.h"]
    BUILD = "bee/judge/build.sh"
    PREFIXES = ("mz_", "tdefl_", "tinfl_", "miniz_", "MZ_")
    ALLOWED = ()
    # The raw files (f) and the zlib streams (z) go through SEPARATE containers: a decompression never sees the
    # originals (otherwise it could find them and copy them instead of decompressing).
    SIDES = ("f", "z")
    SCENARIOS = {"n1": "f", "n6": "f", "n9": "f", "decompression": "z", "memoire": "f"}
    INSTRUCTIONS = ("n1", "n6", "n9", "decompression")
    METRICS = [  # the same definitions as the registry's projects/miniz.yaml and bee/bench/ab.py, English ids
        ("compression_throughput_n1", "higher", "MB/s"),
        ("compression_throughput_n6", "higher", "MB/s"),
        ("compression_throughput_n9", "higher", "MB/s"),
        ("decompression_throughput", "higher", "MB/s"),
        ("ratio_n6", "higher", "ratio"),
        ("max_memory_kb", "lower", "KB"),
    ]
    METHOD = {"max_memory_kb": "ru_maxrss of the process of the scenario « memoire » (streaming in blocks of 64 KiB), read by wait4",
              "ratio_n6": "original size divided by compressed size at level 6, on the timed outputs of scenario n6 "
                          "(perturbed corpus and the verification inputs mixed into it)"}

    def __init__(self, options):
        sortie = options.pop("sortie_compressee", "identique")
        if sortie not in ("identique", "peut_changer"):
            raise Erreur(f"sortie_compressee: identique or peut_changer, not {sortie!r}")
        if options:
            raise Erreur("unknown options: " + ", ".join(sorted(options)))
        self.identique = sortie == "identique"
        self.VERIFICATION = {"sortie_compressee": sortie}

    # -------------------------------------------------------------- inputs

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

    # -------------------------------------------------------------- verification

    def compressee(self, a, b, relatif, original):
        sortie_b = b.exiger("f", relatif)
        if self.identique:
            sortie_a = a.exiger("f", relatif)
            if sortie_a != sortie_b:
                raise Refus(f"compressed output differs from the base: {relatif} ({len(sortie_a)} vs {len(sortie_b)} bytes)")
        elif decompresser_zlib(sortie_b) != original:
            raise Refus(f"the compressed output does not give back the original (host zlib): {relatif}")
        return len(sortie_b)

    def decompressee(self, a, b, e, sortie, etat, unique=True):
        """One decompression of a stream (mz_uncompress, or mz_inflate in chunked streaming): same code as A, same
        bytes (those produced before the error, for a stream in error), and A gives back the original. Returns the
        number of bytes A produced."""
        code_a, _ = a.statut("z", f"{etat}/{e.nom}")
        code_b, _ = b.statut("z", f"{etat}/{e.nom}")
        if code_a != code_b:
            raise Refus(f"decompression ({'mz_uncompress' if unique else 'streamed mz_inflate'}) of {e.nom}: "
                        f"code {code_b}, the base gives {code_a}")
        sa, sb = a.exiger("z", f"{sortie}/{e.nom}"), b.exiger("z", f"{sortie}/{e.nom}")
        if code_a == (MZ_OK if unique else MZ_STREAM_END):
            if sa != sb:
                raise Refus(f"decompression of {e.nom} differs from the base ({sortie})")
            if e.attendu is not None and sa != e.attendu:
                raise Erreur(f"the base does not give back the original of {e.nom} ({sortie}): judge set up wrong")
        elif sa[:min(len(sa), len(sb))] != sb[:min(len(sa), len(sb))]:
            raise Refus(f"decompression of {e.nom} in error: bytes produced differ from the base ({sortie})")
        return len(sa)

    def verify(self, a, b, entrees):
        comparees = 0
        for e in entrees:
            if e.cote != "f":
                continue
            # Sanity check on the base itself (level 6): it detects a judge set up wrong.
            if decompresser_zlib(a.exiger("f", f"c/{e.nom}.6")) != e.donnees:
                raise Erreur(f"the base does not give back the original for {e.nom}: judge set up wrong")
            for niveau in NIVEAUX_UNIQUE:
                self.compressee(a, b, f"c/{e.nom}.{niveau}", e.donnees)
            for niveau in NIVEAUX_FLUX:
                self.compressee(a, b, f"s/{e.nom}.{niveau}", e.donnees)
            self.compressee(a, b, f"m/{e.nom}", e.donnees)
            comparees += len(NIVEAUX_UNIQUE) + len(NIVEAUX_FLUX) + 1
        for e in entrees:
            if e.cote != "z":
                continue
            self.decompressee(a, b, e, "d", "e")
            self.decompressee(a, b, e, "ds", "es", unique=False)
            comparees += 2
        return comparees

    def fixed(self, sorties, corpus):
        total = sum(len(d) for _, d in corpus)
        compresse = sum(len(sorties.exiger("f", f"c/{nom}.6")) for nom, _ in corpus)
        return {"ratio_n6": total / compresse if compresse else None}

    def scenario(self, s, a, b, entrees, mesure):
        """Outputs of a measured scenario, each one checked by the rule of verify(), whatever its input (the common
        judge mixes verification inputs into the measured ones); returns ({metric: value}, outputs compared). n6 also
        computes ratio_n6 from its timed outputs, which replaces the value fixed() reads on verification."""
        if s not in self.SCENARIOS:
            raise Erreur(f"unknown scenario: {s}")
        cpu = mesure["utilisateur_s"] + mesure["systeme_s"]
        mesurees = [e for e in entrees if e.cote == self.SCENARIOS[s]]
        if s in ("n1", "n6", "n9"):
            compresses = [self.compressee(a, b, f"{s}/c/{e.nom}.{s[1]}", e.donnees) for e in mesurees]
            traites = sum(len(e.donnees) for e in mesurees)
            valeurs = {f"compression_throughput_{s}": traites / 1e6 / cpu if cpu > 0 else None}
            if s == "n6":
                valeurs["ratio_n6"] = traites / sum(compresses) if sum(compresses) else None
            return valeurs, len(mesurees)
        if s == "decompression":
            traites = sum(self.decompressee(a, b, e, f"{s}/d", f"{s}/e") for e in mesurees)
            return {"decompression_throughput": traites / 1e6 / cpu if cpu > 0 else None}, len(mesurees)
        for e in mesurees:
            self.compressee(a, b, f"memoire/m/{e.nom}", e.donnees)
        return {"max_memory_kb": mesure["maxrss_ko"]}, len(mesurees)
