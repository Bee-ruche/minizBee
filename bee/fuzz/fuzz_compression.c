/* Harnais de fuzzing Bee (b) : compression miniz, décompression zlib.

   Le premier octet de l'entrée choisit le niveau (0 à 10, niveau 10 compris), le deuxième la stratégie
   et le mode d'appel, le troisième la taille des tampons du mode flux ; le reste est la donnée.

   Ce qui est vérifié :
     1. la sortie de miniz se décompresse avec zlib et redonne exactement la donnée ;
     2. compresser en flux (mz_deflate, petits tampons, avec ou sans MZ_SYNC_FLUSH) donne aussi un flux
        que zlib décompresse en la donnée d'origine ;
     3. en flux sans vidage, la sortie est identique à celle de mz_compress2 (déterminisme) ;
     4. la sortie en une fois ne dépasse pas mz_compressBound (en flux avec vidages, elle peut le dépasser
        légitimement : chaque MZ_SYNC_FLUSH ajoute environ 5 octets, zlib se comporte de même) ;
     5. aucune erreur mémoire ni comportement indéfini (ASan, UBSan). */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <zlib.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMITE_ENTREE (256u * 1024u)

static void ecart(const char *quoi, int niveau, int strategie, size_t taille)
{
    fprintf(stderr, "fuzz_compression : ÉCART %s (niveau %d, stratégie %d, %zu octets)\n", quoi, niveau, strategie, taille);
    abort();
}

static void verifier_avec_zlib(const unsigned char *c, size_t nc, const uint8_t *d, size_t n, unsigned char *tampon,
                               const char *mode, int niveau, int strategie)
{
    uLongf taille = (uLongf)n + 1;
    int r = uncompress(tampon, &taille, c, (uLong)nc);
    if (r != Z_OK)
    {
        fprintf(stderr, "fuzz_compression : %s : uncompress de zlib a renvoyé %d\n", mode, r);
        ecart("zlib ne décompresse pas la sortie de miniz", niveau, strategie, n);
    }
    if (taille != n || (n && memcmp(tampon, d, n) != 0))
    {
        fprintf(stderr, "fuzz_compression : %s\n", mode);
        ecart("la sortie de miniz décompressée par zlib diffère de l'entrée", niveau, strategie, n);
    }
}

