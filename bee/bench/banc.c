/* Banc de mesure Bee pour miniz.

   Sortie (stdout) : un objet JSON sur une ligne, avec exactement ces six clés :
     debit_compression_n1, debit_compression_n6, debit_compression_n9   (Mo/s, Mo = 10^6 octets d'entrée)
     debit_decompression                                                 (Mo/s d'octets produits)
     ratio_n6                                                            (taille originale / taille compressée)
     memoire_max_ko                                                      (Ko, ru_maxrss de getrusage)
   Une métrique non mesurée (option --scenario) vaut null.

   Méthode :
   - Débits : le corpus est chargé en mémoire, puis compressé fichier par fichier avec mz_compress2
     (API compatible zlib, en-tête et Adler-32 compris) ; une « passe » traite tout le corpus. Le débit
     retenu est celui de la passe la plus rapide parmi k (meilleur de k, robuste aux interruptions sur
     une machine partagée). La décompression utilise mz_uncompress sur la sortie du niveau 6, et vérifie
     une fois (hors chronométrage) qu'elle restitue l'original.
   - Ratio : somme des tailles originales / somme des tailles compressées au niveau 6 (déterministe).
   - Mémoire : un processus fils, créé avant le chargement du corpus, fait passer chaque fichier du corpus
     dans miniz en flux (lecture par 64 Kio, mz_deflate aux niveaux 1, 6 et 9, sortie aussitôt décompressée
     par mz_inflate, tampons de 64 Kio). memoire_max_ko est le ru_maxrss de ce fils, lu par wait4 : c'est
     la mémoire de miniz plus celle, fixe, du programme (environ 1,5 Mo), sans les données du corpus.
     On ne lit pas ru_maxrss du processus lui-même : sous Linux, ce compteur survit à execve et vaudrait
     celui du processus parent (Python, par exemple) s'il était plus gros.

   Usage : banc [--corpus DOSSIER] [--scenario tout|n1|n6|n9|decompression|memoire]
                [--passes K] [--passes-n1 K] [--passes-n6 K] [--passes-n9 K] [--passes-decompression K]
                [--prefixe N] [--sans-memoire] [--verbeux] [--info]
   --prefixe N : ne garde que les N premiers octets de chaque fichier (sous-ensemble pour Cachegrind).
   --info : affiche les capacités du binaire (requêtes client Cachegrind compilées ou non) et s'arrête.
   Avec -DBEE_AVEC_CACHEGRIND, seules les passes chronométrées sont instrumentées
   (valgrind --tool=cachegrind --instr-at-start=no). Les fonctions bee_passe_compression et
   bee_passe_decompression servent de cible à callgrind --toggle-collect. */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "corpus.h"

#ifdef BEE_AVEC_CACHEGRIND
#include <valgrind/cachegrind.h>
#define DEBUT_INSTRUMENTATION() CACHEGRIND_START_INSTRUMENTATION
#define FIN_INSTRUMENTATION() CACHEGRIND_STOP_INSTRUMENTATION
#else
#define DEBUT_INSTRUMENTATION() ((void)0)
#define FIN_INSTRUMENTATION() ((void)0)
#endif

#if defined(__GNUC__)
#define BEE_NOINLINE __attribute__((noinline))
#else
#define BEE_NOINLINE
#endif

#define BLOC_FLUX (64 * 1024)

static int verbeux = 0;
static int instrumenter_compression = 1; /* 0 en scénario « decompression » : seule la décompression compte */

static double maintenant(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static void *allouer(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p)
    {
        fprintf(stderr, "banc : mémoire insuffisante (%zu octets)\n", n);
        exit(2);
    }
    return p;
}

/* ------------------------------------------------------------------ mémoire (processus fils) */

static size_t alloc_courant = 0, alloc_pic = 0;

typedef struct
{
    size_t taille;
    size_t remplissage; /* garde l'alignement de 16 octets */
} entete_alloc;

static void *compter_alloc(void *opaque, size_t elements, size_t taille)
{
    size_t n = elements * taille;
    entete_alloc *e = (entete_alloc *)malloc(sizeof(entete_alloc) + n);
    (void)opaque;
    if (!e)
        return NULL;
    e->taille = n;
    alloc_courant += n;
    if (alloc_courant > alloc_pic)
        alloc_pic = alloc_courant;
    return e + 1;
}

