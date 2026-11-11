/* Execution harness of the Bee common judge for miniz (bee/README.md, section "Common judge and plugin").

   It is compiled WITH the miniz to judge, in a container without network, and runs only there. It judges
   nothing itself: it reads inputs prepared by the host, calls miniz, and writes the raw outputs. The host
   (the plugin bee/juge/projet.py, run by the registry's common judge), outside the container, checks
   these outputs with its own zlib and compares them with the base's. The PR's code shares this process:
   nothing this program prints or computes is taken on trust.

   Usage (juge-v3 contract, docs/common-judge.md of the registry): execution, without arguments; descriptor 0
   carries one fixed-length record, the line "<mode> <input_folder> <output_folder>" padded with spaces.
     <input_folder>/liste: one line per input, "f NAME SIZE" (raw file f/NAME) or "z NAME EXPECTED_SIZE" (zlib
                           stream z/NAME, EXPECTED_SIZE = size of the output buffer given to mz_uncompress).
     modes, and the outputs each writes:
       verifier       for each f: c/NAME.L (mz_compress2, L = 0 1 2 3 6 9 10), s/NAME.L (mz_deflate in chunked
                      streaming, L = 1 6 9) and m/NAME (as in memoire); for each z: d/NAME and e/NAME
                      (mz_uncompress: output and status), ds/NAME and es/NAME (mz_inflate in chunked streaming)
       n1, n6, n9     for each f: c/NAME.1, c/NAME.6 or c/NAME.9 (mz_compress2 at level 1, 6 or 9)
       decompression  for each z: d/NAME and e/NAME (mz_uncompress)
       memoire        for each f: m/NAME (mz_deflate level 6 in blocks of 64 KiB, read as it goes, without
                      loading the file: the memory measured from the outside is miniz's)
   A scenario handles every input of its side as verification does: the same output, at the same path, so that
   the judge can compare a verification input mixed into a measurement, byte for byte, with its output in
   verification. The judged code cannot tell from its process whether it is checked or measured: before the
   first call to miniz, the harness reads its parameters to the end of the pipe, copies them, then erases their
   text, its arguments and its environment.
   No measured zone: the instruction count covers the whole process. A "measured" zone would leave the PR's
   code calls outside it (mz_compressBound, for example) to move its work into (adversarial review of 27/10).
   Reading and writing the files are the same for A and B.
   Exit code: 0 if all the outputs were written, 2 otherwise. */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define BLOC_FLUX (64 * 1024)
#define NOM_MAX 64

typedef struct
{
    char type;            /* 'f' ou 'z' */
    char nom[NOM_MAX];
    size_t taille;        /* f : taille du fichier ; z : taille du tampon de sortie */
    unsigned char *donnees;
    size_t longueur;      /* octets lus */
} entree;

extern char **environ;

static char dossier_entrees[256], dossier_sorties[256];

static void mourir(const char *message, const char *detail)
{
    fprintf(stderr, "execution: %s%s%s\n", message, detail ? ": " : "", detail ? detail : "");
    exit(2);
}

static void *allouer(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p)
        mourir("out of memory", NULL);
    return p;
}

static void chemin(char *tampon, size_t taille, const char *racine, const char *sous_dossier, const char *nom,
                   const char *suffixe)
{
    int n = snprintf(tampon, taille, "%s/%s/%s%s", racine, sous_dossier, nom, suffixe ? suffixe : "");
    if (n < 0 || (size_t)n >= taille)
        mourir("path too long", nom);
}

static unsigned char *lire_fichier(const char *chemin_fichier, size_t maximum, size_t *longueur)
{
    FILE *f = fopen(chemin_fichier, "rb");
    unsigned char *tampon;
    size_t lus;
    if (!f)
        mourir("unreadable input", chemin_fichier);
    tampon = (unsigned char *)allouer(maximum);
    lus = fread(tampon, 1, maximum, f);
    if (ferror(f))
        mourir("read failed", chemin_fichier);
    fclose(f);
    *longueur = lus;
    return tampon;
}

