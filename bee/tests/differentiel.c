/* Tests différentiels Bee pour miniz : miniz contre la zlib du système, sur le corpus de référence.

   Pour chaque fichier du corpus et chaque niveau (0, 1, 6, 9) :
     [miniz->zlib]    mz_compress2, puis uncompress de zlib : identique à l'original ;
     [miniz->miniz]   mz_compress2, puis mz_uncompress : identique ;
     [zlib->miniz]    compress2 de zlib, puis mz_uncompress : identique ;
     [flux-1]         mz_deflate puis mz_inflate avec des tampons d'entrée et de sortie de 1 octet ;
     [flux-4096]      idem avec des tampons de 4096 octets ;
                      dans les deux cas, la sortie compressée en flux doit être identique à celle de
                      mz_compress2 (même résultat quel que soit le découpage de l'entrée) ;
     [brut]           Deflate brut (window_bits = -15) en flux 4096, puis inflate brut de zlib ;
                      le flux brut doit être identique au flux zlib privé de son en-tête et de son Adler-32.
   Pour chaque fichier, au niveau 6 seulement :
     [vidages]        mz_deflate avec MZ_SYNC_FLUSH tous les 10007 octets et MZ_FULL_FLUSH tous les
                      50021 octets, puis inflate de zlib : identique.
   Pour chaque fichier :
     [sommes]         mz_adler32 et mz_crc32 égales à adler32 et crc32 de zlib (en une fois et par morceaux).
   Déterminisme : l'empreinte SHA-256 de chaque sortie compressée (niveaux 0, 1, 6, 9 et « 6v » pour
   la variante avec vidages) est comparée au fichier de référence produit sur la version de base.

   Usage : differentiel [--corpus DOSSIER] [--empreintes FICHIER] [--regenerer-empreintes]
                        [--sans-empreintes] [--rapide] [--verbeux]
   Code de sortie : 0 si tout est identique, 1 au moindre écart, 2 en cas d'erreur d'usage ou d'environnement. */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <zlib.h>

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "corpus.h"
#include "sha256.h"

#define NB_NIVEAUX 4
static const int NIVEAUX[NB_NIVEAUX] = { 0, 1, 6, 9 };

/* Au-delà de cette taille, l'option --rapide limite le flux à 1 octet au premier Mo du fichier. */
#define LIMITE_FLUX_1_RAPIDE (64u * 1024u)

typedef struct
{
    unsigned char *octets;
    size_t taille, capacite;
} tampon;

static long nb_echecs = 0, nb_controles = 0;
static int verbeux = 0;

static void echec(const char *controle, const char *fichier, const char *niveau, const char *format, ...)
{
    va_list ap;
    nb_echecs++;
    if (nb_echecs > 200)
        return; /* le décompte reste exact, seul l'affichage est limité */
    fprintf(stderr, "ÉCHEC [%s] niveau %s, %s : ", controle, niveau, fichier);
    va_start(ap, format);
    vfprintf(stderr, format, ap);
    va_end(ap);
    fputc('\n', stderr);
}

static void *allouer(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p)
    {
        fprintf(stderr, "erreur : mémoire insuffisante (%zu octets)\n", n);
        exit(2);
    }
    return p;
}

static void tampon_ajouter(tampon *t, const unsigned char *p, size_t n)
{
    if (n == 0)
        return;
    if (t->taille + n > t->capacite)
    {
        size_t c = t->capacite ? t->capacite : 4096;
        while (c < t->taille + n)
            c *= 2;
        t->octets = (unsigned char *)realloc(t->octets, c);
        if (!t->octets)
        {
            fprintf(stderr, "erreur : mémoire insuffisante\n");
            exit(2);
        }
        t->capacite = c;
    }
    memcpy(t->octets + t->taille, p, n);
    t->taille += n;
}