/* Compresse en flux ; renvoie la taille produite, ou 0 en cas d'erreur. */
static size_t compresser_flux(const uint8_t *d, size_t n, int niveau, int strategie, size_t morceau, int avec_vidage,
                              unsigned char *sortie, size_t capacite)
{
    mz_stream s;
    size_t pos = 0;
    int r;
    memset(&s, 0, sizeof(s));
    if (mz_deflateInit2(&s, niveau, MZ_DEFLATED, MZ_DEFAULT_WINDOW_BITS, 9, strategie) != MZ_OK)
        return 0;
    s.next_out = sortie;
    for (;;)
    {
        size_t prendre = n - pos < morceau ? n - pos : morceau;
        int vidage = (pos + prendre == n) ? MZ_FINISH : (avec_vidage && ((pos / morceau) % 3 == 2) ? MZ_SYNC_FLUSH : MZ_NO_FLUSH);
        s.next_in = d + pos;
        s.avail_in = (unsigned int)prendre;
        do
        {
            size_t place = capacite - s.total_out;
            /* Pour un MZ_SYNC_FLUSH, le manuel de zlib exige avail_out > 6, sinon chaque appel rendu avec
               avail_out == 0 émet un nouveau marqueur de vidage, sans fin (zlib et miniz font de même). */
            size_t tranche = (vidage == MZ_SYNC_FLUSH && morceau < 8) ? 8 : morceau;
            if (place == 0)
            {
                mz_deflateEnd(&s);
                return 0;
            }
            s.avail_out = (unsigned int)(place < tranche ? place : tranche);
            r = mz_deflate(&s, vidage);
            if (r != MZ_OK && r != MZ_STREAM_END && r != MZ_BUF_ERROR)
            {
                mz_deflateEnd(&s);
                return 0;
            }
        } while (r != MZ_STREAM_END && (s.avail_in != 0 || s.avail_out == 0 || vidage == MZ_FINISH));
        pos += prendre;
        if (r == MZ_STREAM_END)
            break;
    }
    {
        size_t total = s.total_out;
        mz_deflateEnd(&s);
        return total;
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *donnees, size_t taille)
{
    static const int strategies[5] = { MZ_DEFAULT_STRATEGY, MZ_FILTERED, MZ_HUFFMAN_ONLY, MZ_RLE, MZ_FIXED };
    static const size_t morceaux[8] = { 1, 2, 5, 16, 100, 1000, 4096, 65536 };
    int niveau, strategie, avec_vidage;
    size_t morceau, n, capacite_flux;
    mz_ulong borne, nc;
    unsigned char *c, *flux, *tampon;
    const uint8_t *d;

    if (taille < 3)
        return 0;
    niveau = donnees[0] % 11;
    strategie = strategies[(donnees[1] & 0x7f) % 5];
    avec_vidage = (donnees[1] & 0x80) != 0;
    morceau = morceaux[donnees[2] & 7];
    d = donnees + 3;
    n = taille - 3;
    if (n > LIMITE_ENTREE)
        n = LIMITE_ENTREE;

    borne = mz_compressBound((mz_ulong)n);
    c = (unsigned char *)malloc(borne);
    /* Chaque MZ_SYNC_FLUSH ajoute un bloc vide de 5 octets environ (et un bloc brut si nécessaire) : avec des
       vidages fréquents, la sortie dépasse légitimement mz_compressBound (zlib aussi). On prévoit 16 octets
       par vidage, en plus de la borne. */
    capacite_flux = borne + 64 + (avec_vidage ? 16 * (n / morceau + 1) : 0);
    flux = (unsigned char *)malloc(capacite_flux);
    tampon = (unsigned char *)malloc(n + 1);
    if (!c || !flux || !tampon)
        abort();

    /* 1. Compression en une fois (niveau et stratégie de l'entrée). */
    {
        mz_stream s;
        int r;
        memset(&s, 0, sizeof(s));
        if (mz_deflateInit2(&s, niveau, MZ_DEFLATED, MZ_DEFAULT_WINDOW_BITS, 9, strategie) != MZ_OK)
            ecart("mz_deflateInit2 refuse des paramètres valides", niveau, strategie, n);
        s.next_in = d;
        s.avail_in = (unsigned int)n;
        s.next_out = c;
        s.avail_out = (unsigned int)borne;
        r = mz_deflate(&s, MZ_FINISH);
        nc = s.total_out;
        mz_deflateEnd(&s);
        if (r != MZ_STREAM_END)
            ecart("mz_deflate(MZ_FINISH) n'aboutit pas avec un tampon de mz_compressBound octets", niveau, strategie, n);
        if (nc > borne)
            ecart("la sortie dépasse mz_compressBound", niveau, strategie, n);
    }
    verifier_avec_zlib(c, nc, d, n, tampon, "une fois", niveau, strategie);

    /* 2 et 3. Compression en flux. */
    {
        size_t nf = compresser_flux(d, n, niveau, strategie, morceau, avec_vidage, flux, capacite_flux);
        if (nf == 0)
            ecart("la compression en flux échoue", niveau, strategie, n);
        verifier_avec_zlib(flux, nf, d, n, tampon, avec_vidage ? "flux avec MZ_SYNC_FLUSH" : "flux", niveau, strategie);
        if (!avec_vidage && (nf != nc || memcmp(flux, c, nc) != 0))
            ecart("la sortie en flux diffère de la sortie en une fois", niveau, strategie, n);
    }

    free(c);
    free(flux);
    free(tampon);
    return 0;
}