static void ecrire_fichier(const char *sous_dossier, const char *nom, const char *suffixe, const void *donnees,
                           size_t longueur)
{
    char p[4096];
    FILE *f;
    chemin(p, sizeof(p), dossier_sorties, sous_dossier, nom, suffixe);
    f = fopen(p, "wb");
    if (!f || (longueur && fwrite(donnees, 1, longueur, f) != longueur) || fclose(f) != 0)
        mourir("write failed", p);
}

static void ecrire_statut(const char *sous_dossier, const char *nom, int code, size_t longueur)
{
    char texte[64];
    int n = snprintf(texte, sizeof(texte), "%d %zu\n", code, longueur);
    ecrire_fichier(sous_dossier, nom, NULL, texte, (size_t)n);
}

static void creer_dossier(const char *sous_dossier)
{
    char p[4096];
    int n = snprintf(p, sizeof(p), "%s/%s", dossier_sorties, sous_dossier);
    if (n < 0 || (size_t)n >= sizeof(p))
        mourir("path too long", sous_dossier);
    if (mkdir(p, 0755) != 0 && errno != EEXIST)
        mourir("cannot create the output folder", p);
}

/* Lit la liste ; charge les données des entrées f si `charger_f`, des entrées z si `charger_z`. */
static entree *lire_liste(size_t *nombre, int charger_f, int charger_z)
{
    char p[4096], ligne[256];
    FILE *f;
    entree *liste = NULL;
    size_t n = 0, capacite = 0;
    int c = snprintf(p, sizeof(p), "%s/liste", dossier_entrees);
    if (c < 0 || (size_t)c >= sizeof(p))
        mourir("path too long", "liste");
    f = fopen(p, "r");
    if (!f)
        mourir("unreadable list", p);
    while (fgets(ligne, sizeof(ligne), f))
    {
        entree e;
        unsigned long long taille;
        char type;
        memset(&e, 0, sizeof(e));
        if (sscanf(ligne, " %c %63s %llu", &type, e.nom, &taille) != 3 || (type != 'f' && type != 'z'))
            mourir("invalid list line", ligne);
        e.type = type;
        e.taille = (size_t)taille;
        if ((type == 'f' && charger_f) || (type == 'z' && charger_z))
        {
            size_t maximum = e.taille;
            char q[4096];
            if (type == 'z')
            {
                struct stat st;
                chemin(q, sizeof(q), dossier_entrees, "z", e.nom, NULL);
                if (stat(q, &st) != 0)
                    mourir("stream not found", q);
                maximum = (size_t)st.st_size;
            }
            else
                chemin(q, sizeof(q), dossier_entrees, "f", e.nom, NULL);
            e.donnees = lire_fichier(q, maximum, &e.longueur);
        }
        if (n == capacite)
        {
            capacite = capacite ? 2 * capacite : 64;
            liste = (entree *)realloc(liste, capacite * sizeof(entree));
            if (!liste)
                mourir("out of memory", NULL);
        }
        liste[n++] = e;
    }
    fclose(f);
    *nombre = n;
    return liste;
}

/* ------------------------------------------------------------------ vérification (toutes les API) */

static const int NIVEAUX_UNIQUE[] = {0, 1, 2, 3, 6, 9, 10};
static const int NIVEAUX_FLUX[] = {1, 6, 9};

/* Tailles des morceaux d'entrée et de sortie du flux découpé, choisies selon l'indice de l'entrée. */
static void tailles_flux(size_t indice, size_t taille, size_t *morceau_entree, size_t *morceau_sortie, int *flush_regulier)
{
    static const size_t paires[][2] = {{7, 13}, {4096, 1}, {65536, 4096}, {1, 65536}, {333, 777}};
    size_t k = indice % (sizeof(paires) / sizeof(paires[0]));
    *morceau_entree = paires[k][0];
    *morceau_sortie = paires[k][1];
    if (taille > (1u << 20) && (*morceau_entree < 4096 || *morceau_sortie < 4096))
    {
        *morceau_entree = 65536;
        *morceau_sortie = 4096;
    }
    *flush_regulier = (indice % 2) == 1;
}