/* Compare une sortie décompressée à l'original ; renvoie 1 si identique. */
static int verifier_identique(const char *controle, const char *fichier, const char *niveau,
                              const unsigned char *obtenu, size_t taille_obtenue,
                              const unsigned char *attendu, size_t taille_attendue)
{
    size_t i, n = taille_obtenue < taille_attendue ? taille_obtenue : taille_attendue;
    nb_controles++;
    for (i = 0; i < n; i++)
        if (obtenu[i] != attendu[i])
            break;
    if (i == n && taille_obtenue == taille_attendue)
        return 1;
    if (i < n)
        echec(controle, fichier, niveau, "premier octet différent à la position %zu (taille obtenue %zu, attendue %zu)",
              i, taille_obtenue, taille_attendue);
    else
        echec(controle, fichier, niveau, "taille différente : %zu octets au lieu de %zu", taille_obtenue, taille_attendue);
    return 0;
}

/* ------------------------------------------------------------------ miniz en flux */

/* Compresse en flux avec mz_deflate. window_bits = 15 (zlib) ou -15 (brut).
   sync_tous / full_tous : position des MZ_SYNC_FLUSH / MZ_FULL_FLUSH (0 = jamais).
   Renvoie 0 si tout va bien, sinon -1 avec un message dans erreur. */
static int miniz_deflate_flux(const unsigned char *src, size_t n, int niveau, int window_bits,
                              size_t morceau_entree, size_t morceau_sortie, size_t sync_tous, size_t full_tous,
                              tampon *sortie, char *erreur, size_t taille_erreur)
{
    mz_stream s;
    unsigned char *bloc = (unsigned char *)allouer(morceau_sortie);
    size_t pos = 0;
    int r = 0, fini = 0;
    memset(&s, 0, sizeof(s));
    sortie->taille = 0;
    if ((r = mz_deflateInit2(&s, niveau, MZ_DEFLATED, window_bits, 9, MZ_DEFAULT_STRATEGY)) != MZ_OK)
    {
        snprintf(erreur, taille_erreur, "mz_deflateInit2 a renvoyé %d", r);
        free(bloc);
        return -1;
    }
    while (!fini)
    {
        size_t prendre = n - pos < morceau_entree ? n - pos : morceau_entree;
        size_t fin_morceau = pos + prendre;
        int vidage = MZ_NO_FLUSH;
        /* Un vidage tombe à la fin d'un morceau qui franchit un multiple de sync_tous ou full_tous. */
        if (sync_tous && prendre && (fin_morceau / sync_tous) != (pos / sync_tous))
            vidage = MZ_SYNC_FLUSH;
        if (full_tous && prendre && (fin_morceau / full_tous) != (pos / full_tous))
            vidage = MZ_FULL_FLUSH;
        if (fin_morceau == n)
            vidage = MZ_FINISH;
        s.next_in = src + pos;
        s.avail_in = (unsigned int)prendre;
        for (;;)
        {
            size_t avant_sortie;
            s.next_out = bloc;
            s.avail_out = (unsigned int)morceau_sortie;
            avant_sortie = s.avail_out;
            r = mz_deflate(&s, vidage);
            tampon_ajouter(sortie, bloc, avant_sortie - s.avail_out);
            if (r == MZ_STREAM_END)
            {
                fini = 1;
                break;
            }
            if (r != MZ_OK && r != MZ_BUF_ERROR)
            {
                snprintf(erreur, taille_erreur, "mz_deflate a renvoyé %d (entrée consommée %zu sur %zu)", r,
                         pos + prendre - s.avail_in, n);
                mz_deflateEnd(&s);
                free(bloc);
                return -1;
            }
            if (vidage == MZ_FINISH)
            {
                if (r == MZ_BUF_ERROR && s.avail_out != 0)
                {
                    snprintf(erreur, taille_erreur, "mz_deflate(MZ_FINISH) ne progresse plus sans renvoyer MZ_STREAM_END");
                    mz_deflateEnd(&s);
                    free(bloc);
                    return -1;
                }
                continue;
            }
            /* Comme zlib : l'appel est terminé quand l'entrée est consommée et qu'il reste de la place en sortie. */
            if (s.avail_in == 0 && s.avail_out != 0)
                break;
            if (r == MZ_BUF_ERROR && s.avail_in != 0)
            {
                snprintf(erreur, taille_erreur, "mz_deflate ne consomme plus l'entrée (MZ_BUF_ERROR)");
                mz_deflateEnd(&s);
                free(bloc);
                return -1;
            }
        }
        pos = fin_morceau;
    }
    mz_deflateEnd(&s);
    free(bloc);
    return 0;
}

