/* Harnais de miniz-0029 : statistiques LZ de miniz sur le corpus, avec les copies instrumentées de
   miniz_tdef.c et miniz_tinfl.c (stats_lz.py les produit et compile ce harnais avec elles).

   Pour chaque fichier du corpus (--prefixe N : ses N premiers octets) et chaque niveau demandé :
     - remet les compteurs de tdefl à zéro, compresse avec mz_compress2, écrit une ligne JSON avec la
       taille, la SHA-256 de la sortie et les compteurs ;
     - au niveau 6, décompresse cette sortie avec mz_uncompress (flux « miniz6 », celui du banc), puis le
       flux de zlib niveau 6 (compress2 de la libz.a liée, flux « zlib6 », comme le scénario de
       décompression du juge commun), vérifie chaque fois l'original, et écrit les compteurs de tinfl.
   --ecrire-zlib6 DOSSIER : écrit seulement les flux zlib niveau 6 (DOSSIER/<i>.z, dans l'ordre du
   corpus) et s'arrête.

   Usage : stats_lz --corpus DOSSIER [--prefixe N] [--niveaux 1,6,9] [--ecrire-zlib6 DOSSIER] */
#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES
#include "miniz.h"

#include <zlib.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "corpus.h"
#include "sha256.h"
#include "stats_lz.h"

m29_tdefl m29_d;
m29_tinfl m29_i;

static void tableau(const char *cle, const m29_u64 *t, size_t n, int virgule)
{
    size_t fin = n, i;
    while (fin > 0 && t[fin - 1] == 0)
        fin--;
    printf("\"%s\": [", cle);
    for (i = 0; i < fin; i++)
        printf("%s%llu", i ? ", " : "", t[i]);
    printf("]%s", virgule ? ", " : "");
}

#define N(x) printf("\"" #x "\": %llu, ", s->x)

static void ecrire_tdefl(const m29_tdefl *s)
{
    printf("\"d\": {");
    N(appels); N(appels_paresseux); N(appels_budget_long); N(sondes); N(candidats); N(comparaisons);
    N(comparaisons_vaines); N(octets_compares); N(ameliorations); N(trouvees); N(rejet_len3_loin); N(rejet_pos);
    N(sondes_rejet_len3_loin); N(sondes_trouvees); N(sondes_sans_resultat); N(len3_trouvees); N(litteraux);
    N(correspondances); N(octets_correspondances); N(somme_distances); N(chevauchantes); N(dist1); N(dist_moins_de_8);
    tableau("sorties", s->sorties, M29_NB_SORTIES, 1);
    tableau("hist_sondes", s->hist_sondes, M29_SONDES_MAX + 1, 1);
    tableau("hist_prof", s->hist_prof, M29_SONDES_MAX + 1, 1);
    tableau("hist_len_trouvee", s->hist_len_trouvee, 259, 1);
    tableau("hist_dcode_len3", s->hist_dcode_len3, 30, 1);
    tableau("hist_len", s->hist_len, 259, 1);
    tableau("hist_dcode", s->hist_dcode, 30, 0);
    printf("}");
}

static void ecrire_tinfl(const m29_tinfl *s)
{
    printf("\"i\": {");
    N(tours_rapides); N(litteraux_rapides); N(litteraux_lents); N(arbre_litt); N(correspondances);
    N(octets_correspondances); N(somme_distances); N(copie_lente); N(copie_large_4_8); N(copie_large_9_plus); N(copie_octets_len3);
    N(copie_octets_chevauchee); N(copie_octets_dist1); N(copie_octets_dist_2_7); N(octets_copie_octets);
    tableau("blocs", s->blocs, 4, 1);
    tableau("hist_len", s->hist_len, 259, 1);
    tableau("hist_dcode", s->hist_dcode, 30, 0);
    printf("}");
}