static void deflate_flux(const entree *e, size_t indice, int niveau)
{
    mz_stream s;
    size_t morceau_entree, morceau_sortie, consomme = 0, produit = 0, capacite, appels = 0, garde, blocs = 0;
    int flush_regulier, r, flush, demande;
    unsigned char *sortie, *tampon;
    char suffixe[8];
    tailles_flux(indice, e->longueur, &morceau_entree, &morceau_sortie, &flush_regulier);
    memset(&s, 0, sizeof(s));
    if (mz_deflateInit(&s, niveau) != MZ_OK)
        mourir("mz_deflateInit failed", e->nom);
    /* Chaque MZ_SYNC_FLUSH ajoute au plus quelques octets : marge large. */
    capacite = (size_t)mz_deflateBound(&s, (mz_ulong)e->longueur) * 2 + 4096;
    garde = 4 * (e->longueur + capacite) + 4096;
    sortie = (unsigned char *)allouer(capacite);
    tampon = (unsigned char *)allouer(morceau_sortie);
    do
    {
        size_t reste = e->longueur - consomme;
        size_t a_donner = reste < morceau_entree ? reste : morceau_entree;
        flush = a_donner == reste ? MZ_FINISH : (flush_regulier && blocs % 16 == 15 ? MZ_SYNC_FLUSH : MZ_NO_FLUSH);
        blocs++;
        s.next_in = e->donnees + consomme;
        s.avail_in = (unsigned int)a_donner;
        /* miniz émet un nouveau marqueur à CHAQUE appel avec MZ_SYNC_FLUSH (zlib, une seule fois) : une fois
           l'entrée du morceau consommée, on ne fait plus que vider la sortie en attente (MZ_NO_FLUSH). */
        demande = flush;
        do
        {
            size_t sorti;
            s.next_out = tampon;
            s.avail_out = (unsigned int)morceau_sortie;
            r = mz_deflate(&s, demande);
            if (demande == MZ_SYNC_FLUSH && s.avail_in == 0)
                demande = MZ_NO_FLUSH;
            if (r != MZ_OK && r != MZ_STREAM_END && r != MZ_BUF_ERROR)
                mourir("mz_deflate failed", e->nom);
            sorti = morceau_sortie - s.avail_out;
            if (sorti > capacite - produit || ++appels > garde)
                mourir("mz_deflate does not finish", e->nom);
            memcpy(sortie + produit, tampon, sorti);
            produit += sorti;
        } while (s.avail_in > 0 || s.avail_out == 0 || (flush == MZ_FINISH && r != MZ_STREAM_END));
        consomme += a_donner;
    } while (flush != MZ_FINISH);
    mz_deflateEnd(&s);
    snprintf(suffixe, sizeof(suffixe), ".%d", niveau);
    ecrire_fichier("s", e->nom, suffixe, sortie, produit);
    free(sortie);
    free(tampon);
}

