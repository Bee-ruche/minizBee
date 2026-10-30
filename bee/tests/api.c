/* Cas limites de l'API compatible zlib de miniz, comparés à zlib (tâche Bee miniz-0026).

   Chaque cas fait le même appel avec miniz (mz_*) et avec la zlib du système, puis compare les deux
   codes de retour aux codes attendus, écrits dans ce fichier. Les deux attendus sont égaux, sauf pour
   un écart toléré : le cas renvoie alors à la liste ci-dessous, qui dit pourquoi miniz diffère.
     - Code de miniz différent de l'attendu : ÉCHEC (code de sortie 1). Le comportement d'erreur de
       miniz a changé ; ce test le garde pour les optimisations de miniz.c et de tdefl_compress.
     - Code de zlib différent de l'attendu : AVERTISSEMENT seulement. Les attendus sont ceux de zlib 1.3,
       celle de la CI ; une autre version peut différer sans que miniz soit en cause.
   Autour des codes, des contrôles sur miniz (ÉCHEC s'ils ne tiennent pas) : total_in et total_out,
   octets consommés égaux à ceux de zlib, flux encore utilisable après un appel refusé, sortie identique
   après une remise à zéro, sortie de miniz relue par zlib.

   Écarts tolérés (même appel, code de miniz différent de celui de zlib) :
     [E1]  Paramètre invalide : miniz rend MZ_PARAM_ERROR (-10000, code propre à miniz), zlib Z_STREAM_ERROR.
     [E2]  Fenêtre : miniz n'accepte que window_bits = 15 ou -15 (32 Kio, flux zlib ou Deflate brut) et rend
           MZ_PARAM_ERROR ; zlib accepte aussi les fenêtres plus petites, gzip (+16), la détection
           automatique (+32) et, en décompression, 0 (taille lue dans l'en-tête).
     [E3]  Niveau et stratégie : miniz accepte un niveau hors de -1..9 (10 = MZ_UBER_COMPRESSION, au-delà
           ramené à 10, autre niveau négatif traité comme -1) et une stratégie inconnue (stratégie par
           défaut) ; zlib rend Z_STREAM_ERROR. Le flux produit reste valide (relu par zlib).
     [E4]  Vidages : mz_deflate ne connaît pas MZ_BLOCK, et mz_inflate n'accepte que MZ_NO_FLUSH,
           MZ_PARTIAL_FLUSH, MZ_SYNC_FLUSH et MZ_FINISH (miniz.h) : MZ_STREAM_ERROR là où zlib accepte.
     [E5]  Premier mz_deflate sans entrée ni vidage : miniz n'a rien à produire et rend MZ_BUF_ERROR ; zlib
           écrit déjà l'en-tête et rend Z_OK.
     [E6]  MZ_SYNC_FLUSH répété sans nouvelle entrée : miniz émet un nouveau bloc vide et rend MZ_OK ; zlib
           refuse un vidage sans effet (Z_BUF_ERROR).
     [E7]  mz_deflate après la fin du flux : sans MZ_FINISH, miniz rend MZ_BUF_ERROR et zlib Z_STREAM_ERROR ;
           avec MZ_FINISH et une nouvelle entrée, miniz rend MZ_STREAM_END sans la consommer, zlib
           Z_BUF_ERROR.
     [E8]  mz_inflate et MZ_FINISH (miniz.h) : au premier appel, MZ_FINISH suppose des tampons assez grands
           pour tout le flux ; si la sortie est trop petite, le flux ne reprend pas (MZ_DATA_ERROR ensuite),
           alors que zlib reprend. Après un MZ_FINISH, miniz refuse un appel sans MZ_FINISH
           (MZ_STREAM_ERROR) ; zlib l'accepte.
     [E9]  Dictionnaire prédéfini (bit FDICT de l'en-tête) : miniz ne le gère pas et rend MZ_DATA_ERROR ;
           zlib rend Z_NEED_DICT. mz_uncompress et uncompress rendent tous deux une erreur de données.
     [E10] Libération : mz_deflateEnd et mz_inflateEnd rendent MZ_OK sur un flux déjà libéré (zlib :
           Z_STREAM_ERROR), et mz_deflateEnd aussi sur un flux inachevé (zlib : Z_DATA_ERROR).
     [E11] Longueur au-delà de 32 bits (mz_ulong de 64 bits) : mz_compress2 et mz_uncompress2 rendent
           MZ_PARAM_ERROR ; zlib traite la longueur par tranches.
     [E12] uncompress de zlib déduit l'erreur de l'état de la sortie : sortie de 0 octet pour un flux non
           vide, Z_DATA_ERROR ; sortie remplie pile au moment où l'entrée, tronquée, s'épuise, Z_BUF_ERROR.
           mz_uncompress rend MZ_BUF_ERROR dans le premier cas (sortie trop petite) et MZ_DATA_ERROR dans le
           second (flux incomplet).

   Usage : api [--verbeux]       (--verbeux : un cas par ligne, avec les deux codes)
   Code de sortie : 0 si tout est conforme, 1 au moindre échec, 2 en cas d'erreur d'environnement. */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <zlib.h>

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TAILLE 100000u
#define CAPACITE (2u * TAILLE + 1024u)

static unsigned char donnees[TAILLE];
static unsigned char sortie_m[CAPACITE], sortie_z[CAPACITE], reference[CAPACITE], copie[CAPACITE], relu[CAPACITE];
/* Données compressées par zlib : flux zlib et Deflate brut au niveau 6, flux zlib au niveau 0 (blocs stockés). */
static unsigned char flux_zlib[CAPACITE], flux_brut[CAPACITE], flux_stocke[CAPACITE];
static unsigned long n_flux_zlib, n_flux_brut, n_flux_stocke;

static long nb_cas = 0, nb_ecarts = 0, nb_controles = 0, nb_echecs = 0, nb_avertissements = 0;
static int verbeux = 0;

static const char *nom(int code)
{
    switch (code)
    {
        case MZ_OK: return "OK";
        case MZ_STREAM_END: return "STREAM_END";
        case MZ_NEED_DICT: return "NEED_DICT";
        case MZ_ERRNO: return "ERRNO";
        case MZ_STREAM_ERROR: return "STREAM_ERROR";
        case MZ_DATA_ERROR: return "DATA_ERROR";
        case MZ_MEM_ERROR: return "MEM_ERROR";
        case MZ_BUF_ERROR: return "BUF_ERROR";
        case MZ_VERSION_ERROR: return "VERSION_ERROR";
        case MZ_PARAM_ERROR: return "PARAM_ERROR";
        default: return "inconnu";
    }
}

/* Nom de cas formaté (tampon statique : consommé aussitôt par codes() ou controle()). */
static const char *cas_f(const char *format, ...)
{
    static char tampon[200];
    va_list ap;
    va_start(ap, format);
    vsnprintf(tampon, sizeof(tampon), format, ap);
    va_end(ap);
    return tampon;
}

/* Mode --verbeux : nom du cas sur 72 colonnes (caractères UTF-8, pas octets). */
static void aligner(const char *cas)
{
    int colonnes = 0;
    const char *p;
    for (p = cas; *p; p++)
        colonnes += ((unsigned char)*p & 0xC0) != 0x80;
    printf("  %s%*s", cas, colonnes < 72 ? 72 - colonnes : 1, "");
}

/* Codes de miniz (m) et de zlib (z) pour un même appel, contre leurs attendus. ecart : renvoi « En » à la
   liste des écarts tolérés quand les deux attendus diffèrent, NULL sinon. */
static void codes(const char *cas, int m, int attendu_m, int z, int attendu_z, const char *ecart)
{
    if ((attendu_m != attendu_z) != (ecart != NULL))
    {
        fprintf(stderr, "erreur interne [%s] : un écart toléré, et lui seul, renvoie à la liste des écarts\n", cas);
        exit(2);
    }
    nb_cas++;
    nb_ecarts += ecart != NULL;
    if (m != attendu_m)
    {
        nb_echecs++;
        fprintf(stderr, "ÉCHEC [%s] miniz rend %s (%d), attendu %s ; zlib rend %s\n", cas, nom(m), m, nom(attendu_m), nom(z));
    }
    if (z != attendu_z)
    {
        nb_avertissements++;
        fprintf(stderr, "AVERTISSEMENT [%s] zlib %s rend %s (%d), attendu %s (zlib 1.3)\n", cas, zlibVersion(), nom(z), z,
                nom(attendu_z));
    }
    if (verbeux)
    {
        aligner(cas);
        printf(" miniz %-12s zlib %-12s %s\n", nom(m), nom(z), ecart ? ecart : "");
    }
}

#define IDEM(cas, m, z, attendu) codes((cas), (m), (attendu), (z), (attendu), NULL)
#define ECART(cas, m, attendu_m, z, attendu_z, e) codes((cas), (m), (attendu_m), (z), (attendu_z), (e))

