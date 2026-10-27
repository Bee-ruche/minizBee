#!/usr/bin/env python3
"""Génère le corpus de référence Bee pour miniz, de façon déterministe.

Toutes les données viennent d'une graine fixe et d'un générateur pseudo-aléatoire
écrit ici (SplitMix64), en arithmétique entière : le résultat est identique bit pour
bit quelle que soit la version de Python (3.8 et plus) ou la machine. Le texte de
code source vient des sources de miniz du commit de base, lus par identifiant
d'objet git (liste figée, somme SHA-256 vérifiée).

Usage :
  python3 bee/corpus/generer.py                       génère dans bee/corpus/donnees/ et vérifie
  python3 bee/corpus/generer.py --verifier-seulement  vérifie les fichiers déjà générés
  python3 bee/corpus/generer.py --mettre-a-jour-sommes  réécrit bee/corpus/SHA256SUMS (réservé
                                                       aux tâches qui ont le droit de changer le corpus)
Code de sortie : 0 si les sommes correspondent à bee/corpus/SHA256SUMS, 1 sinon.
"""

import argparse
import hashlib
import os
import struct
import subprocess
import sys

GRAINE = 0x0B5EB5EE2026
MASQUE = (1 << 64) - 1
ICI = os.path.dirname(os.path.abspath(__file__))
SOMMES_REFERENCE = os.path.join(ICI, "SHA256SUMS")
SORTIE_DEFAUT = os.path.join(ICI, "donnees")

# Fichiers de miniz repris tels quels, figés au commit de base 2948eebafc5b9f1c69bebed80333e403a09bd62d.
# (chemin d'origine, identifiant d'objet git, SHA-256 du contenu)
SOURCES_FIGEES = [
    ("miniz.h", "1ba9a7f42dc486d51f1e169cb45bb1f4aea2d982", "d5b08814d037f1aee60c426743434c70ee25f91c47c0cda56a3a2290e90711b1"),
    ("miniz_common.h", "6f07f0b45f19b0107e64620f0c4e28d8cf21af31", "d0770cc478923e33bf22820fc51bbe22b6b99c3230ce4f5fc10eea3debc75623"),
    ("miniz_tdef.h", "3cb89f7d8f09606bfd5890bd8dcd2fa11e45796a", "18d4da29bd70a9395404e60b35b25e690fbc6bbc540bade2581639be05d5534b"),
    ("miniz_tinfl.h", "c130451f2d46d4d609dc36a0c75448ca79561704", "2c89615a4cbc5de4eac5b861051849392ec698264ee7dd399ea587c592cf68d1"),
    ("miniz_zip.h", "f034101d6a1287aeb69c15dbe520b81751284658", "43d09867f79993a9ba1627cb1f3bbd78d3bf5ee0c91cd6e7527aa9ca1e3aed44"),
    ("miniz.c", "c92a896929308505fefade1be56cfa9314e11b91", "29a0c08c4610d20ab18381cbf18190f91b4b41d05c242376364756061b631f1d"),
    ("miniz_tdef.c", "e041ce1938c7bd7c79f3ff883b790f57f6a24c6b", "989e124126377e9e892469749822e3582fa11afc6ad2ec6f53c0f0fba20869a7"),
    ("miniz_tinfl.c", "d1f3215611ee24529722b1f15b794a10015a5717", "7113a08a7722d671ce89b8de61fe6d02d0cadca0ff274ba357bf2a9dc85745ca"),
    ("miniz_zip.c", "85fd0ac0636983bbdc37a209f84d72ebf68b7551", "6a362314a0f4ea0a8bf931a4d9b293238533cebecc2619fe7d0f9f743b0ad509"),
    ("tests/catch_amalgamated.hpp", "694fe1e4d81b3fd62da919d1502bb23771460947", "bc734753c5697ab8cbea01b414f953dc27a6a68a24c6cbbddd09e4b128415e74"),
    ("tests/catch_amalgamated.cpp", "eba3f00ac486820090cda0c545606767a4d00914", "2390c8355c78de01d7b90a8dd0bbd48491dc50ba7e77d5b1e80895baa4c42af4"),
    ("readme.md", "9734435fab52430717e997cf0c13840a50a5dad3", "b4ea367be28a36e5386f65118b73962bc659a67936d248be68b7a7c03b8d359b"),
    ("ChangeLog.md", "562acea9e59f23081b564aaecf9d8eac6d1281c6", "ff3b6040f7cbd8c9779a0690e906c66408f7efe3cf88a25019323f0189025ec3"),
    ("LICENSE", "1982f4bb8f4afa3dcbe803887fb4af7573430e51", "0115478d567121238cf6cc1c0c361926cf07a49d9e4c9e66da97fac6a01646b3"),
]