static void compter_liberation(void *opaque, void *adresse)
{
    entete_alloc *e;
    (void)opaque;
    if (!adresse)
        return;
    e = (entete_alloc *)adresse - 1;
    alloc_courant -= e->taille;
    free(e);
}

/* Fait passer le flux compressé produit dans `bloc` par l'inflateur, sortie jetée. */
static int vider_vers_inflate(mz_stream *inf, const unsigned char *bloc, size_t n, unsigned char *sortie)
{
    inf->next_in = bloc;
    inf->avail_in = (unsigned int)n;
    while (inf->avail_in)
    {
        int r;
        inf->next_out = sortie;
        inf->avail_out = BLOC_FLUX;
        r = mz_inflate(inf, MZ_NO_FLUSH);
        if (r == MZ_STREAM_END)
            return 0;
        if (r != MZ_OK && r != MZ_BUF_ERROR)
            return -1;
        if (r == MZ_BUF_ERROR && inf->avail_out == BLOC_FLUX)
            return -1;
    }
    /* Vide ce qui reste dans la fenêtre de l'inflateur. */
    for (;;)
    {
        int r;
        inf->next_out = sortie;
        inf->avail_out = BLOC_FLUX;
        r = mz_inflate(inf, MZ_NO_FLUSH);
        if (r == MZ_STREAM_END || inf->avail_out == BLOC_FLUX)
            return 0;
        if (r != MZ_OK && r != MZ_BUF_ERROR)
            return -1;
    }
}

static int flux_fichier(const char *chemin, int niveau, unsigned char *entree, unsigned char *compresse, unsigned char *sortie)
{
    FILE *f = fopen(chemin, "rb");
    mz_stream def, inf;
    int fini = 0, r;
    if (!f)
        return -1;
    memset(&def, 0, sizeof(def));
    memset(&inf, 0, sizeof(inf));
    def.zalloc = inf.zalloc = compter_alloc;
    def.zfree = inf.zfree = compter_liberation;
    if (mz_deflateInit2(&def, niveau, MZ_DEFLATED, MZ_DEFAULT_WINDOW_BITS, 9, MZ_DEFAULT_STRATEGY) != MZ_OK || mz_inflateInit(&inf) != MZ_OK)
    {
        fclose(f);
        return -1;
    }
    while (!fini)
    {
        size_t lu = fread(entree, 1, BLOC_FLUX, f);
        int vidage = (lu < BLOC_FLUX) ? MZ_FINISH : MZ_NO_FLUSH;
        def.next_in = entree;
        def.avail_in = (unsigned int)lu;
        do
        {
            def.next_out = compresse;
            def.avail_out = BLOC_FLUX;
            r = mz_deflate(&def, vidage);
            if (r != MZ_OK && r != MZ_STREAM_END && r != MZ_BUF_ERROR)
                goto erreur;
            if (vider_vers_inflate(&inf, compresse, BLOC_FLUX - def.avail_out, sortie) != 0)
                goto erreur;
            if (r == MZ_STREAM_END)
                fini = 1;
        } while (!fini && (def.avail_out == 0 || (vidage == MZ_FINISH)));
    }
    mz_deflateEnd(&def);
    mz_inflateEnd(&inf);
    fclose(f);
    return 0;
erreur:
    mz_deflateEnd(&def);
    mz_inflateEnd(&inf);
    fclose(f);
    return -1;
}