/* Contrôle sur miniz autour des codes de retour. */
static void controle(const char *cas, int condition)
{
    nb_controles++;
    if (!condition)
    {
        nb_echecs++;
        fprintf(stderr, "ÉCHEC [%s]\n", cas);
    }
    else if (verbeux)
    {
        aligner(cas);
        printf(" vérifié\n");
    }
}

static void erreur_env(const char *quoi)
{
    fprintf(stderr, "erreur : %s a échoué alors que l'appel est valide (environnement ?)\n", quoi);
    exit(2);
}

/* Texte pseudo-aléatoire déterministe (mots d'un petit vocabulaire, octets quelconques mêlés). */
static void generer_donnees(void)
{
    static const char *const mots[] = { "abeille ", "ruche ", "miel ", "cire ", "pollen ", "reine ", "essaim ", "fleur ", "butine ", "rayon\n" };
    unsigned long x = 2026;
    size_t i = 0;
    while (i < TAILLE)
    {
        const char *mot;
        x = (x * 1103515245ul + 12345ul) & 0x7ffffffful;
        if ((x >> 8) % 7 == 0)
        {
            donnees[i++] = (unsigned char)(x >> 16);
            continue;
        }
        for (mot = mots[(x >> 16) % 10]; *mot && i < TAILLE; mot++)
            donnees[i++] = (unsigned char)*mot;
    }
}

static void mz_ouvrir_def(mz_stream *s, int niveau, int fenetre)
{
    memset(s, 0, sizeof(*s));
    if (mz_deflateInit2(s, niveau, MZ_DEFLATED, fenetre, 8, MZ_DEFAULT_STRATEGY) != MZ_OK)
        erreur_env("mz_deflateInit2");
}

static void z_ouvrir_def(z_stream *s, int niveau, int fenetre)
{
    memset(s, 0, sizeof(*s));
    if (deflateInit2(s, niveau, Z_DEFLATED, fenetre, 8, Z_DEFAULT_STRATEGY) != Z_OK)
        erreur_env("deflateInit2");
}

static void mz_ouvrir_inf(mz_stream *s, int fenetre)
{
    memset(s, 0, sizeof(*s));
    if (mz_inflateInit2(s, fenetre) != MZ_OK)
        erreur_env("mz_inflateInit2");
}

static void z_ouvrir_inf(z_stream *s, int fenetre)
{
    memset(s, 0, sizeof(*s));
    if (inflateInit2(s, fenetre) != Z_OK)
        erreur_env("inflateInit2");
}

static void mz_tampons(mz_stream *s, const unsigned char *src, size_t n, unsigned char *dst, size_t cap)
{
    s->next_in = src;
    s->avail_in = (unsigned int)n;
    s->next_out = dst;
    s->avail_out = (unsigned int)cap;
}

static void z_tampons(z_stream *s, const unsigned char *src, size_t n, unsigned char *dst, size_t cap)
{
    s->next_in = (Bytef *)src;
    s->avail_in = (uInt)n;
    s->next_out = dst;
    s->avail_out = (uInt)cap;
}

/* 1 si zlib décompresse c (fenêtre 15 : flux zlib ; -15 : Deflate brut) en exactement attendu[0..n). */
static int relu_par_zlib(const unsigned char *c, size_t nc, int fenetre, const unsigned char *attendu, size_t n)
{
    z_stream z;
    int r;
    z_ouvrir_inf(&z, fenetre);
    z_tampons(&z, c, nc, relu, sizeof(relu));
    r = inflate(&z, Z_FINISH);
    inflateEnd(&z);
    return r == Z_STREAM_END && z.avail_in == 0 && z.total_out == n && memcmp(relu, attendu, n) == 0;
}

/* Décompression en flux : entrée par morceaux de 1000 octets, MZ_NO_FLUSH, jusqu'à un code autre que OK. */
static int mz_inflate_flux(mz_stream *s, const unsigned char *src, size_t n, unsigned char *dst, size_t cap)
{
    size_t pos = 0, morceau;
    int r = MZ_OK, i;
    s->next_out = dst;
    s->avail_out = (unsigned int)cap;
    for (i = 0; i < 10000 && r == MZ_OK; i++)
    {
        morceau = n - pos < 1000 ? n - pos : 1000;
        s->next_in = src + pos;
        s->avail_in = (unsigned int)morceau;
        r = mz_inflate(s, MZ_NO_FLUSH);
        pos += morceau - s->avail_in;
    }
    return r;
}

static int z_inflate_flux(z_stream *s, const unsigned char *src, size_t n, unsigned char *dst, size_t cap)
{
    size_t pos = 0, morceau;
    int r = Z_OK, i;
    s->next_out = dst;
    s->avail_out = (uInt)cap;
    for (i = 0; i < 10000 && r == Z_OK; i++)
    {
        morceau = n - pos < 1000 ? n - pos : 1000;
        s->next_in = (Bytef *)src + pos;
        s->avail_in = (uInt)morceau;
        r = inflate(s, Z_NO_FLUSH);
        pos += morceau - s->avail_in;
    }
    return r;
}

static int mz_inflate_finir(mz_stream *s)
{
    int r = MZ_OK, i;
    for (i = 0; i < 1000 && r == MZ_OK; i++)
        r = mz_inflate(s, MZ_FINISH);
    return r;
}

/* ------------------------------------------------------------------ constantes */

static void cas_constantes(void)
{
    static const struct
    {
        const char *nom;
        int m, z;
    } c[] = {
        { "MZ_OK", MZ_OK, Z_OK }, { "MZ_STREAM_END", MZ_STREAM_END, Z_STREAM_END }, { "MZ_NEED_DICT", MZ_NEED_DICT, Z_NEED_DICT },
        { "MZ_ERRNO", MZ_ERRNO, Z_ERRNO }, { "MZ_STREAM_ERROR", MZ_STREAM_ERROR, Z_STREAM_ERROR },
        { "MZ_DATA_ERROR", MZ_DATA_ERROR, Z_DATA_ERROR }, { "MZ_MEM_ERROR", MZ_MEM_ERROR, Z_MEM_ERROR },
        { "MZ_BUF_ERROR", MZ_BUF_ERROR, Z_BUF_ERROR }, { "MZ_VERSION_ERROR", MZ_VERSION_ERROR, Z_VERSION_ERROR },
        { "MZ_NO_FLUSH", MZ_NO_FLUSH, Z_NO_FLUSH }, { "MZ_PARTIAL_FLUSH", MZ_PARTIAL_FLUSH, Z_PARTIAL_FLUSH },
        { "MZ_SYNC_FLUSH", MZ_SYNC_FLUSH, Z_SYNC_FLUSH }, { "MZ_FULL_FLUSH", MZ_FULL_FLUSH, Z_FULL_FLUSH },
        { "MZ_FINISH", MZ_FINISH, Z_FINISH }, { "MZ_BLOCK", MZ_BLOCK, Z_BLOCK }, { "MZ_DEFLATED", MZ_DEFLATED, Z_DEFLATED },
        { "MZ_DEFAULT_COMPRESSION", MZ_DEFAULT_COMPRESSION, Z_DEFAULT_COMPRESSION },
        { "MZ_DEFAULT_STRATEGY", MZ_DEFAULT_STRATEGY, Z_DEFAULT_STRATEGY }, { "MZ_FILTERED", MZ_FILTERED, Z_FILTERED },
        { "MZ_HUFFMAN_ONLY", MZ_HUFFMAN_ONLY, Z_HUFFMAN_ONLY }, { "MZ_RLE", MZ_RLE, Z_RLE }, { "MZ_FIXED", MZ_FIXED, Z_FIXED },
    };
    size_t i;
    /* Les cas suivants comparent les codes numériquement : les constantes doivent coïncider. */
    for (i = 0; i < sizeof(c) / sizeof(c[0]); i++)
        controle(cas_f("constante %s égale à celle de zlib", c[i].nom), c[i].m == c[i].z);
}

/* ------------------------------------------------------------------ initialisation */