static void decompresser(const char *nom, const char *flux, const unsigned char *z, size_t nz,
                         const unsigned char *original, size_t taille, unsigned char *tampon)
{
    mz_ulong n = (mz_ulong)taille;
    memset(&m29_i, 0, sizeof(m29_i));
    if (mz_uncompress(tampon, &n, z, (mz_ulong)nz) != MZ_OK || n != taille || memcmp(tampon, original, taille))
    {
        fprintf(stderr, "stats_lz : décompression du flux %s de %s fausse\n", flux, nom);
        exit(1);
    }
    printf("{\"fichier\": \"%s\", \"flux\": \"%s\", \"taille\": %zu, \"compresse\": %zu, ", nom, flux, taille, nz);
    ecrire_tinfl(&m29_i);
    printf("}\n");
}

int main(int argc, char **argv)
{
    const char *dossier = NULL, *dossier_zlib = NULL, *niveaux = "1,6,9";
    long prefixe = -1;
    bee_corpus c;
    size_t i;
    int a;
    for (a = 1; a < argc; a++)
    {
        if (!strcmp(argv[a], "--corpus") && a + 1 < argc)
            dossier = argv[++a];
        else if (!strcmp(argv[a], "--prefixe") && a + 1 < argc)
            prefixe = atol(argv[++a]);
        else if (!strcmp(argv[a], "--niveaux") && a + 1 < argc)
            niveaux = argv[++a];
        else if (!strcmp(argv[a], "--ecrire-zlib6") && a + 1 < argc)
            dossier_zlib = argv[++a];
        else
        {
            fprintf(stderr, "usage : stats_lz --corpus DOSSIER [--prefixe N] [--niveaux 1,6,9] [--ecrire-zlib6 DOSSIER]\n");
            return 2;
        }
    }
    if (!dossier || bee_corpus_charger(dossier, &c) != 0)
        return 2;
    for (i = 0; i < c.nombre; i++)
    {
        bee_fichier *f = &c.fichiers[i];
        size_t taille = (prefixe >= 0 && f->taille > (size_t)prefixe) ? (size_t)prefixe : f->taille;
        mz_ulong borne = mz_compressBound((mz_ulong)taille);
        uLongf zborne = compressBound((uLong)taille);
        unsigned char *sortie = (unsigned char *)malloc(borne), *zsortie = (unsigned char *)malloc(zborne);
        unsigned char *tampon = (unsigned char *)malloc(taille ? taille : 1);
        const char *p;
        if (!sortie || !zsortie || !tampon)
            return 2;
        if (compress2(zsortie, &zborne, f->donnees, (uLong)taille, 6) != Z_OK)
            return 2;
        if (dossier_zlib)
        {
            char chemin[4096];
            FILE *g;
            snprintf(chemin, sizeof(chemin), "%s/%zu.z", dossier_zlib, i);
            g = fopen(chemin, "wb");
            if (!g || fwrite(zsortie, 1, zborne, g) != zborne || fclose(g))
                return 2;
            printf("z %zu %zu %s\n", i, taille, f->nom);
            free(sortie), free(zsortie), free(tampon);
            continue;
        }
        for (p = niveaux; *p; p++)
        {
            int niveau;
            mz_ulong n = borne;
            char hex[65];
            if (*p < '0' || *p > '9')
                continue;
            niveau = *p - '0';
            memset(&m29_d, 0, sizeof(m29_d));
            if (mz_compress2(sortie, &n, f->donnees, (mz_ulong)taille, niveau) != MZ_OK)
            {
                fprintf(stderr, "stats_lz : mz_compress2 a échoué (%s, niveau %d)\n", f->nom, niveau);
                return 1;
            }
            bee_sha256_hex(sortie, n, hex);
            printf("{\"fichier\": \"%s\", \"niveau\": %d, \"taille\": %zu, \"compresse\": %lu, \"sha256\": \"%s\", ",
                   f->nom, niveau, taille, (unsigned long)n, hex);
            ecrire_tdefl(&m29_d);
            printf("}\n");
            if (niveau == 6)
            {
                decompresser(f->nom, "miniz6", sortie, n, f->donnees, taille, tampon);
                decompresser(f->nom, "zlib6", zsortie, zborne, f->donnees, taille, tampon);
            }
        }
        free(sortie), free(zsortie), free(tampon);
    }
    bee_corpus_liberer(&c);
    return 0;
}