/* Décompresse en flux avec mz_inflate (window_bits 15 ou -15). */
static int miniz_inflate_flux(const unsigned char *src, size_t n, int window_bits, size_t morceau_entree,
                              size_t morceau_sortie, tampon *sortie, char *erreur, size_t taille_erreur)
{
    mz_stream s;
    unsigned char *bloc = (unsigned char *)allouer(morceau_sortie);
    size_t pos = 0;
    long sans_progres = 0;
    int r;
    memset(&s, 0, sizeof(s));
    sortie->taille = 0;
    if ((r = mz_inflateInit2(&s, window_bits)) != MZ_OK)
    {
        snprintf(erreur, taille_erreur, "mz_inflateInit2 a renvoyé %d", r);
        free(bloc);
        return -1;
    }
    for (;;)
    {
        size_t produit;
        unsigned int avant_entree;
        if (s.avail_in == 0 && pos < n)
        {
            size_t prendre = n - pos < morceau_entree ? n - pos : morceau_entree;
            s.next_in = src + pos;
            s.avail_in = (unsigned int)prendre;
            pos += prendre;
        }
        avant_entree = s.avail_in;
        s.next_out = bloc;
        s.avail_out = (unsigned int)morceau_sortie;
        r = mz_inflate(&s, MZ_NO_FLUSH);
        produit = morceau_sortie - s.avail_out;
        tampon_ajouter(sortie, bloc, produit);
        if (r == MZ_STREAM_END)
            break;
        if (r != MZ_OK && r != MZ_BUF_ERROR)
        {
            snprintf(erreur, taille_erreur, "mz_inflate a renvoyé %d après %zu octets produits", r, sortie->taille);
            mz_inflateEnd(&s);
            free(bloc);
            return -1;
        }
        if (produit == 0 && s.avail_in == avant_entree)
        {
            if (pos >= n && s.avail_in == 0)
            {
                snprintf(erreur, taille_erreur, "flux tronqué : fin de l'entrée sans MZ_STREAM_END");
                mz_inflateEnd(&s);
                free(bloc);
                return -1;
            }
            if (++sans_progres > 1000)
            {
                snprintf(erreur, taille_erreur, "mz_inflate ne progresse plus (code %d)", r);
                mz_inflateEnd(&s);
                free(bloc);
                return -1;
            }
        }
        else
            sans_progres = 0;
    }
    mz_inflateEnd(&s);
    free(bloc);
    return 0;
}

/* ------------------------------------------------------------------ zlib en flux */

static int zlib_inflate_flux(const unsigned char *src, size_t n, int window_bits, tampon *sortie, char *erreur, size_t taille_erreur)
{
    z_stream s;
    unsigned char bloc[4096];
    int r;
    memset(&s, 0, sizeof(s));
    sortie->taille = 0;
    if ((r = inflateInit2(&s, window_bits)) != Z_OK)
    {
        snprintf(erreur, taille_erreur, "inflateInit2 de zlib a renvoyé %d", r);
        return -1;
    }
    s.next_in = (Bytef *)src;
    s.avail_in = (uInt)n;
    do
    {
        s.next_out = bloc;
        s.avail_out = sizeof(bloc);
        r = inflate(&s, Z_NO_FLUSH);
        if (r != Z_OK && r != Z_STREAM_END)
        {
            snprintf(erreur, taille_erreur, "inflate de zlib a renvoyé %d (%s) après %lu octets produits", r,
                     s.msg ? s.msg : "", (unsigned long)s.total_out);
            inflateEnd(&s);
            return -1;
        }
        tampon_ajouter(sortie, bloc, sizeof(bloc) - s.avail_out);
        if (r == Z_OK && s.avail_in == 0 && s.avail_out != 0)
        {
            snprintf(erreur, taille_erreur, "flux tronqué pour zlib : fin de l'entrée sans Z_STREAM_END");
            inflateEnd(&s);
            return -1;
        }
    } while (r != Z_STREAM_END);
    inflateEnd(&s);
    return 0;
}

/* ------------------------------------------------------------------ empreintes */

typedef struct
{
    char niveau[8];
    char *fichier;
    unsigned long taille;
    char sha[65];
} empreinte;