static void inflate_flux(const entree *e, size_t indice)
{
    mz_stream s;
    size_t morceau_entree, morceau_sortie, consomme = 0, produit = 0, capacite = e->taille + 1, appels = 0;
    size_t garde = 4 * (e->longueur + e->taille) + 4096;
    int flush_regulier, r = MZ_OK;
    unsigned char *sortie, *tampon;
    tailles_flux(indice, e->taille, &morceau_entree, &morceau_sortie, &flush_regulier);
    memset(&s, 0, sizeof(s));
    if (mz_inflateInit(&s) != MZ_OK)
        mourir("mz_inflateInit failed", e->nom);
    sortie = (unsigned char *)allouer(capacite);
    tampon = (unsigned char *)allouer(morceau_sortie);
    for (;;)
    {
        size_t a_donner = e->longueur - consomme;
        size_t avant;
        if (a_donner > morceau_entree)
            a_donner = morceau_entree;
        s.next_in = e->donnees + consomme;
        s.avail_in = (unsigned int)a_donner;
        s.next_out = tampon;
        s.avail_out = (unsigned int)morceau_sortie;
        avant = s.avail_in;
        r = mz_inflate(&s, MZ_NO_FLUSH);
        consomme += avant - s.avail_in;
        if (morceau_sortie - s.avail_out > capacite - produit)
        {
            r = -100; /* plus long que l'original attendu : arrêt, statut dédié */
            break;
        }
        memcpy(sortie + produit, tampon, morceau_sortie - s.avail_out);
        produit += morceau_sortie - s.avail_out;
        if (r == MZ_STREAM_END)
            break;
        if (r != MZ_OK && r != MZ_BUF_ERROR)
            break;
        /* Plus rien à donner et aucun progrès : flux tronqué. */
        if (consomme == e->longueur && s.avail_out == morceau_sortie)
            break;
        if (++appels > garde)
        {
            r = -101; /* aucun progrès : arrêt, statut dédié */
            break;
        }
    }
    mz_inflateEnd(&s);
    ecrire_statut("es", e->nom, r, produit);
    ecrire_fichier("ds", e->nom, NULL, sortie, produit);
    free(sortie);
    free(tampon);
}

static int memoire(entree *liste, size_t n);

static int verifier(entree *liste, size_t n)
{
    size_t i, j;
    const char *dossiers[] = {"c", "s", "d", "e", "ds", "es"};
    for (i = 0; i < sizeof(dossiers) / sizeof(dossiers[0]); i++)
        creer_dossier(dossiers[i]);
    for (i = 0; i < n; i++)
    {
        entree *e = &liste[i];
        if (e->type == 'f')
        {
            for (j = 0; j < sizeof(NIVEAUX_UNIQUE) / sizeof(NIVEAUX_UNIQUE[0]); j++)
            {
                mz_ulong borne = mz_compressBound((mz_ulong)e->longueur), taille = borne;
                unsigned char *sortie = (unsigned char *)allouer(borne);
                char suffixe[8];
                int r = mz_compress2(sortie, &taille, e->donnees, (mz_ulong)e->longueur, NIVEAUX_UNIQUE[j]);
                snprintf(suffixe, sizeof(suffixe), ".%d", NIVEAUX_UNIQUE[j]);
                if (r != MZ_OK)
                    mourir("mz_compress2 failed", e->nom);
                ecrire_fichier("c", e->nom, suffixe, sortie, (size_t)taille);
                free(sortie);
            }
            for (j = 0; j < sizeof(NIVEAUX_FLUX) / sizeof(NIVEAUX_FLUX[0]); j++)
                deflate_flux(e, i, NIVEAUX_FLUX[j]);
        }
        else
        {
            mz_ulong taille = (mz_ulong)e->taille;
            unsigned char *sortie = (unsigned char *)allouer(e->taille + 1);
            int r = mz_uncompress(sortie, &taille, e->donnees, (mz_ulong)e->longueur);
            if (r != MZ_OK)
                taille = 0;
            ecrire_statut("e", e->nom, r, (size_t)taille);
            ecrire_fichier("d", e->nom, NULL, sortie, (size_t)taille);
            free(sortie);
            inflate_flux(e, i);
        }
    }
    /* m/NAME, as the memoire scenario writes it: a mixed-in input of that scenario is compared with it. */
    return memoire(liste, n);
}

/* ------------------------------------------------------------------ scénarios mesurés */