static void cas_init_compression(void)
{
    static const struct
    {
        const char *cas;
        int niveau, methode, fenetre, memoire, strategie, attendu_m, attendu_z;
        const char *ecart;
    } t[] = {
        { "niveau -1 (défaut)", -1, 8, 15, 8, 0, MZ_OK, Z_OK, NULL },
        { "niveau 0", 0, 8, 15, 8, 0, MZ_OK, Z_OK, NULL },
        { "niveau 1", 1, 8, 15, 8, 0, MZ_OK, Z_OK, NULL },
        { "niveau 9", 9, 8, 15, 8, 0, MZ_OK, Z_OK, NULL },
        { "niveau 10", 10, 8, 15, 8, 0, MZ_OK, Z_STREAM_ERROR, "E3" },
        { "niveau 11", 11, 8, 15, 8, 0, MZ_OK, Z_STREAM_ERROR, "E3" },
        { "niveau -2", -2, 8, 15, 8, 0, MZ_OK, Z_STREAM_ERROR, "E3" },
        { "méthode 7", 6, 7, 15, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre -15 (Deflate brut)", 6, 8, -15, 8, 0, MZ_OK, Z_OK, NULL },
        { "fenêtre 14", 6, 8, 14, 8, 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 9", 6, 8, 9, 8, 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 8", 6, 8, 8, 8, 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre -9", 6, 8, -9, 8, 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 31 (gzip)", 6, 8, 31, 8, 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 7", 6, 8, 7, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre -8", 6, 8, -8, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre 0", 6, 8, 0, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre 16", 6, 8, 16, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre -16", 6, 8, -16, 8, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "mem_level 1", 6, 8, 15, 1, 0, MZ_OK, Z_OK, NULL },
        { "mem_level 9", 6, 8, 15, 9, 0, MZ_OK, Z_OK, NULL },
        { "mem_level 0", 6, 8, 15, 0, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "mem_level 10", 6, 8, 15, 10, 0, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "stratégie MZ_FILTERED", 6, 8, 15, 8, MZ_FILTERED, MZ_OK, Z_OK, NULL },
        { "stratégie MZ_HUFFMAN_ONLY", 6, 8, 15, 8, MZ_HUFFMAN_ONLY, MZ_OK, Z_OK, NULL },
        { "stratégie MZ_RLE", 6, 8, 15, 8, MZ_RLE, MZ_OK, Z_OK, NULL },
        { "stratégie MZ_FIXED", 6, 8, 15, 8, MZ_FIXED, MZ_OK, Z_OK, NULL },
        { "stratégie 5", 6, 8, 15, 8, 5, MZ_OK, Z_STREAM_ERROR, "E3" },
        { "stratégie -1", 6, 8, 15, 8, -1, MZ_OK, Z_STREAM_ERROR, "E3" },
    };
    size_t i;
    for (i = 0; i < sizeof(t) / sizeof(t[0]); i++)
    {
        mz_stream m;
        z_stream z;
        int cm, cz;
        memset(&m, 0, sizeof(m));
        memset(&z, 0, sizeof(z));
        cm = mz_deflateInit2(&m, t[i].niveau, t[i].methode, t[i].fenetre, t[i].memoire, t[i].strategie);
        cz = deflateInit2(&z, t[i].niveau, t[i].methode, t[i].fenetre, t[i].memoire, t[i].strategie);
        codes(cas_f("mz_deflateInit2 %s", t[i].cas), cm, t[i].attendu_m, cz, t[i].attendu_z, t[i].ecart);
        if (cm == MZ_OK)
        {
            /* Un paramètre accepté doit donner un flux valide. */
            mz_tampons(&m, donnees, 20000, sortie_m, sizeof(sortie_m));
            cm = mz_deflate(&m, MZ_FINISH);
            controle(cas_f("mz_deflateInit2 %s : flux de miniz relu par zlib", t[i].cas),
                     cm == MZ_STREAM_END && relu_par_zlib(sortie_m, m.total_out, t[i].fenetre, donnees, 20000));
            mz_deflateEnd(&m);
        }
        if (cz == Z_OK)
            deflateEnd(&z);
    }
    IDEM("mz_deflateInit2 flux nul", mz_deflateInit2(NULL, 6, MZ_DEFLATED, 15, 8, 0), deflateInit2(NULL, 6, Z_DEFLATED, 15, 8, 0),
         MZ_STREAM_ERROR);
}

static void cas_init_decompression(void)
{
    static const struct
    {
        const char *cas;
        int fenetre, attendu_m, attendu_z;
        const char *ecart;
    } t[] = {
        { "fenêtre 15", 15, MZ_OK, Z_OK, NULL },
        { "fenêtre -15 (Deflate brut)", -15, MZ_OK, Z_OK, NULL },
        { "fenêtre 8", 8, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 14", 14, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre -8", -8, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 0 (taille lue dans l'en-tête)", 0, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 16 (gzip)", 16, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 31 (gzip)", 31, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 47 (détection automatique)", 47, MZ_PARAM_ERROR, Z_OK, "E2" },
        { "fenêtre 7", 7, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre -7", -7, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre -16", -16, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
        { "fenêtre 48", 48, MZ_PARAM_ERROR, Z_STREAM_ERROR, "E1" },
    };
    size_t i;
    for (i = 0; i < sizeof(t) / sizeof(t[0]); i++)
    {
        mz_stream m;
        z_stream z;
        int cm, cz;
        memset(&m, 0, sizeof(m));
        memset(&z, 0, sizeof(z));
        cm = mz_inflateInit2(&m, t[i].fenetre);
        cz = inflateInit2(&z, t[i].fenetre);
        codes(cas_f("mz_inflateInit2 %s", t[i].cas), cm, t[i].attendu_m, cz, t[i].attendu_z, t[i].ecart);
        if (cm == MZ_OK)
        {
            const unsigned char *src = t[i].fenetre > 0 ? flux_zlib : flux_brut;
            size_t n = t[i].fenetre > 0 ? n_flux_zlib : n_flux_brut;
            mz_tampons(&m, src, n, sortie_m, sizeof(sortie_m));
            cm = mz_inflate(&m, MZ_FINISH);
            controle(cas_f("mz_inflateInit2 %s : flux de zlib décompressé", t[i].cas),
                     cm == MZ_STREAM_END && m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
            mz_inflateEnd(&m);
        }
        if (cz == Z_OK)
            inflateEnd(&z);
    }
    IDEM("mz_inflateInit2 flux nul", mz_inflateInit2(NULL, 15), inflateInit2(NULL, 15), MZ_STREAM_ERROR);
}

/* ------------------------------------------------------------------ allocateurs */

typedef struct
{
    long allocations, liberations, refuser, mauvais_opaque;
} compteur;

static compteur compte;

static void *mz_allouer(void *opaque, size_t n, size_t taille)
{
    compteur *c = (compteur *)opaque;
    compte.mauvais_opaque += c != &compte;
    if (compte.refuser)
        return NULL;
    compte.allocations++;
    return malloc(n * taille);
}

static void mz_liberer(void *opaque, void *p)
{
    compte.mauvais_opaque += (compteur *)opaque != &compte;
    compte.liberations += p != NULL;
    free(p);
}

static voidpf z_allouer(voidpf opaque, uInt n, uInt taille)
{
    (void)opaque;
    return compte.refuser ? Z_NULL : malloc((size_t)n * taille);
}

static void z_liberer(voidpf opaque, voidpf p)
{
    (void)opaque;
    free(p);
}

static void cas_allocateurs(void)
{
    mz_stream m;
    z_stream z;
    int cm, cz;

    compte.refuser = 1;
    memset(&m, 0, sizeof(m));
    memset(&z, 0, sizeof(z));
    m.zalloc = mz_allouer, m.zfree = mz_liberer, m.opaque = &compte;
    z.zalloc = z_allouer, z.zfree = z_liberer, z.opaque = &compte;
    IDEM("mz_deflateInit2 allocation refusée", mz_deflateInit2(&m, 6, MZ_DEFLATED, 15, 8, 0), deflateInit2(&z, 6, Z_DEFLATED, 15, 8, 0),
         MZ_MEM_ERROR);
    IDEM("mz_inflateInit2 allocation refusée", mz_inflateInit2(&m, 15), inflateInit2(&z, 15), MZ_MEM_ERROR);

    /* Allocateur de l'appelant : opaque transmis, chaque allocation libérée par mz_*End. */
    compte.refuser = 0;
    memset(&m, 0, sizeof(m));
    m.zalloc = mz_allouer, m.zfree = mz_liberer, m.opaque = &compte;
    cm = mz_deflateInit2(&m, 6, MZ_DEFLATED, 15, 8, 0);
    mz_tampons(&m, donnees, TAILLE, sortie_m, sizeof(sortie_m));
    cz = mz_deflate(&m, MZ_FINISH);
    mz_deflateEnd(&m);
    controle("compression avec l'allocateur de l'appelant : opaque transmis, tout libéré",
             cm == MZ_OK && cz == MZ_STREAM_END && compte.allocations > 0 && compte.allocations == compte.liberations &&
                 !compte.mauvais_opaque);
    memset(&compte, 0, sizeof(compte));
    memset(&m, 0, sizeof(m));
    m.zalloc = mz_allouer, m.zfree = mz_liberer, m.opaque = &compte;
    cm = mz_inflateInit2(&m, 15);
    mz_tampons(&m, flux_zlib, n_flux_zlib, sortie_m, sizeof(sortie_m));
    cz = mz_inflate(&m, MZ_FINISH);
    mz_inflateEnd(&m);
    controle("décompression avec l'allocateur de l'appelant : opaque transmis, tout libéré",
             cm == MZ_OK && cz == MZ_STREAM_END && compte.allocations > 0 && compte.allocations == compte.liberations &&
                 !compte.mauvais_opaque);
}

/* ------------------------------------------------------------------ mz_deflate */

static void cas_deflate(void)
{
    mz_stream m;
    z_stream z;
    mz_ulong n_ref = sizeof(reference), n_sync = 0, avant;
    size_t i;

    if (mz_compress2(reference, &n_ref, donnees, TAILLE, 6) != MZ_OK)
        erreur_env("mz_compress2");

    /* Appels refusés sur un flux neuf : rien n'est consommé, et le flux donne ensuite la même sortie. */
    mz_ouvrir_def(&m, 6, 15);
    z_ouvrir_def(&z, 6, 15);
    mz_tampons(&m, donnees, TAILLE, NULL, 100);
    z_tampons(&z, donnees, TAILLE, NULL, 100);
    IDEM("mz_deflate flux nul", mz_deflate(NULL, MZ_NO_FLUSH), deflate(NULL, Z_NO_FLUSH), MZ_STREAM_ERROR);
    IDEM("mz_deflate sans next_out", mz_deflate(&m, MZ_NO_FLUSH), deflate(&z, Z_NO_FLUSH), MZ_STREAM_ERROR);
    m.avail_out = z.avail_out = 0;
    IDEM("mz_deflate sans next_out, avail_out = 0", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_ERROR);
    m.next_out = sortie_m, z.next_out = sortie_z;
    IDEM("mz_deflate avail_out = 0", mz_deflate(&m, MZ_NO_FLUSH), deflate(&z, Z_NO_FLUSH), MZ_BUF_ERROR);
    IDEM("mz_deflate avail_out = 0, MZ_FINISH", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_BUF_ERROR);
    m.avail_out = z.avail_out = sizeof(sortie_m);
    IDEM("mz_deflate vidage -1", mz_deflate(&m, -1), deflate(&z, -1), MZ_STREAM_ERROR);
    IDEM("mz_deflate vidage 6", mz_deflate(&m, 6), deflate(&z, 6), MZ_STREAM_ERROR);
    controle("mz_deflate après les appels refusés : rien consommé ni produit",
             m.total_in == 0 && m.total_out == 0 && m.avail_in == TAILLE && m.next_in == donnees);
    IDEM("mz_deflate MZ_FINISH après les appels refusés", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_END);
    controle("mz_deflate après les appels refusés : sortie identique à mz_compress2",
             m.total_out == n_ref && memcmp(sortie_m, reference, n_ref) == 0);
    mz_deflateEnd(&m);
    deflateEnd(&z);

    mz_ouvrir_def(&m, 6, 15);
    z_ouvrir_def(&z, 6, 15);
    mz_tampons(&m, donnees, TAILLE, sortie_m, sizeof(sortie_m));
    z_tampons(&z, donnees, TAILLE, sortie_z, sizeof(sortie_z));
    ECART("mz_deflate vidage MZ_BLOCK", mz_deflate(&m, MZ_BLOCK), MZ_STREAM_ERROR, deflate(&z, Z_BLOCK), Z_OK, "E4");
    controle("mz_deflate après MZ_BLOCK refusé : rien consommé ni produit", m.total_in == 0 && m.total_out == 0);
    ECART("mz_deflateEnd sur un flux inachevé", mz_deflateEnd(&m), MZ_OK, deflateEnd(&z), Z_DATA_ERROR, "E10");

    /* Vidage au milieu de l'entrée ; miniz traite MZ_PARTIAL_FLUSH comme MZ_SYNC_FLUSH (même sortie). */
    for (i = 0; i < 3; i++)
    {
        static const int vidages[] = { MZ_SYNC_FLUSH, MZ_PARTIAL_FLUSH, MZ_FULL_FLUSH };
        static const char *const noms[] = { "MZ_SYNC_FLUSH", "MZ_PARTIAL_FLUSH", "MZ_FULL_FLUSH" };
        mz_ouvrir_def(&m, 6, 15);
        z_ouvrir_def(&z, 6, 15);
        mz_tampons(&m, donnees, TAILLE / 2, sortie_m, sizeof(sortie_m));
        z_tampons(&z, donnees, TAILLE / 2, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("mz_deflate %s au milieu de l'entrée", noms[i]), mz_deflate(&m, vidages[i]), deflate(&z, vidages[i]), MZ_OK);
        m.avail_in = z.avail_in = TAILLE - TAILLE / 2;
        IDEM(cas_f("mz_deflate %s, puis MZ_FINISH", noms[i]), mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_END);
        controle(cas_f("mz_deflate %s : flux de miniz relu par zlib", noms[i]), relu_par_zlib(sortie_m, m.total_out, 15, donnees, TAILLE));
        if (vidages[i] == MZ_SYNC_FLUSH)
            memcpy(reference, sortie_m, n_sync = m.total_out);
        else if (vidages[i] == MZ_PARTIAL_FLUSH)
            controle("mz_deflate MZ_PARTIAL_FLUSH : même sortie que MZ_SYNC_FLUSH", m.total_out == n_sync && !memcmp(sortie_m, reference, n_sync));
        mz_deflateEnd(&m);
        deflateEnd(&z);
    }

    /* Appels sans entrée, puis après la fin du flux. */
    mz_ouvrir_def(&m, 6, 15);
    z_ouvrir_def(&z, 6, 15);
    mz_tampons(&m, donnees, 0, sortie_m, sizeof(sortie_m));
    z_tampons(&z, donnees, 0, sortie_z, sizeof(sortie_z));
    ECART("mz_deflate premier appel sans entrée ni vidage", mz_deflate(&m, MZ_NO_FLUSH), MZ_BUF_ERROR, deflate(&z, Z_NO_FLUSH), Z_OK, "E5");
    IDEM("mz_deflate deuxième appel sans entrée ni vidage", mz_deflate(&m, MZ_NO_FLUSH), deflate(&z, Z_NO_FLUSH), MZ_BUF_ERROR);
    IDEM("mz_deflate MZ_SYNC_FLUSH sans entrée", mz_deflate(&m, MZ_SYNC_FLUSH), deflate(&z, Z_SYNC_FLUSH), MZ_OK);
    avant = m.total_out;
    ECART("mz_deflate MZ_SYNC_FLUSH répété sans entrée", mz_deflate(&m, MZ_SYNC_FLUSH), MZ_OK, deflate(&z, Z_SYNC_FLUSH), Z_BUF_ERROR,
          "E6");
    controle("mz_deflate MZ_SYNC_FLUSH répété sans entrée : un nouveau bloc vide émis", m.total_out > avant);
    IDEM("mz_deflate MZ_FULL_FLUSH sans entrée", mz_deflate(&m, MZ_FULL_FLUSH), deflate(&z, Z_FULL_FLUSH), MZ_OK);
    IDEM("mz_deflate MZ_FINISH sans entrée", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_END);
    controle("mz_deflate sans entrée : flux vide de miniz relu par zlib", relu_par_zlib(sortie_m, m.total_out, 15, donnees, 0));
    IDEM("mz_deflate après la fin : MZ_FINISH", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_END);
    ECART("mz_deflate après la fin : MZ_NO_FLUSH", mz_deflate(&m, MZ_NO_FLUSH), MZ_BUF_ERROR, deflate(&z, Z_NO_FLUSH), Z_STREAM_ERROR,
          "E7");
    ECART("mz_deflate après la fin : MZ_SYNC_FLUSH", mz_deflate(&m, MZ_SYNC_FLUSH), MZ_BUF_ERROR, deflate(&z, Z_SYNC_FLUSH),
          Z_STREAM_ERROR, "E7");
    m.avail_in = z.avail_in = 10;
    ECART("mz_deflate après la fin : MZ_FINISH avec une nouvelle entrée", mz_deflate(&m, MZ_FINISH), MZ_STREAM_END,
          deflate(&z, Z_FINISH), Z_BUF_ERROR, "E7");
    controle("mz_deflate après la fin : nouvelle entrée non consommée", m.avail_in == 10 && m.total_in == 0);
    m.avail_out = z.avail_out = 0;
    IDEM("mz_deflate après la fin : avail_out = 0", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_BUF_ERROR);
    IDEM("mz_deflateEnd après la fin", mz_deflateEnd(&m), deflateEnd(&z), MZ_OK);
    IDEM("mz_deflate après mz_deflateEnd", mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH), MZ_STREAM_ERROR);
    ECART("mz_deflateEnd deux fois", mz_deflateEnd(&m), MZ_OK, deflateEnd(&z), Z_STREAM_ERROR, "E10");
    IDEM("mz_deflateEnd flux nul", mz_deflateEnd(NULL), deflateEnd(NULL), MZ_STREAM_ERROR);
}

/* ------------------------------------------------------------------ mz_compress2, mz_compress */

static void cas_compress(void)
{
    static const int niveaux_hors_zlib[] = { 10, 11, 100, -2 }; /* -2 en dernier : comparé ensuite au niveau -1 */
    mz_ulong lm, lz, exact_m, exact_z, n_moins_1;
    size_t i;

    lm = mz_compressBound(TAILLE), lz = compressBound(TAILLE);
    IDEM("mz_compress2 tampon de mz_compressBound", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6),
         compress2(sortie_z, &lz, donnees, TAILLE, 6), MZ_OK);
    exact_m = lm, exact_z = lz;
    IDEM("mz_compress2 tampon de taille exacte", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6), compress2(sortie_z, &lz, donnees, TAILLE, 6),
         MZ_OK);
    controle("mz_compress2 tampon de taille exacte : taille rendue", lm == exact_m);
    lm = exact_m - 1, lz = exact_z - 1;
    IDEM("mz_compress2 taille exacte - 1", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6), compress2(sortie_z, &lz, donnees, TAILLE, 6),
         MZ_BUF_ERROR);
    lm = exact_m / 2, lz = exact_z / 2;
    IDEM("mz_compress2 moitié de la taille exacte", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6),
         compress2(sortie_z, &lz, donnees, TAILLE, 6), MZ_BUF_ERROR);
    lm = lz = 1;
    IDEM("mz_compress2 tampon de 1 octet", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6), compress2(sortie_z, &lz, donnees, TAILLE, 6),
         MZ_BUF_ERROR);
    lm = lz = 0;
    IDEM("mz_compress2 tampon de 0 octet", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6), compress2(sortie_z, &lz, donnees, TAILLE, 6),
         MZ_BUF_ERROR);
    lm = lz = 0;
    IDEM("mz_compress2 sans tampon de sortie", mz_compress2(NULL, &lm, donnees, TAILLE, 6), compress2(NULL, &lz, donnees, TAILLE, 6),
         MZ_STREAM_ERROR);

    lm = lz = sizeof(sortie_m);
    IDEM("mz_compress2 entrée vide", mz_compress2(sortie_m, &lm, donnees, 0, 6), compress2(sortie_z, &lz, donnees, 0, 6), MZ_OK);
    controle("mz_compress2 entrée vide : flux relu par zlib", relu_par_zlib(sortie_m, lm, 15, donnees, 0));
    lm = lm - 1, lz = lz - 1;
    IDEM("mz_compress2 entrée vide, taille exacte - 1", mz_compress2(sortie_m, &lm, donnees, 0, 6), compress2(sortie_z, &lz, donnees, 0, 6),
         MZ_BUF_ERROR);

    n_moins_1 = lz = sizeof(reference);
    IDEM("mz_compress2 niveau -1", mz_compress2(reference, &n_moins_1, donnees, TAILLE, -1), compress2(sortie_z, &lz, donnees, TAILLE, -1),
         MZ_OK);
    for (i = 0; i < sizeof(niveaux_hors_zlib) / sizeof(niveaux_hors_zlib[0]); i++)
    {
        int niveau = niveaux_hors_zlib[i];
        lm = lz = sizeof(sortie_m);
        ECART(cas_f("mz_compress2 niveau %d", niveau), mz_compress2(sortie_m, &lm, donnees, TAILLE, niveau), MZ_OK,
              compress2(sortie_z, &lz, donnees, TAILLE, niveau), Z_STREAM_ERROR, "E3");
        controle(cas_f("mz_compress2 niveau %d : flux relu par zlib", niveau), relu_par_zlib(sortie_m, lm, 15, donnees, TAILLE));
    }
    controle("mz_compress2 niveau -2 : même sortie qu'au niveau -1", lm == n_moins_1 && memcmp(sortie_m, reference, lm) == 0);

    lm = lz = sizeof(sortie_m);
    IDEM("mz_compress tampon suffisant", mz_compress(sortie_m, &lm, donnees, TAILLE), compress(sortie_z, &lz, donnees, TAILLE), MZ_OK);
    lm = lm - 1, lz = lz - 1;
    IDEM("mz_compress taille exacte - 1", mz_compress(sortie_m, &lm, donnees, TAILLE), compress(sortie_z, &lz, donnees, TAILLE), MZ_BUF_ERROR);

    if (sizeof(mz_ulong) > 4)
    {
        /* Longueur de sortie annoncée de 2^32 octets : miniz refuse avant tout accès ; zlib n'écrit que le
           flux produit, qui tient dans le tampon réel (mz_compressBound). */
        lm = lz = (mz_ulong)0xFFFFFFFFu + 1u;
        ECART("mz_compress2 longueur de sortie de 2^32 octets", mz_compress2(sortie_m, &lm, donnees, TAILLE, 6), MZ_PARAM_ERROR,
              compress2(sortie_z, &lz, donnees, TAILLE, 6), Z_OK, "E11");
        controle("mz_compress2 longueur de 2^32 octets : longueur inchangée", lm == (mz_ulong)0xFFFFFFFFu + 1u);
    }
}