typedef struct
{
    empreinte *elements;
    size_t nombre, capacite;
} liste_empreintes;

static void empreinte_ajouter(liste_empreintes *l, const char *niveau, const char *fichier, size_t taille, const char *sha)
{
    empreinte *e;
    if (l->nombre == l->capacite)
    {
        l->capacite = l->capacite ? 2 * l->capacite : 256;
        l->elements = (empreinte *)realloc(l->elements, l->capacite * sizeof(empreinte));
        if (!l->elements)
            exit(2);
    }
    e = &l->elements[l->nombre++];
    snprintf(e->niveau, sizeof(e->niveau), "%s", niveau);
    e->fichier = strdup(fichier);
    e->taille = (unsigned long)taille;
    memcpy(e->sha, sha, 65);
}

static int lire_empreintes(const char *chemin, liste_empreintes *l)
{
    FILE *f = fopen(chemin, "r");
    char ligne[8192];
    if (!f)
        return -1;
    while (fgets(ligne, sizeof(ligne), f))
    {
        char niveau[8], sha[65], fichier[4096];
        unsigned long taille;
        if (ligne[0] == '#' || ligne[0] == '\n')
            continue;
        if (sscanf(ligne, "%7s %lu %64s %4095[^\n]", niveau, &taille, sha, fichier) == 4)
            empreinte_ajouter(l, niveau, fichier, taille, sha);
    }
    fclose(f);
    return 0;
}

static void liberer_empreintes(liste_empreintes *l)
{
    size_t i;
    for (i = 0; i < l->nombre; i++)
        free(l->elements[i].fichier);
    free(l->elements);
    memset(l, 0, sizeof(*l));
}

static const empreinte *chercher(const liste_empreintes *l, const char *niveau, const char *fichier)
{
    size_t i;
    for (i = 0; i < l->nombre; i++)
        if (!strcmp(l->elements[i].niveau, niveau) && !strcmp(l->elements[i].fichier, fichier))
            return &l->elements[i];
    return NULL;
}

/* ------------------------------------------------------------------ programme */

static void usage(void)
{
    fprintf(stderr, "usage : differentiel [--corpus DOSSIER] [--empreintes FICHIER] [--regenerer-empreintes] "
                    "[--sans-empreintes] [--rapide] [--verbeux]\n");
}

