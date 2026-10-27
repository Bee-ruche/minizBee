/* Harnais de fuzzing Bee (a) : inflate différentiel, miniz contre zlib.

   L'entrée arbitraire est décompressée trois fois :
     - miniz, en une fois (mz_uncompress2, flux zlib) ;
     - miniz, en flux (mz_inflate, tampons d'entrée et de sortie de 1 à 4096 octets, taille tirée de l'entrée) ;
     - zlib (inflate, flux zlib).
   Le premier octet choisit le format : pair = flux zlib (en-tête et Adler-32), impair = Deflate brut
   (window_bits = -15) ; le second octet choisit la taille des tampons du mode flux ; le reste est la donnée.

   Ce qui est vérifié :
     1. quand miniz (en une fois) ET zlib réussissent, leurs sorties sont identiques octet pour octet ;
     2. quand miniz en une fois ET miniz en flux réussissent, leurs sorties sont identiques ;
     3. aucune erreur mémoire ni comportement indéfini (ASan, UBSan).

   Écarts tolérés (non signalés) : seuls les statuts peuvent différer, jamais une sortie réussie.
     - sur une entrée invalide, l'un peut réussir et l'autre échouer : miniz et zlib, ou miniz en une
       fois et miniz en flux, n'ont pas toujours le même statut. Le harnais ne compare donc les sorties
       que lorsque les deux décompressions comparées ont réussi ;
     - données après la fin du flux : ignorées des deux côtés ;
     - sortie plus grande que la limite (1 Mio) : le cas est écarté. */

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <zlib.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMITE_SORTIE (1u << 20)

static unsigned char sortie_miniz[LIMITE_SORTIE + 1], sortie_flux[LIMITE_SORTIE + 1], sortie_zlib[LIMITE_SORTIE + 1];

static void ecart(const char *quoi, size_t a, size_t b)
{
    fprintf(stderr, "fuzz_inflate : ÉCART %s (%zu / %zu octets)\n", quoi, a, b);
    abort();
}

/* Renvoie 1 et la taille si la décompression réussit et tient dans la limite, 0 sinon. */
static int inflate_miniz_une_fois(const uint8_t *d, size_t n, int brut, size_t *taille)
{
    mz_stream s;
    int r;
    memset(&s, 0, sizeof(s));
    if (mz_inflateInit2(&s, brut ? -MZ_DEFAULT_WINDOW_BITS : MZ_DEFAULT_WINDOW_BITS) != MZ_OK)
        return 0;
    s.next_in = d;
    s.avail_in = (unsigned int)n;
    s.next_out = sortie_miniz;
    s.avail_out = LIMITE_SORTIE + 1;
    r = mz_inflate(&s, MZ_FINISH);
    *taille = s.total_out;
    mz_inflateEnd(&s);
    return r == MZ_STREAM_END && *taille <= LIMITE_SORTIE;
}

static int inflate_miniz_flux(const uint8_t *d, size_t n, int brut, size_t morceau, size_t *taille)
{
    mz_stream s;
    size_t pos = 0, produit = 0;
    int r = MZ_OK, sans_progres = 0;
    memset(&s, 0, sizeof(s));
    if (mz_inflateInit2(&s, brut ? -MZ_DEFAULT_WINDOW_BITS : MZ_DEFAULT_WINDOW_BITS) != MZ_OK)
        return 0;
    for (;;)
    {
        unsigned int avant;
        size_t place = LIMITE_SORTIE + 1 - produit;
        if (s.avail_in == 0 && pos < n)
        {
            size_t prendre = n - pos < morceau ? n - pos : morceau;
            s.next_in = d + pos;
            s.avail_in = (unsigned int)prendre;
            pos += prendre;
        }
        if (place == 0)
            break;
        avant = s.avail_in;
        s.next_out = sortie_flux + produit;
        s.avail_out = (unsigned int)(place < morceau ? place : morceau);
        {
            unsigned int sortie_avant = s.avail_out;
            r = mz_inflate(&s, MZ_NO_FLUSH);
            produit += sortie_avant - s.avail_out;
            if (r == MZ_STREAM_END || (r != MZ_OK && r != MZ_BUF_ERROR))
                break;
            if (s.avail_in == avant && s.avail_out == sortie_avant)
            {
                if (pos >= n || ++sans_progres > 100)
                    break;
            }
            else
                sans_progres = 0;
        }
    }
    *taille = produit;
    mz_inflateEnd(&s);
    return r == MZ_STREAM_END && produit <= LIMITE_SORTIE;
}

static int inflate_zlib(const uint8_t *d, size_t n, int brut, size_t *taille)
{
    z_stream s;
    int r;
    memset(&s, 0, sizeof(s));
    if (inflateInit2(&s, brut ? -MAX_WBITS : MAX_WBITS) != Z_OK)
        return 0;
    s.next_in = (Bytef *)d;
    s.avail_in = (uInt)n;
    s.next_out = sortie_zlib;
    s.avail_out = LIMITE_SORTIE + 1;
    r = inflate(&s, Z_FINISH);
    *taille = s.total_out;
    inflateEnd(&s);
    return r == Z_STREAM_END && *taille <= LIMITE_SORTIE;
}

int LLVMFuzzerTestOneInput(const uint8_t *donnees, size_t taille)
{
    static const size_t morceaux[8] = { 1, 2, 3, 7, 64, 255, 1024, 4096 };
    size_t t_une, t_flux, t_zlib;
    int brut, ok_une, ok_flux, ok_zlib;
    size_t morceau;
    if (taille < 2)
        return 0;
    brut = donnees[0] & 1;
    morceau = morceaux[donnees[1] & 7];
    donnees += 2;
    taille -= 2;

    ok_une = inflate_miniz_une_fois(donnees, taille, brut, &t_une);
    ok_flux = inflate_miniz_flux(donnees, taille, brut, morceau, &t_flux);
    ok_zlib = inflate_zlib(donnees, taille, brut, &t_zlib);

    if (ok_une && ok_flux && (t_une != t_flux || memcmp(sortie_miniz, sortie_flux, t_une) != 0))
        ecart("miniz en une fois et miniz en flux produisent des sorties différentes", t_une, t_flux);
    if (ok_une && ok_zlib && (t_une != t_zlib || memcmp(sortie_miniz, sortie_zlib, t_une) != 0))
        ecart("miniz et zlib réussissent tous deux mais produisent des sorties différentes", t_une, t_zlib);
    return 0;
}
