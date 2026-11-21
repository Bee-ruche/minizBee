/**************************************************************************
 *
 * Copyright 2013-2014 RAD Game Tools and Valve Software
 * Copyright 2010-2014 Rich Geldreich and Tenacious Software LLC
 * All Rights Reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 **************************************************************************/

#include "miniz.h"

/* Sortie des bits par mots de 64 bits pour tdefl_compress_lz_codes (tâche miniz-0011). Elle accumule
   les codes de Huffman dans un registre 64 bits et écrit 8 octets d'un coup par memcpy (aucun
   transtypage de pointeur, donc aucun comportement indéfini ni violation d'alias strict ; seuls
   bits_in >> 3 octets sont réellement avancés, les octets en trop tombent dans la marge de 16 octets
   de m_pOutput_buf_end). On la compile dès que la plateforme est petit-boutiste avec des registres
   64 bits rapides, indépendamment de MINIZ_USE_UNALIGNED_LOADS_AND_STORES (qui, lui, concerne aussi
   la décompression, hors périmètre de cette tâche). La variante générique, gros-boutiste et 32 bits,
   reste le repli et peut être forcée avec -DTDEFL_USE_64BIT_BITBUF=0. La sortie compressée est
   strictement identique à celle de la variante générique (vérifié par les tests différentiels). */
#if !defined(TDEFL_USE_64BIT_BITBUF)
#if MINIZ_LITTLE_ENDIAN && MINIZ_HAS_64BIT_REGISTERS
#define TDEFL_USE_64BIT_BITBUF 1
#else
#define TDEFL_USE_64BIT_BITBUF 0
#endif
#endif

/* Comparaison des correspondances par mots de 64 bits dans tdefl_find_match (tâche miniz-0015).
   Sur plateforme petit-boutiste à registres 64 bits : XOR de 8 octets lus par memcpy (aucun
   transtypage de pointeur), puis position du premier octet différent par __builtin_ctzll. La boucle
   de mots ne s'exécute que tant qu'il reste au moins 8 octets sous le plafond max_match_len, et la
   fin se fait octet par octet : elle calcule donc EXACTEMENT la même longueur que la comparaison
   octet par octet (mêmes correspondances choisies, sortie compressée identique) et ne lit jamais
   au-delà de max_match_len octets, donc jamais au-delà du dictionnaire. Repli octet par octet sinon.
   Indépendant de MINIZ_USE_UNALIGNED_LOADS_AND_STORES ; peut être forcé avec -DTDEFL_FIND_MATCH_64BIT=0. */
#if !defined(TDEFL_FIND_MATCH_64BIT)
#if MINIZ_LITTLE_ENDIAN && MINIZ_HAS_64BIT_REGISTERS && (defined(__GNUC__) || defined(__clang__))
#define TDEFL_FIND_MATCH_64BIT 1
#else
#define TDEFL_FIND_MATCH_64BIT 0
#endif
#endif

#ifndef MINIZ_NO_DEFLATE_APIS