class Alea:
    """SplitMix64 : petit générateur entier, identique partout."""

    def __init__(self, graine):
        self.etat = graine & MASQUE

    def suivant(self):
        self.etat = (self.etat + 0x9E3779B97F4A7C15) & MASQUE
        z = self.etat
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASQUE
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASQUE
        return z ^ (z >> 31)

    def entier(self, n):
        """Entier dans [0, n). Le biais du modulo (n petit devant 2**64) est négligeable et, surtout, fixe."""
        return self.suivant() % n

    def entre(self, a, b):
        return a + self.entier(b - a + 1)

    def choix(self, liste):
        return liste[self.entier(len(liste))]

    def octets(self, n):
        sortie = bytearray()
        while len(sortie) < n:
            sortie += self.suivant().to_bytes(8, "little")
        return bytes(sortie[:n])


class ChoixPondere:
    """Tirage selon des poids entiers (aucun calcul flottant)."""

    def __init__(self, elements, poids):
        self.elements = elements
        self.cumul = []
        total = 0
        for p in poids:
            total += p
            self.cumul.append(total)
        self.total = total

    def tirer(self, alea):
        cible = alea.entier(self.total)
        bas, haut = 0, len(self.cumul) - 1
        while bas < haut:
            milieu = (bas + haut) // 2
            if self.cumul[milieu] > cible:
                haut = milieu
            else:
                bas = milieu + 1
        return self.elements[bas]


def racine_depot():
    return os.path.dirname(os.path.dirname(ICI))


def lire_source_figee(chemin, objet, somme):
    resultat = subprocess.run(["git", "-C", racine_depot(), "cat-file", "blob", objet], capture_output=True)
    if resultat.returncode != 0:
        sys.exit(f"erreur : objet git {objet} ({chemin}) introuvable. Le corpus a besoin de l'historique "
                 f"complet du dépôt : git fetch --unshallow (ou clonez sans --depth).")
    contenu = resultat.stdout
    if hashlib.sha256(contenu).hexdigest() != somme:
        sys.exit(f"erreur : la somme SHA-256 de {chemin} ({objet}) ne correspond pas à la liste figée.")
    return contenu


# ---------------------------------------------------------------- texte naturel

def texte_anglais_markov(alea, sources, taille):
    """Chaîne de Markov d'ordre 2 sur les mots des textes anglais de miniz (readme, journal des
    changements, licence, commentaires de miniz.h)."""
    mots = []
    for texte in sources:
        mots.extend(texte.decode("utf-8", "replace").split())
    suites = {}
    for i in range(len(mots) - 2):
        suites.setdefault((mots[i], mots[i + 1]), []).append(mots[i + 2])
    cles = sorted(suites)
    debuts = [c for c in cles if c[0][:1].isupper()] or cles
    lignes, ligne, paragraphe = [], [], 0
    taille_actuelle = 0
    etat = alea.choix(debuts)
    ligne.extend(etat)
    while taille_actuelle < taille:
        suivants = suites.get(etat)
        if not suivants or alea.entier(40) == 0:
            etat = alea.choix(debuts)
            mot = etat[0]
            suivant_mot = etat[1]
            ligne.append(mot)
            mot = suivant_mot
        else:
            mot = alea.choix(suivants)
            etat = (etat[1], mot)
        ligne.append(mot)
        if sum(len(m) + 1 for m in ligne) > 72:
            texte_ligne = " ".join(ligne[:-1])
            lignes.append(texte_ligne)
            taille_actuelle += len(texte_ligne.encode("utf-8")) + 1
            ligne = [ligne[-1]]
            paragraphe += 1
            if paragraphe >= 4 + alea.entier(8) and mot.endswith("."):
                lignes.append("")
                taille_actuelle += 1
                paragraphe = 0
    lignes.append(" ".join(ligne))
    return ("\n".join(lignes) + "\n").encode("utf-8")