int main(int argc, char **argv)
{
    const char *dossier = "bee/corpus/donnees", *chemin_empreintes = "bee/tests/empreintes-reference.txt";
    int regenerer = 0, sans_empreintes = 0, rapide = 0, a;
    bee_corpus corpus;
    liste_empreintes obtenues = { NULL, 0, 0 }, reference = { NULL, 0, 0 };
    size_t i;
    tampon flux = { NULL, 0, 0 }, retour = { NULL, 0, 0 };
    char erreur[512];
    time_t debut = time(NULL);

    setvbuf(stdout, NULL, _IOLBF, 0); /* garde l'ordre des messages quand stdout et stderr vont au même endroit */
    for (a = 1; a < argc; a++)
    {
        if (!strcmp(argv[a], "--corpus") && a + 1 < argc)
            dossier = argv[++a];
        else if (!strcmp(argv[a], "--empreintes") && a + 1 < argc)
            chemin_empreintes = argv[++a];
        else if (!strcmp(argv[a], "--regenerer-empreintes"))
            regenerer = 1;
        else if (!strcmp(argv[a], "--sans-empreintes"))
            sans_empreintes = 1;
        else if (!strcmp(argv[a], "--rapide"))
            rapide = 1;
        else if (!strcmp(argv[a], "--verbeux"))
            verbeux = 1;
        else
        {
            usage();
            return 2;
        }
    }

    if (bee_corpus_charger(dossier, &corpus) != 0)
        return 2;
    printf("miniz %s, zlib %s (en-têtes %s), corpus : %zu fichiers, %zu octets\n", mz_version(), zlibVersion(),
           ZLIB_VERSION, corpus.nombre, corpus.total);

    for (i = 0; i < corpus.nombre; i++)
    {
        const bee_fichier *f = &corpus.fichiers[i];
        const char *nom = f->nom;
        int k;
        char sha[65];
        long echecs_avant = nb_echecs;

        /* [sommes] */
        {
            mz_ulong a1 = mz_adler32(MZ_ADLER32_INIT, f->donnees, f->taille);
            mz_ulong c1 = mz_crc32(MZ_CRC32_INIT, f->donnees, f->taille);
            uLong a2 = adler32(adler32(0L, Z_NULL, 0), f->donnees, (uInt)f->taille);
            uLong c2 = crc32(crc32(0L, Z_NULL, 0), f->donnees, (uInt)f->taille);
            mz_ulong a3 = MZ_ADLER32_INIT, c3 = MZ_CRC32_INIT;
            size_t p = 0, pas = 1;
            while (p < f->taille) /* morceaux de tailles 1, 2, 3, ... pour croiser les bornes de blocs */
            {
                size_t n = f->taille - p < pas ? f->taille - p : pas;
                a3 = mz_adler32(a3, f->donnees + p, n);
                c3 = mz_crc32(c3, f->donnees + p, n);
                p += n;
                pas = pas % 6000 + 1;
            }
            nb_controles += 2;
            if (a1 != a2 || a3 != a2)
                echec("sommes", nom, "-", "mz_adler32 = %08lx (par morceaux %08lx), adler32 de zlib = %08lx", a1, a3, a2);
            if (c1 != c2 || c3 != c2)
                echec("sommes", nom, "-", "mz_crc32 = %08lx (par morceaux %08lx), crc32 de zlib = %08lx", c1, c3, c2);
        }

        for (k = 0; k < NB_NIVEAUX; k++)
        {
            int niveau = NIVEAUX[k], r;
            char nom_niveau[8];
            mz_ulong borne = mz_compressBound((mz_ulong)f->taille), taille_c = borne, taille_d;
            uLongf taille_z = compressBound((uLong)f->taille), taille_zd;
            unsigned char *c = (unsigned char *)allouer(borne);
            unsigned char *z = (unsigned char *)allouer(taille_z);
            unsigned char *d = (unsigned char *)allouer(f->taille + 1);
            snprintf(nom_niveau, sizeof(nom_niveau), "%d", niveau);

            /* [miniz->zlib] et [miniz->miniz] */
            r = mz_compress2(c, &taille_c, f->donnees, (mz_ulong)f->taille, niveau);
            nb_controles++;
            if (r != MZ_OK)
            {
                echec("miniz->zlib", nom, nom_niveau, "mz_compress2 a renvoyé %d (borne mz_compressBound = %lu)", r, borne);
                taille_c = 0;
            }
            else
            {
                bee_sha256_hex(c, taille_c, sha);
                empreinte_ajouter(&obtenues, nom_niveau, nom, taille_c, sha);
                taille_zd = (uLongf)f->taille + 1;
                r = uncompress(d, &taille_zd, c, (uLong)taille_c);
                if (r != Z_OK)
                    echec("miniz->zlib", nom, nom_niveau, "uncompress de zlib a renvoyé %d", r);
                else
                    verifier_identique("miniz->zlib", nom, nom_niveau, d, taille_zd, f->donnees, f->taille);
                taille_d = (mz_ulong)f->taille + 1;
                r = mz_uncompress(d, &taille_d, c, taille_c);
                if (r != MZ_OK)
                    echec("miniz->miniz", nom, nom_niveau, "mz_uncompress a renvoyé %d", r);
                else
                    verifier_identique("miniz->miniz", nom, nom_niveau, d, taille_d, f->donnees, f->taille);
            }

            /* [zlib->miniz] */
            r = compress2(z, &taille_z, f->donnees, (uLong)f->taille, niveau);
            if (r != Z_OK)
                echec("zlib->miniz", nom, nom_niveau, "compress2 de zlib a renvoyé %d", r);
            else
            {
                taille_d = (mz_ulong)f->taille + 1;
                r = mz_uncompress(d, &taille_d, z, (mz_ulong)taille_z);
                if (r != MZ_OK)
                    echec("zlib->miniz", nom, nom_niveau, "mz_uncompress a renvoyé %d", r);
                else
                    verifier_identique("zlib->miniz", nom, nom_niveau, d, taille_d, f->donnees, f->taille);
            }

            /* [flux-1] et [flux-4096] */
            {
                static const size_t morceaux[2] = { 1, 4096 };
                int m;
                for (m = 0; m < 2; m++)
                {
                    char controle[32];
                    size_t n = f->taille;
                    snprintf(controle, sizeof(controle), "flux-%zu", morceaux[m]);
                    if (morceaux[m] == 1 && rapide && n > LIMITE_FLUX_1_RAPIDE)
                        continue;
                    if (miniz_deflate_flux(f->donnees, n, niveau, MZ_DEFAULT_WINDOW_BITS, morceaux[m], morceaux[m], 0, 0, &flux,
                                           erreur, sizeof(erreur)) != 0)
                    {
                        echec(controle, nom, nom_niveau, "compression : %s", erreur);
                        continue;
                    }
                    nb_controles++;
                    if (taille_c && (flux.taille != taille_c || memcmp(flux.octets, c, taille_c) != 0))
                        echec(controle, nom, nom_niveau,
                              "la sortie compressée en flux (%zu octets) diffère de celle de mz_compress2 (%lu octets)", flux.taille,
                              taille_c);
                    if (miniz_inflate_flux(flux.octets, flux.taille, MZ_DEFAULT_WINDOW_BITS, morceaux[m], morceaux[m], &retour,
                                           erreur, sizeof(erreur)) != 0)
                        echec(controle, nom, nom_niveau, "décompression : %s", erreur);
                    else
                        verifier_identique(controle, nom, nom_niveau, retour.octets, retour.taille, f->donnees, f->taille);
                }
            }

            /* [brut] */
            if (miniz_deflate_flux(f->donnees, f->taille, niveau, -MZ_DEFAULT_WINDOW_BITS, 4096, 4096, 0, 0, &flux, erreur,
                                   sizeof(erreur)) != 0)
                echec("brut", nom, nom_niveau, "compression : %s", erreur);
            else
            {
                nb_controles++;
                if (taille_c >= 6 && (flux.taille != taille_c - 6 || memcmp(flux.octets, c + 2, taille_c - 6) != 0))
                    echec("brut", nom, nom_niveau, "le flux brut (%zu octets) n'est pas le flux zlib (%lu octets) sans en-tête ni Adler-32",
                          flux.taille, taille_c);
                if (zlib_inflate_flux(flux.octets, flux.taille, -MAX_WBITS, &retour, erreur, sizeof(erreur)) != 0)
                    echec("brut", nom, nom_niveau, "%s", erreur);
                else
                    verifier_identique("brut", nom, nom_niveau, retour.octets, retour.taille, f->donnees, f->taille);
                if (miniz_inflate_flux(flux.octets, flux.taille, -MZ_DEFAULT_WINDOW_BITS, 4096, 4096, &retour, erreur, sizeof(erreur)) != 0)
                    echec("brut", nom, nom_niveau, "mz_inflate brut : %s", erreur);
                else
                    verifier_identique("brut", nom, nom_niveau, retour.octets, retour.taille, f->donnees, f->taille);
            }

            /* [vidages] au niveau 6 */
            if (niveau == 6)
            {
                if (miniz_deflate_flux(f->donnees, f->taille, 6, MZ_DEFAULT_WINDOW_BITS, 4096, 4096, 10007, 50021, &flux, erreur,
                                       sizeof(erreur)) != 0)
                    echec("vidages", nom, "6v", "compression : %s", erreur);
                else
                {
                    bee_sha256_hex(flux.octets, flux.taille, sha);
                    empreinte_ajouter(&obtenues, "6v", nom, flux.taille, sha);
                    if (zlib_inflate_flux(flux.octets, flux.taille, MAX_WBITS, &retour, erreur, sizeof(erreur)) != 0)
                        echec("vidages", nom, "6v", "%s", erreur);
                    else
                        verifier_identique("vidages", nom, "6v", retour.octets, retour.taille, f->donnees, f->taille);
                    if (miniz_inflate_flux(flux.octets, flux.taille, MZ_DEFAULT_WINDOW_BITS, 1000, 1000, &retour, erreur, sizeof(erreur)) != 0)
                        echec("vidages", nom, "6v", "mz_inflate : %s", erreur);
                    else
                        verifier_identique("vidages", nom, "6v", retour.octets, retour.taille, f->donnees, f->taille);
                }
            }
            free(c);
            free(z);
            free(d);
        }
        if (verbeux)
            printf("  %-45s %10zu octets : %s\n", nom, f->taille, nb_echecs > echecs_avant ? "ÉCARTS" : "ok");
    }

    /* Déterminisme */
    if (regenerer)
    {
        FILE *e = fopen(chemin_empreintes, "w");
        if (!e)
        {
            fprintf(stderr, "erreur : impossible d'écrire %s\n", chemin_empreintes);
            return 2;
        }
        if (nb_echecs)
        {
            fprintf(stderr, "erreur : %ld écarts relevés, les empreintes ne sont pas régénérées\n", nb_echecs);
            fclose(e);
            return 1;
        }
        fprintf(e, "# Empreintes SHA-256 des sorties compressées de miniz sur le corpus de référence Bee.\n");
        fprintf(e, "# Produites par bee/tests/lancer.sh --regenerer-empreintes. Colonnes : niveau, taille compressée,\n");
        fprintf(e, "# SHA-256, fichier. « 6v » : niveau 6 en flux avec MZ_SYNC_FLUSH et MZ_FULL_FLUSH (voir differentiel.c).\n");
        for (i = 0; i < obtenues.nombre; i++)
            fprintf(e, "%s %lu %s %s\n", obtenues.elements[i].niveau, obtenues.elements[i].taille, obtenues.elements[i].sha,
                    obtenues.elements[i].fichier);
        fclose(e);
        printf("Empreintes régénérées : %zu lignes dans %s\n", obtenues.nombre, chemin_empreintes);
    }
    else if (!sans_empreintes)
    {
        long differences = 0;
        if (lire_empreintes(chemin_empreintes, &reference) != 0)
        {
            fprintf(stderr, "erreur : fichier d'empreintes introuvable : %s\n", chemin_empreintes);
            return 2;
        }
        for (i = 0; i < obtenues.nombre; i++)
        {
            const empreinte *o = &obtenues.elements[i];
            const empreinte *r = chercher(&reference, o->niveau, o->fichier);
            nb_controles++;
            if (!r)
            {
                echec("empreintes", o->fichier, o->niveau, "absent du fichier de référence (corpus modifié ?)");
                differences++;
            }
            else if (strcmp(r->sha, o->sha) != 0)
            {
                echec("empreintes", o->fichier, o->niveau,
                      "la sortie compressée a changé (%lu octets au lieu de %lu ; SHA-256 %.16s… au lieu de %.16s…)", o->taille,
                      r->taille, o->sha, r->sha);
                differences++;
            }
        }
        for (i = 0; i < reference.nombre; i++)
            if (!chercher(&obtenues, reference.elements[i].niveau, reference.elements[i].fichier))
            {
                echec("empreintes", reference.elements[i].fichier, reference.elements[i].niveau, "attendu mais non produit");
                differences++;
            }
        if (differences)
            fprintf(stderr,
                    "\n%ld empreintes diffèrent : la sortie compressée n'est plus identique à celle de la version de base.\n"
                    "C'est interdit sauf si la tâche l'autorise (sortie_compressee: peut_changer) ; relancez alors avec "
                    "--sans-empreintes.\n",
                    differences);
        else
            printf("Déterminisme : %zu empreintes identiques à la référence.\n", obtenues.nombre);
    }
    else
        printf("Déterminisme : contrôle des empreintes sauté (--sans-empreintes).\n");

    printf("%ld contrôles, %ld écarts, %ld s.\n", nb_controles, nb_echecs, (long)(time(NULL) - debut));
    free(flux.octets);
    free(retour.octets);
    liberer_empreintes(&obtenues);
    liberer_empreintes(&reference);
    bee_corpus_liberer(&corpus);
    if (nb_echecs)
    {
        fprintf(stderr, "RÉSULTAT : ÉCHEC (%ld écarts).\n", nb_echecs);
        return 1;
    }
    printf("RÉSULTAT : OK, miniz et zlib sont d'accord sur tout le corpus.\n");
    return 0;
}