/* ------------------------------------------------------------------ mz_uncompress, mz_uncompress2 */

static void cas_uncompress(void)
{
    mz_ulong lm, lz, sm, sz;
    const mz_ulong troncatures[] = { 0, 1, 2, 6, n_flux_zlib / 2, n_flux_zlib - 4, n_flux_zlib - 1 };
    unsigned char vide[16];
    mz_ulong n_vide = sizeof(vide);
    size_t i;

    lm = lz = TAILLE;
    IDEM("mz_uncompress taille exacte", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib), uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib),
         MZ_OK);
    controle("mz_uncompress taille exacte : sortie et taille", lm == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
    lm = lz = TAILLE + 100;
    IDEM("mz_uncompress tampon plus grand", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib),
         uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), MZ_OK);
    controle("mz_uncompress tampon plus grand : taille rendue égale à celle de zlib", lm == TAILLE && lz == TAILLE);
    lm = lz = TAILLE - 1;
    IDEM("mz_uncompress taille exacte - 1", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib),
         uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), MZ_BUF_ERROR);
    lm = lz = TAILLE / 2;
    IDEM("mz_uncompress moitié de la taille", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib),
         uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), MZ_BUF_ERROR);
    lm = lz = 1;
    IDEM("mz_uncompress tampon de 1 octet", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib),
         uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), MZ_BUF_ERROR);
    lm = lz = 0;
    ECART("mz_uncompress tampon de 0 octet", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib), MZ_BUF_ERROR,
          uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), Z_DATA_ERROR, "E12");

    /* Flux d'une entrée vide. */
    if (compress2(vide, &n_vide, donnees, 0, 6) != Z_OK)
        erreur_env("compress2");
    lm = lz = 0;
    IDEM("mz_uncompress flux vide, tampon de 0 octet", mz_uncompress(sortie_m, &lm, vide, n_vide), uncompress(sortie_z, &lz, vide, n_vide),
         MZ_OK);
    controle("mz_uncompress flux vide : taille 0", lm == 0);

    /* Données après la fin du flux : ignorées, et mz_uncompress2 rend les octets consommés. */
    memcpy(copie, flux_zlib, n_flux_zlib);
    memset(copie + n_flux_zlib, 0xA5, 16);
    lm = lz = TAILLE, sm = sz = n_flux_zlib + 16;
    IDEM("mz_uncompress2 données après la fin du flux", mz_uncompress2(sortie_m, &lm, copie, &sm), uncompress2(sortie_z, &lz, copie, &sz),
         MZ_OK);
    controle("mz_uncompress2 données après la fin du flux : octets consommés égaux à ceux de zlib", sm == n_flux_zlib && sm == sz);
    lm = lz = TAILLE, sm = sz = n_flux_zlib;
    IDEM("mz_uncompress2 taille exacte", mz_uncompress2(sortie_m, &lm, flux_zlib, &sm), uncompress2(sortie_z, &lz, flux_zlib, &sz), MZ_OK);
    controle("mz_uncompress2 taille exacte : octets consommés", sm == n_flux_zlib && sz == n_flux_zlib);

    /* Entrée tronquée, avec une sortie d'un octet de plus que nécessaire (voir [E12] pour une sortie pile). */
    for (i = 0; i < sizeof(troncatures) / sizeof(troncatures[0]); i++)
    {
        lm = lz = TAILLE + 1;
        IDEM(cas_f("mz_uncompress entrée tronquée à %lu octets sur %lu", troncatures[i], n_flux_zlib),
             mz_uncompress(sortie_m, &lm, flux_zlib, troncatures[i]), uncompress(sortie_z, &lz, flux_zlib, troncatures[i]), MZ_DATA_ERROR);
    }
    lm = lz = TAILLE;
    ECART("mz_uncompress Adler-32 tronqué, sortie remplie pile", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib - 4), MZ_DATA_ERROR,
          uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib - 4), Z_BUF_ERROR, "E12");
    /* Bloc stocké tronqué : en-tête zlib (2 octets) et du bloc (5 octets), puis 1000 octets de données ;
       la sortie de 1000 octets se remplit pile quand l'entrée s'épuise. */
    if ((flux_stocke[2] & 6) == 0 && (flux_stocke[3] ^ flux_stocke[5]) == 0xFF && (flux_stocke[4] ^ flux_stocke[6]) == 0xFF &&
        (flux_stocke[3] | flux_stocke[4] << 8) >= 1000)
    {
        lm = lz = 1000;
        ECART("mz_uncompress bloc stocké tronqué, sortie remplie pile", mz_uncompress(sortie_m, &lm, flux_stocke, 7 + 1000), MZ_DATA_ERROR,
              uncompress(sortie_z, &lz, flux_stocke, 7 + 1000), Z_BUF_ERROR, "E12");
    }
    else
    {
        nb_avertissements++;
        fprintf(stderr, "AVERTISSEMENT : zlib %s ne commence pas le niveau 0 par un bloc stocké ; cas sauté\n", zlibVersion());
    }
    lm = lz = 100;
    IDEM("mz_uncompress entrée tronquée et sortie trop petite", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib / 2),
         uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib / 2), MZ_BUF_ERROR);

    /* Entrée altérée. */
    memcpy(copie, flux_zlib, n_flux_zlib);
    copie[1] ^= 1;
    lm = lz = TAILLE;
    IDEM("mz_uncompress somme de l'en-tête fausse", mz_uncompress(sortie_m, &lm, copie, n_flux_zlib),
         uncompress(sortie_z, &lz, copie, n_flux_zlib), MZ_DATA_ERROR);
    memcpy(copie, flux_zlib, n_flux_zlib);
    copie[n_flux_zlib - 1] ^= 1;
    lm = lz = TAILLE;
    IDEM("mz_uncompress Adler-32 faux", mz_uncompress(sortie_m, &lm, copie, n_flux_zlib), uncompress(sortie_z, &lz, copie, n_flux_zlib),
         MZ_DATA_ERROR);
    /* En-tête 78 20 : bit FDICT, suivi de l'identifiant (4 octets) d'un dictionnaire. */
    copie[0] = 0x78, copie[1] = 0x20, copie[2] = 0x12, copie[3] = 0x34, copie[4] = 0x56, copie[5] = 0x78;
    memcpy(copie + 6, flux_zlib + 2, n_flux_zlib - 2);
    lm = lz = TAILLE;
    IDEM("mz_uncompress en-tête avec dictionnaire prédéfini", mz_uncompress(sortie_m, &lm, copie, n_flux_zlib + 4),
         uncompress(sortie_z, &lz, copie, n_flux_zlib + 4), MZ_DATA_ERROR);

    if (sizeof(mz_ulong) > 4)
    {
        /* Comme pour mz_compress2 : zlib n'écrit que les TAILLE octets décompressés. */
        lm = lz = (mz_ulong)0xFFFFFFFFu + 1u;
        ECART("mz_uncompress longueur de sortie de 2^32 octets", mz_uncompress(sortie_m, &lm, flux_zlib, n_flux_zlib), MZ_PARAM_ERROR,
              uncompress(sortie_z, &lz, flux_zlib, n_flux_zlib), Z_OK, "E11");
        controle("mz_uncompress longueur de 2^32 octets : longueur inchangée", lm == (mz_ulong)0xFFFFFFFFu + 1u);
    }
}