MOTS_FRANCAIS = (
    "de la le et les des en un une du que est pour qui dans par plus pas au sur ne se ce il "
    "sont avec ou son elle mais comme on tout nous sa leur bien aussi fait été très deux même "
    "peut ces y entre faire sans dont cette où après autres sous nouveau temps premier moins "
    "ans ont contre lui grand avant toujours encore depuis donc partie ainsi selon déjà alors "
    "chez notre avoir vie monde ville pays jour fois travail année projet logiciel données "
    "fichier compression mémoire vitesse réseau serveur client page image texte code source "
    "libre version mesure banc test résultat sortie entrée bibliothèque fonction tableau "
    "valeur octet bloc flux dictionnaire arbre symbole longueur distance niveau taux gain "
    "perte erreur réussite échec étape agent tâche registre contribution relecture vote règle "
    "conseil communauté utilisateur machine processeur cœur fréquence cache instruction "
    "chemin principal rapide lent petit grand nouveau ancien premier dernier simple complexe "
    "général particulier public privé ouvert fermé haut bas long court fort faible clair "
    "précis exact possible nécessaire important différent semblable même autre chaque quelque "
    "plusieurs certains beaucoup peu trop assez jamais souvent parfois ici là maintenant hier "
    "demain matin soir semaine mois saison été hiver printemps automne pluie soleil vent mer "
    "montagne rivière forêt champ jardin maison rue place école bureau marché gare port pont "
    "livre lettre mot phrase idée question réponse raison cause effet moyen façon manière "
    "besoin envie peur espoir joie colère surprise confiance doute vérité histoire mémoire "
    "regarder voir entendre écouter parler dire penser savoir croire vouloir pouvoir devoir "
    "aller venir partir arriver rester passer prendre donner mettre tenir porter trouver "
    "chercher perdre gagner commencer finir continuer changer garder montrer expliquer "
    "comprendre apprendre écrire lire compter mesurer comparer vérifier corriger améliorer"
).split()