/* Renvoie le ru_maxrss (Ko) du fils, ou -1 en cas d'échec. */
static long mesurer_memoire(const char *dossier)
{
    pid_t pid;
    int statut = 0;
    struct rusage ru;
    fflush(stdout);
    fflush(stderr);
    pid = fork();
    if (pid < 0)
        return -1;
    if (pid == 0)
    {
        static const int niveaux[3] = { 1, 6, 9 };
        bee_corpus liste;
        unsigned char *entree = (unsigned char *)allouer(BLOC_FLUX), *compresse = (unsigned char *)allouer(BLOC_FLUX),
                      *sortie = (unsigned char *)allouer(BLOC_FLUX);
        size_t i;
        int k;
        if (bee_corpus_lister(dossier, &liste) != 0)
            _exit(3);
        for (k = 0; k < 3; k++)
            for (i = 0; i < liste.nombre; i++)
            {
                char chemin[8192];
                snprintf(chemin, sizeof(chemin), "%s/%s", dossier, liste.fichiers[i].nom);
                if (flux_fichier(chemin, niveaux[k], entree, compresse, sortie) != 0)
                {
                    fprintf(stderr, "banc : échec du passage en flux de %s au niveau %d\n", chemin, niveaux[k]);
                    _exit(4);
                }
            }
        if (verbeux)
            fprintf(stderr, "banc : pic des allocations de miniz en flux : %zu octets\n", alloc_pic);
        fflush(stderr);
        _exit(0);
    }
    if (wait4(pid, &statut, 0, &ru) < 0 || !WIFEXITED(statut) || WEXITSTATUS(statut) != 0)
    {
        fprintf(stderr, "banc : le processus de mesure mémoire a échoué (statut %d)\n", statut);
        return -1;
    }
    return ru.ru_maxrss;
}

/* ------------------------------------------------------------------ débits */

typedef struct
{
    unsigned char **sorties;
    mz_ulong *tailles, *bornes;
    size_t total;
} compresses;

static BEE_NOINLINE int bee_passe_compression(const bee_corpus *c, int niveau, compresses *z)
{
    size_t i;
    z->total = 0;
    for (i = 0; i < c->nombre; i++)
    {
        z->tailles[i] = z->bornes[i];
        if (mz_compress2(z->sorties[i], &z->tailles[i], c->fichiers[i].donnees, (mz_ulong)c->fichiers[i].taille, niveau) != MZ_OK)
            return -1;
        z->total += z->tailles[i];
    }
    return 0;
}

static BEE_NOINLINE int bee_passe_decompression(const bee_corpus *c, const compresses *z, unsigned char *sortie, size_t capacite)
{
    size_t i;
    for (i = 0; i < c->nombre; i++)
    {
        mz_ulong n = (mz_ulong)capacite;
        if (mz_uncompress(sortie, &n, z->sorties[i], z->tailles[i]) != MZ_OK || n != c->fichiers[i].taille)
            return -1;
    }
    return 0;
}

static double mesurer_compression(const bee_corpus *c, int niveau, int passes, compresses *z)
{
    double meilleur = -1;
    size_t total_precedent = 0;
    int p;
    for (p = 0; p < passes; p++)
    {
        double t0, t;
        int r;
        if (instrumenter_compression)
            DEBUT_INSTRUMENTATION();
        t0 = maintenant();
        r = bee_passe_compression(c, niveau, z);
        t = maintenant() - t0;
        if (instrumenter_compression)
            FIN_INSTRUMENTATION();
        if (r != 0)
        {
            fprintf(stderr, "banc : mz_compress2 a échoué au niveau %d\n", niveau);
            exit(1);
        }
        if (p > 0 && z->total != total_precedent)
        {
            fprintf(stderr, "banc : la taille compressée varie d'une passe à l'autre au niveau %d (non déterministe)\n", niveau);
            exit(1);
        }
        total_precedent = z->total;
        if (meilleur < 0 || t < meilleur)
            meilleur = t;
    }
    if (verbeux)
        fprintf(stderr, "banc : niveau %d, %d passes, meilleure %.4f s, %zu -> %zu octets\n", niveau, passes, meilleur, c->total, z->total);
    return meilleur;
}

static void usage(void)
{
    fprintf(stderr, "usage : banc [--corpus DOSSIER] [--scenario tout|n1|n6|n9|decompression|memoire] [--passes K]\n"
                    "             [--passes-n1 K] [--passes-n6 K] [--passes-n9 K] [--passes-decompression K]\n"
                    "             [--prefixe N] [--sans-memoire] [--verbeux]\n");
}