/* ------------------------------------------------------------------ mz_deflateReset */

static void cas_deflate_reset(void)
{
    static const struct
    {
        int niveau, fenetre;
    } v[] = { { 6, 15 }, { 1, 15 }, { 9, -15 } };
    size_t i;

    IDEM("mz_deflateReset flux nul", mz_deflateReset(NULL), deflateReset(NULL), MZ_STREAM_ERROR);
    for (i = 0; i < sizeof(v) / sizeof(v[0]); i++)
    {
        mz_stream m;
        z_stream z;
        mz_ulong n_ref;
        int niveau = v[i].niveau, fenetre = v[i].fenetre;

        /* Référence : un flux neuf, mêmes paramètres. */
        mz_ouvrir_def(&m, niveau, fenetre);
        mz_tampons(&m, donnees, TAILLE, reference, sizeof(reference));
        if (mz_deflate(&m, MZ_FINISH) != MZ_STREAM_END)
            erreur_env("mz_deflate");
        n_ref = m.total_out;
        mz_deflateEnd(&m);

        mz_ouvrir_def(&m, niveau, fenetre);
        z_ouvrir_def(&z, niveau, fenetre);
        mz_tampons(&m, donnees, TAILLE, sortie_m, sizeof(sortie_m));
        z_tampons(&z, donnees, TAILLE, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("niveau %d fenêtre %d : mz_deflate MZ_FINISH", niveau, fenetre), mz_deflate(&m, MZ_FINISH), deflate(&z, Z_FINISH),
             MZ_STREAM_END);
        IDEM(cas_f("niveau %d fenêtre %d : mz_deflateReset après la fin", niveau, fenetre), mz_deflateReset(&m), deflateReset(&z), MZ_OK);
        controle(cas_f("niveau %d fenêtre %d : total_in et total_out remis à zéro", niveau, fenetre), m.total_in == 0 && m.total_out == 0);
        mz_tampons(&m, donnees, TAILLE, sortie_m, sizeof(sortie_m));
        z_tampons(&z, donnees, TAILLE, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("niveau %d fenêtre %d : MZ_FINISH après mz_deflateReset", niveau, fenetre), mz_deflate(&m, MZ_FINISH),
             deflate(&z, Z_FINISH), MZ_STREAM_END);
        controle(cas_f("niveau %d fenêtre %d : sortie après mz_deflateReset identique à un flux neuf", niveau, fenetre),
                 m.total_out == n_ref && memcmp(sortie_m, reference, n_ref) == 0);

        /* Remise à zéro en cours de flux, sortie à moitié vidée. */
        mz_tampons(&m, donnees, TAILLE / 2, sortie_m, 64);
        z_tampons(&z, donnees, TAILLE / 2, sortie_z, 64);
        mz_deflateReset(&m);
        deflateReset(&z);
        IDEM(cas_f("niveau %d fenêtre %d : mz_deflate sortie de 64 octets", niveau, fenetre), mz_deflate(&m, MZ_NO_FLUSH),
             deflate(&z, Z_NO_FLUSH), MZ_OK);
        IDEM(cas_f("niveau %d fenêtre %d : mz_deflateReset en cours de flux", niveau, fenetre), mz_deflateReset(&m), deflateReset(&z), MZ_OK);
        mz_tampons(&m, donnees, TAILLE, sortie_m, sizeof(sortie_m));
        z_tampons(&z, donnees, TAILLE, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("niveau %d fenêtre %d : MZ_FINISH après remise à zéro en cours", niveau, fenetre), mz_deflate(&m, MZ_FINISH),
             deflate(&z, Z_FINISH), MZ_STREAM_END);
        controle(cas_f("niveau %d fenêtre %d : sortie après remise à zéro en cours identique à un flux neuf", niveau, fenetre),
                 m.total_out == n_ref && memcmp(sortie_m, reference, n_ref) == 0);
        mz_deflateEnd(&m);
        deflateEnd(&z);
    }
}