def texte_francais_zipf(alea, taille):
    """Texte français synthétique : mots tirés selon une loi de Zipf (poids entiers 10**6 // rang)."""
    tirage = ChoixPondere(MOTS_FRANCAIS, [1000000 // (rang + 1) for rang in range(len(MOTS_FRANCAIS))])
    sortie, ligne, phrases = [], "", 0
    total = 0
    while total < taille:
        mots = [tirage.tirer(alea) for _ in range(alea.entre(6, 22))]
        if alea.entier(3) == 0:
            mots[alea.entier(len(mots) - 1)] += ","
        phrase = " ".join(mots)
        phrase = phrase[0].upper() + phrase[1:] + alea.choix([".", ".", ".", ".", " ?", " !", " ;"])
        for mot in phrase.split(" "):
            if len(ligne) + len(mot) + 1 > 78:
                sortie.append(ligne)
                total += len(ligne.encode("utf-8")) + 1
                ligne = mot
            else:
                ligne = (ligne + " " + mot) if ligne else mot
        phrases += 1
        if phrases >= alea.entre(3, 9):
            sortie.append(ligne)
            sortie.append("")
            total += len(ligne.encode("utf-8")) + 2
            ligne, phrases = "", 0
    sortie.append(ligne)
    return ("\n".join(sortie) + "\n").encode("utf-8")


# ---------------------------------------------------------------- données structurées

PRENOMS = ["Camille", "Louis", "Léa", "Hugo", "Chloé", "Arthur", "Manon", "Jules", "Inès", "Gabriel",
           "Zoé", "Raphaël", "Alice", "Adam", "Lina", "Paul", "Emma", "Nathan", "Jade", "Tom",
           "Sarah", "Noé", "Clara", "Lucas", "Mila", "Ethan", "Rose", "Sacha", "Anna", "Yanis"]
NOMS = ["Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard", "Durand", "Dubois", "Moreau",
        "Laurent", "Simon", "Michel", "Lefèvre", "Leroy", "Roux", "David", "Bertrand", "Morel",
        "Fournier", "Girard", "Bonnet", "Dupont", "Lambert", "Fontaine", "Rousseau", "Vincent"]
VILLES = ["Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Montpellier", "Strasbourg",
          "Bordeaux", "Lille", "Rennes", "Reims", "Toulon", "Grenoble", "Dijon", "Angers", "Nîmes",
          "Brest", "Limoges", "Tours", "Amiens", "Metz", "Besançon", "Perpignan", "Orléans", "Caen"]
ETIQUETTES = ["rapide", "fiable", "compact", "libre", "testé", "mesuré", "stable", "nouveau",
              "ancien", "prioritaire", "archivé", "public", "interne", "expérimental"]


def date_iso(alea):
    return "20%02d-%02d-%02dT%02d:%02d:%02dZ" % (alea.entre(15, 26), alea.entre(1, 12), alea.entre(1, 28),
                                                 alea.entier(24), alea.entier(60), alea.entier(60))


def decimal(entier, chiffres):
    """Écrit entier / 10**chiffres sans passer par un flottant."""
    signe = "-" if entier < 0 else ""
    entier = abs(entier)
    return "%s%d.%0*d" % (signe, entier // 10 ** chiffres, chiffres, entier % 10 ** chiffres)


def chaine_json(texte):
    return '"' + texte.replace("\\", "\\\\").replace('"', '\\"') + '"'


def json_enregistrements(alea, taille):
    """Tableau JSON d'enregistrements imbriqués, indenté sur deux espaces, écrit à la main pour
    ne dépendre d'aucun détail de sérialisation de Python."""
    morceaux, total, numero = ["[\n"], 2, 0
    while total < taille:
        numero += 1
        prenom, nom = alea.choix(PRENOMS), alea.choix(NOMS)
        etiquettes = ", ".join(chaine_json(alea.choix(ETIQUETTES)) for _ in range(alea.entier(4)))
        historique = ",\n".join(
            '      {"date": %s, "montant": %s, "valide": %s}' % (
                chaine_json(date_iso(alea)), decimal(alea.entre(-50000, 500000), 2),
                "true" if alea.entier(5) else "false")
            for _ in range(alea.entre(0, 4)))
        enregistrement = (
            '  {\n'
            '    "id": %d,\n'
            '    "nom": %s,\n'
            '    "courriel": %s,\n'
            '    "age": %d,\n'
            '    "ville": %s,\n'
            '    "position": {"lat": %s, "lon": %s},\n'
            '    "score": %s,\n'
            '    "actif": %s,\n'
            '    "etiquettes": [%s],\n'
            '    "inscrit_le": %s,\n'
            '    "historique": [%s]\n'
            '  }' % (
                numero, chaine_json(prenom + " " + nom),
                chaine_json("%s.%s%d@exemple.org" % (prenom.lower(), nom.lower(), alea.entier(100))),
                alea.entre(18, 90), chaine_json(alea.choix(VILLES)),
                decimal(alea.entre(4200000, 5100000), 5), decimal(alea.entre(-480000, 760000), 5),
                decimal(alea.entier(100001), 3), "true" if alea.entier(3) else "false", etiquettes,
                chaine_json(date_iso(alea)),
                ("\n" + historique + "\n    ") if historique else ""))
        separateur = ",\n" if total > 2 else ""
        morceau = separateur + enregistrement
        morceaux.append(morceau)
        total += len(morceau.encode("utf-8"))
    morceaux.append("\n]\n")
    return "".join(morceaux).encode("utf-8")


def csv_mesures(alea, taille):
    """Relevés de capteurs : marches aléatoires entières, une ligne par minute."""
    lignes = ["horodatage;capteur;temperature_c;humidite_pct;pression_hpa;tension_v;etat"]
    total = len(lignes[0]) + 1
    temperatures = [alea.entre(1000, 2500) for _ in range(16)]
    humidites = [alea.entre(3000, 8000) for _ in range(16)]
    pressions = [alea.entre(99000, 103000) for _ in range(16)]
    minute = 0
    while total < taille:
        capteur = alea.entier(16)
        temperatures[capteur] += alea.entre(-15, 15)
        humidites[capteur] = min(10000, max(0, humidites[capteur] + alea.entre(-40, 40)))
        pressions[capteur] += alea.entre(-12, 12)
        minute += alea.entre(0, 2)
        etat = "OK" if alea.entier(50) else alea.choix(["ALERTE", "MAINTENANCE", "HORS_LIGNE"])
        ligne = "2026-%02d-%02d %02d:%02d;C%02d;%s;%s;%s;%s;%s" % (
            1 + (minute // 43200) % 12, 1 + (minute // 1440) % 28, (minute // 60) % 24, minute % 60,
            capteur, decimal(temperatures[capteur], 2), decimal(humidites[capteur], 2),
            decimal(pressions[capteur], 2), decimal(alea.entre(3200, 3400), 3), etat)
        lignes.append(ligne)
        total += len(ligne) + 1
    return ("\n".join(lignes) + "\n").encode("utf-8")


def journal_serveur(alea, taille):
    methodes = ["GET", "GET", "GET", "POST", "PUT", "DELETE"]
    chemins = ["/api/v1/objets/%d", "/api/v1/utilisateurs/%d/profil", "/statique/img/%d.png",
               "/recherche?q=terme%d", "/api/v1/taches/%d/votes", "/sante"]
    codes = [200, 200, 200, 200, 201, 204, 301, 304, 400, 403, 404, 500, 503]
    lignes, total, ms = [], 0, 0
    while total < taille:
        ms += alea.entre(1, 900)
        niveau = "INFO " if alea.entier(20) else alea.choix(["WARN ", "ERROR", "DEBUG"])
        chemin = alea.choix(chemins)
        if "%d" in chemin:
            chemin = chemin % alea.entier(5000)
        ligne = "2026-10-%02dT%02d:%02d:%02d.%03dZ %s [serveur-%02d] %s %s %d %sms octets=%d agent=bee/%d.%d" % (
            1 + (ms // 86400000) % 28, (ms // 3600000) % 24, (ms // 60000) % 60, (ms // 1000) % 60, ms % 1000,
            niveau, alea.entier(8), alea.choix(methodes), chemin, alea.choix(codes),
            decimal(alea.entre(1, 250000), 1), alea.entier(200000), alea.entier(3), alea.entier(10))
        lignes.append(ligne)
        total += len(ligne) + 1
    return ("\n".join(lignes) + "\n").encode("utf-8")


# ---------------------------------------------------------------- binaire

def aleatoire_incompressible(taille):
    """SHA-256 en mode compteur : incompressible et indépendant de tout générateur maison."""
    sortie = bytearray()
    compteur = 0
    while len(sortie) < taille:
        sortie += hashlib.sha256(b"bee-corpus-aleatoire" + compteur.to_bytes(8, "little")).digest()
        compteur += 1
    return bytes(sortie[:taille])


def oscillateur(alea, echantillons, amplitude, bruit):
    """Résonateur numérique en virgule fixe (entiers seulement) : y[n] = (2c·y[n-1] >> 14) - y[n-2]."""
    sortie = []
    coefficients = [32622, 31164, 28378, 23170]  # 2·cos(w)·2**14 pour quatre fréquences
    voix = [[amplitude // 4, 0] for _ in coefficients]
    for n in range(echantillons):
        somme = 0
        for i, c in enumerate(coefficients):
            y = (c * voix[i][0] >> 14) - voix[i][1]
            voix[i][1], voix[i][0] = voix[i][0], y
            somme += y
        if n % 4096 == 0:  # recale l'amplitude pour éviter toute dérive
            voix = [[amplitude // 4, 0] for _ in coefficients]
        sortie.append(somme + alea.entre(-bruit, bruit))
    return sortie


def signal_float32(alea, taille):
    valeurs = oscillateur(alea, taille // 4, 30000, 300)
    # Chaque valeur est un entier / 2**15 : exactement représentable en float32.
    return b"".join(struct.pack("<f", v / 32768.0) for v in valeurs)


def pcm_int16(alea, taille):
    valeurs = oscillateur(alea, taille // 2, 24000, 600)
    return b"".join(struct.pack("<h", max(-32768, min(32767, v))) for v in valeurs)


# ---------------------------------------------------------------- données répétitives

def motif_repete(motif, taille):
    return (motif * (taille // len(motif) + 1))[:taille]


# ---------------------------------------------------------------- assemblage

def construire_corpus():
    """Renvoie la liste ordonnée (chemin relatif, contenu)."""
    alea = Alea(GRAINE)
    sources = {chemin: lire_source_figee(chemin, objet, somme) for chemin, objet, somme in SOURCES_FIGEES}
    commentaires_miniz_h = b"\n".join(l for l in sources["miniz.h"].split(b"\n")[:115])
    fichiers = []

    fichiers.append(("texte/anglais-markov.txt", texte_anglais_markov(
        Alea(GRAINE + 1), [sources["readme.md"], sources["ChangeLog.md"], sources["LICENSE"], commentaires_miniz_h],
        2500 * 1024)))
    fichiers.append(("texte/francais-zipf.txt", texte_francais_zipf(Alea(GRAINE + 2), 1024 * 1024)))
    fichiers.append(("texte/readme.md", sources["readme.md"]))
    fichiers.append(("texte/ChangeLog.md", sources["ChangeLog.md"]))

    for chemin, _, _ in SOURCES_FIGEES:
        if chemin.endswith((".c", ".h", ".cpp", ".hpp")):
            fichiers.append(("code/" + os.path.basename(chemin), sources[chemin]))

    fichiers.append(("structure/enregistrements.json", json_enregistrements(Alea(GRAINE + 3), 1536 * 1024)))
    fichiers.append(("structure/mesures.csv", csv_mesures(Alea(GRAINE + 4), 1024 * 1024)))
    fichiers.append(("structure/journal.log", journal_serveur(Alea(GRAINE + 5), 768 * 1024)))

    fichiers.append(("binaire/aleatoire.bin", aleatoire_incompressible(1024 * 1024)))
    fichiers.append(("binaire/signal-float32.bin", signal_float32(Alea(GRAINE + 6), 512 * 1024)))
    fichiers.append(("binaire/pcm-int16.bin", pcm_int16(Alea(GRAINE + 7), 512 * 1024)))

    fichiers.append(("repetitif/zeros.bin", bytes(512 * 1024)))
    fichiers.append(("repetitif/motif-court.txt", motif_repete(b"abc", 256 * 1024)))
    fichiers.append(("repetitif/motif-1000-octets.bin", motif_repete(Alea(GRAINE + 8).octets(1000), 512 * 1024)))
    fichiers.append(("repetitif/lignes-identiques.log", motif_repete(
        b"2026-10-27T00:00:00.000Z INFO  [serveur-00] GET /sante 200 0.1ms octets=2 agent=bee/0.1\n", 256 * 1024)))

    # Petits fichiers (< 1 Kio) : tranches des autres données, tailles choisies autour des bords.
    tailles = [1, 2, 3, 4, 5, 7, 8, 15, 16, 31, 32, 47, 63, 64, 65, 100, 127, 128, 129, 200, 255, 256,
               257, 300, 400, 500, 511, 512, 513, 600, 700, 800, 900, 1000, 1023]
    familles = [("txt", fichiers[0][1]), ("json", fichiers[-9][1]), ("bin", fichiers[-7][1]),
                ("rep", fichiers[-1][1]), ("c", sources["miniz_tinfl.c"])]
    for i, taille in enumerate(tailles):
        extension, source = familles[i % len(familles)]
        debut = alea.entier(len(source) - taille)
        fichiers.append(("petits/petit-%02d-%04d.%s" % (i, taille, extension), source[debut:debut + taille]))

    fichiers.append(("vide/vide.bin", b""))
    return fichiers


def lire_sommes(chemin):
    sommes = {}
    if not os.path.exists(chemin):
        return sommes
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.rstrip("\n")
            if ligne and not ligne.startswith("#"):
                somme, nom = ligne.split("  ", 1)
                sommes[nom] = somme
    return sommes


def sommes_du_dossier(dossier):
    sommes = {}
    for base, _, noms in os.walk(dossier):
        for nom in noms:
            if nom.startswith("."):
                continue
            chemin = os.path.join(base, nom)
            relatif = os.path.relpath(chemin, dossier).replace(os.sep, "/")
            with open(chemin, "rb") as f:
                sommes[relatif] = hashlib.sha256(f.read()).hexdigest()
    return sommes


def comparer(obtenues, attendues):
    problemes = []
    for nom in sorted(set(obtenues) | set(attendues)):
        if nom not in attendues:
            problemes.append(f"fichier en trop : {nom}")
        elif nom not in obtenues:
            problemes.append(f"fichier manquant : {nom}")
        elif obtenues[nom] != attendues[nom]:
            problemes.append(f"somme différente : {nom}")
    return problemes


def main():
    analyseur = argparse.ArgumentParser(description="Génère et vérifie le corpus de référence Bee pour miniz.")
    analyseur.add_argument("--sortie", default=SORTIE_DEFAUT, help="dossier de sortie (défaut : bee/corpus/donnees)")
    analyseur.add_argument("--verifier-seulement", action="store_true", help="vérifie le dossier sans rien régénérer")
    analyseur.add_argument("--mettre-a-jour-sommes", action="store_true", help="réécrit bee/corpus/SHA256SUMS")
    args = analyseur.parse_args()

    if not args.verifier_seulement:
        fichiers = construire_corpus()
        attendus = {nom for nom, _ in fichiers}
        for base, _, noms in os.walk(args.sortie):  # retire les fichiers d'un ancien corpus
            for nom in noms:
                relatif = os.path.relpath(os.path.join(base, nom), args.sortie).replace(os.sep, "/")
                if relatif not in attendus and not nom.startswith("."):
                    os.remove(os.path.join(base, nom))
        for nom, contenu in fichiers:
            chemin = os.path.join(args.sortie, *nom.split("/"))
            os.makedirs(os.path.dirname(chemin), exist_ok=True)
            with open(chemin, "wb") as f:
                f.write(contenu)
    obtenues = sommes_du_dossier(args.sortie)
    total = sum(os.path.getsize(os.path.join(args.sortie, *n.split("/"))) for n in obtenues)

    if args.mettre_a_jour_sommes:
        with open(SOMMES_REFERENCE, "w", encoding="utf-8") as f:
            f.write("# Sommes SHA-256 du corpus de référence Bee pour miniz (python3 bee/corpus/generer.py).\n")
            f.write("# Vérification manuelle : cd bee/corpus/donnees && grep -v '^#' ../SHA256SUMS | sha256sum -c\n")
            for nom in sorted(obtenues):
                f.write(f"{obtenues[nom]}  {nom}\n")
        print(f"SHA256SUMS réécrit : {len(obtenues)} fichiers, {total} octets.")
        return 0

    problemes = comparer(obtenues, lire_sommes(SOMMES_REFERENCE))
    if problemes:
        print("ÉCHEC : le corpus ne correspond pas à bee/corpus/SHA256SUMS :", file=sys.stderr)
        for p in problemes[:50]:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"Corpus conforme : {len(obtenues)} fichiers, {total} octets ({total / 1e6:.2f} Mo), dans {args.sortie}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
