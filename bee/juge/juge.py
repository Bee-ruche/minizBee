#!/usr/bin/env python3
"""Juge isolé Bee pour miniz : exécuter le code de la PR en conteneur et le juger de l'extérieur.

Modèle de menace complet : bee/README.md, section « Juge isolé ». En bref :
- ce programme (l'hôte) n'exécute JAMAIS un fichier issu des sources de la PR. Compilation, exécution et
  décompte d'instructions ont lieu dans des conteneurs sans réseau, en lecture seule, sans privilège,
  limités à deux processus, qui ne voient que leurs entrées et un dossier de sorties ;
- la justesse est vérifiée ici, avec la zlib de l'hôte : chaque sortie compressée doit redonner
  l'original, être identique octet pour octet à celle de la base quand la tâche l'exige, et chaque
  décompression (flux valides, corrompus, tronqués, tampon trop petit) doit se comporter comme la base ;
- une part des entrées est tirée au hasard à chaque exécution (graine choisie ici, après la compilation)
  et les entrées des mesures sont perturbées à chaque répétition : aucune table de réponses précalculées
  ne peut servir, et rien ne peut être mis en cache d'une répétition à l'autre ;
- le temps processeur et la mémoire sont mesurés par le noyau (wait4) dans un lanceur de la base
  (chrono), et le décompte d'instructions est relevé par ce lanceur sur la dernière ligne de Valgrind ;
- une analyse des objets compilés (analyse.py) liste ce qui pourrait tromper la mesure de l'intérieur
  (appels système, requêtes Valgrind, horloge, constructeurs, symboles qui en remplacent d'autres).

Usage :
  python3 bee/juge/juge.py --image-seulement [--outillage DOSSIER]     construit l'image, affiche son étiquette
  python3 bee/juge/juge.py --source-a DOSSIER --source-b DOSSIER [--outillage DOSSIER]
                           [--sortie-compressee identique|peut_changer] [--repetitions 10] [--chauffe 1]
                           [--sans-instructions] [--prefixe-instructions 131072] [--json juge.json]
                           [--depot-diff DOSSIER --base REV --tete REV] [--graine HEX] [--reseau-construction host]
  --source-a / --source-b : dossiers qui contiennent miniz*.c et miniz*.h (A = référence, B = candidate)
  --outillage             : copie de la BASE dont viennent bee/juge, bee/commun, bee/corpus (défaut : ce dépôt)
Sortie : rapport JSON au format d'ab.py (mesures, metriques, instructions) plus une section « juge ».
Code de sortie : 0 si toutes les sorties de B sont justes, 1 si le juge refuse B (sortie fausse ou
absente, exécution en échec, isolation contournée), 2 si l'environnement ne convient pas.
"""

import argparse
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zlib

ICI = os.path.dirname(os.path.abspath(__file__))
OUTILLAGE_DEFAUT = os.path.dirname(os.path.dirname(ICI))
sys.path.insert(0, ICI)
import analyse  # noqa: E402