/* ------------------------------------------------------------------ mz_inflateReset */

static void cas_inflate_reset(void)
{
    static const int fenetres[] = { 15, -15 };
    size_t i;

    IDEM("mz_inflateReset flux nul", mz_inflateReset(NULL), inflateReset(NULL), MZ_STREAM_ERROR);
    for (i = 0; i < sizeof(fenetres) / sizeof(fenetres[0]); i++)
    {
        mz_stream m;
        z_stream z;
        int fenetre = fenetres[i];
        const unsigned char *src = fenetre > 0 ? flux_zlib : flux_brut;
        size_t n = fenetre > 0 ? n_flux_zlib : n_flux_brut;

        mz_ouvrir_inf(&m, fenetre);
        z_ouvrir_inf(&z, fenetre);
        IDEM(cas_f("fenêtre %d : mz_inflate en flux", fenetre), mz_inflate_flux(&m, src, n, sortie_m, sizeof(sortie_m)),
             z_inflate_flux(&z, src, n, sortie_z, sizeof(sortie_z)), MZ_STREAM_END);
        IDEM(cas_f("fenêtre %d : mz_inflateReset après la fin", fenetre), mz_inflateReset(&m), inflateReset(&z), MZ_OK);
        controle(cas_f("fenêtre %d : total_in et total_out remis à zéro", fenetre), m.total_in == 0 && m.total_out == 0);
        memset(sortie_m, 0, TAILLE);
        IDEM(cas_f("fenêtre %d : mz_inflate en flux après mz_inflateReset", fenetre), mz_inflate_flux(&m, src, n, sortie_m, sizeof(sortie_m)),
             z_inflate_flux(&z, src, n, sortie_z, sizeof(sortie_z)), MZ_STREAM_END);
        controle(cas_f("fenêtre %d : sortie après mz_inflateReset", fenetre), m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);

        /* Remise à zéro en cours de flux. */
        mz_inflateReset(&m);
        inflateReset(&z);
        mz_tampons(&m, src, 1000, sortie_m, sizeof(sortie_m));
        z_tampons(&z, src, 1000, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("fenêtre %d : mz_inflate des 1000 premiers octets", fenetre), mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_OK);
        IDEM(cas_f("fenêtre %d : mz_inflateReset en cours de flux", fenetre), mz_inflateReset(&m), inflateReset(&z), MZ_OK);
        /* Premier appel après la remise à zéro : MZ_FINISH en une fois redevient possible. */
        mz_tampons(&m, src, n, sortie_m, sizeof(sortie_m));
        z_tampons(&z, src, n, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("fenêtre %d : MZ_FINISH en une fois après remise à zéro en cours", fenetre), mz_inflate(&m, MZ_FINISH),
             inflate(&z, Z_FINISH), MZ_STREAM_END);
        controle(cas_f("fenêtre %d : sortie après remise à zéro en cours", fenetre),
                 m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);

        /* Sortie trop petite pour MZ_FINISH en une fois [E8] : seule une remise à zéro relance le flux. */
        mz_inflateReset(&m);
        inflateReset(&z);
        mz_tampons(&m, src, n, sortie_m, TAILLE / 2);
        z_tampons(&z, src, n, sortie_z, TAILLE / 2);
        IDEM(cas_f("fenêtre %d : MZ_FINISH en une fois, sortie trop petite", fenetre), mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH),
             MZ_BUF_ERROR);
        IDEM(cas_f("fenêtre %d : mz_inflateReset après MZ_BUF_ERROR", fenetre), mz_inflateReset(&m), inflateReset(&z), MZ_OK);
        mz_tampons(&m, src, n, sortie_m, sizeof(sortie_m));
        z_tampons(&z, src, n, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("fenêtre %d : MZ_FINISH en une fois après mz_inflateReset", fenetre), mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH),
             MZ_STREAM_END);
        controle(cas_f("fenêtre %d : sortie après remise à zéro sur MZ_BUF_ERROR", fenetre),
                 m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);

        /* Après une erreur de données. Fenêtre 15 : somme de l'en-tête fausse ; -15 : type de bloc 3 (réservé). */
        memcpy(copie, src, n);
        if (fenetre > 0)
            copie[1] ^= 1;
        else
            copie[0] = 0x07;
        mz_inflateReset(&m);
        inflateReset(&z);
        mz_tampons(&m, copie, n, sortie_m, sizeof(sortie_m));
        z_tampons(&z, copie, n, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("fenêtre %d : mz_inflate données invalides", fenetre), mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_DATA_ERROR);
        IDEM(cas_f("fenêtre %d : mz_inflate rappelé après l'erreur", fenetre), mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH),
             MZ_DATA_ERROR);
        IDEM(cas_f("fenêtre %d : mz_inflateReset après MZ_DATA_ERROR", fenetre), mz_inflateReset(&m), inflateReset(&z), MZ_OK);
        IDEM(cas_f("fenêtre %d : mz_inflate en flux après remise à zéro sur erreur", fenetre),
             mz_inflate_flux(&m, src, n, sortie_m, sizeof(sortie_m)), z_inflate_flux(&z, src, n, sortie_z, sizeof(sortie_z)), MZ_STREAM_END);
        controle(cas_f("fenêtre %d : sortie après remise à zéro sur erreur", fenetre),
                 m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
        mz_inflateEnd(&m);
        inflateEnd(&z);
    }
}