static int compresser(entree *liste, size_t n, int niveau)
{
    size_t i;
    char suffixe[8];
    unsigned char **sorties = (unsigned char **)allouer(n * sizeof(unsigned char *));
    mz_ulong *tailles = (mz_ulong *)allouer(n * sizeof(mz_ulong));
    int *codes = (int *)allouer(n * sizeof(int));
    for (i = 0; i < n; i++)
    {
        sorties[i] = NULL;
        if (liste[i].type == 'f')
        {
            tailles[i] = mz_compressBound((mz_ulong)liste[i].longueur);
            sorties[i] = (unsigned char *)allouer(tailles[i]);
        }
    }
    for (i = 0; i < n; i++)
        if (liste[i].type == 'f')
            codes[i] = mz_compress2(sorties[i], &tailles[i], liste[i].donnees, (mz_ulong)liste[i].longueur, niveau);
    creer_dossier("c");
    snprintf(suffixe, sizeof(suffixe), ".%d", niveau);
    for (i = 0; i < n; i++)
        if (liste[i].type == 'f')
        {
            if (codes[i] != MZ_OK)
                mourir("mz_compress2 failed", liste[i].nom);
            ecrire_fichier("c", liste[i].nom, suffixe, sorties[i], (size_t)tailles[i]);
            free(sorties[i]);
        }
    free(sorties);
    free(tailles);
    free(codes);
    return 0;
}

static int decompresser(entree *liste, size_t n)
{
    size_t i;
    unsigned char **sorties = (unsigned char **)allouer(n * sizeof(unsigned char *));
    mz_ulong *tailles = (mz_ulong *)allouer(n * sizeof(mz_ulong));
    int *codes = (int *)allouer(n * sizeof(int));
    for (i = 0; i < n; i++)
    {
        sorties[i] = NULL;
        if (liste[i].type == 'z')
        {
            tailles[i] = (mz_ulong)liste[i].taille;
            sorties[i] = (unsigned char *)allouer(liste[i].taille + 1);
        }
    }
    for (i = 0; i < n; i++)
        if (liste[i].type == 'z')
            codes[i] = mz_uncompress(sorties[i], &tailles[i], liste[i].donnees, (mz_ulong)liste[i].longueur);
    creer_dossier("d");
    creer_dossier("e");
    for (i = 0; i < n; i++)
        if (liste[i].type == 'z')
        {
            /* As in verification: a stream in error (a verification input mixed into the measurement) gives its
               status and an empty output, never a stop. */
            if (codes[i] != MZ_OK)
                tailles[i] = 0;
            ecrire_statut("e", liste[i].nom, codes[i], (size_t)tailles[i]);
            ecrire_fichier("d", liste[i].nom, NULL, sorties[i], (size_t)tailles[i]);
            free(sorties[i]);
        }
    free(sorties);
    free(tailles);
    free(codes);
    return 0;
}

/* Flux par blocs de 64 Kio lus au fil de l'eau : la mémoire maximale du processus, mesurée de
   l'extérieur (wait4), est celle de miniz plus celle, fixe, du programme. */