NIVEAUX_UNIQUE = (0, 1, 2, 3, 6, 9, 10)
NIVEAUX_FLUX = (1, 6, 9)
SCENARIOS = ("n1", "n6", "n9", "decompression", "memoire")
SCENARIOS_INSTRUCTIONS = ("n1", "n6", "n9", "decompression")
MZ_OK, MZ_STREAM_END = 0, 1
TAILLE_MAX_SORTIE = 256 * 1024 * 1024
ISOLATION = ["--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "-e", "HOME=/tmp", "-e", "LC_ALL=C"]


class Erreur(Exception):
    """L'environnement ne convient pas (Docker absent, base qui ne compile pas…) : code 2."""


class Refus(Exception):
    """Le juge refuse B : code 1."""


def journal(message):
    print(f"juge : {message}", file=sys.stderr, flush=True)


def propre(octets, maximum=1500):
    """Texte venu du conteneur, affichable sans risque : tronqué, caractères de contrôle retirés."""
    texte = octets.decode("utf-8", "replace") if isinstance(octets, bytes) else str(octets)
    texte = re.sub(r"[^\x20-\x7e\n -￿]", "?", texte[-maximum:])
    return texte.replace("::", ": :")  # pas de commande de workflow GitHub


# ------------------------------------------------------------------ conteneurs

class Docker:
    def __init__(self, image, memoire="4g"):
        self.image, self.memoire = image, memoire

    def lancer(self, commande, montages, pids=2, entree=None, delai=3600):
        nom = "bee-juge-" + secrets.token_hex(6)
        cmd = ["docker", "run", "--rm", "--name", nom, "--pids-limit", str(pids),
               "--memory", self.memoire, "--memory-swap", self.memoire] + ISOLATION
        if entree is not None:
            cmd.append("-i")
        for hote, cible, lecture_seule in montages:
            cmd += ["--mount", f"type=bind,source={hote},target={cible}" + (",readonly" if lecture_seule else "")]
        cmd += [self.image] + commande
        try:
            return subprocess.run(cmd, input=entree, capture_output=True, timeout=delai)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", nom], capture_output=True)
            raise Refus(f"délai de {delai} s dépassé dans le conteneur ({commande[0]})")


def construire_image(outillage, reseau=None):
    dossier = os.path.join(outillage, "bee", "juge")
    with open(os.path.join(dossier, "Dockerfile"), "rb") as f:
        etiquette = "bee-juge:" + hashlib.sha256(f.read()).hexdigest()[:16]
    if subprocess.run(["docker", "image", "inspect", etiquette], capture_output=True).returncode == 0:
        return etiquette
    journal(f"construction de l'image {etiquette} (seule étape avec réseau, avant tout fichier de la PR)")
    commande = ["docker", "build", "-q", "-t", etiquette] + (["--network", reseau] if reseau else []) + [dossier]
    r = subprocess.run(commande, capture_output=True, text=True)
    if r.returncode != 0:
        raise Erreur("construction de l'image impossible : " + r.stderr[-2000:])
    return etiquette


def dossier_ouvert(chemin):
    """Dossier que le conteneur (utilisateur 65534) peut écrire."""
    os.makedirs(chemin, exist_ok=True)
    os.chmod(chemin, 0o777)
    return chemin


# ------------------------------------------------------------------ lecture sûre des sorties

def lire_sortie(racine, relatif, maximum=TAILLE_MAX_SORTIE):
    """Lit racine/relatif sans jamais suivre un lien symbolique (le conteneur a écrit dans racine).

    Renvoie None si le fichier n'existe pas ; Refus s'il n'est pas un fichier ordinaire ou s'il est trop gros."""
    morceaux = relatif.split("/")
    fd = os.open(racine, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for m in morceaux[:-1]:
            try:
                suivant = os.open(m, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError:
                raise Refus(f"sortie invalide (dossier piégé) : {relatif}")
            os.close(fd)
            fd = suivant
        try:
            ffd = os.open(morceaux[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise Refus(f"sortie invalide (lien ou fichier spécial) : {relatif}")
    finally:
        os.close(fd)
    try:
        st = os.fstat(ffd)
        if not stat.S_ISREG(st.st_mode):
            raise Refus(f"sortie invalide (pas un fichier ordinaire) : {relatif}")
        if st.st_size > maximum:
            raise Refus(f"sortie trop grosse : {relatif} ({st.st_size} octets)")
        morceaux_lus, total = [], 0
        while True:
            bloc = os.read(ffd, 1 << 20)
            if not bloc:
                break
            total += len(bloc)
            if total > maximum:
                raise Refus(f"sortie trop grosse : {relatif}")
            morceaux_lus.append(bloc)
        return b"".join(morceaux_lus)
    finally:
        os.close(ffd)


def exiger(racine, relatif, maximum=TAILLE_MAX_SORTIE):
    donnees = lire_sortie(racine, relatif, maximum)
    if donnees is None:
        raise Refus(f"sortie absente : {relatif}")
    return donnees


def statut(racine, relatif):
    texte = exiger(racine, relatif, 64)
    m = re.fullmatch(rb"(-?\d{1,6}) (\d{1,12})\n", texte)
    if not m:
        raise Refus(f"statut illisible : {relatif}")
    return int(m.group(1)), int(m.group(2))


def decompresser_zlib(donnees):
    """Décompression de référence (zlib de l'hôte) d'un flux zlib complet ; None s'il est invalide."""
    d = zlib.decompressobj()
    try:
        sortie = d.decompress(donnees) + d.flush()
    except zlib.error:
        return None
    return sortie if d.eof and not d.unused_data else None


# ------------------------------------------------------------------ entrées

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


def ecrire_entrees(dossier, fichiers, flux):
    os.makedirs(os.path.join(dossier, "f"), exist_ok=True)
    os.makedirs(os.path.join(dossier, "z"), exist_ok=True)
    lignes = []
    for nom, d in fichiers:
        with open(os.path.join(dossier, "f", nom), "wb") as f:
            f.write(d)
        lignes.append(f"f {nom} {len(d)}")
    for nom, z, taille, _ in flux:
        with open(os.path.join(dossier, "z", nom), "wb") as f:
            f.write(z)
        lignes.append(f"z {nom} {taille}")
    with open(os.path.join(dossier, "liste"), "w", encoding="ascii") as f:
        f.write("\n".join(lignes) + "\n")


def perturber(rng, fichiers, prefixe=None):
    """Copie du corpus avec quelques octets changés au hasard : mêmes formes, réponses imprévisibles."""
    resultat = []
    for nom, d in fichiers:
        b = bytearray(d[:prefixe] if prefixe else d)
        for _ in range(max(1, len(b) // 65536) if b else 0):
            b[rng.randrange(len(b))] ^= rng.randrange(1, 256)
        resultat.append((nom, bytes(b)))
    return resultat


def charger_corpus(outillage):
    generer = os.path.join(outillage, "bee", "corpus", "generer.py")
    r = subprocess.run([sys.executable, generer], capture_output=True, text=True, cwd=outillage)
    if r.returncode != 0:
        raise Erreur("corpus non conforme : " + r.stderr[-1000:])
    racine = os.path.join(outillage, "bee", "corpus", "donnees")
    fichiers = []
    for dossier, sous, noms in os.walk(racine):
        sous.sort()
        for n in sorted(noms):
            with open(os.path.join(dossier, n), "rb") as f:
                fichiers.append((f"k{len(fichiers):03d}", f.read()))
    if not fichiers:
        raise Erreur("corpus vide")
    return fichiers


# ------------------------------------------------------------------ préparation et construction

MOTIF_SOURCE = re.compile(r"miniz[A-Za-z0-9_]*\.[ch]")


def copier_sources(depot, destination):
    os.makedirs(destination, exist_ok=True)
    trouves = []
    for nom in sorted(os.listdir(depot)):
        if not MOTIF_SOURCE.fullmatch(nom):
            continue
        chemin = os.path.join(depot, nom)
        st = os.lstat(chemin)
        if stat.S_ISLNK(st.st_mode):
            raise Refus(f"{nom} est un lien symbolique : refusé")
        if stat.S_ISREG(st.st_mode):
            shutil.copyfile(chemin, os.path.join(destination, nom))
            trouves.append(nom)
    for requis in ("miniz.c", "miniz_tdef.c", "miniz_tinfl.c", "miniz.h"):
        if requis not in trouves:
            raise Refus(f"{requis} introuvable dans {depot}")
    return destination


def copier_outillage(outillage, source_a, destination):
    """Ce que la base fournit au conteneur : le harnais, le lanceur, bee/commun et SES en-têtes de miniz."""
    for sous in ("juge", "commun"):
        shutil.copytree(os.path.join(outillage, "bee", sous), os.path.join(destination, "bee", sous),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    os.makedirs(os.path.join(destination, "miniz"))
    for nom in os.listdir(source_a):
        if nom.endswith(".h"):
            shutil.copyfile(os.path.join(source_a, nom), os.path.join(destination, "miniz", nom))
    return destination


def construire(docker, sources, outillage, sortie, avec_chrono, etiquette):
    dossier_ouvert(sortie)
    commande = ["sh", "/outillage/bee/juge/construire.sh", "/sources", "/outillage", "/sortie"] + (["--chrono"] if avec_chrono else [])
    r = docker.lancer(commande, [(sources, "/sources", True), (outillage, "/outillage", True), (sortie, "/sortie", False)],
                      pids=64, delai=900)
    if r.returncode != 0:
        message = f"la compilation de {etiquette} a échoué : " + propre(r.stderr)
        raise (Erreur(message) if etiquette == "A" else Refus(message))
    return {cle: exiger(sortie, nom, 64 << 20).decode("utf-8", "replace")
            for cle, nom in (("symboles", "symboles.txt"), ("sections", "sections.txt"), ("desassemblage", "desassemblage.txt"))}


# ------------------------------------------------------------------ exécution sous chrono

class Execution:
    """Lance un plan de commandes dans un conteneur, sous le lanceur chrono de la base."""

    def __init__(self, docker, chrono, constructions, travail):
        self.docker, self.chrono, self.constructions, self.travail = docker, chrono, constructions, travail

    def lancer(self, variante, entrees, sorties, plan, valgrind=False, delai=1800):
        """plan : [(étiquette, [programme, arguments…])]. Renvoie {étiquette: mesure}."""
        dossier_plan = tempfile.mkdtemp(prefix="plan-", dir=self.travail)
        os.chmod(dossier_plan, 0o755)
        with open(os.path.join(dossier_plan, "plan.txt"), "w", encoding="utf-8") as f:
            for etiquette, commande in plan:
                f.write("\t".join([etiquette] + commande) + "\n")
        os.chmod(os.path.join(dossier_plan, "plan.txt"), 0o644)
        dossier_ouvert(sorties)
        dossier_ouvert(os.path.join(sorties, "journal"))
        jeton = secrets.token_hex(16)
        commande = ["/chrono/chrono", "--delai", str(delai), "--journal", "/sorties/journal"] + (["--valgrind"] if valgrind else []) + ["/plan/plan.txt"]
        montages = [(self.chrono, "/chrono", True), (self.constructions[variante], "/variante", True), (entrees, "/entrees", True),
                    (sorties, "/sorties", False), (dossier_plan, "/plan", True)]
        r = self.docker.lancer(commande, montages, pids=2, entree=(jeton + "\n").encode(), delai=delai * len(plan) + 300)
        shutil.rmtree(dossier_plan, ignore_errors=True)
        if r.returncode != 0:
            raise Refus(f"le lanceur a échoué pour {variante} (code {r.returncode}) : " + propre(r.stderr))
        mesures = {}
        lignes = [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
        if len(lignes) != len(plan):
            raise Refus(f"{variante} : {len(lignes)} mesure(s) pour {len(plan)} commande(s)")
        for ligne, (etiquette, _) in zip(lignes, plan):
            m = json.loads(ligne)
            if m.get("jeton") != jeton or m.get("etiquette") != etiquette:
                raise Refus(f"{variante} : ligne de mesure non authentique ({etiquette})")
            if m.get("code") != 0 or m.get("signal") != 0:
                trace = lire_sortie(sorties, f"journal/{etiquette}.err", 1 << 20) or b""
                raise Refus(f"{variante}/{etiquette} : code {m.get('code')}, signal {m.get('signal')}. " + propre(trace, 800))
            if valgrind and not isinstance(m.get("instructions"), int):
                raise Refus(f"{variante}/{etiquette} : résumé de Valgrind absent ou illisible")
            mesures[etiquette] = m
        return mesures


# ------------------------------------------------------------------ vérification

class Verificateur:
    def __init__(self, sortie_compressee):
        self.identique = sortie_compressee == "identique"
        self.comparees = 0

    def compressee(self, racine_a, racine_b, relatif, original, flux=False):
        b = exiger(racine_b, relatif)
        self.comparees += 1
        if self.identique:
            a = exiger(racine_a, relatif)
            if a != b:
                raise Refus(f"sortie compressée différente de la base : {relatif} ({len(a)} contre {len(b)} octets)")
        elif decompresser_zlib(b) != original:
            raise Refus(f"la sortie compressée ne redonne pas l'original (zlib de l'hôte) : {relatif}")
        return len(b)

    def verifier(self, racine_a, racine_b, fichiers, flux):
        for nom, d in fichiers:
            # Contrôle de bon sens sur la base elle-même (niveau 6) : il détecte un juge mal monté.
            if decompresser_zlib(exiger(racine_a, f"c/{nom}.6")) != d:
                raise Erreur(f"la base ne redonne pas l'original pour {nom} : juge mal monté")
            for niveau in NIVEAUX_UNIQUE:
                self.compressee(racine_a, racine_b, f"c/{nom}.{niveau}", d)
            for niveau in NIVEAUX_FLUX:
                self.compressee(racine_a, racine_b, f"s/{nom}.{niveau}", d, flux=True)
        for nom, _, _, original in flux:
            for sortie, etat, unique in (("d", "e", True), ("ds", "es", False)):
                code_a, long_a = statut(racine_a, f"{etat}/{nom}")
                code_b, long_b = statut(racine_b, f"{etat}/{nom}")
                if code_a != code_b:
                    raise Refus(f"décompression ({'mz_uncompress' if unique else 'mz_inflate en flux'}) de {nom} : "
                                f"code {code_b}, la base donne {code_a}")
                a, b = exiger(racine_a, f"{sortie}/{nom}"), exiger(racine_b, f"{sortie}/{nom}")
                self.comparees += 1
                reussi = code_a == (MZ_OK if unique else MZ_STREAM_END)
                if reussi:
                    if a != b:
                        raise Refus(f"décompression de {nom} différente de la base ({sortie})")
                    if original is not None and a != original:
                        raise Erreur(f"la base ne redonne pas l'original de {nom} ({sortie}) : juge mal monté")
                elif a[:min(len(a), len(b))] != b[:min(len(a), len(b))]:
                    raise Refus(f"décompression de {nom} en erreur : octets produits différents de la base ({sortie})")

    def scenario(self, racine_a, racine_b, scenario, fichiers, flux):
        """Sorties d'un scénario mesuré ; renvoie (octets traités, octets compressés)."""
        traites = compresses = 0
        if scenario in ("n1", "n6", "n9"):
            for nom, d in fichiers:
                compresses += self.compressee(racine_a, racine_b, f"{scenario}/c/{nom}", d)
                traites += len(d)
        elif scenario == "decompression":
            for nom, _, _, original in flux:
                b = exiger(racine_b, f"decompression/d/{nom}")
                self.comparees += 1
                if b != original:
                    raise Refus(f"décompression mesurée de {nom} différente de l'original")
                traites += len(original)
        elif scenario == "memoire":
            for nom, d in fichiers:
                compresses += self.compressee(racine_a, racine_b, f"memoire/m/{nom}", d, flux=True)
                traites += len(d)
        return traites, compresses


# ------------------------------------------------------------------ programme

def statistiques():
    sys.path.insert(0, os.path.join(os.path.dirname(ICI), "bench"))
    import ab  # outillage de la base : test du signe, résumés, description de la machine
    return ab


def plan_scenarios():
    return [(s, ["/variante/execution", s, "/entrees", f"/sorties/{s}"]) for s in SCENARIOS]


def main():
    analyseur = argparse.ArgumentParser(description="Juge isolé Bee pour miniz (voir l'aide du module).")
    analyseur.add_argument("--source-a")
    analyseur.add_argument("--source-b")
    analyseur.add_argument("--image-seulement", action="store_true",
                           help="construit l'image du conteneur (seule étape avec réseau) et affiche son étiquette")
    analyseur.add_argument("--outillage", default=OUTILLAGE_DEFAUT)
    analyseur.add_argument("--sortie-compressee", choices=["identique", "peut_changer"], default="identique")
    analyseur.add_argument("--repetitions", type=int, default=10)
    analyseur.add_argument("--chauffe", type=int, default=1)
    analyseur.add_argument("--sans-instructions", action="store_true")
    analyseur.add_argument("--prefixe-instructions", type=int, default=131072)
    analyseur.add_argument("--seuil-instructions", type=float, default=0.002)
    analyseur.add_argument("--json")
    analyseur.add_argument("--depot-diff", help="clone git qui contient --base et --tete (diff des sources pour l'analyse)")
    analyseur.add_argument("--base")
    analyseur.add_argument("--tete")
    analyseur.add_argument("--graine", help="graine hexadécimale (reproduction locale) ; défaut : tirée au hasard")
    analyseur.add_argument("--reseau-construction", help="réseau de docker build (« host » sans pont Docker)")
    analyseur.add_argument("--memoire", default="4g")
    analyseur.add_argument("--garder", action="store_true")
    args = analyseur.parse_args()

    debut = time.time()
    if shutil.which("docker") is None:
        raise Erreur("docker introuvable")
    outillage = os.path.abspath(args.outillage)
    if args.image_seulement:
        print(construire_image(outillage, args.reseau_construction))
        return 0
    if not (args.source_a and args.source_b):
        analyseur.error("--source-a et --source-b sont requis")
    ab = statistiques()
    travail = tempfile.mkdtemp(prefix="bee-juge-")
    os.chmod(travail, 0o755)
    try:
        image = construire_image(outillage, args.reseau_construction)
        docker = Docker(image, args.memoire)
        source_a = copier_sources(os.path.abspath(args.source_a), os.path.join(travail, "sources-A"))
        source_b = copier_sources(os.path.abspath(args.source_b), os.path.join(travail, "sources-B"))
        outils = copier_outillage(outillage, source_a, os.path.join(travail, "outillage"))
        constructions = {v: os.path.join(travail, f"construction-{v}") for v in "AB"}
        releves = {"A": construire(docker, source_a, outils, constructions["A"], True, "A"),
                   "B": construire(docker, source_b, outils, constructions["B"], False, "B")}
        chrono = os.path.join(travail, "chrono")
        os.makedirs(chrono)
        shutil.copy2(os.path.join(constructions["A"], "chrono"), os.path.join(chrono, "chrono"))
        os.chmod(chrono, 0o755)
        journal("A et B compilés dans le conteneur")

        diff = ""
        if args.depot_diff and args.base and args.tete:
            diff = subprocess.run(["git", "-C", args.depot_diff, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=0",
                                   f"{args.base}...{args.tete}", "--", "miniz*.c", "miniz*.h"],
                                  capture_output=True, text=True, errors="replace").stdout
        suspects = analyse.analyser(releves["A"], releves["B"], diff)
        for s in suspects:
            journal(f"construction suspecte : {s['detail']}")

        # La graine est tirée maintenant, après la compilation : rien de ce qui a été compilé ne la connaît.
        graine = bytes.fromhex(args.graine) if args.graine else secrets.token_bytes(16)
        rng = random.Random(int.from_bytes(graine, "big"))
        corpus = charger_corpus(outillage)
        execution = Execution(docker, chrono, constructions, travail)
        verificateur = Verificateur(args.sortie_compressee)

        # 1. Vérification : toutes les API, corpus + entrées aléatoires + flux valides et invalides.
        aleatoires = entrees_aleatoires(rng, corpus)
        fichiers = corpus + aleatoires
        flux = flux_zlib(rng, [f for f in aleatoires if len(f[1]) <= 2_000_000] + corpus[::max(1, len(corpus) // 12)])
        entrees = os.path.join(travail, "verification")
        ecrire_entrees(entrees, fichiers, flux)
        racines = {}
        for v in "AB":
            racines[v] = os.path.join(travail, f"sorties-verification-{v}")
            execution.lancer(v, entrees, racines[v], [("verifier", ["/variante/execution", "verifier", "/entrees", "/sorties"])], delai=3600)
        verificateur.verifier(racines["A"], racines["B"], fichiers, flux)
        ratio = {}
        for v in "AB":
            total = sum(len(d) for _, d in corpus)
            compresse = sum(len(exiger(racines[v], f"c/{nom}.6")) for nom, _ in corpus)
            ratio[v] = total / compresse if compresse else None
            shutil.rmtree(racines[v], ignore_errors=True)
        shutil.rmtree(entrees, ignore_errors=True)
        journal(f"vérification : {verificateur.comparees} sorties de B justes ({len(fichiers)} entrées, {len(flux)} flux)")

        # 2. Mesures au chronomètre (temps processeur du fils, lu par le noyau), A et B entrelacés.
        mesures = {"A": [], "B": []}
        for i in range(args.chauffe + args.repetitions):
            perturbes = perturber(rng, corpus)
            flux_rep = [(nom, zlib.compress(d, 6), len(d), d) for nom, d in perturbes]
            entrees = os.path.join(travail, f"repetition-{i}")
            ecrire_entrees(entrees, perturbes, flux_rep)
            sorties, brut = {}, {}
            for v in (("A", "B") if i % 2 == 0 else ("B", "A")):
                sorties[v] = os.path.join(travail, f"sorties-{i}-{v}")
                for s in SCENARIOS:
                    dossier_ouvert(os.path.join(sorties[v], s))
                brut[v] = execution.lancer(v, entrees, sorties[v], plan_scenarios())
            for v in "AB":
                valeurs = {}
                for s in SCENARIOS:
                    traites, compresses = verificateur.scenario(sorties["A"], sorties[v], s, perturbes, flux_rep)
                    cpu = brut[v][s]["utilisateur_s"] + brut[v][s]["systeme_s"]
                    if s == "memoire":
                        valeurs["memoire_max_ko"] = brut[v][s]["maxrss_ko"]
                    elif s == "decompression":
                        valeurs["debit_decompression"] = traites / 1e6 / cpu if cpu > 0 else None
                    else:
                        valeurs[f"debit_compression_{s}"] = traites / 1e6 / cpu if cpu > 0 else None
                valeurs["ratio_n6"] = ratio[v]
                if i >= args.chauffe:
                    mesures[v].append(valeurs)
            for v in "AB":
                shutil.rmtree(sorties[v], ignore_errors=True)
            shutil.rmtree(entrees, ignore_errors=True)
            journal(f"répétition {i + 1}/{args.chauffe + args.repetitions} ({'chauffe' if i < args.chauffe else 'mesurée'}) faite")

        rapport = {
            "repetitions": args.repetitions, "chauffe": args.chauffe, "ordre": "A, B puis B, A, en alternance",
            "machine": ab.description_machine(),
            "methode": {
                "valeur_retenue": "médiane des répétitions",
                "gain": "médiane(B)/médiane(A) - 1 (plus_haut) ; 1 - médiane(B)/médiane(A) (plus_bas) ; positif = mieux",
                "au_dela_du_bruit": f"test du signe sur les paires entrelacées, comme ab.py (k = {ab.seuil_signe(args.repetitions)} sur {args.repetitions})",
                "chronometre": ("temps processeur (utilisateur + système) du processus qui exécute un scénario, lu par le "
                                "lanceur chrono de la base avec wait4 ; une exécution par scénario et par répétition, "
                                "sur un corpus perturbé à chaque répétition ; débit = octets traités / temps"),
                "memoire": "ru_maxrss du processus du scénario « memoire » (flux par blocs de 64 Kio), lu par wait4",
            },
            "metriques": {}, "mesures": {"A": {}, "B": {}},
        }
        for nom, sens, unite in ab.METRIQUES:
            valeurs_a = [m.get(nom) for m in mesures["A"]]
            valeurs_b = [m.get(nom) for m in mesures["B"]]
            a, b = ab.resume(valeurs_a), ab.resume(valeurs_b)
            signe = ab.test_du_signe(valeurs_a, valeurs_b, sens)
            rapport["metriques"][nom] = {
                "sens": sens, "unite": unite, "A": a, "B": b, "gain": ab.gain_relatif(a["mediane"], b["mediane"], sens),
                "au_dela_du_bruit": signe["au_dela_du_bruit"], "degradation_au_dela_du_bruit": signe["degradation_au_dela_du_bruit"],
                "test_du_signe": signe,
                "minmax_disjoints": (a["mediane"] is not None and b["mediane"] is not None and (a["max"] < b["min"] or b["max"] < a["min"])),
            }
            rapport["mesures"]["A"][nom] = a["mediane"]
            rapport["mesures"]["B"][nom] = b["mediane"]

        # 3. Décompte d'instructions : Valgrind dans le conteneur, résumé relevé par chrono.
        if not args.sans_instructions:
            perturbes = perturber(rng, corpus, args.prefixe_instructions)
            flux_rep = [(nom, zlib.compress(d, 6), len(d), d) for nom, d in perturbes]
            entrees = os.path.join(travail, "instructions")
            ecrire_entrees(entrees, perturbes, flux_rep)
            plan = [(s, ["/usr/bin/valgrind", "--tool=cachegrind", "--cache-sim=no", "--instr-at-start=no", "--vgdb=no",
                         "--cachegrind-out-file=/dev/null", "/variante/execution", s, "/entrees", f"/sorties/{s}"])
                    for s in SCENARIOS_INSTRUCTIONS]
            comptes, sorties = {}, {}
            for v in "AB":
                sorties[v] = os.path.join(travail, f"sorties-instructions-{v}")
                for s in SCENARIOS_INSTRUCTIONS:
                    dossier_ouvert(os.path.join(sorties[v], s))
                comptes[v] = execution.lancer(v, entrees, sorties[v], plan, valgrind=True, delai=3600)
            for s in SCENARIOS_INSTRUCTIONS:
                verificateur.scenario(sorties["A"], sorties["B"], s, perturbes, flux_rep)
            rapport["instructions"] = {}
            for s in SCENARIOS_INSTRUCTIONS:
                a, b = comptes["A"][s]["instructions"], comptes["B"][s]["instructions"]
                gain = ab.gain_relatif(a, b, "plus_bas")
                rapport["instructions"]["instructions_" + s] = {
                    "sens": "plus_bas", "unite": "instructions", "A": a, "B": b, "gain": gain,
                    "au_dela_du_bruit": gain is not None and abs(gain) > args.seuil_instructions}
            rapport["methode"]["instructions"] = (
                f"valgrind --tool=cachegrind dans le conteneur, appels à miniz seulement (requêtes du harnais de la base), "
                f"{args.prefixe_instructions} premiers octets de chaque fichier du corpus, perturbés ; résumé relevé par "
                f"chrono sur la dernière ligne de Valgrind ; au-delà du bruit si l'écart dépasse {100 * args.seuil_instructions:.2f} %")

        rapport["juge"] = {
            "version": 1,
            "graine": graine.hex(),
            "image": image,
            "isolation": " ".join(ISOLATION) + " --pids-limit 2 (exécution), 64 (compilation)",
            "verification": {"sorties_comparees": verificateur.comparees, "sortie_compressee": args.sortie_compressee},
            "constructions_suspectes": suspects,
        }
        rapport["duree_s"] = round(time.time() - debut, 1)
    finally:
        if args.garder:
            journal(f"dossier de travail conservé : {travail}")
        else:
            shutil.rmtree(travail, ignore_errors=True)

    ab.afficher_tableau(rapport)
    texte = json.dumps(rapport, ensure_ascii=False, indent=2)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(texte + "\n")
    print(texte)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refus as e:
        print(f"juge : REFUS : {e}", file=sys.stderr)
        sys.exit(1)
    except Erreur as e:
        print(f"juge : erreur : {e}", file=sys.stderr)
        sys.exit(2)