#ifdef __cplusplus
extern "C"
{
#endif /* __cplusplus */

    /* ------------------- Low-level Compression (independent from all decompression API's) */

    /* Purposely making these tables static for faster init and thread safety. */
    static const mz_uint16 s_tdefl_len_sym[256] = {
        257, 258, 259, 260, 261, 262, 263, 264, 265, 265, 266, 266, 267, 267, 268, 268, 269, 269, 269, 269, 270, 270, 270, 270, 271, 271, 271, 271, 272, 272, 272, 272,
        273, 273, 273, 273, 273, 273, 273, 273, 274, 274, 274, 274, 274, 274, 274, 274, 275, 275, 275, 275, 275, 275, 275, 275, 276, 276, 276, 276, 276, 276, 276, 276,
        277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 277, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278, 278,
        279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 279, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280,
        281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281, 281,
        282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282, 282,
        283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283, 283,
        284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 284, 285
    };

    static const mz_uint8 s_tdefl_len_extra[256] = {
        0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
        4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 0
    };

    static const mz_uint8 s_tdefl_small_dist_sym[512] = {
        0, 1, 2, 3, 4, 4, 5, 5, 6, 6, 6, 6, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9, 9, 9, 9, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11,
        11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 13,
        13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14,
        14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14,
        14, 14, 14, 14, 14, 14, 14, 14, 14, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15,
        15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16,
        16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16,
        16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16,
        16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17,
        17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17,
        17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17,
        17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17
    };

    static const mz_uint8 s_tdefl_small_dist_extra[512] = {
        0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7
    };

    static const mz_uint8 s_tdefl_large_dist_sym[128] = {
        0, 0, 18, 19, 20, 20, 21, 21, 22, 22, 22, 22, 23, 23, 23, 23, 24, 24, 24, 24, 24, 24, 24, 24, 25, 25, 25, 25, 25, 25, 25, 25, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26,
        26, 26, 26, 26, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
        28, 28, 28, 28, 28, 28, 28, 28, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29
    };

    static const mz_uint8 s_tdefl_large_dist_extra[128] = {
        0, 0, 8, 8, 9, 9, 9, 9, 10, 10, 10, 10, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
        12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13,
        13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13
    };

    /* Radix sorts tdefl_sym_freq[] array by 16-bit key m_key. Returns ptr to sorted values. */
    typedef struct
    {
        mz_uint16 m_key, m_sym_index;
    } tdefl_sym_freq;
    static tdefl_sym_freq *tdefl_radix_sort_syms(mz_uint num_syms, tdefl_sym_freq *pSyms0, tdefl_sym_freq *pSyms1)
    {
        mz_uint32 total_passes = 2, pass_shift, pass, i, hist[256 * 2];
        tdefl_sym_freq *pCur_syms = pSyms0, *pNew_syms = pSyms1;
        MZ_CLEAR_ARR(hist);
        for (i = 0; i < num_syms; i++)
        {
            mz_uint freq = pSyms0[i].m_key;
            hist[freq & 0xFF]++;
            hist[256 + ((freq >> 8) & 0xFF)]++;
        }
        while ((total_passes > 1) && (num_syms == hist[(total_passes - 1) * 256]))
            total_passes--;
        for (pass_shift = 0, pass = 0; pass < total_passes; pass++, pass_shift += 8)
        {
            const mz_uint32 *pHist = &hist[pass << 8];
            mz_uint offsets[256], cur_ofs = 0;
            for (i = 0; i < 256; i++)
            {
                offsets[i] = cur_ofs;
                cur_ofs += pHist[i];
            }
            for (i = 0; i < num_syms; i++)
                pNew_syms[offsets[(pCur_syms[i].m_key >> pass_shift) & 0xFF]++] = pCur_syms[i];
            {
                tdefl_sym_freq *t = pCur_syms;
                pCur_syms = pNew_syms;
                pNew_syms = t;
            }
        }
        return pCur_syms;
    }

    /* tdefl_calculate_minimum_redundancy() originally written by: Alistair Moffat, alistair@cs.mu.oz.au, Jyrki Katajainen, jyrki@diku.dk, November 1996. */
    static void tdefl_calculate_minimum_redundancy(tdefl_sym_freq *A, int n)
    {
        int root, leaf, next, avbl, used, dpth;
        if (n == 0)
            return;
        else if (n == 1)
        {
            A[0].m_key = 1;
            return;
        }
        A[0].m_key += A[1].m_key;
        root = 0;
        leaf = 2;
        for (next = 1; next < n - 1; next++)
        {
            if (leaf >= n || A[root].m_key < A[leaf].m_key)
            {
                A[next].m_key = A[root].m_key;
                A[root++].m_key = (mz_uint16)next;
            }
            else
                A[next].m_key = A[leaf++].m_key;
            if (leaf >= n || (root < next && A[root].m_key < A[leaf].m_key))
            {
                A[next].m_key = (mz_uint16)(A[next].m_key + A[root].m_key);
                A[root++].m_key = (mz_uint16)next;
            }
            else
                A[next].m_key = (mz_uint16)(A[next].m_key + A[leaf++].m_key);
        }
        A[n - 2].m_key = 0;
        for (next = n - 3; next >= 0; next--)
            A[next].m_key = A[A[next].m_key].m_key + 1;
        avbl = 1;
        used = dpth = 0;
        root = n - 2;
        next = n - 1;
        while (avbl > 0)
        {
            while (root >= 0 && (int)A[root].m_key == dpth)
            {
                used++;
                root--;
            }
            while (avbl > used)
            {
                A[next--].m_key = (mz_uint16)(dpth);
                avbl--;
            }
            avbl = 2 * used;
            dpth++;
            used = 0;
        }
    }

    /* Limits canonical Huffman code table's max code size. */
    enum
    {
        TDEFL_MAX_SUPPORTED_HUFF_CODESIZE = 32
    };
    static void tdefl_huffman_enforce_max_code_size(int *pNum_codes, int code_list_len, int max_code_size)
    {
        int i;
        mz_uint32 total = 0;
        if (code_list_len <= 1)
            return;
        for (i = max_code_size + 1; i <= TDEFL_MAX_SUPPORTED_HUFF_CODESIZE; i++)
            pNum_codes[max_code_size] += pNum_codes[i];
        for (i = max_code_size; i > 0; i--)
            total += (((mz_uint32)pNum_codes[i]) << (max_code_size - i));
        while (total != (1UL << max_code_size))
        {
            pNum_codes[max_code_size]--;
            for (i = max_code_size - 1; i > 0; i--)
                if (pNum_codes[i])
                {
                    pNum_codes[i]--;
                    pNum_codes[i + 1] += 2;
                    break;
                }
            total--;
        }
    }

    static void tdefl_optimize_huffman_table(tdefl_compressor *d, int table_num, int table_len, int code_size_limit, int static_table)
    {
        int i, j, l, num_codes[1 + TDEFL_MAX_SUPPORTED_HUFF_CODESIZE];
        mz_uint next_code[TDEFL_MAX_SUPPORTED_HUFF_CODESIZE + 1];
        MZ_CLEAR_ARR(num_codes);
        if (static_table)
        {
            for (i = 0; i < table_len; i++)
                num_codes[d->m_huff_code_sizes[table_num][i]]++;
        }
        else
        {
            tdefl_sym_freq syms0[TDEFL_MAX_HUFF_SYMBOLS], syms1[TDEFL_MAX_HUFF_SYMBOLS], *pSyms;
            int num_used_syms = 0;
            const mz_uint16 *pSym_count = &d->m_huff_count[table_num][0];
            for (i = 0; i < table_len; i++)
                if (pSym_count[i])
                {
                    syms0[num_used_syms].m_key = (mz_uint16)pSym_count[i];
                    syms0[num_used_syms++].m_sym_index = (mz_uint16)i;
                }

            pSyms = tdefl_radix_sort_syms(num_used_syms, syms0, syms1);
            tdefl_calculate_minimum_redundancy(pSyms, num_used_syms);

            for (i = 0; i < num_used_syms; i++)
                num_codes[pSyms[i].m_key]++;

            tdefl_huffman_enforce_max_code_size(num_codes, num_used_syms, code_size_limit);

            MZ_CLEAR_ARR(d->m_huff_code_sizes[table_num]);
            MZ_CLEAR_ARR(d->m_huff_codes[table_num]);
            for (i = 1, j = num_used_syms; i <= code_size_limit; i++)
                for (l = num_codes[i]; l > 0; l--)
                    d->m_huff_code_sizes[table_num][pSyms[--j].m_sym_index] = (mz_uint8)(i);
        }

        next_code[1] = 0;
        for (j = 0, i = 2; i <= code_size_limit; i++)
            next_code[i] = j = ((j + num_codes[i - 1]) << 1);

        for (i = 0; i < table_len; i++)
        {
            mz_uint rev_code = 0, code, code_size;
            if ((code_size = d->m_huff_code_sizes[table_num][i]) == 0)
                continue;
            code = next_code[code_size]++;
            for (l = code_size; l > 0; l--, code >>= 1)
                rev_code = (rev_code << 1) | (code & 1);
            d->m_huff_codes[table_num][i] = (mz_uint16)rev_code;
        }
    }

#define TDEFL_PUT_BITS(b, l)                                       \
    do                                                             \
    {                                                              \
        mz_uint bits = b;                                          \
        mz_uint len = l;                                           \
        MZ_ASSERT(bits <= ((1U << len) - 1U));                     \
        d->m_bit_buffer |= (bits << d->m_bits_in);                 \
        d->m_bits_in += len;                                       \
        while (d->m_bits_in >= 8)                                  \
        {                                                          \
            if (d->m_pOutput_buf < d->m_pOutput_buf_end)           \
                *d->m_pOutput_buf++ = (mz_uint8)(d->m_bit_buffer); \
            d->m_bit_buffer >>= 8;                                 \
            d->m_bits_in -= 8;                                     \
        }                                                          \
    }                                                              \
    MZ_MACRO_END

#define TDEFL_RLE_PREV_CODE_SIZE()                                                                                       \
    {                                                                                                                    \
        if (rle_repeat_count)                                                                                            \
        {                                                                                                                \
            if (rle_repeat_count < 3)                                                                                    \
            {                                                                                                            \
                d->m_huff_count[2][prev_code_size] = (mz_uint16)(d->m_huff_count[2][prev_code_size] + rle_repeat_count); \
                while (rle_repeat_count--)                                                                               \
                    packed_code_sizes[num_packed_code_sizes++] = prev_code_size;                                         \
            }                                                                                                            \
            else                                                                                                         \
            {                                                                                                            \
                d->m_huff_count[2][16] = (mz_uint16)(d->m_huff_count[2][16] + 1);                                        \
                packed_code_sizes[num_packed_code_sizes++] = 16;                                                         \
                packed_code_sizes[num_packed_code_sizes++] = (mz_uint8)(rle_repeat_count - 3);                           \
            }                                                                                                            \
            rle_repeat_count = 0;                                                                                        \
        }                                                                                                                \
    }

#define TDEFL_RLE_ZERO_CODE_SIZE()                                                         \
    {                                                                                      \
        if (rle_z_count)                                                                   \
        {                                                                                  \
            if (rle_z_count < 3)                                                           \
            {                                                                              \
                d->m_huff_count[2][0] = (mz_uint16)(d->m_huff_count[2][0] + rle_z_count);  \
                while (rle_z_count--)                                                      \
                    packed_code_sizes[num_packed_code_sizes++] = 0;                        \
            }                                                                              \
            else if (rle_z_count <= 10)                                                    \
            {                                                                              \
                d->m_huff_count[2][17] = (mz_uint16)(d->m_huff_count[2][17] + 1);          \
                packed_code_sizes[num_packed_code_sizes++] = 17;                           \
                packed_code_sizes[num_packed_code_sizes++] = (mz_uint8)(rle_z_count - 3);  \
            }                                                                              \
            else                                                                           \
            {                                                                              \
                d->m_huff_count[2][18] = (mz_uint16)(d->m_huff_count[2][18] + 1);          \
                packed_code_sizes[num_packed_code_sizes++] = 18;                           \
                packed_code_sizes[num_packed_code_sizes++] = (mz_uint8)(rle_z_count - 11); \
            }                                                                              \
            rle_z_count = 0;                                                               \
        }                                                                                  \
    }

    static const mz_uint8 s_tdefl_packed_code_size_syms_swizzle[] = { 16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15 };

    static void tdefl_start_dynamic_block(tdefl_compressor *d)
    {
        int num_lit_codes, num_dist_codes, num_bit_lengths;
        mz_uint i, total_code_sizes_to_pack, num_packed_code_sizes, rle_z_count, rle_repeat_count, packed_code_sizes_index;
        mz_uint8 code_sizes_to_pack[TDEFL_MAX_HUFF_SYMBOLS_0 + TDEFL_MAX_HUFF_SYMBOLS_1], packed_code_sizes[TDEFL_MAX_HUFF_SYMBOLS_0 + TDEFL_MAX_HUFF_SYMBOLS_1], prev_code_size = 0xFF;

        d->m_huff_count[0][256] = 1;

        tdefl_optimize_huffman_table(d, 0, TDEFL_MAX_HUFF_SYMBOLS_0, 15, MZ_FALSE);
        tdefl_optimize_huffman_table(d, 1, TDEFL_MAX_HUFF_SYMBOLS_1, 15, MZ_FALSE);

        for (num_lit_codes = 286; num_lit_codes > 257; num_lit_codes--)
            if (d->m_huff_code_sizes[0][num_lit_codes - 1])
                break;
        for (num_dist_codes = 30; num_dist_codes > 1; num_dist_codes--)
            if (d->m_huff_code_sizes[1][num_dist_codes - 1])
                break;

        memcpy(code_sizes_to_pack, &d->m_huff_code_sizes[0][0], num_lit_codes);
        memcpy(code_sizes_to_pack + num_lit_codes, &d->m_huff_code_sizes[1][0], num_dist_codes);
        total_code_sizes_to_pack = num_lit_codes + num_dist_codes;
        num_packed_code_sizes = 0;
        rle_z_count = 0;
        rle_repeat_count = 0;

        memset(&d->m_huff_count[2][0], 0, sizeof(d->m_huff_count[2][0]) * TDEFL_MAX_HUFF_SYMBOLS_2);
        for (i = 0; i < total_code_sizes_to_pack; i++)
        {
            mz_uint8 code_size = code_sizes_to_pack[i];
            if (!code_size)
            {
                TDEFL_RLE_PREV_CODE_SIZE();
                if (++rle_z_count == 138)
                {
                    TDEFL_RLE_ZERO_CODE_SIZE();
                }
            }
            else
            {
                TDEFL_RLE_ZERO_CODE_SIZE();
                if (code_size != prev_code_size)
                {
                    TDEFL_RLE_PREV_CODE_SIZE();
                    d->m_huff_count[2][code_size] = (mz_uint16)(d->m_huff_count[2][code_size] + 1);
                    packed_code_sizes[num_packed_code_sizes++] = code_size;
                }
                else if (++rle_repeat_count == 6)
                {
                    TDEFL_RLE_PREV_CODE_SIZE();
                }
            }
            prev_code_size = code_size;
        }
        if (rle_repeat_count)
        {
            TDEFL_RLE_PREV_CODE_SIZE();
        }
        else
        {
            TDEFL_RLE_ZERO_CODE_SIZE();
        }

        tdefl_optimize_huffman_table(d, 2, TDEFL_MAX_HUFF_SYMBOLS_2, 7, MZ_FALSE);

        TDEFL_PUT_BITS(2, 2);

        TDEFL_PUT_BITS(num_lit_codes - 257, 5);
        TDEFL_PUT_BITS(num_dist_codes - 1, 5);

        for (num_bit_lengths = 18; num_bit_lengths >= 0; num_bit_lengths--)
            if (d->m_huff_code_sizes[2][s_tdefl_packed_code_size_syms_swizzle[num_bit_lengths]])
                break;
        num_bit_lengths = MZ_MAX(4, (num_bit_lengths + 1));
        TDEFL_PUT_BITS(num_bit_lengths - 4, 4);
        for (i = 0; (int)i < num_bit_lengths; i++)
            TDEFL_PUT_BITS(d->m_huff_code_sizes[2][s_tdefl_packed_code_size_syms_swizzle[i]], 3);

        for (packed_code_sizes_index = 0; packed_code_sizes_index < num_packed_code_sizes;)
        {
            mz_uint code = packed_code_sizes[packed_code_sizes_index++];
            MZ_ASSERT(code < TDEFL_MAX_HUFF_SYMBOLS_2);
            TDEFL_PUT_BITS(d->m_huff_codes[2][code], d->m_huff_code_sizes[2][code]);
            if (code >= 16)
                TDEFL_PUT_BITS(packed_code_sizes[packed_code_sizes_index++], "\02\03\07"[code - 16]);
        }
    }

    static void tdefl_start_static_block(tdefl_compressor *d)
    {
        mz_uint i;
        mz_uint8 *p = &d->m_huff_code_sizes[0][0];

        for (i = 0; i <= 143; ++i)
            *p++ = 8;
        for (; i <= 255; ++i)
            *p++ = 9;
        for (; i <= 279; ++i)
            *p++ = 7;
        for (; i <= 287; ++i)
            *p++ = 8;

        memset(d->m_huff_code_sizes[1], 5, 32);

        tdefl_optimize_huffman_table(d, 0, 288, 15, MZ_TRUE);
        tdefl_optimize_huffman_table(d, 1, 32, 15, MZ_TRUE);

        TDEFL_PUT_BITS(1, 2);
    }

    static const mz_uint mz_bitmasks[17] = { 0x0000, 0x0001, 0x0003, 0x0007, 0x000F, 0x001F, 0x003F, 0x007F, 0x00FF, 0x01FF, 0x03FF, 0x07FF, 0x0FFF, 0x1FFF, 0x3FFF, 0x7FFF, 0xFFFF };

#if TDEFL_USE_64BIT_BITBUF
    static mz_bool tdefl_compress_lz_codes(tdefl_compressor *d)
    {
        mz_uint flags;
        mz_uint8 *pLZ_codes;
        mz_uint8 *pOutput_buf = d->m_pOutput_buf;
        mz_uint8 *pLZ_code_buf_end = d->m_pLZ_code_buf;
        mz_uint64 bit_buffer = d->m_bit_buffer;
        mz_uint bits_in = d->m_bits_in;

#define TDEFL_PUT_BITS_FAST(b, l)                    \
    {                                                \
        bit_buffer |= (((mz_uint64)(b)) << bits_in); \
        bits_in += (l);                              \
    }

        flags = 1;
        for (pLZ_codes = d->m_lz_code_buf; pLZ_codes < pLZ_code_buf_end; flags >>= 1)
        {
            if (flags == 1)
                flags = *pLZ_codes++ | 0x100;

            if (flags & 1)
            {
                mz_uint s0, s1, n0, n1, sym, num_extra_bits;
                mz_uint match_len = pLZ_codes[0];
                mz_uint match_dist = (pLZ_codes[1] | (pLZ_codes[2] << 8));
                pLZ_codes += 3;

                MZ_ASSERT(d->m_huff_code_sizes[0][s_tdefl_len_sym[match_len]]);
                TDEFL_PUT_BITS_FAST(d->m_huff_codes[0][s_tdefl_len_sym[match_len]], d->m_huff_code_sizes[0][s_tdefl_len_sym[match_len]]);
                TDEFL_PUT_BITS_FAST(match_len & mz_bitmasks[s_tdefl_len_extra[match_len]], s_tdefl_len_extra[match_len]);

                /* This sequence coaxes MSVC into using cmov's vs. jmp's. */
                s0 = s_tdefl_small_dist_sym[match_dist & 511];
                n0 = s_tdefl_small_dist_extra[match_dist & 511];
                s1 = s_tdefl_large_dist_sym[match_dist >> 8];
                n1 = s_tdefl_large_dist_extra[match_dist >> 8];
                sym = (match_dist < 512) ? s0 : s1;
                num_extra_bits = (match_dist < 512) ? n0 : n1;

                MZ_ASSERT(d->m_huff_code_sizes[1][sym]);
                TDEFL_PUT_BITS_FAST(d->m_huff_codes[1][sym], d->m_huff_code_sizes[1][sym]);
                TDEFL_PUT_BITS_FAST(match_dist & mz_bitmasks[num_extra_bits], num_extra_bits);
            }
            else
            {
                mz_uint lit = *pLZ_codes++;
                MZ_ASSERT(d->m_huff_code_sizes[0][lit]);
                TDEFL_PUT_BITS_FAST(d->m_huff_codes[0][lit], d->m_huff_code_sizes[0][lit]);

                if (((flags & 2) == 0) && (pLZ_codes < pLZ_code_buf_end))
                {
                    flags >>= 1;
                    lit = *pLZ_codes++;
                    MZ_ASSERT(d->m_huff_code_sizes[0][lit]);
                    TDEFL_PUT_BITS_FAST(d->m_huff_codes[0][lit], d->m_huff_code_sizes[0][lit]);

                    if (((flags & 2) == 0) && (pLZ_codes < pLZ_code_buf_end))
                    {
                        flags >>= 1;
                        lit = *pLZ_codes++;
                        MZ_ASSERT(d->m_huff_code_sizes[0][lit]);
                        TDEFL_PUT_BITS_FAST(d->m_huff_codes[0][lit], d->m_huff_code_sizes[0][lit]);
                    }
                }
            }

            if (pOutput_buf >= d->m_pOutput_buf_end)
                return MZ_FALSE;

            memcpy(pOutput_buf, &bit_buffer, sizeof(mz_uint64));
            pOutput_buf += (bits_in >> 3);
            bit_buffer >>= (bits_in & ~7);
            bits_in &= 7;
        }

#undef TDEFL_PUT_BITS_FAST

        d->m_pOutput_buf = pOutput_buf;
        d->m_bits_in = 0;
        d->m_bit_buffer = 0;

        while (bits_in)
        {
            mz_uint32 n = MZ_MIN(bits_in, 16);
            TDEFL_PUT_BITS((mz_uint)bit_buffer & mz_bitmasks[n], n);
            bit_buffer >>= n;
            bits_in -= n;
        }

        TDEFL_PUT_BITS(d->m_huff_codes[0][256], d->m_huff_code_sizes[0][256]);

        return (d->m_pOutput_buf < d->m_pOutput_buf_end);
    }
#else
static mz_bool tdefl_compress_lz_codes(tdefl_compressor *d)
{
    mz_uint flags;
    mz_uint8 *pLZ_codes;

    flags = 1;
    for (pLZ_codes = d->m_lz_code_buf; pLZ_codes < d->m_pLZ_code_buf; flags >>= 1)
    {
        if (flags == 1)
            flags = *pLZ_codes++ | 0x100;
        if (flags & 1)
        {
            mz_uint sym, num_extra_bits;
            mz_uint match_len = pLZ_codes[0], match_dist = (pLZ_codes[1] | (pLZ_codes[2] << 8));
            pLZ_codes += 3;

            MZ_ASSERT(d->m_huff_code_sizes[0][s_tdefl_len_sym[match_len]]);
            TDEFL_PUT_BITS(d->m_huff_codes[0][s_tdefl_len_sym[match_len]], d->m_huff_code_sizes[0][s_tdefl_len_sym[match_len]]);
            TDEFL_PUT_BITS(match_len & mz_bitmasks[s_tdefl_len_extra[match_len]], s_tdefl_len_extra[match_len]);

            if (match_dist < 512)
            {
                sym = s_tdefl_small_dist_sym[match_dist];
                num_extra_bits = s_tdefl_small_dist_extra[match_dist];
            }
            else
            {
                sym = s_tdefl_large_dist_sym[match_dist >> 8];
                num_extra_bits = s_tdefl_large_dist_extra[match_dist >> 8];
            }
            MZ_ASSERT(d->m_huff_code_sizes[1][sym]);
            TDEFL_PUT_BITS(d->m_huff_codes[1][sym], d->m_huff_code_sizes[1][sym]);
            TDEFL_PUT_BITS(match_dist & mz_bitmasks[num_extra_bits], num_extra_bits);
        }
        else
        {
            mz_uint lit = *pLZ_codes++;
            MZ_ASSERT(d->m_huff_code_sizes[0][lit]);
            TDEFL_PUT_BITS(d->m_huff_codes[0][lit], d->m_huff_code_sizes[0][lit]);
        }
    }

    TDEFL_PUT_BITS(d->m_huff_codes[0][256], d->m_huff_code_sizes[0][256]);

    return (d->m_pOutput_buf < d->m_pOutput_buf_end);
}
#endif /* TDEFL_USE_64BIT_BITBUF */

    static mz_bool tdefl_compress_block(tdefl_compressor *d, mz_bool static_block)
    {
        if (static_block)
            tdefl_start_static_block(d);
        else
            tdefl_start_dynamic_block(d);
        return tdefl_compress_lz_codes(d);
    }

    static const mz_uint s_tdefl_num_probes[11] = { 0, 1, 6, 32, 16, 32, 128, 256, 512, 768, 1500 };

    static int tdefl_flush_block(tdefl_compressor *d, int flush)
    {
        mz_uint saved_bit_buf, saved_bits_in;
        mz_uint8 *pSaved_output_buf;
        mz_bool comp_block_succeeded = MZ_FALSE;
        int n, use_raw_block = ((d->m_flags & TDEFL_FORCE_ALL_RAW_BLOCKS) != 0) && (d->m_lookahead_pos - d->m_lz_code_buf_dict_pos) <= d->m_dict_size;
        mz_uint8 *pOutput_buf_start = ((d->m_pPut_buf_func == NULL) && ((*d->m_pOut_buf_size - d->m_out_buf_ofs) >= TDEFL_OUT_BUF_SIZE)) ? ((mz_uint8 *)d->m_pOut_buf + d->m_out_buf_ofs) : d->m_output_buf;

        d->m_pOutput_buf = pOutput_buf_start;
        d->m_pOutput_buf_end = d->m_pOutput_buf + TDEFL_OUT_BUF_SIZE - 16;

        MZ_ASSERT(!d->m_output_flush_remaining);
        d->m_output_flush_ofs = 0;
        d->m_output_flush_remaining = 0;

        *d->m_pLZ_flags = (mz_uint8)(*d->m_pLZ_flags >> d->m_num_flags_left);
        d->m_pLZ_code_buf -= (d->m_num_flags_left == 8);

        if ((d->m_flags & TDEFL_WRITE_ZLIB_HEADER) && (!d->m_block_index))
        {
            const mz_uint8 cmf = 0x78;
            mz_uint8 flg, flevel = 3;
            mz_uint header, i, mz_un = sizeof(s_tdefl_num_probes) / sizeof(mz_uint);

            /* Determine compression level by reversing the process in tdefl_create_comp_flags_from_zip_params() */
            for (i = 0; i < mz_un; i++)
                if (s_tdefl_num_probes[i] == (d->m_flags & 0xFFF))
                    break;

            if (i < 2)
                flevel = 0;
            else if (i < 6)
                flevel = 1;
            else if (i == 6)
                flevel = 2;

            header = cmf << 8 | (flevel << 6);
            header += 31 - (header % 31);
            flg = header & 0xFF;

            TDEFL_PUT_BITS(cmf, 8);
            TDEFL_PUT_BITS(flg, 8);
        }

        TDEFL_PUT_BITS(flush == TDEFL_FINISH, 1);

        pSaved_output_buf = d->m_pOutput_buf;
        saved_bit_buf = d->m_bit_buffer;
        saved_bits_in = d->m_bits_in;

        if (!use_raw_block)
            comp_block_succeeded = tdefl_compress_block(d, (d->m_flags & TDEFL_FORCE_ALL_STATIC_BLOCKS) || (d->m_total_lz_bytes < 48));

        /* If the block gets expanded, forget the current contents of the output buffer and send a raw block instead. */
        if (((use_raw_block) || ((d->m_total_lz_bytes) && ((d->m_pOutput_buf - pSaved_output_buf + 1U) >= d->m_total_lz_bytes))) &&
            ((d->m_lookahead_pos - d->m_lz_code_buf_dict_pos) <= d->m_dict_size))
        {
            mz_uint i;
            d->m_pOutput_buf = pSaved_output_buf;
            d->m_bit_buffer = saved_bit_buf, d->m_bits_in = saved_bits_in;
            TDEFL_PUT_BITS(0, 2);
            if (d->m_bits_in)
            {
                TDEFL_PUT_BITS(0, 8 - d->m_bits_in);
            }
            for (i = 2; i; --i, d->m_total_lz_bytes ^= 0xFFFF)
            {
                TDEFL_PUT_BITS(d->m_total_lz_bytes & 0xFFFF, 16);
            }
            /* The bit buffer is empty here (byte aligned, then two whole 16-bit fields): the block's bytes are
               copied straight from the circular dictionary, in pieces where it wraps, up to the end of the
               output buffer, exactly as the byte-by-byte TDEFL_PUT_BITS(…, 8) loop wrote them. */
            MZ_ASSERT(!d->m_bits_in);
            {
                mz_uint pos = d->m_lz_code_buf_dict_pos & TDEFL_LZ_DICT_SIZE_MASK;
                size_t room = (size_t)(d->m_pOutput_buf_end - d->m_pOutput_buf);
                size_t left = (d->m_total_lz_bytes < room) ? d->m_total_lz_bytes : room;
                while (left)
                {
                    size_t piece = TDEFL_LZ_DICT_SIZE - pos;
                    if (piece > left)
                        piece = left;
                    memcpy(d->m_pOutput_buf, d->m_dict + pos, piece);
                    d->m_pOutput_buf += piece;
                    left -= piece;
                    pos = 0;
                }
            }
        }
        /* Check for the extremely unlikely (if not impossible) case of the compressed block not fitting into the output buffer when using dynamic codes. */
        else if (!comp_block_succeeded)
        {
            d->m_pOutput_buf = pSaved_output_buf;
            d->m_bit_buffer = saved_bit_buf, d->m_bits_in = saved_bits_in;
            tdefl_compress_block(d, MZ_TRUE);
        }

        if (flush)
        {
            if (flush == TDEFL_FINISH)
            {
                if (d->m_bits_in)
                {
                    TDEFL_PUT_BITS(0, 8 - d->m_bits_in);
                }
                if (d->m_flags & TDEFL_WRITE_ZLIB_HEADER)
                {
                    mz_uint i, a = d->m_adler32;
                    for (i = 0; i < 4; i++)
                    {
                        TDEFL_PUT_BITS((a >> 24) & 0xFF, 8);
                        a <<= 8;
                    }
                }
            }
            else
            {
                mz_uint i, z = 0;
                TDEFL_PUT_BITS(0, 3);
                if (d->m_bits_in)
                {
                    TDEFL_PUT_BITS(0, 8 - d->m_bits_in);
                }
                for (i = 2; i; --i, z ^= 0xFFFF)
                {
                    TDEFL_PUT_BITS(z & 0xFFFF, 16);
                }
            }
        }

        MZ_ASSERT(d->m_pOutput_buf < d->m_pOutput_buf_end);

        memset(&d->m_huff_count[0][0], 0, sizeof(d->m_huff_count[0][0]) * TDEFL_MAX_HUFF_SYMBOLS_0);
        memset(&d->m_huff_count[1][0], 0, sizeof(d->m_huff_count[1][0]) * TDEFL_MAX_HUFF_SYMBOLS_1);

        d->m_pLZ_code_buf = d->m_lz_code_buf + 1;
        d->m_pLZ_flags = d->m_lz_code_buf;
        d->m_num_flags_left = 8;
        d->m_lz_code_buf_dict_pos += d->m_total_lz_bytes;
        d->m_total_lz_bytes = 0;
        d->m_block_index++;

        if ((n = (int)(d->m_pOutput_buf - pOutput_buf_start)) != 0)
        {
            if (d->m_pPut_buf_func)
            {
                *d->m_pIn_buf_size = d->m_pSrc - (const mz_uint8 *)d->m_pIn_buf;
                if (!(*d->m_pPut_buf_func)(d->m_output_buf, n, d->m_pPut_buf_user))
                    return (d->m_prev_return_status = TDEFL_STATUS_PUT_BUF_FAILED);
            }
            else if (pOutput_buf_start == d->m_output_buf)
            {
                int bytes_to_copy = (int)MZ_MIN((size_t)n, (size_t)(*d->m_pOut_buf_size - d->m_out_buf_ofs));
                memcpy((mz_uint8 *)d->m_pOut_buf + d->m_out_buf_ofs, d->m_output_buf, bytes_to_copy);
                d->m_out_buf_ofs += bytes_to_copy;
                if ((n -= bytes_to_copy) != 0)
                {
                    d->m_output_flush_ofs = bytes_to_copy;
                    d->m_output_flush_remaining = n;
                }
            }
            else
            {
                d->m_out_buf_ofs += n;
            }
        }

        return d->m_output_flush_remaining;
    }

#if MINIZ_USE_UNALIGNED_LOADS_AND_STORES
#ifdef MINIZ_UNALIGNED_USE_MEMCPY
    static mz_uint16 TDEFL_READ_UNALIGNED_WORD(const mz_uint8 *p)
    {
        mz_uint16 ret;
        memcpy(&ret, p, sizeof(mz_uint16));
        return ret;
    }
    static mz_uint16 TDEFL_READ_UNALIGNED_WORD2(const mz_uint16 *p)
    {
        mz_uint16 ret;
        memcpy(&ret, p, sizeof(mz_uint16));
        return ret;
    }
#else
#define TDEFL_READ_UNALIGNED_WORD(p) *(const mz_uint16 *)(p)
#define TDEFL_READ_UNALIGNED_WORD2(p) *(const mz_uint16 *)(p)
#endif /* MINIZ_UNALIGNED_USE_MEMCPY */
    static MZ_FORCEINLINE void tdefl_find_match(tdefl_compressor *d, mz_uint lookahead_pos, mz_uint max_dist, mz_uint max_match_len, mz_uint *pMatch_dist, mz_uint *pMatch_len, const mz_uint long_budget)
    {
        mz_uint dist, pos = lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK, match_len = *pMatch_len, probe_pos = pos, next_probe_pos, probe_len;
        mz_uint num_probes_left = d->m_max_probes[match_len >= 32];
        const mz_uint16 *s = (const mz_uint16 *)(d->m_dict + pos), *p, *q;
        mz_uint16 c01 = TDEFL_READ_UNALIGNED_WORD(&d->m_dict[pos + match_len - 1]), s01 = TDEFL_READ_UNALIGNED_WORD2(s);
        MZ_ASSERT(max_match_len <= TDEFL_MAX_MATCH_LEN);
        (void)long_budget;
        if (max_match_len <= match_len)
            return;
        for (;;)
        {
            for (;;)
            {
                if (--num_probes_left == 0)
                    return;
#define TDEFL_PROBE                                                                             \
    next_probe_pos = d->m_next[probe_pos];                                                      \
    if ((!next_probe_pos) || ((dist = (mz_uint16)(lookahead_pos - next_probe_pos)) > max_dist)) \
        return;                                                                                 \
    probe_pos = next_probe_pos & TDEFL_LZ_DICT_SIZE_MASK;                                       \
    if (TDEFL_READ_UNALIGNED_WORD(&d->m_dict[probe_pos + match_len - 1]) == c01)                \
        break;
                TDEFL_PROBE;
                TDEFL_PROBE;
                TDEFL_PROBE;
            }
            if (!dist)
                break;
            q = (const mz_uint16 *)(d->m_dict + probe_pos);
            if (TDEFL_READ_UNALIGNED_WORD2(q) != s01)
                continue;
            p = s;
            probe_len = 32;
            do
            {
            } while ((TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) &&
                     (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (--probe_len > 0));
            if (!probe_len)
            {
                *pMatch_dist = dist;
                *pMatch_len = MZ_MIN(max_match_len, (mz_uint)TDEFL_MAX_MATCH_LEN);
                break;
            }
            else if ((probe_len = ((mz_uint)(p - s) * 2) + (mz_uint)(*(const mz_uint8 *)p == *(const mz_uint8 *)q)) > match_len)
            {
                *pMatch_dist = dist;
                if ((*pMatch_len = match_len = MZ_MIN(max_match_len, probe_len)) == max_match_len)
                    break;
                c01 = TDEFL_READ_UNALIGNED_WORD(&d->m_dict[pos + match_len - 1]);
            }
        }
    }
#else
/* Longueur commune de p et q, plafonnée à max_match_len : par mots de 64 bits tant qu'il reste au
   moins 8 octets sous le plafond, puis octet par octet (voir TDEFL_FIND_MATCH_64BIT plus haut). */
static MZ_FORCEINLINE mz_uint tdefl_match_length(const mz_uint8 *p, const mz_uint8 *q, mz_uint max_match_len)
{
    mz_uint probe_len;
#if TDEFL_FIND_MATCH_64BIT
    probe_len = 0;
    while ((max_match_len - probe_len) >= 8)
    {
        mz_uint64 wp, wq, x;
        memcpy(&wp, p, sizeof(wp));
        memcpy(&wq, q, sizeof(wq));
        x = wp ^ wq;
        if (x)
            return probe_len + (mz_uint)(__builtin_ctzll(x) >> 3);
        p += 8;
        q += 8;
        probe_len += 8;
    }
    while ((probe_len < max_match_len) && (*p == *q))
    {
        p++;
        q++;
        probe_len++;
    }
#else
    for (probe_len = 0; probe_len < max_match_len; probe_len++)
        if (*p++ != *q++)
            break;
#endif
    return probe_len;
}

#if defined(__GNUC__) || defined(__clang__)
#define TDEFL_NOINLINE __attribute__((__noinline__))
#elif defined(_MSC_VER)
#define TDEFL_NOINLINE __declspec(noinline)
#else
#define TDEFL_NOINLINE
#endif

/* The general search of tdefl_find_match (task miniz-0036), for a budget of 3 or more: the probes of
   the chain of lookahead_pos, in the same order, with the same budget and the same comparisons as
   before. Returns 0 if no match longer than match_len was found, (distance << 16) | length otherwise
   (length >= 3, distance < 32768). It is a function of its own so that its loop keeps its registers,
   and the caller's loop its own. Since task miniz-0044, it is entered at the first candidate of the
   chain, from tdefl_find_match_first (below), with dist_base = max_dist - lookahead_pos,
   pTail = m_dict + match_len - 1, and state = (budget left << 16) | the candidate's masked position.
   Per probe: the index is a size_t (no extension between the mask and the two reads it indexes), and
   the distance test is made against a base computed once per call. With
   dist = (mz_uint16)(lookahead_pos - next) and max_dist < 32768,
   (mz_uint16)(next + max_dist - lookahead_pos) is max_dist - dist when dist <= max_dist, and
   65536 + max_dist - dist > max_dist otherwise: it exceeds max_dist exactly when dist does. The
   distance itself is computed for the candidates only, from the masked positions: a candidate has
   dist <= max_dist < 32768, so dist == (pos - probe_pos) & TDEFL_LZ_DICT_SIZE_MASK. */
static TDEFL_NOINLINE mz_uint tdefl_find_match_long(const tdefl_compressor *d, mz_uint dist_base, mz_uint max_dist, mz_uint max_match_len, const mz_uint8 *pTail, mz_uint state)
{
    const mz_uint lookahead_pos = max_dist - dist_base;
    const mz_uint pos = lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK;
    const mz_uint16 max_dist16 = (mz_uint16)max_dist;
    mz_uint dist, probe_len, found = 0;
    mz_uint num_probes_left = state >> 16;
    size_t probe_pos = state & 0xFFFF;
    mz_uint match_len = (mz_uint)(pTail - d->m_dict) + 1;
    mz_uint16 c01, w;
    MZ_ASSERT(max_dist < TDEFL_LZ_DICT_SIZE);
    memcpy(&c01, pTail + pos, sizeof(c01));
/* End of the chain: a null m_next, or a distance beyond max_dist. */
#define TDEFL_CHAIN_END(n) ((!(n)) || ((mz_uint16)((n) + dist_base) > max_dist16))
/* The same, where a null m_next is beyond max_dist by itself: (mz_uint16)lookahead_pos > max_dist. */
#define TDEFL_CHAIN_END_FAR(n) ((mz_uint16)((n) + dist_base) > max_dist16)
#define TDEFL_PROBE_LONG(FIN)                                                                     \
    probe_pos = d->m_next[probe_pos];                                                             \
    if (FIN(probe_pos))                                                                           \
        return found;                                                                             \
    probe_pos &= TDEFL_LZ_DICT_SIZE_MASK;                                                         \
    memcpy(&w, pTail + probe_pos, sizeof(w));                                                     \
    if (w == c01)                                                                                 \
        break;
/* The loop as before, entered at its first candidate (ENTRY), which tdefl_find_match_first found. */
#define TDEFL_PROBE_LOOP(FIN, ENTRY)                                                              \
    for (;;)                                                                                      \
    {                                                                                             \
        for (;;)                                                                                  \
        {                                                                                         \
            if (--num_probes_left == 0)                                                           \
                return found;                                                                     \
            TDEFL_PROBE_LONG(FIN)                                                                 \
            TDEFL_PROBE_LONG(FIN)                                                                 \
            TDEFL_PROBE_LONG(FIN)                                                                 \
        }                                                                                         \
    ENTRY:                                                                                        \
        dist = (pos - (mz_uint)probe_pos) & TDEFL_LZ_DICT_SIZE_MASK;                              \
        if (!dist)                                                                                \
            return found;                                                                         \
        probe_len = tdefl_match_length(d->m_dict + pos, d->m_dict + probe_pos, max_match_len);    \
        if (probe_len > match_len)                                                                \
        {                                                                                         \
            match_len = probe_len;                                                                \
            found = (dist << 16) | probe_len;                                                     \
            if (probe_len == max_match_len)                                                       \
                return found;                                                                     \
            pTail = d->m_dict + match_len - 1;                                                    \
            memcpy(&c01, pTail + pos, sizeof(c01));                                               \
        }                                                                                         \
    }
    /* Two versions of the same loop: where position 0 lies beyond max_dist, the distance test alone
       ends the chain on a null m_next, and the zero test is left out. */
    if ((mz_uint16)lookahead_pos > max_dist)
    {
        goto tdefl_candidate_far;
        TDEFL_PROBE_LOOP(TDEFL_CHAIN_END_FAR, tdefl_candidate_far)
    }
    else
    {
        goto tdefl_candidate_near;
        TDEFL_PROBE_LOOP(TDEFL_CHAIN_END, tdefl_candidate_near)
    }
#undef TDEFL_PROBE_LOOP
}

/* Task miniz-0044: the start of the general search, up to its first candidate. Most searches at level 6
   have none (about two in three): they end here, in a function whose loop needs no register that a
   call must save, and so pays for none. On a candidate, it hands the search on to
   tdefl_find_match_long, at that candidate, with the budget left (state, below), and returns what it
   returns. Same probes, in the same order, with the same budget and the same comparisons as before.
   The caller made the first probe's test of the end of the chain: probe_pos is the first link, which
   that test let through. The first test of the budget is known to be false (a budget of 3 or more),
   so the budget is decremented once at the start and the loop is entered after both. The state handed
   on is (num_probes_left << 16) | probe_pos: probe_pos is masked (below 32768), and a budget is at most
   1 + (0xFFF + 2) / 3 = 1366. tdefl_find_match_long takes dist_base and pTail, from which it finds
   lookahead_pos and match_len again, so that this loop keeps neither. */
static TDEFL_NOINLINE mz_uint tdefl_find_match_first(const tdefl_compressor *d, mz_uint lookahead_pos, mz_uint max_dist, mz_uint max_match_len, mz_uint match_len, size_t probe_pos)
{
    const mz_uint dist_base = max_dist - lookahead_pos;
    const mz_uint16 max_dist16 = (mz_uint16)max_dist;
    const mz_uint found = 0;
    mz_uint num_probes_left = d->m_max_probes[match_len >= 32];
    const mz_uint8 *const pTail = d->m_dict + match_len - 1;
    mz_uint16 c01, w;
    MZ_ASSERT((num_probes_left >= 3) && (num_probes_left < 65536));
    memcpy(&c01, pTail + (lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK), sizeof(c01));
    num_probes_left--;
#define TDEFL_PROBE_LOOP(FIN, ENTRY)                                                              \
    for (;;)                                                                                      \
    {                                                                                             \
        if (--num_probes_left == 0)                                                               \
            return found;                                                                         \
        probe_pos = d->m_next[probe_pos];                                                         \
        if (FIN(probe_pos))                                                                       \
            return found;                                                                         \
    ENTRY:                                                                                        \
        probe_pos &= TDEFL_LZ_DICT_SIZE_MASK;                                                     \
        memcpy(&w, pTail + probe_pos, sizeof(w));                                                 \
        if (w == c01)                                                                             \
            break;                                                                                \
        TDEFL_PROBE_LONG(FIN)                                                                     \
        TDEFL_PROBE_LONG(FIN)                                                                     \
    }
    if ((mz_uint16)lookahead_pos > max_dist)
    {
        goto tdefl_entry_far;
        TDEFL_PROBE_LOOP(TDEFL_CHAIN_END_FAR, tdefl_entry_far)
    }
    else
    {
        goto tdefl_entry_near;
        TDEFL_PROBE_LOOP(TDEFL_CHAIN_END, tdefl_entry_near)
    }
    return tdefl_find_match_long(d, dist_base, max_dist, max_match_len, pTail, (num_probes_left << 16) | (mz_uint)probe_pos);
#undef TDEFL_PROBE_LOOP
#undef TDEFL_PROBE_LONG
#undef TDEFL_CHAIN_END_FAR
#undef TDEFL_CHAIN_END
}

/* Task miniz-0045: long_budget is nonzero only where both budgets of d->m_max_probes are known to be 3 or more
   (see tdefl_compress_normal): the test of the budget is then known to be true, and is left out. */
static MZ_FORCEINLINE void tdefl_find_match(tdefl_compressor *d, mz_uint lookahead_pos, mz_uint max_dist, mz_uint max_match_len, mz_uint *pMatch_dist, mz_uint *pMatch_len, const mz_uint long_budget)
{
    mz_uint dist, pos, match_len = *pMatch_len, probe_pos, next_probe_pos, probe_len;
    mz_uint num_probes_left;
    /* pTail pointe sur m_dict + match_len - 1 : les deux octets de fin de correspondance (positions
       match_len - 1 et match_len) se lisent en une fois par memcpy, sans calcul d'indice par sonde.
       L'égalité de deux mots lus de la même façon équivaut à celle des deux octets, quel que soit
       le boutisme ; ce sont les mêmes octets que lisait la version octet par octet (match_len >= 1). */
    const mz_uint8 *pTail;
    mz_uint16 c01, w;
    MZ_ASSERT(max_match_len <= TDEFL_MAX_MATCH_LEN);
    if (max_match_len <= match_len)
        return;
    num_probes_left = d->m_max_probes[match_len >= 32];
    /* Recherche courte (tâche miniz-0038) : avec un budget de 1 ou 2 (niveau 1), la recherche générale
       fait au plus trois sondes et au plus une comparaison, après laquelle le budget est épuisé. Mêmes
       sondes, dans le même ordre, et même comparaison, écrites en ligne droite : la mise en place de
       la recherche générale (tdefl_find_match_long) n'est payée que par les budgets plus grands. */
    if ((long_budget) || ((num_probes_left - 1U) > 1U))
    {
        mz_uint found;
#if defined(__GNUC__) || defined(__clang__)
        /* The probes wait on memory more than on instructions: m_next and m_dict do not fit the first
           cache together, and each probe's address comes from the one before. The search of the next
           position cannot start before this one ends, but the start of its chain is known now:
           position lookahead_pos + 1 is in the chains as soon as the lookahead holds 4 bytes (the last
           position inserted is lookahead_pos + lookahead_size - 3), so its m_next is written, and so
           is the m_next of the position it names (an earlier position, or 0). Ask, while this search
           runs, for the lines the first probes of the next one read: the first link's m_next and
           m_dict, and the second link's m_next. Hints only, which change no result. */
        if (max_match_len > TDEFL_MIN_MATCH_LEN)
        {
            const size_t next_first = d->m_next[(lookahead_pos + 1) & TDEFL_LZ_DICT_SIZE_MASK] & TDEFL_LZ_DICT_SIZE_MASK;
            __builtin_prefetch(&d->m_next[next_first]);
            __builtin_prefetch(d->m_dict + next_first);
            __builtin_prefetch(&d->m_next[d->m_next[next_first] & TDEFL_LZ_DICT_SIZE_MASK]);
        }
#endif
        {
            /* Task miniz-0044: the first probe's test of the end of the chain, made here, as the general
               search made it (the test of the budget before it is known to be false): about one search
               in four at level 6 ends on it, and then pays for no call. */
            const mz_uint first = d->m_next[lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK];
            if ((!first) || ((mz_uint16)(lookahead_pos - first) > max_dist))
                return;
            found = tdefl_find_match_first(d, lookahead_pos, max_dist, max_match_len, match_len, first);
        }
        if (found)
        {
            *pMatch_dist = found >> 16;
            *pMatch_len = found & 0xFFFF;
        }
        return;
    }
    if (num_probes_left == 1)
        return;
    probe_pos = pos = lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK;
    pTail = d->m_dict + match_len - 1;
    memcpy(&c01, pTail + pos, sizeof(c01));
#define TDEFL_PROBE(TROUVE)                                                                       \
    next_probe_pos = d->m_next[probe_pos];                                                        \
    if ((!next_probe_pos) || ((dist = (mz_uint16)(lookahead_pos - next_probe_pos)) > max_dist))   \
        return;                                                                                   \
    probe_pos = next_probe_pos & TDEFL_LZ_DICT_SIZE_MASK;                                         \
    memcpy(&w, pTail + probe_pos, sizeof(w));                                                     \
    if (w == c01)                                                                                 \
        TROUVE;
    TDEFL_PROBE(goto candidat_court);
    TDEFL_PROBE(goto candidat_court);
    TDEFL_PROBE(goto candidat_court);
    return;
candidat_court:
    if (!dist)
        return;
    probe_len = tdefl_match_length(d->m_dict + pos, d->m_dict + probe_pos, max_match_len);
    if (probe_len > match_len)
    {
        *pMatch_dist = dist;
        *pMatch_len = probe_len;
    }
#undef TDEFL_PROBE
}
#endif /* MINIZ_USE_UNALIGNED_LOADS_AND_STORES */

#if MINIZ_USE_UNALIGNED_LOADS_AND_STORES && MINIZ_LITTLE_ENDIAN
#ifdef MINIZ_UNALIGNED_USE_MEMCPY
    static mz_uint32 TDEFL_READ_UNALIGNED_WORD32(const mz_uint8 *p)
    {
        mz_uint32 ret;
        memcpy(&ret, p, sizeof(mz_uint32));
        return ret;
    }
#else
#define TDEFL_READ_UNALIGNED_WORD32(p) *(const mz_uint32 *)(p)
#endif /* MINIZ_UNALIGNED_USE_MEMCPY */
    static mz_bool tdefl_compress_fast(tdefl_compressor *d)
    {
        /* Faster, minimally featured LZRW1-style match+parse loop with better register utilization. Intended for applications where raw throughput is valued more highly than ratio. */
        mz_uint lookahead_pos = d->m_lookahead_pos, lookahead_size = d->m_lookahead_size, dict_size = d->m_dict_size, total_lz_bytes = d->m_total_lz_bytes, num_flags_left = d->m_num_flags_left;
        mz_uint8 *pLZ_code_buf = d->m_pLZ_code_buf, *pLZ_flags = d->m_pLZ_flags;
        mz_uint cur_pos = lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK;

        while ((d->m_src_buf_left) || ((d->m_flush) && (lookahead_size)))
        {
            const mz_uint TDEFL_COMP_FAST_LOOKAHEAD_SIZE = 4096;
            mz_uint dst_pos = (lookahead_pos + lookahead_size) & TDEFL_LZ_DICT_SIZE_MASK;
            mz_uint num_bytes_to_process = (mz_uint)MZ_MIN(d->m_src_buf_left, TDEFL_COMP_FAST_LOOKAHEAD_SIZE - lookahead_size);
            d->m_src_buf_left -= num_bytes_to_process;
            lookahead_size += num_bytes_to_process;

            while (num_bytes_to_process)
            {
                mz_uint32 n = MZ_MIN(TDEFL_LZ_DICT_SIZE - dst_pos, num_bytes_to_process);
                memcpy(d->m_dict + dst_pos, d->m_pSrc, n);
                if (dst_pos < (TDEFL_MAX_MATCH_LEN - 1))
                    memcpy(d->m_dict + TDEFL_LZ_DICT_SIZE + dst_pos, d->m_pSrc, MZ_MIN(n, (TDEFL_MAX_MATCH_LEN - 1) - dst_pos));
                d->m_pSrc += n;
                dst_pos = (dst_pos + n) & TDEFL_LZ_DICT_SIZE_MASK;
                num_bytes_to_process -= n;
            }

            dict_size = MZ_MIN(TDEFL_LZ_DICT_SIZE - lookahead_size, dict_size);
            if ((!d->m_flush) && (lookahead_size < TDEFL_COMP_FAST_LOOKAHEAD_SIZE))
                break;

            while (lookahead_size >= 4)
            {
                mz_uint cur_match_dist, cur_match_len = 1;
                mz_uint8 *pCur_dict = d->m_dict + cur_pos;
                mz_uint first_trigram = TDEFL_READ_UNALIGNED_WORD32(pCur_dict) & 0xFFFFFF;
                mz_uint hash = (first_trigram ^ (first_trigram >> (24 - (TDEFL_LZ_HASH_BITS - 8)))) & TDEFL_LEVEL1_HASH_SIZE_MASK;
                mz_uint probe_pos = d->m_hash[hash];
                d->m_hash[hash] = (mz_uint16)lookahead_pos;

                if (((cur_match_dist = (mz_uint16)(lookahead_pos - probe_pos)) <= dict_size) && ((TDEFL_READ_UNALIGNED_WORD32(d->m_dict + (probe_pos &= TDEFL_LZ_DICT_SIZE_MASK)) & 0xFFFFFF) == first_trigram))
                {
                    const mz_uint16 *p = (const mz_uint16 *)pCur_dict;
                    const mz_uint16 *q = (const mz_uint16 *)(d->m_dict + probe_pos);
                    mz_uint32 probe_len = 32;
                    do
                    {
                    } while ((TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) &&
                             (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (TDEFL_READ_UNALIGNED_WORD2(++p) == TDEFL_READ_UNALIGNED_WORD2(++q)) && (--probe_len > 0));
                    cur_match_len = ((mz_uint)(p - (const mz_uint16 *)pCur_dict) * 2) + (mz_uint)(*(const mz_uint8 *)p == *(const mz_uint8 *)q);
                    if (!probe_len)
                        cur_match_len = cur_match_dist ? TDEFL_MAX_MATCH_LEN : 0;

                    if ((cur_match_len < TDEFL_MIN_MATCH_LEN) || ((cur_match_len == TDEFL_MIN_MATCH_LEN) && (cur_match_dist >= 8U * 1024U)))
                    {
                        cur_match_len = 1;
                        *pLZ_code_buf++ = (mz_uint8)first_trigram;
                        *pLZ_flags = (mz_uint8)(*pLZ_flags >> 1);
                        d->m_huff_count[0][(mz_uint8)first_trigram]++;
                    }
                    else
                    {
                        mz_uint32 s0, s1;
                        cur_match_len = MZ_MIN(cur_match_len, lookahead_size);

                        MZ_ASSERT((cur_match_len >= TDEFL_MIN_MATCH_LEN) && (cur_match_dist >= 1) && (cur_match_dist <= TDEFL_LZ_DICT_SIZE));

                        cur_match_dist--;

                        pLZ_code_buf[0] = (mz_uint8)(cur_match_len - TDEFL_MIN_MATCH_LEN);
#ifdef MINIZ_UNALIGNED_USE_MEMCPY
                        memcpy(&pLZ_code_buf[1], &cur_match_dist, sizeof(cur_match_dist));
#else
                        *(mz_uint16 *)(&pLZ_code_buf[1]) = (mz_uint16)cur_match_dist;
#endif /* MINIZ_UNALIGNED_USE_MEMCPY */
                        pLZ_code_buf += 3;
                        *pLZ_flags = (mz_uint8)((*pLZ_flags >> 1) | 0x80);

                        s0 = s_tdefl_small_dist_sym[cur_match_dist & 511];
                        s1 = s_tdefl_large_dist_sym[cur_match_dist >> 8];
                        d->m_huff_count[1][(cur_match_dist < 512) ? s0 : s1]++;

                        d->m_huff_count[0][s_tdefl_len_sym[cur_match_len - TDEFL_MIN_MATCH_LEN]]++;
                    }
                }
                else
                {
                    *pLZ_code_buf++ = (mz_uint8)first_trigram;
                    *pLZ_flags = (mz_uint8)(*pLZ_flags >> 1);
                    d->m_huff_count[0][(mz_uint8)first_trigram]++;
                }

                if (--num_flags_left == 0)
                {
                    num_flags_left = 8;
                    pLZ_flags = pLZ_code_buf++;
                }

                total_lz_bytes += cur_match_len;
                lookahead_pos += cur_match_len;
                dict_size = MZ_MIN(dict_size + cur_match_len, (mz_uint)TDEFL_LZ_DICT_SIZE);
                cur_pos = (cur_pos + cur_match_len) & TDEFL_LZ_DICT_SIZE_MASK;
                MZ_ASSERT(lookahead_size >= cur_match_len);
                lookahead_size -= cur_match_len;

                if (pLZ_code_buf > &d->m_lz_code_buf[TDEFL_LZ_CODE_BUF_SIZE - 8])
                {
                    int n;
                    d->m_lookahead_pos = lookahead_pos;
                    d->m_lookahead_size = lookahead_size;
                    d->m_dict_size = dict_size;
                    d->m_total_lz_bytes = total_lz_bytes;
                    d->m_pLZ_code_buf = pLZ_code_buf;
                    d->m_pLZ_flags = pLZ_flags;
                    d->m_num_flags_left = num_flags_left;
                    if ((n = tdefl_flush_block(d, 0)) != 0)
                        return (n < 0) ? MZ_FALSE : MZ_TRUE;
                    total_lz_bytes = d->m_total_lz_bytes;
                    pLZ_code_buf = d->m_pLZ_code_buf;
                    pLZ_flags = d->m_pLZ_flags;
                    num_flags_left = d->m_num_flags_left;
                }
            }

            while (lookahead_size)
            {
                mz_uint8 lit = d->m_dict[cur_pos];

                total_lz_bytes++;
                *pLZ_code_buf++ = lit;
                *pLZ_flags = (mz_uint8)(*pLZ_flags >> 1);
                if (--num_flags_left == 0)
                {
                    num_flags_left = 8;
                    pLZ_flags = pLZ_code_buf++;
                }

                d->m_huff_count[0][lit]++;

                lookahead_pos++;
                dict_size = MZ_MIN(dict_size + 1, (mz_uint)TDEFL_LZ_DICT_SIZE);
                cur_pos = (cur_pos + 1) & TDEFL_LZ_DICT_SIZE_MASK;
                lookahead_size--;

                if (pLZ_code_buf > &d->m_lz_code_buf[TDEFL_LZ_CODE_BUF_SIZE - 8])
                {
                    int n;
                    d->m_lookahead_pos = lookahead_pos;
                    d->m_lookahead_size = lookahead_size;
                    d->m_dict_size = dict_size;
                    d->m_total_lz_bytes = total_lz_bytes;
                    d->m_pLZ_code_buf = pLZ_code_buf;
                    d->m_pLZ_flags = pLZ_flags;
                    d->m_num_flags_left = num_flags_left;
                    if ((n = tdefl_flush_block(d, 0)) != 0)
                        return (n < 0) ? MZ_FALSE : MZ_TRUE;
                    total_lz_bytes = d->m_total_lz_bytes;
                    pLZ_code_buf = d->m_pLZ_code_buf;
                    pLZ_flags = d->m_pLZ_flags;
                    num_flags_left = d->m_num_flags_left;
                }
            }
        }

        d->m_lookahead_pos = lookahead_pos;
        d->m_lookahead_size = lookahead_size;
        d->m_dict_size = dict_size;
        d->m_total_lz_bytes = total_lz_bytes;
        d->m_pLZ_code_buf = pLZ_code_buf;
        d->m_pLZ_flags = pLZ_flags;
        d->m_num_flags_left = num_flags_left;
        return MZ_TRUE;
    }
#endif /* MINIZ_USE_UNALIGNED_LOADS_AND_STORES && MINIZ_LITTLE_ENDIAN */

    /* Task miniz-0019: the write position in m_lz_code_buf, the flag byte being filled and the count of flags
       left in it belong to tdefl_compress_normal, which keeps them in local variables (tdefl_lz_state) between
       two calls of tdefl_flush_block and copies them back into d before each of them and where it returns. */
    typedef struct
    {
        mz_uint8 *m_pLZ_code_buf, *m_pLZ_flags;
        mz_uint m_num_flags_left;
    } tdefl_lz_state;

    static MZ_FORCEINLINE void tdefl_record_literal(tdefl_compressor *d, tdefl_lz_state *lz, mz_uint8 lit)
    {
        d->m_total_lz_bytes++;
        *lz->m_pLZ_code_buf++ = lit;
        *lz->m_pLZ_flags = (mz_uint8)(*lz->m_pLZ_flags >> 1);
        if (--lz->m_num_flags_left == 0)
        {
            lz->m_num_flags_left = 8;
            lz->m_pLZ_flags = lz->m_pLZ_code_buf++;
        }
        d->m_huff_count[0][lit]++;
    }

    static MZ_FORCEINLINE void tdefl_record_match(tdefl_compressor *d, tdefl_lz_state *lz, mz_uint match_len, mz_uint match_dist)
    {
        mz_uint32 s0, s1;
        mz_uint8 *pLZ_code_buf = lz->m_pLZ_code_buf;

        MZ_ASSERT((match_len >= TDEFL_MIN_MATCH_LEN) && (match_dist >= 1) && (match_dist <= TDEFL_LZ_DICT_SIZE));

        d->m_total_lz_bytes += match_len;

        match_dist -= 1;
        pLZ_code_buf[0] = (mz_uint8)(match_len - TDEFL_MIN_MATCH_LEN);
        pLZ_code_buf[1] = (mz_uint8)(match_dist & 0xFF);
        pLZ_code_buf[2] = (mz_uint8)(match_dist >> 8);
        pLZ_code_buf += 3;

        *lz->m_pLZ_flags = (mz_uint8)((*lz->m_pLZ_flags >> 1) | 0x80);
        if (--lz->m_num_flags_left == 0)
        {
            lz->m_num_flags_left = 8;
            lz->m_pLZ_flags = pLZ_code_buf++;
        }
        lz->m_pLZ_code_buf = pLZ_code_buf;

        s0 = s_tdefl_small_dist_sym[match_dist & 511];
        s1 = s_tdefl_large_dist_sym[(match_dist >> 8) & 127];
        d->m_huff_count[1][(match_dist < 512) ? s0 : s1]++;
        d->m_huff_count[0][s_tdefl_len_sym[match_len - TDEFL_MIN_MATCH_LEN]]++;
    }

/* Task miniz-0020: the smallest number of bytes in m_lz_code_buf at which tdefl_compress_normal's flush test can be
   true. That test is (n > TDEFL_LZ_CODE_BUF_SIZE - 8) || ((t > 31 * 1024) && (((n * 115) >> 7) >= t || raw)), with n
   the bytes in the buffer and t = m_total_lz_bytes. Its first term needs n >= TDEFL_LZ_CODE_BUF_SIZE - 7. The
   second needs t >= 31 * 1024 + 1 and n * 115 >= t * 128, hence n >= ceil((31 * 1024 + 1) * 128 / 115) = 35334. With
   TDEFL_FORCE_ALL_RAW_BLOCKS (raw), tdefl_compress_normal looks for no match and records literals only: n is then
   t + t / 8 + 1 (one flag byte per 8 literals, the first one allocated ahead), which is >= 35713 once t > 31 * 1024.
   Below this bound the test is false, so one comparison settles it; the flushes happen at the same symbols. */
#define TDEFL_LZ_FLUSH_MIN_CODE_BYTES MZ_MIN(TDEFL_LZ_CODE_BUF_SIZE - 7, ((31 * 1024 + 1) * 128 + 114) / 115)

    /* Task miniz-0045: the body of tdefl_compress_normal, with d->m_flags and d->m_greedy_parsing as parameters;
       tdefl_compress_normal below calls it in two places, see there. */
    static MZ_FORCEINLINE mz_bool tdefl_compress_normal_body(tdefl_compressor *d, const mz_uint flags, const mz_uint greedy_parsing, const mz_uint long_budget)
    {
        const mz_uint8 *pSrc = d->m_pSrc;
        size_t src_buf_left = d->m_src_buf_left;
        tdefl_flush flush = d->m_flush;
        /* Task miniz-0019: the window's three counters live in local variables, as in tdefl_compress_fast, and
           are written back into d only where something else reads them: before tdefl_flush_block (which reads
           m_lookahead_pos and m_dict_size, and changes neither) and where the function returns. The loop
           stores bytes into d->m_dict and d->m_lz_code_buf, stores that may alias d itself: kept in d, each
           counter was read again and written again at every symbol. Same values, same order, same flushes. */
        mz_uint lookahead_pos = d->m_lookahead_pos, lookahead_size = d->m_lookahead_size, dict_size = d->m_dict_size;
        tdefl_lz_state lz;
        /* Task miniz-0037: the rolling hash of the last two bytes of the window is kept in a variable from one
           iteration to the next instead of being read back from m_dict each time. TDEFL_LZ_HASH_SHIFT * 3 >=
           TDEFL_LZ_HASH_BITS, so after the update ((hash << TDEFL_LZ_HASH_SHIFT) ^ c) & (TDEFL_LZ_HASH_SIZE - 1)
           only the last three bytes remain in hash: the value the insertion loops leave gives, at the next update,
           exactly what the hash recomputed from the last two bytes gave. It is computed once, below.
           Start of the stream (or first bytes after a full flush): while the window and the lookahead hold fewer
           than TDEFL_MIN_MATCH_LEN - 1 bytes, bytes are only copied, as before: no string is inserted before its
           third byte. This was a path of the loop, taken until the lookahead was full; from the second byte on it
           made the same writes, in the same order, as the general insertion loop (same position
           m_lookahead_pos + m_lookahead_size - 2 before the byte is counted, same hash of the three bytes), which
           now does them. Once two bytes are there they stay there until the function returns (m_dict_size is reset
           outside it), so the loop no longer tests for it; if the source ends before the second byte, the loop
           inserts nothing (num_bytes_to_process is 0) and hash is not used. */
        mz_uint hash = 0;
        /* Task miniz-0045: the lazy match held from one position to the next (its length, distance and the literal
           at its position) lives in local variables, read from d once here and written back into d before
           tdefl_flush_block and where the function returns. Kept in d, each was read again after every store into
           d->m_dict, d->m_lz_code_buf or d->m_huff_count, which may alias d. */
        mz_uint saved_match_len = d->m_saved_match_len, saved_match_dist = d->m_saved_match_dist, saved_lit = d->m_saved_lit;
        lz.m_pLZ_code_buf = d->m_pLZ_code_buf;
        lz.m_pLZ_flags = d->m_pLZ_flags;
        lz.m_num_flags_left = d->m_num_flags_left;
        while (((lookahead_size + dict_size) < (TDEFL_MIN_MATCH_LEN - 1)) && (src_buf_left))
        {
            mz_uint8 c = *pSrc++;
            mz_uint dst_pos = (lookahead_pos + lookahead_size++) & TDEFL_LZ_DICT_SIZE_MASK;
            src_buf_left--;
            d->m_dict[dst_pos] = c;
            if (dst_pos < (TDEFL_MAX_MATCH_LEN - 1))
                d->m_dict[TDEFL_LZ_DICT_SIZE + dst_pos] = c;
        }
        if ((lookahead_size + dict_size) >= (TDEFL_MIN_MATCH_LEN - 1))
        {
            mz_uint ins_pos = lookahead_pos + lookahead_size - 2;
            hash = (d->m_dict[ins_pos & TDEFL_LZ_DICT_SIZE_MASK] << TDEFL_LZ_HASH_SHIFT) ^ d->m_dict[(ins_pos + 1) & TDEFL_LZ_DICT_SIZE_MASK];
        }

        while ((src_buf_left) || ((flush) && (lookahead_size)))
        {
            mz_uint len_to_move, cur_match_dist, cur_match_len, cur_pos;
            /* Update dictionary and hash chains. Keeps the lookahead size equal to TDEFL_MAX_MATCH_LEN. */
            mz_uint dst_pos = (lookahead_pos + lookahead_size) & TDEFL_LZ_DICT_SIZE_MASK, ins_pos = lookahead_pos + lookahead_size - 2;
            mz_uint num_bytes_to_process = (mz_uint)MZ_MIN(src_buf_left, TDEFL_MAX_MATCH_LEN - lookahead_size);
            src_buf_left -= num_bytes_to_process;
            lookahead_size += num_bytes_to_process;
            if ((dst_pos >= (TDEFL_MAX_MATCH_LEN - 1)) && ((dst_pos + num_bytes_to_process) <= TDEFL_LZ_DICT_SIZE))
            {
                /* Cas courant (tâche miniz-0013) : ni dst_pos ni ins_pos ne reviennent au début de la
                   fenêtre, et aucun octet ne tombe dans la copie miroir (dst_pos >= TDEFL_MAX_MATCH_LEN - 1),
                   donc ins_pos & TDEFL_LZ_DICT_SIZE_MASK == dst_pos - 2. Mêmes écritures, dans le même
                   ordre (octet k = 0, 1, 2…), que la boucle générale ci-dessous, sans masque ni test
                   par octet ; boucle déroulée par deux, l'octet impair éventuel passe en premier. */
                mz_uint8 *pDst = d->m_dict + dst_pos;
                mz_uint16 *pNext = d->m_next + (dst_pos - 2);
                size_t i = num_bytes_to_process & 1;
#define TDEFL_INSERT_BYTE(k)                                                   \
    do                                                                         \
    {                                                                          \
        mz_uint8 c = pSrc[k];                                                  \
        pDst[k] = c;                                                           \
        hash = ((hash << TDEFL_LZ_HASH_SHIFT) ^ c) & (TDEFL_LZ_HASH_SIZE - 1); \
        pNext[k] = d->m_hash[hash];                                            \
        d->m_hash[hash] = (mz_uint16)(ins_pos + (k));                          \
    } MZ_MACRO_END
                if (i)
                    TDEFL_INSERT_BYTE(0);
                for (; i < num_bytes_to_process; i += 2)
                {
                    TDEFL_INSERT_BYTE(i);
                    TDEFL_INSERT_BYTE(i + 1);
                }
#undef TDEFL_INSERT_BYTE
                if (num_bytes_to_process)
                    pSrc += num_bytes_to_process;
            }
            else
            {
                const mz_uint8 *pSrc_end = pSrc ? pSrc + num_bytes_to_process : NULL;
                while (pSrc != pSrc_end)
                {
                    mz_uint8 c = *pSrc++;
                    d->m_dict[dst_pos] = c;
                    if (dst_pos < (TDEFL_MAX_MATCH_LEN - 1))
                        d->m_dict[TDEFL_LZ_DICT_SIZE + dst_pos] = c;
                    hash = ((hash << TDEFL_LZ_HASH_SHIFT) ^ c) & (TDEFL_LZ_HASH_SIZE - 1);
                    d->m_next[ins_pos & TDEFL_LZ_DICT_SIZE_MASK] = d->m_hash[hash];
                    d->m_hash[hash] = (mz_uint16)(ins_pos);
                    dst_pos = (dst_pos + 1) & TDEFL_LZ_DICT_SIZE_MASK;
                    ins_pos++;
                }
            }
            dict_size = MZ_MIN(TDEFL_LZ_DICT_SIZE - lookahead_size, dict_size);
            if ((!flush) && (lookahead_size < TDEFL_MAX_MATCH_LEN))
                break;

            /* Simple lazy/greedy parsing state machine. */
            len_to_move = 1;
            cur_match_dist = 0;
            cur_match_len = saved_match_len ? saved_match_len : (TDEFL_MIN_MATCH_LEN - 1);
            cur_pos = lookahead_pos & TDEFL_LZ_DICT_SIZE_MASK;
            if (flags & (TDEFL_RLE_MATCHES | TDEFL_FORCE_ALL_RAW_BLOCKS))
            {
                if ((dict_size) && (!(flags & TDEFL_FORCE_ALL_RAW_BLOCKS)))
                {
                    mz_uint8 c = d->m_dict[(cur_pos - 1) & TDEFL_LZ_DICT_SIZE_MASK];
                    cur_match_len = 0;
                    while (cur_match_len < lookahead_size)
                    {
                        if (d->m_dict[cur_pos + cur_match_len] != c)
                            break;
                        cur_match_len++;
                    }
                    if (cur_match_len < TDEFL_MIN_MATCH_LEN)
                        cur_match_len = 0;
                    else
                        cur_match_dist = 1;
                }
            }
            else
            {
                tdefl_find_match(d, lookahead_pos, dict_size, lookahead_size, &cur_match_dist, &cur_match_len, long_budget);
            }
            /* Task miniz-0045: a match was found exactly when cur_match_dist is nonzero (tdefl_find_match and the RLE
               search set both, or neither). Without one, cur_match_len is still its first value (the held match's
               length, or TDEFL_MIN_MATCH_LEN - 1), or 0 if the test below cleared it: it is then never greater than
               saved_match_len, and the choice is the same whatever the test below decides. So both tests start by
               asking whether there is a match: the path without one reads neither cur_match_len nor cur_pos. */
            if ((cur_match_dist) && (((cur_match_len == TDEFL_MIN_MATCH_LEN) && (cur_match_dist >= 8U * 1024U)) || (cur_pos == cur_match_dist) || ((flags & TDEFL_FILTER_MATCHES) && (cur_match_len <= 5))))
            {
                cur_match_dist = cur_match_len = 0;
            }
            if (saved_match_len)
            {
                if ((cur_match_dist) && (cur_match_len > saved_match_len))
                {
                    tdefl_record_literal(d, &lz, (mz_uint8)saved_lit);
                    if (cur_match_len >= 128)
                    {
                        tdefl_record_match(d, &lz, cur_match_len, cur_match_dist);
                        saved_match_len = 0;
                        len_to_move = cur_match_len;
                    }
                    else
                    {
                        saved_lit = d->m_dict[cur_pos];
                        saved_match_dist = cur_match_dist;
                        saved_match_len = cur_match_len;
                    }
                }
                else
                {
                    tdefl_record_match(d, &lz, saved_match_len, saved_match_dist);
                    len_to_move = saved_match_len - 1;
                    saved_match_len = 0;
                }
            }
            else if (!cur_match_dist)
                tdefl_record_literal(d, &lz, d->m_dict[MZ_MIN(cur_pos, sizeof(d->m_dict) - 1)]);
            else if ((greedy_parsing) || (flags & TDEFL_RLE_MATCHES) || (cur_match_len >= 128))
            {
                tdefl_record_match(d, &lz, cur_match_len, cur_match_dist);
                len_to_move = cur_match_len;
            }
            else
            {
                saved_lit = d->m_dict[MZ_MIN(cur_pos, sizeof(d->m_dict) - 1)];
                saved_match_dist = cur_match_dist;
                saved_match_len = cur_match_len;
            }
            /* Move the lookahead forward by len_to_move bytes. */
            lookahead_pos += len_to_move;
            MZ_ASSERT(lookahead_size >= len_to_move);
            lookahead_size -= len_to_move;
            /* Task miniz-0020: not clamped to TDEFL_LZ_DICT_SIZE here. Until the next iteration clamps it to
               TDEFL_LZ_DICT_SIZE - m_lookahead_size (a smaller bound), m_dict_size is only compared with small
               constants, which the clamp cannot change; it is clamped below wherever it leaves this loop. */
            dict_size += len_to_move;
            /* Check if it's time to flush the current LZ codes to the internal output buffer. */
            if ((lz.m_pLZ_code_buf > &d->m_lz_code_buf[TDEFL_LZ_FLUSH_MIN_CODE_BYTES - 1]) &&
                ((lz.m_pLZ_code_buf > &d->m_lz_code_buf[TDEFL_LZ_CODE_BUF_SIZE - 8]) ||
                 ((d->m_total_lz_bytes > 31 * 1024) && (((((mz_uint)(lz.m_pLZ_code_buf - d->m_lz_code_buf) * 115) >> 7) >= d->m_total_lz_bytes) || (flags & TDEFL_FORCE_ALL_RAW_BLOCKS)))))
            {
                int n;
                dict_size = MZ_MIN(dict_size, (mz_uint)TDEFL_LZ_DICT_SIZE);
                d->m_lookahead_pos = lookahead_pos;
                d->m_lookahead_size = lookahead_size;
                d->m_dict_size = dict_size;
                d->m_pSrc = pSrc;
                d->m_src_buf_left = src_buf_left;
                d->m_pLZ_code_buf = lz.m_pLZ_code_buf;
                d->m_pLZ_flags = lz.m_pLZ_flags;
                d->m_num_flags_left = lz.m_num_flags_left;
                d->m_saved_match_len = saved_match_len;
                d->m_saved_match_dist = saved_match_dist;
                d->m_saved_lit = saved_lit;
                if ((n = tdefl_flush_block(d, 0)) != 0)
                    return (n < 0) ? MZ_FALSE : MZ_TRUE;
                lz.m_pLZ_code_buf = d->m_pLZ_code_buf;
                lz.m_pLZ_flags = d->m_pLZ_flags;
                lz.m_num_flags_left = d->m_num_flags_left;
            }
        }

        d->m_lookahead_pos = lookahead_pos;
        d->m_lookahead_size = lookahead_size;
        d->m_dict_size = MZ_MIN(dict_size, (mz_uint)TDEFL_LZ_DICT_SIZE);
        d->m_pLZ_code_buf = lz.m_pLZ_code_buf;
        d->m_pLZ_flags = lz.m_pLZ_flags;
        d->m_num_flags_left = lz.m_num_flags_left;
        d->m_pSrc = pSrc;
        d->m_src_buf_left = src_buf_left;
        d->m_saved_match_len = saved_match_len;
        d->m_saved_match_dist = saved_match_dist;
        d->m_saved_lit = saved_lit;
        return MZ_TRUE;
    }

    /* Task miniz-0045: the loop reads its flags only in four tests, all on TDEFL_RLE_MATCHES,
       TDEFL_FORCE_ALL_RAW_BLOCKS, TDEFL_FILTER_MATCHES or greedy parsing. When none of them is set (lazy parsing,
       levels 4 to 9 of mz_deflate), every one of those tests is false, and the body is compiled with flags 0 and
       greedy_parsing 0: the tests disappear from the choice made at each position, and the values they read no
       longer take registers in the loop. When, as well, both budgets of m_max_probes are 3 or more (they are set by
       tdefl_init only), tdefl_find_match is told so by long_budget and skips its test of the budget. Otherwise the
       body runs as before, with the compressor's own flags. Same tests' outcomes, same choices, same symbols. */
    static mz_bool tdefl_compress_normal(tdefl_compressor *d)
    {
        if ((!d->m_greedy_parsing) && (!(d->m_flags & (TDEFL_RLE_MATCHES | TDEFL_FORCE_ALL_RAW_BLOCKS | TDEFL_FILTER_MATCHES))) &&
            (d->m_max_probes[0] > 2) && (d->m_max_probes[1] > 2))
            return tdefl_compress_normal_body(d, 0, 0, 1);
        return tdefl_compress_normal_body(d, d->m_flags, d->m_greedy_parsing, 0);
    }

    static tdefl_status tdefl_flush_output_buffer(tdefl_compressor *d)
    {
        if (d->m_pIn_buf_size)
        {
            *d->m_pIn_buf_size = d->m_pSrc - (const mz_uint8 *)d->m_pIn_buf;
        }

        if (d->m_pOut_buf_size)
        {
            size_t n = MZ_MIN(*d->m_pOut_buf_size - d->m_out_buf_ofs, d->m_output_flush_remaining);
            memcpy((mz_uint8 *)d->m_pOut_buf + d->m_out_buf_ofs, d->m_output_buf + d->m_output_flush_ofs, n);
            d->m_output_flush_ofs += (mz_uint)n;
            d->m_output_flush_remaining -= (mz_uint)n;
            d->m_out_buf_ofs += n;

            *d->m_pOut_buf_size = d->m_out_buf_ofs;
        }

        return (d->m_finished && !d->m_output_flush_remaining) ? TDEFL_STATUS_DONE : TDEFL_STATUS_OKAY;
    }

    tdefl_status tdefl_compress(tdefl_compressor *d, const void *pIn_buf, size_t *pIn_buf_size, void *pOut_buf, size_t *pOut_buf_size, tdefl_flush flush)
    {
        if (!d)
        {
            if (pIn_buf_size)
                *pIn_buf_size = 0;
            if (pOut_buf_size)
                *pOut_buf_size = 0;
            return TDEFL_STATUS_BAD_PARAM;
        }

        d->m_pIn_buf = pIn_buf;
        d->m_pIn_buf_size = pIn_buf_size;
        d->m_pOut_buf = pOut_buf;
        d->m_pOut_buf_size = pOut_buf_size;
        d->m_pSrc = (const mz_uint8 *)(pIn_buf);
        d->m_src_buf_left = pIn_buf_size ? *pIn_buf_size : 0;
        d->m_out_buf_ofs = 0;
        d->m_flush = flush;

        if (((d->m_pPut_buf_func != NULL) == ((pOut_buf != NULL) || (pOut_buf_size != NULL))) || (d->m_prev_return_status != TDEFL_STATUS_OKAY) ||
            (d->m_wants_to_finish && (flush != TDEFL_FINISH)) || (pIn_buf_size && *pIn_buf_size && !pIn_buf) || (pOut_buf_size && *pOut_buf_size && !pOut_buf))
        {
            if (pIn_buf_size)
                *pIn_buf_size = 0;
            if (pOut_buf_size)
                *pOut_buf_size = 0;
            return (d->m_prev_return_status = TDEFL_STATUS_BAD_PARAM);
        }
        d->m_wants_to_finish |= (flush == TDEFL_FINISH);

        if ((d->m_output_flush_remaining) || (d->m_finished))
            return (d->m_prev_return_status = tdefl_flush_output_buffer(d));

#if MINIZ_USE_UNALIGNED_LOADS_AND_STORES && MINIZ_LITTLE_ENDIAN
        if (((d->m_flags & TDEFL_MAX_PROBES_MASK) == 1) &&
            ((d->m_flags & TDEFL_GREEDY_PARSING_FLAG) != 0) &&
            ((d->m_flags & (TDEFL_FILTER_MATCHES | TDEFL_FORCE_ALL_RAW_BLOCKS | TDEFL_RLE_MATCHES)) == 0))
        {
            if (!tdefl_compress_fast(d))
                return d->m_prev_return_status;
        }
        else
#endif /* MINIZ_USE_UNALIGNED_LOADS_AND_STORES && MINIZ_LITTLE_ENDIAN */
        {
            if (!tdefl_compress_normal(d))
                return d->m_prev_return_status;
        }

        if ((d->m_flags & (TDEFL_WRITE_ZLIB_HEADER | TDEFL_COMPUTE_ADLER32)) && (pIn_buf))
            d->m_adler32 = (mz_uint32)mz_adler32(d->m_adler32, (const mz_uint8 *)pIn_buf, d->m_pSrc - (const mz_uint8 *)pIn_buf);

        if ((flush) && (!d->m_lookahead_size) && (!d->m_src_buf_left) && (!d->m_output_flush_remaining))
        {
            if (tdefl_flush_block(d, flush) < 0)
                return d->m_prev_return_status;
            d->m_finished = (flush == TDEFL_FINISH);
            if (flush == TDEFL_FULL_FLUSH)
            {
                MZ_CLEAR_ARR(d->m_hash);
                MZ_CLEAR_ARR(d->m_next);
                d->m_dict_size = 0;
            }
        }

        return (d->m_prev_return_status = tdefl_flush_output_buffer(d));
    }

    tdefl_status tdefl_compress_buffer(tdefl_compressor *d, const void *pIn_buf, size_t in_buf_size, tdefl_flush flush)
    {
        MZ_ASSERT(d->m_pPut_buf_func);
        return tdefl_compress(d, pIn_buf, &in_buf_size, NULL, NULL, flush);
    }

    tdefl_status tdefl_init(tdefl_compressor *d, tdefl_put_buf_func_ptr pPut_buf_func, void *pPut_buf_user, int flags)
    {
        d->m_pPut_buf_func = pPut_buf_func;
        d->m_pPut_buf_user = pPut_buf_user;
        d->m_flags = (mz_uint)(flags);
        d->m_max_probes[0] = 1 + ((flags & 0xFFF) + 2) / 3;
        d->m_greedy_parsing = (flags & TDEFL_GREEDY_PARSING_FLAG) != 0;
        d->m_max_probes[1] = 1 + (((flags & 0xFFF) >> 2) + 2) / 3;
        if (!(flags & TDEFL_NONDETERMINISTIC_PARSING_FLAG))
            MZ_CLEAR_ARR(d->m_hash);
        d->m_lookahead_pos = d->m_lookahead_size = d->m_dict_size = d->m_total_lz_bytes = d->m_lz_code_buf_dict_pos = d->m_bits_in = 0;
        d->m_output_flush_ofs = d->m_output_flush_remaining = d->m_finished = d->m_block_index = d->m_bit_buffer = d->m_wants_to_finish = 0;
        d->m_pLZ_code_buf = d->m_lz_code_buf + 1;
        d->m_pLZ_flags = d->m_lz_code_buf;
        *d->m_pLZ_flags = 0;
        d->m_num_flags_left = 8;
        d->m_pOutput_buf = d->m_output_buf;
        d->m_pOutput_buf_end = d->m_output_buf;
        d->m_prev_return_status = TDEFL_STATUS_OKAY;
        d->m_saved_match_dist = d->m_saved_match_len = d->m_saved_lit = 0;
        d->m_adler32 = 1;
        d->m_pIn_buf = NULL;
        d->m_pOut_buf = NULL;
        d->m_pIn_buf_size = NULL;
        d->m_pOut_buf_size = NULL;
        d->m_flush = TDEFL_NO_FLUSH;
        d->m_pSrc = NULL;
        d->m_src_buf_left = 0;
        d->m_out_buf_ofs = 0;
        if (!(flags & TDEFL_NONDETERMINISTIC_PARSING_FLAG))
            MZ_CLEAR_ARR(d->m_dict);
        memset(&d->m_huff_count[0][0], 0, sizeof(d->m_huff_count[0][0]) * TDEFL_MAX_HUFF_SYMBOLS_0);
        memset(&d->m_huff_count[1][0], 0, sizeof(d->m_huff_count[1][0]) * TDEFL_MAX_HUFF_SYMBOLS_1);
        return TDEFL_STATUS_OKAY;
    }

    tdefl_status tdefl_get_prev_return_status(tdefl_compressor *d)
    {
        return d->m_prev_return_status;
    }

    mz_uint32 tdefl_get_adler32(tdefl_compressor *d)
    {
        return d->m_adler32;
    }

    mz_bool tdefl_compress_mem_to_output(const void *pBuf, size_t buf_len, tdefl_put_buf_func_ptr pPut_buf_func, void *pPut_buf_user, int flags)
    {
        tdefl_compressor *pComp;
        mz_bool succeeded;
        if (((buf_len) && (!pBuf)) || (!pPut_buf_func))
            return MZ_FALSE;
        pComp = (tdefl_compressor *)MZ_MALLOC(sizeof(tdefl_compressor));
        if (!pComp)
            return MZ_FALSE;
        succeeded = (tdefl_init(pComp, pPut_buf_func, pPut_buf_user, flags) == TDEFL_STATUS_OKAY);
        succeeded = succeeded && (tdefl_compress_buffer(pComp, pBuf, buf_len, TDEFL_FINISH) == TDEFL_STATUS_DONE);
        MZ_FREE(pComp);
        return succeeded;
    }

    typedef struct
    {
        size_t m_size, m_capacity;
        mz_uint8 *m_pBuf;
        mz_bool m_expandable;
    } tdefl_output_buffer;

    static mz_bool tdefl_output_buffer_putter(const void *pBuf, int len, void *pUser)
    {
        tdefl_output_buffer *p = (tdefl_output_buffer *)pUser;
        size_t new_size = p->m_size + len;
        if (new_size > p->m_capacity)
        {
            size_t new_capacity = p->m_capacity;
            mz_uint8 *pNew_buf;
            if (!p->m_expandable)
                return MZ_FALSE;
            do
            {
                new_capacity = MZ_MAX(128U, new_capacity << 1U);
            } while (new_size > new_capacity);
            pNew_buf = (mz_uint8 *)MZ_REALLOC(p->m_pBuf, new_capacity);
            if (!pNew_buf)
                return MZ_FALSE;
            p->m_pBuf = pNew_buf;
            p->m_capacity = new_capacity;
        }
        memcpy((mz_uint8 *)p->m_pBuf + p->m_size, pBuf, len);
        p->m_size = new_size;
        return MZ_TRUE;
    }

    void *tdefl_compress_mem_to_heap(const void *pSrc_buf, size_t src_buf_len, size_t *pOut_len, int flags)
    {
        tdefl_output_buffer out_buf;
        MZ_CLEAR_OBJ(out_buf);
        if (!pOut_len)
            return MZ_FALSE;
        else
            *pOut_len = 0;
        out_buf.m_expandable = MZ_TRUE;
        if (!tdefl_compress_mem_to_output(pSrc_buf, src_buf_len, tdefl_output_buffer_putter, &out_buf, flags))
            return NULL;
        *pOut_len = out_buf.m_size;
        return out_buf.m_pBuf;
    }

    size_t tdefl_compress_mem_to_mem(void *pOut_buf, size_t out_buf_len, const void *pSrc_buf, size_t src_buf_len, int flags)
    {
        tdefl_output_buffer out_buf;
        MZ_CLEAR_OBJ(out_buf);
        if (!pOut_buf)
            return 0;
        out_buf.m_pBuf = (mz_uint8 *)pOut_buf;
        out_buf.m_capacity = out_buf_len;
        if (!tdefl_compress_mem_to_output(pSrc_buf, src_buf_len, tdefl_output_buffer_putter, &out_buf, flags))
            return 0;
        return out_buf.m_size;
    }

    /* level may actually range from [0,10] (10 is a "hidden" max level, where we want a bit more compression and it's fine if throughput to fall off a cliff on some files). */
    mz_uint tdefl_create_comp_flags_from_zip_params(int level, int window_bits, int strategy)
    {
        mz_uint comp_flags = s_tdefl_num_probes[(level >= 0) ? MZ_MIN(10, level) : MZ_DEFAULT_LEVEL] | ((level <= 3) ? TDEFL_GREEDY_PARSING_FLAG : 0);
        if (window_bits > 0)
            comp_flags |= TDEFL_WRITE_ZLIB_HEADER;

        if (!level)
            comp_flags |= TDEFL_FORCE_ALL_RAW_BLOCKS;
        else if (strategy == MZ_FILTERED)
            comp_flags |= TDEFL_FILTER_MATCHES;
        else if (strategy == MZ_HUFFMAN_ONLY)
            comp_flags &= ~TDEFL_MAX_PROBES_MASK;
        else if (strategy == MZ_FIXED)
            comp_flags |= TDEFL_FORCE_ALL_STATIC_BLOCKS;
        else if (strategy == MZ_RLE)
            comp_flags |= TDEFL_RLE_MATCHES;

        return comp_flags;
    }

#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4204) /* nonstandard extension used : non-constant aggregate initializer (also supported by GNU C and C99, so no big deal) */
#endif /* _MSC_VER */

    /* Simple PNG writer function by Alex Evans, 2011. Released into the public domain: https://gist.github.com/908299, more context at
     http://altdevblogaday.org/2011/04/06/a-smaller-jpg-encoder/.
     This is actually a modification of Alex's original code so PNG files generated by this function pass pngcheck. */
    void *tdefl_write_image_to_png_file_in_memory_ex(const void *pImage, int w, int h, int num_chans, size_t *pLen_out, mz_uint level, mz_bool flip)
    {
        /* Using a local copy of this array here in case MINIZ_NO_ZLIB_APIS was defined. */
        static const mz_uint s_tdefl_png_num_probes[11] = { 0, 1, 6, 32, 16, 32, 128, 256, 512, 768, 1500 };
        tdefl_compressor *pComp = (tdefl_compressor *)MZ_MALLOC(sizeof(tdefl_compressor));
        tdefl_output_buffer out_buf;
        int i, bpl = w * num_chans, y, z;
        mz_uint32 c;
        *pLen_out = 0;
        if (!pComp)
            return NULL;
        if (w <= 0 || h <= 0 || w > 0xFFFF || h > 0xFFFF || num_chans < 1 || num_chans > 4)
        {
            MZ_FREE(pComp);
            return NULL;
        }
        MZ_CLEAR_OBJ(out_buf);
        out_buf.m_expandable = MZ_TRUE;
        out_buf.m_capacity = 57 + MZ_MAX(64, (1 + bpl) * h);
        if (NULL == (out_buf.m_pBuf = (mz_uint8 *)MZ_MALLOC(out_buf.m_capacity)))
        {
            MZ_FREE(pComp);
            return NULL;
        }
        /* write dummy header */
        for (z = 41; z; --z)
            tdefl_output_buffer_putter(&z, 1, &out_buf);
        /* compress image data */
        tdefl_init(pComp, tdefl_output_buffer_putter, &out_buf, s_tdefl_png_num_probes[MZ_MIN(10, level)] | TDEFL_WRITE_ZLIB_HEADER);
        for (y = 0; y < h; ++y)
        {
            tdefl_compress_buffer(pComp, &z, 1, TDEFL_NO_FLUSH);
            tdefl_compress_buffer(pComp, (mz_uint8 *)pImage + (flip ? (h - 1 - y) : y) * bpl, bpl, TDEFL_NO_FLUSH);
        }
        if (tdefl_compress_buffer(pComp, NULL, 0, TDEFL_FINISH) != TDEFL_STATUS_DONE)
        {
            MZ_FREE(pComp);
            MZ_FREE(out_buf.m_pBuf);
            return NULL;
        }
        /* write real header */
        *pLen_out = out_buf.m_size - 41;
        {
            static const mz_uint8 chans[] = { 0x00, 0x00, 0x04, 0x02, 0x06 };
            mz_uint8 pnghdr[41] = { 0x89, 0x50, 0x4e, 0x47, 0x0d,
                                    0x0a, 0x1a, 0x0a, 0x00, 0x00,
                                    0x00, 0x0d, 0x49, 0x48, 0x44,
                                    0x52, 0x00, 0x00, 0x00, 0x00,
                                    0x00, 0x00, 0x00, 0x00, 0x08,
                                    0x00, 0x00, 0x00, 0x00, 0x00,
                                    0x00, 0x00, 0x00, 0x00, 0x00,
                                    0x00, 0x00, 0x49, 0x44, 0x41,
                                    0x54 };
            pnghdr[18] = (mz_uint8)(w >> 8);
            pnghdr[19] = (mz_uint8)w;
            pnghdr[22] = (mz_uint8)(h >> 8);
            pnghdr[23] = (mz_uint8)h;
            pnghdr[25] = chans[num_chans];
            pnghdr[33] = (mz_uint8)(*pLen_out >> 24);
            pnghdr[34] = (mz_uint8)(*pLen_out >> 16);
            pnghdr[35] = (mz_uint8)(*pLen_out >> 8);
            pnghdr[36] = (mz_uint8)*pLen_out;
            c = (mz_uint32)mz_crc32(MZ_CRC32_INIT, pnghdr + 12, 17);
            for (i = 0; i < 4; ++i, c <<= 8)
                ((mz_uint8 *)(pnghdr + 29))[i] = (mz_uint8)(c >> 24);
            memcpy(out_buf.m_pBuf, pnghdr, 41);
        }
        /* write footer (IDAT CRC-32, followed by IEND chunk) */
        if (!tdefl_output_buffer_putter("\0\0\0\0\0\0\0\0\x49\x45\x4e\x44\xae\x42\x60\x82", 16, &out_buf))
        {
            *pLen_out = 0;
            MZ_FREE(pComp);
            MZ_FREE(out_buf.m_pBuf);
            return NULL;
        }
        c = (mz_uint32)mz_crc32(MZ_CRC32_INIT, out_buf.m_pBuf + 41 - 4, *pLen_out + 4);
        for (i = 0; i < 4; ++i, c <<= 8)
            (out_buf.m_pBuf + out_buf.m_size - 16)[i] = (mz_uint8)(c >> 24);
        /* compute final size of file, grab compressed data buffer and return */
        *pLen_out += 57;
        MZ_FREE(pComp);
        return out_buf.m_pBuf;
    }
    void *tdefl_write_image_to_png_file_in_memory(const void *pImage, int w, int h, int num_chans, size_t *pLen_out)
    {
        /* Level 6 corresponds to TDEFL_DEFAULT_MAX_PROBES or MZ_DEFAULT_LEVEL (but we can't depend on MZ_DEFAULT_LEVEL being available in case the zlib API's where #defined out) */
        return tdefl_write_image_to_png_file_in_memory_ex(pImage, w, h, num_chans, pLen_out, 6, MZ_FALSE);
    }

#ifndef MINIZ_NO_MALLOC
    /* Allocate the tdefl_compressor and tinfl_decompressor structures in C so that */
    /* non-C language bindings to tdefL_ and tinfl_ API don't need to worry about */
    /* structure size and allocation mechanism. */
    tdefl_compressor *tdefl_compressor_alloc(void)
    {
        return (tdefl_compressor *)MZ_MALLOC(sizeof(tdefl_compressor));
    }

    void tdefl_compressor_free(tdefl_compressor *pComp)
    {
        MZ_FREE(pComp);
    }
#endif /* MINIZ_NO_MALLOC */

#ifdef _MSC_VER
#pragma warning(pop)
#endif /* _MSC_VER */

#ifdef __cplusplus
}
#endif /* __cplusplus */

#endif /* MINIZ_NO_DEFLATE_APIS */