/* ------------------------------------------------------------------ mz_inflate */

static void cas_inflate(void)
{
    static const int vidages_hors_miniz[] = { MZ_FULL_FLUSH, MZ_BLOCK, -1 };
    static const int attendu_zlib[] = { Z_STREAM_END, Z_OK, Z_STREAM_END };
    mz_stream m;
    z_stream z;
    size_t i;

    IDEM("mz_inflate flux nul", mz_inflate(NULL, MZ_NO_FLUSH), inflate(NULL, Z_NO_FLUSH), MZ_STREAM_ERROR);

    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    mz_tampons(&m, flux_zlib, 0, sortie_m, sizeof(sortie_m));
    z_tampons(&z, flux_zlib, 0, sortie_z, sizeof(sortie_z));
    IDEM("mz_inflate sans entrée", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_BUF_ERROR);
    mz_tampons(&m, flux_zlib, n_flux_zlib, sortie_m, 0);
    z_tampons(&z, flux_zlib, n_flux_zlib, sortie_z, 0);
    IDEM("mz_inflate avail_out = 0", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_OK);
    m.avail_out = z.avail_out = sizeof(sortie_m);
    IDEM("mz_inflate avail_out = 0, puis sortie suffisante", mz_inflate_flux(&m, m.next_in, m.avail_in, sortie_m, sizeof(sortie_m)),
         z_inflate_flux(&z, z.next_in, z.avail_in, sortie_z, sizeof(sortie_z)), MZ_STREAM_END);
    controle("mz_inflate avail_out = 0, puis sortie suffisante : sortie", m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
    IDEM("mz_inflate après la fin, sans entrée", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_STREAM_END);
    IDEM("mz_inflate après la fin, MZ_FINISH", mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH), MZ_STREAM_END);
    ECART("mz_inflate après la fin, sans MZ_FINISH après un MZ_FINISH", mz_inflate(&m, MZ_NO_FLUSH), MZ_STREAM_ERROR,
          inflate(&z, Z_NO_FLUSH), Z_STREAM_END, "E8");
    mz_inflateEnd(&m);
    inflateEnd(&z);

    for (i = 0; i < sizeof(vidages_hors_miniz) / sizeof(vidages_hors_miniz[0]); i++)
    {
        int vidage = vidages_hors_miniz[i];
        mz_ouvrir_inf(&m, 15);
        z_ouvrir_inf(&z, 15);
        mz_tampons(&m, flux_zlib, n_flux_zlib, sortie_m, sizeof(sortie_m));
        z_tampons(&z, flux_zlib, n_flux_zlib, sortie_z, sizeof(sortie_z));
        ECART(cas_f("mz_inflate vidage %d", vidage), mz_inflate(&m, vidage), MZ_STREAM_ERROR, inflate(&z, vidage), attendu_zlib[i], "E4");
        controle(cas_f("mz_inflate vidage %d refusé : flux toujours utilisable", vidage),
                 m.total_in == 0 && mz_inflate(&m, MZ_FINISH) == MZ_STREAM_END && m.total_out == TAILLE &&
                     memcmp(sortie_m, donnees, TAILLE) == 0);
        mz_inflateEnd(&m);
        inflateEnd(&z);
    }

    for (i = 0; i < 2; i++)
    {
        int vidage = i ? MZ_SYNC_FLUSH : MZ_PARTIAL_FLUSH;
        mz_ouvrir_inf(&m, 15);
        z_ouvrir_inf(&z, 15);
        mz_tampons(&m, flux_zlib, n_flux_zlib, sortie_m, sizeof(sortie_m));
        z_tampons(&z, flux_zlib, n_flux_zlib, sortie_z, sizeof(sortie_z));
        IDEM(cas_f("mz_inflate vidage %d", vidage), mz_inflate(&m, vidage), inflate(&z, vidage), MZ_STREAM_END);
        mz_inflateEnd(&m);
        inflateEnd(&z);
    }

    /* MZ_FINISH au premier appel avec une sortie trop petite [E8], blocs compressés puis stockés. */
    for (i = 0; i < 2; i++)
    {
        const unsigned char *src = i ? flux_stocke : flux_zlib;
        size_t n = i ? n_flux_stocke : n_flux_zlib;
        const char *genre = i ? "blocs stockés" : "niveau 6";
        mz_ouvrir_inf(&m, 15);
        z_ouvrir_inf(&z, 15);
        mz_tampons(&m, src, n, sortie_m, TAILLE / 2);
        z_tampons(&z, src, n, sortie_z, TAILLE / 2);
        IDEM(cas_f("mz_inflate MZ_FINISH au premier appel, sortie trop petite (%s)", genre), mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH),
             MZ_BUF_ERROR);
        m.avail_out = z.avail_out = sizeof(sortie_m) - TAILLE / 2;
        ECART(cas_f("mz_inflate MZ_FINISH rappelé avec une sortie suffisante (%s)", genre), mz_inflate(&m, MZ_FINISH), MZ_DATA_ERROR,
              inflate(&z, Z_FINISH), Z_STREAM_END, "E8");
        mz_inflateEnd(&m);
        inflateEnd(&z);
    }

    /* MZ_FINISH après un premier appel en flux, sortie trop petite. */
    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    mz_tampons(&m, flux_zlib, 100, sortie_m, sizeof(sortie_m));
    z_tampons(&z, flux_zlib, 100, sortie_z, sizeof(sortie_z));
    IDEM("mz_inflate 100 premiers octets en flux", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_OK);
    mz_tampons(&m, flux_zlib + m.total_in, n_flux_zlib - m.total_in, sortie_m + m.total_out, TAILLE / 2 - m.total_out);
    z_tampons(&z, flux_zlib + z.total_in, n_flux_zlib - z.total_in, sortie_z + z.total_out, TAILLE / 2 - z.total_out);
    IDEM("mz_inflate MZ_FINISH ensuite, sortie trop petite", mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH), MZ_BUF_ERROR);
    m.avail_out = (unsigned int)(sizeof(sortie_m) - m.total_out);
    z.avail_out = (uInt)(sizeof(sortie_z) - z.total_out);
    ECART("mz_inflate sans MZ_FINISH après un MZ_FINISH", mz_inflate(&m, MZ_NO_FLUSH), MZ_STREAM_ERROR, inflate(&z, Z_NO_FLUSH),
          Z_STREAM_END, "E8");
    controle("mz_inflate MZ_FINISH rappelé avec une sortie suffisante : sortie",
             mz_inflate_finir(&m) == MZ_STREAM_END && m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
    mz_inflateEnd(&m);
    inflateEnd(&z);

    /* MZ_FINISH après un premier appel en flux : la fin du flux est atteinte, mais il manque un octet de sortie. */
    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    mz_tampons(&m, flux_zlib, 100, sortie_m, sizeof(sortie_m));
    z_tampons(&z, flux_zlib, 100, sortie_z, sizeof(sortie_z));
    IDEM("mz_inflate 100 premiers octets en flux, puis", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_OK);
    mz_tampons(&m, flux_zlib + m.total_in, n_flux_zlib - m.total_in, sortie_m + m.total_out, TAILLE - 1 - m.total_out);
    z_tampons(&z, flux_zlib + z.total_in, n_flux_zlib - z.total_in, sortie_z + z.total_out, TAILLE - 1 - z.total_out);
    IDEM("mz_inflate MZ_FINISH, sortie trop courte d'un octet", mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH), MZ_BUF_ERROR);
    m.avail_out = z.avail_out = 1;
    IDEM("mz_inflate MZ_FINISH avec l'octet manquant", mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH), MZ_STREAM_END);
    controle("mz_inflate MZ_FINISH avec l'octet manquant : sortie", m.total_out == TAILLE && memcmp(sortie_m, donnees, TAILLE) == 0);
    mz_inflateEnd(&m);
    inflateEnd(&z);

    /* Données après la fin du flux, en flux : mêmes octets laissés que zlib. */
    memcpy(copie, flux_zlib, n_flux_zlib);
    memset(copie + n_flux_zlib, 0xA5, 16);
    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    mz_tampons(&m, copie, n_flux_zlib + 16, sortie_m, sizeof(sortie_m));
    z_tampons(&z, copie, n_flux_zlib + 16, sortie_z, sizeof(sortie_z));
    IDEM("mz_inflate données après la fin du flux", mz_inflate(&m, MZ_NO_FLUSH), inflate(&z, Z_NO_FLUSH), MZ_STREAM_END);
    controle("mz_inflate données après la fin du flux : octets laissés égaux à ceux de zlib", m.avail_in == 16 && m.avail_in == z.avail_in);
    mz_inflateEnd(&m);
    inflateEnd(&z);

    /* Adler-32 faux, en flux. */
    memcpy(copie, flux_zlib, n_flux_zlib);
    copie[n_flux_zlib - 1] ^= 1;
    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    IDEM("mz_inflate Adler-32 faux, en flux", mz_inflate_flux(&m, copie, n_flux_zlib, sortie_m, sizeof(sortie_m)),
         z_inflate_flux(&z, copie, n_flux_zlib, sortie_z, sizeof(sortie_z)), MZ_DATA_ERROR);
    mz_inflateEnd(&m);
    inflateEnd(&z);

    /* Dictionnaire prédéfini [E9]. */
    copie[0] = 0x78, copie[1] = 0x20, copie[2] = 0x12, copie[3] = 0x34, copie[4] = 0x56, copie[5] = 0x78;
    memcpy(copie + 6, flux_zlib + 2, n_flux_zlib - 2);
    mz_ouvrir_inf(&m, 15);
    z_ouvrir_inf(&z, 15);
    mz_tampons(&m, copie, n_flux_zlib + 4, sortie_m, sizeof(sortie_m));
    z_tampons(&z, copie, n_flux_zlib + 4, sortie_z, sizeof(sortie_z));
    ECART("mz_inflate en-tête avec dictionnaire prédéfini", mz_inflate(&m, MZ_NO_FLUSH), MZ_DATA_ERROR, inflate(&z, Z_NO_FLUSH), Z_NEED_DICT,
          "E9");
    IDEM("mz_inflateEnd après une erreur", mz_inflateEnd(&m), inflateEnd(&z), MZ_OK);
    IDEM("mz_inflate après mz_inflateEnd", mz_inflate(&m, MZ_FINISH), inflate(&z, Z_FINISH), MZ_STREAM_ERROR);
    ECART("mz_inflateEnd deux fois", mz_inflateEnd(&m), MZ_OK, inflateEnd(&z), Z_STREAM_ERROR, "E10");
    IDEM("mz_inflateEnd flux nul", mz_inflateEnd(NULL), inflateEnd(NULL), MZ_STREAM_ERROR);
}

