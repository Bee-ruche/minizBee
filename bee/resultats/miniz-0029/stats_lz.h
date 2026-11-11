/* Compteurs de miniz-0029, inclus par les copies instrumentées de miniz_tdef.c et miniz_tinfl.c que
   produit stats_lz.py (dans bee/construction/miniz-0029/instr/, jamais versionnées). miniz lui-même
   n'est pas modifié. Les compteurs ne lisent que des variables locales de miniz, n'écrivent que dans
   ces deux structures et ne changent aucun flot de contrôle : stats_lz.py vérifie que les sorties
   compressées restent identiques aux empreintes de référence. */
#ifndef BEE_M29_STATS_LZ_H
#define BEE_M29_STATS_LZ_H

typedef unsigned long long m29_u64;

#define M29_SONDES_MAX 1023 /* au-delà, histogramme saturé (niveau 9 : au plus 3 x 171 = 513 sondes) */

enum
{
    M29_IMMEDIATE,    /* max_match_len <= match_len : aucune sonde */
    M29_BUDGET,       /* --num_probes_left == 0 */
    M29_FIN_CHAINE,   /* m_next nul */
    M29_TROP_LOIN,    /* distance > max_dist */
    M29_DIST_NULLE,   /* la chaîne revient à la position courante */
    M29_LONGUEUR_MAX, /* correspondance de longueur max_match_len trouvée */
    M29_NB_SORTIES
};

typedef struct
{
    /* tdefl_find_match */
    m29_u64 appels, appels_paresseux, appels_budget_long;
    m29_u64 sondes, candidats, comparaisons, comparaisons_vaines, octets_compares, ameliorations;
    m29_u64 sorties[M29_NB_SORTIES];
    m29_u64 hist_sondes[M29_SONDES_MAX + 1]; /* sondes par appel */
    m29_u64 hist_prof[M29_SONDES_MAX + 1];   /* rang de la sonde qui a donné le résultat (0 : aucun) */
    unsigned cur_sondes, cur_prof, dernieres_sondes;
    /* résultat de tdefl_find_match, vu par tdefl_compress_normal avant le rejet de la l. 1285 */
    m29_u64 trouvees, rejet_len3_loin, rejet_pos, sondes_rejet_len3_loin, sondes_trouvees, sondes_sans_resultat;
    m29_u64 len3_trouvees, hist_len_trouvee[259], hist_dcode_len3[30];
    /* symboles émis (tdefl_record_literal, tdefl_record_match) */
    m29_u64 litteraux, correspondances, octets_correspondances, somme_distances, chevauchantes, dist1, dist_moins_de_8;
    m29_u64 hist_len[259], hist_dcode[30];
} m29_tdefl;

typedef struct
{
    m29_u64 blocs[4]; /* stockés, fixes, dynamiques, invalides */
    m29_u64 tours_rapides, litteraux_rapides, litteraux_lents, arbre_litt;
    m29_u64 correspondances, octets_correspondances, somme_distances, hist_len[259], hist_dcode[30];
    m29_u64 copie_lente, copie_large_4_8, copie_large_9_plus;
    m29_u64 copie_octets_len3, copie_octets_chevauchee, copie_octets_dist1, copie_octets_dist_2_7, octets_copie_octets;
} m29_tinfl;

extern m29_tdefl m29_d;
extern m29_tinfl m29_i;

/* Code de distance Deflate (0 à 29) d'une distance de 1 à 32768. */
static unsigned m29_dcode(unsigned dist)
{
    unsigned x = dist - 1, n = 0;
    if (x < 4)
        return x;
    while ((x >> n) > 1)
        n++;
    return 2 * n + ((x >> (n - 1)) & 1);
}

#define M29_ENTREE(match_len)                         \
    do                                                \
    {                                                 \
        m29_d.appels++;                               \
        m29_d.appels_paresseux += ((match_len) >= 3); \
        m29_d.appels_budget_long += ((match_len) >= 32); \
        m29_d.cur_sondes = 0;                         \
        m29_d.cur_prof = 0;                           \
    } while (0)

#define M29_SORTIE(raison)                                                                                         \
    do                                                                                                             \
    {                                                                                                              \
        m29_d.sorties[raison]++;                                                                                   \
        m29_d.sondes += m29_d.cur_sondes;                                                                          \
        m29_d.hist_sondes[m29_d.cur_sondes < M29_SONDES_MAX ? m29_d.cur_sondes : M29_SONDES_MAX]++;                \
        m29_d.hist_prof[m29_d.cur_prof < M29_SONDES_MAX ? m29_d.cur_prof : M29_SONDES_MAX]++;                      \
        m29_d.dernieres_sondes = m29_d.cur_sondes;                                                                 \
    } while (0)

static void m29_resultat(unsigned len, unsigned dist, unsigned cur_pos)
{
    if (!dist)
    {
        m29_d.sondes_sans_resultat += m29_d.dernieres_sondes;
        return;
    }
    m29_d.trouvees++;
    m29_d.sondes_trouvees += m29_d.dernieres_sondes;
    m29_d.hist_len_trouvee[len < 258 ? len : 258]++;
    if (len == 3)
    {
        m29_d.len3_trouvees++;
        m29_d.hist_dcode_len3[m29_dcode(dist)]++;
        if (dist >= 8U * 1024U)
        {
            m29_d.rejet_len3_loin++;
            m29_d.sondes_rejet_len3_loin += m29_d.dernieres_sondes;
        }
    }
    if (cur_pos == dist)
        m29_d.rejet_pos++;
}

static void m29_correspondance_d(unsigned len, unsigned dist)
{
    m29_d.correspondances++;
    m29_d.octets_correspondances += len;
    m29_d.somme_distances += dist;
    m29_d.hist_len[len < 258 ? len : 258]++;
    m29_d.hist_dcode[m29_dcode(dist)]++;
    m29_d.chevauchantes += (dist < len);
    m29_d.dist1 += (dist == 1);
    m29_d.dist_moins_de_8 += (dist < 8);
}

static void m29_correspondance_i(unsigned len, unsigned dist)
{
    m29_i.correspondances++;
    m29_i.octets_correspondances += len;
    m29_i.somme_distances += dist;
    m29_i.hist_len[len < 258 ? len : 258]++;
    if (dist >= 1 && dist <= 32768)
        m29_i.hist_dcode[m29_dcode(dist)]++;
}

static void m29_copie_octets(unsigned len, unsigned dist)
{
    m29_i.octets_copie_octets += len;
    if (len < 4)
        m29_i.copie_octets_len3++;
    else
    {
        m29_i.copie_octets_chevauchee++;
        if (dist == 1)
            m29_i.copie_octets_dist1++;
        else if (dist < 8)
            m29_i.copie_octets_dist_2_7++;
    }
}

#endif
