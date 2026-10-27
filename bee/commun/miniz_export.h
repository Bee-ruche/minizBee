/* Remplace l'en-tête miniz_export.h que CMake génère dans son dossier de construction.
   L'outillage Bee compile miniz sans CMake : la bibliothèque est liée statiquement,
   aucun attribut d'export n'est nécessaire. */
#ifndef MINIZ_EXPORT
#define MINIZ_EXPORT
#endif