static int memoire(entree *liste, size_t n)
{
    size_t i;
    unsigned char *bloc = (unsigned char *)allouer(BLOC_FLUX), *sortie = (unsigned char *)allouer(BLOC_FLUX);
    creer_dossier("m");
    for (i = 0; i < n; i++)
    {
        char p[4096];
        FILE *f, *g;
        mz_stream s;
        int r = MZ_OK, fin = 0;
        if (liste[i].type != 'f')
            continue;
        chemin(p, sizeof(p), dossier_entrees, "f", liste[i].nom, NULL);
        f = fopen(p, "rb");
        if (!f)
            mourir("unreadable input", p);
        chemin(p, sizeof(p), dossier_sorties, "m", liste[i].nom, NULL);
        g = fopen(p, "wb");
        if (!g)
            mourir("write failed", p);
        memset(&s, 0, sizeof(s));
        if (mz_deflateInit(&s, 6) != MZ_OK)
            mourir("mz_deflateInit failed", liste[i].nom);
        while (r != MZ_STREAM_END)
        {
            size_t lus = 0;
            if (!fin)
            {
                lus = fread(bloc, 1, BLOC_FLUX, f);
                if (ferror(f))
                    mourir("read failed", liste[i].nom);
                fin = lus < BLOC_FLUX;
            }
            s.next_in = bloc;
            s.avail_in = (unsigned int)lus;
            do
            {
                s.next_out = sortie;
                s.avail_out = BLOC_FLUX;
                r = mz_deflate(&s, fin ? MZ_FINISH : MZ_NO_FLUSH);
                if (r != MZ_OK && r != MZ_STREAM_END && r != MZ_BUF_ERROR)
                    mourir("mz_deflate failed", liste[i].nom);
                if (fwrite(sortie, 1, BLOC_FLUX - s.avail_out, g) != BLOC_FLUX - s.avail_out)
                    mourir("write failed", liste[i].nom);
            } while (s.avail_out == 0);
        }
        mz_deflateEnd(&s);
        fclose(f);
        if (fclose(g) != 0)
            mourir("write failed", liste[i].nom);
    }
    free(bloc);
    free(sortie);
    return 0;
}

enum { VERIFIER, N1, N6, N9, DECOMPRESSION, MEMOIRE };

/* Reads the parameters on descriptor 0 to the end of the pipe (one record of fixed length, the same in every
   mode), keeps the folders and the mode's number, then erases their text, the arguments and the environment:
   after that, no text in the process tells the mode. */
static int parametres(int argc, char **argv)
{
    static const char *const modes[] = {"verifier", "n1", "n6", "n9", "decompression", "memoire"};
    char texte[1024], lu[64], reste[2];
    size_t n = 0, k;
    ssize_t r;
    int i, mode = -1;
    char **e;
    while (n < sizeof(texte) - 1 && ((r = read(0, texte + n, sizeof(texte) - 1 - n)) > 0 || (r < 0 && errno == EINTR)))
        n += r > 0 ? (size_t)r : 0;
    texte[n] = 0;
    if (n < sizeof(texte) - 1 && argc == 1 && sscanf(texte, "%63s %255s %255s %1s", lu, dossier_entrees, dossier_sorties, reste) == 3)
        for (k = 0; k < sizeof(modes) / sizeof(modes[0]); k++)
            if (strcmp(lu, modes[k]) == 0)
                mode = (int)k;
    explicit_bzero(texte, sizeof(texte));
    explicit_bzero(lu, sizeof(lu));
    for (i = 0; i < argc; i++)
        explicit_bzero(argv[i], strlen(argv[i]));
    for (e = environ; e && *e; e++)
        explicit_bzero(*e, strlen(*e));
    if (environ)
        environ[0] = NULL;
    if (mode < 0)
        mourir("usage", "execution, without arguments; parameters \"<mode> <input_folder> <output_folder>\" on descriptor 0, "
               "mode verifier, n1, n6, n9, decompression or memoire");
    return mode;
}

int main(int argc, char **argv)
{
    size_t n;
    entree *liste;
    int mode;
    umask(0); /* l'hôte doit pouvoir effacer les sorties (écrites par un autre utilisateur) */
    mode = parametres(argc, argv);
    if (mode == VERIFIER)
    {
        liste = lire_liste(&n, 1, 1);
        return verifier(liste, n);
    }
    if (mode == N1 || mode == N6 || mode == N9)
    {
        liste = lire_liste(&n, 1, 0);
        return compresser(liste, n, mode == N1 ? 1 : mode == N6 ? 6 : 9);
    }
    if (mode == DECOMPRESSION)
    {
        liste = lire_liste(&n, 0, 1);
        return decompresser(liste, n);
    }
    liste = lire_liste(&n, 0, 0);
    return memoire(liste, n);
}