/* ------------------------------------------------------------------ mz_error, valeur initiale des sommes */

static void cas_error(void)
{
    static const int connus[] = { MZ_OK, MZ_STREAM_END, MZ_NEED_DICT, MZ_ERRNO, MZ_STREAM_ERROR,
                                  MZ_DATA_ERROR, MZ_MEM_ERROR, MZ_BUF_ERROR, MZ_VERSION_ERROR, MZ_PARAM_ERROR };
    size_t i;
    for (i = 0; i < sizeof(connus) / sizeof(connus[0]); i++)
        controle(cas_f("mz_error(%s) décrit le code", nom(connus[i])), mz_error(connus[i]) != NULL);
    controle("mz_error(MZ_OK) est vide, comme zError(Z_OK)", mz_error(MZ_OK) && !strcmp(mz_error(MZ_OK), zError(Z_OK)));
    controle("mz_error(code inconnu) rend NULL", mz_error(12345) == NULL);
    /* Valeur initiale des sommes, selon l'idiome de zlib.h (pointeur nul, longueur 0). */
    controle("mz_adler32(0, NULL, 0) égal à adler32(0, Z_NULL, 0)", mz_adler32(0, NULL, 0) == adler32(0, Z_NULL, 0));
    controle("mz_crc32(0, NULL, 0) égal à crc32(0, Z_NULL, 0)", mz_crc32(0, NULL, 0) == crc32(0, Z_NULL, 0));
}

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++)
    {
        if (!strcmp(argv[a], "--verbeux"))
            verbeux = 1;
        else
        {
            fprintf(stderr, "usage : %s [--verbeux]\n", argv[0]);
            return 2;
        }
    }
    printf("miniz %s, zlib %s : cas limites de l'API compatible zlib\n", mz_version(), zlibVersion());

    generer_donnees();
    {
        z_stream z;
        n_flux_zlib = sizeof(flux_zlib);
        n_flux_stocke = sizeof(flux_stocke);
        if (compress2(flux_zlib, &n_flux_zlib, donnees, TAILLE, 6) != Z_OK ||
            compress2(flux_stocke, &n_flux_stocke, donnees, TAILLE, 0) != Z_OK)
            erreur_env("compress2");
        z_ouvrir_def(&z, 6, -15);
        z_tampons(&z, donnees, TAILLE, flux_brut, sizeof(flux_brut));
        if (deflate(&z, Z_FINISH) != Z_STREAM_END)
            erreur_env("deflate brut");
        n_flux_brut = z.total_out;
        deflateEnd(&z);
    }

    cas_constantes();
    cas_init_compression();
    cas_init_decompression();
    cas_allocateurs();
    cas_deflate();
    cas_compress();
    cas_uncompress();
    cas_deflate_reset();
    cas_inflate_reset();
    cas_inflate();
    cas_error();

    printf("%ld cas comparés à zlib (dont %ld écarts tolérés, listés en tête de bee/tests/api.c), %ld contrôles, %ld échecs, "
           "%ld avertissements.\n",
           nb_cas, nb_ecarts, nb_controles, nb_echecs, nb_avertissements);
    if (nb_echecs)
    {
        fprintf(stderr, "RÉSULTAT : ÉCHEC (%ld).\n", nb_echecs);
        return 1;
    }
    printf("RÉSULTAT : OK, codes de retour de miniz conformes aux attendus.\n");
    return 0;
}