static void ecrire_nombre(const char *cle, double valeur, int decimales, int dernier)
{
    if (valeur < 0)
        printf("\"%s\": null%s", cle, dernier ? "" : ", ");
    else
        printf("\"%s\": %.*f%s", cle, decimales, valeur, dernier ? "" : ", ");
}

int main(int argc, char **argv)
{
    const char *dossier = "bee/corpus/donnees", *scenario = "tout";
    int passes_n1 = 5, passes_n6 = 2, passes_n9 = 2, passes_dec = 10, sans_memoire = 0, a;
    long prefixe = -1, memoire = -1;
    double debit[10], debit_dec = -1, ratio = -1;
    int niveaux_voulus[10] = { 0 };
    bee_corpus corpus;
    compresses z;
    size_t i, plus_grand = 0;
    int k;

    for (k = 0; k < 10; k++)
        debit[k] = -1;
    for (a = 1; a < argc; a++)
    {
        const char *o = argv[a];
        int avec_valeur = (a + 1 < argc);
        if (!strcmp(o, "--corpus") && avec_valeur)
            dossier = argv[++a];
        else if (!strcmp(o, "--scenario") && avec_valeur)
            scenario = argv[++a];
        else if (!strcmp(o, "--passes") && avec_valeur)
            passes_n1 = passes_n6 = passes_n9 = passes_dec = atoi(argv[++a]);
        else if (!strcmp(o, "--passes-n1") && avec_valeur)
            passes_n1 = atoi(argv[++a]);
        else if (!strcmp(o, "--passes-n6") && avec_valeur)
            passes_n6 = atoi(argv[++a]);
        else if (!strcmp(o, "--passes-n9") && avec_valeur)
            passes_n9 = atoi(argv[++a]);
        else if (!strcmp(o, "--passes-decompression") && avec_valeur)
            passes_dec = atoi(argv[++a]);
        else if (!strcmp(o, "--prefixe") && avec_valeur)
            prefixe = atol(argv[++a]);
        else if (!strcmp(o, "--sans-memoire"))
            sans_memoire = 1;
        else if (!strcmp(o, "--verbeux"))
            verbeux = 1;
        else if (!strcmp(o, "--info"))
        {
            /* Capacités de ce binaire, pour ab.py. */
#ifdef BEE_AVEC_CACHEGRIND
            printf("{\"cachegrind_requetes_client\": true, \"miniz\": \"%s\"}\n", mz_version());
#else
            printf("{\"cachegrind_requetes_client\": false, \"miniz\": \"%s\"}\n", mz_version());
#endif
            return 0;
        }
        else
        {
            usage();
            return 2;
        }
    }
    if (!strcmp(scenario, "decompression"))
        instrumenter_compression = 0;
    if (passes_n1 < 1 || passes_n6 < 1 || passes_n9 < 1 || passes_dec < 1)
    {
        fprintf(stderr, "banc : le nombre de passes doit être au moins 1\n");
        return 2;
    }
    if (!strcmp(scenario, "tout"))
        niveaux_voulus[1] = niveaux_voulus[6] = niveaux_voulus[9] = 1;
    else if (!strcmp(scenario, "n1"))
        niveaux_voulus[1] = 1;
    else if (!strcmp(scenario, "n6") || !strcmp(scenario, "decompression"))
        niveaux_voulus[6] = 1;
    else if (!strcmp(scenario, "n9"))
        niveaux_voulus[9] = 1;
    else if (strcmp(scenario, "memoire") != 0)
    {
        usage();
        return 2;
    }

    /* 1. Mémoire, avant tout chargement : le fils hérite d'un processus presque vide. */
    if (!sans_memoire && (!strcmp(scenario, "tout") || !strcmp(scenario, "memoire")))
    {
        memoire = mesurer_memoire(dossier);
        if (memoire < 0)
            return 1;
    }

    /* 2. Débits et ratio. */
    if (strcmp(scenario, "memoire") != 0)
    {
        unsigned char *sortie;
        if (bee_corpus_charger(dossier, &corpus) != 0)
            return 2;
        if (prefixe >= 0)
        {
            corpus.total = 0;
            for (i = 0; i < corpus.nombre; i++)
            {
                if (corpus.fichiers[i].taille > (size_t)prefixe)
                    corpus.fichiers[i].taille = (size_t)prefixe;
                corpus.total += corpus.fichiers[i].taille;
            }
        }
        z.sorties = (unsigned char **)allouer(corpus.nombre * sizeof(unsigned char *));
        z.tailles = (mz_ulong *)allouer(corpus.nombre * sizeof(mz_ulong));
        z.bornes = (mz_ulong *)allouer(corpus.nombre * sizeof(mz_ulong));
        for (i = 0; i < corpus.nombre; i++)
        {
            z.bornes[i] = mz_compressBound((mz_ulong)corpus.fichiers[i].taille);
            z.sorties[i] = (unsigned char *)allouer(z.bornes[i]);
            memset(z.sorties[i], 0, z.bornes[i]); /* les pages sont touchées hors chronométrage */
            if (corpus.fichiers[i].taille > plus_grand)
                plus_grand = corpus.fichiers[i].taille;
        }
        sortie = (unsigned char *)allouer(plus_grand);
        memset(sortie, 0, plus_grand ? plus_grand : 1);

        for (k = 1; k <= 9; k++)
        {
            double t;
            if (!niveaux_voulus[k] || k == 6)
                continue;
            t = mesurer_compression(&corpus, k, k == 1 ? passes_n1 : passes_n9, &z);
            debit[k] = (double)corpus.total / t / 1e6;
        }
        /* Le niveau 6 en dernier : sa sortie sert à la décompression. */
        if (niveaux_voulus[6])
        {
            int scen_dec = !strcmp(scenario, "decompression");
            double t = mesurer_compression(&corpus, 6, scen_dec ? 1 : passes_n6, &z);
            if (!scen_dec)
                debit[6] = (double)corpus.total / t / 1e6;
            ratio = z.total ? (double)corpus.total / (double)z.total : -1;
            if (!strcmp(scenario, "tout") || scen_dec)
            {
                double meilleur = -1;
                int p;
                /* Vérification de l'aller-retour, hors chronométrage. */
                for (i = 0; i < corpus.nombre; i++)
                {
                    mz_ulong n = (mz_ulong)plus_grand;
                    if (mz_uncompress(sortie, &n, z.sorties[i], z.tailles[i]) != MZ_OK || n != corpus.fichiers[i].taille ||
                        (n && memcmp(sortie, corpus.fichiers[i].donnees, n) != 0))
                    {
                        fprintf(stderr, "banc : la décompression ne restitue pas %s\n", corpus.fichiers[i].nom);
                        return 1;
                    }
                }
                for (p = 0; p < passes_dec; p++)
                {
                    double t0, td;
                    int r;
                    DEBUT_INSTRUMENTATION();
                    t0 = maintenant();
                    r = bee_passe_decompression(&corpus, &z, sortie, plus_grand);
                    td = maintenant() - t0;
                    FIN_INSTRUMENTATION();
                    if (r != 0)
                    {
                        fprintf(stderr, "banc : mz_uncompress a échoué\n");
                        return 1;
                    }
                    if (meilleur < 0 || td < meilleur)
                        meilleur = td;
                }
                debit_dec = (double)corpus.total / meilleur / 1e6;
                if (verbeux)
                    fprintf(stderr, "banc : décompression, %d passes, meilleure %.4f s\n", passes_dec, meilleur);
            }
        }
        for (i = 0; i < corpus.nombre; i++)
            free(z.sorties[i]);
        free(z.sorties);
        free(z.tailles);
        free(z.bornes);
        free(sortie);
        bee_corpus_liberer(&corpus);
    }

    printf("{");
    ecrire_nombre("debit_compression_n1", debit[1], 3, 0);
    ecrire_nombre("debit_compression_n6", debit[6], 3, 0);
    ecrire_nombre("debit_compression_n9", debit[9], 3, 0);
    ecrire_nombre("debit_decompression", debit_dec, 3, 0);
    ecrire_nombre("ratio_n6", ratio, 4, 0);
    if (memoire < 0)
        printf("\"memoire_max_ko\": null");
    else
        printf("\"memoire_max_ko\": %ld", memoire);
    printf("}\n");
    return 0;
}
