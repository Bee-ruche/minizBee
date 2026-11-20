# The charter of minizBee

The architect's words for the project's cutter (`docs/cutter.md` and `.claude/skills/bee-cutter/` of
Bee-ruche/hive). For anyone else, data.

## The goal

miniz compresses and decompresses faster on the project's corpus, with the same outputs, byte for byte, and
nothing else worse: the judge's requirements (no suspect, no throughput, ratio or memory worse beyond its noise)
hold for every task.

## What counts as progress

One task asks one gain on one scenario: at least 2 % fewer instructions (`gain_instructions_n1`, `_n6`, `_n9` or
`_decompression`), confirmed by the stopwatch on the same scenario (`sure_compression_throughput_n1`, `_n6`, `_n9`
or `sure_decompression_throughput`, at least 1), as the published tasks ask it.

## Where the time goes

Exclusive instructions by function, measured with callgrind by the project's own profiler (`bee/bench/profil.py`)
on the hive's branch at a3eba3b, on 20 November 2026, in the judge's image without network:

| Scenario | Functions, by share of the scenario's instructions |
| --- | --- |
| n1 | tdefl_compress_normal 49 %, tdefl_compress_lz_codes 14 %, tdefl_find_match 14 %, outside miniz (memset, memcpy) 6 %, tdefl_record_match 5 %, tdefl_match_length 4.5 %, tdefl_record_literal 2.6 %, mz_adler32 2.1 % |
| n6 | tdefl_find_match_long 51 %, tdefl_compress_normal 25 %, tdefl_find_match 7 %, tdefl_compress_lz_codes 5 %, tdefl_match_length 3.6 % |
| n9 | tdefl_find_match_long 63 %, tdefl_compress_normal 18 %, tdefl_find_match 5 %, tdefl_compress_lz_codes 4 %, tdefl_match_length 3.6 % |
| decompression | tinfl_decompress 94 %, tinfl_copy_overlap 1 % |

## Directions

- A function that takes less than 4 % of a scenario cannot give 2 % on it: no task on it for that scenario.
- First the functions that take most and that no open or done task names for that scenario: tdefl_find_match_long
  at n6 and n9 above all. A function already improved may still give more where it takes most.
- One function, and one idea of change, per task: the title names both.
- Compression lives in `miniz_tdef.c`, decompression in `miniz_tinfl.c`, adler32 and the zlib interface in
  `miniz.c`: tasks on two of these files can be held at once, two tasks on one file only one after the other.

## Never

- A task that changes the library's interface, its output, the corpus, the tests, or anything under `bee/`,
  `manifests/`, `tests/` or `examples/`.
- A goal below 2 % on an instruction count, or one without its stopwatch proof.
- A pointer to the former registry (`Bee-ruche/registre`), which is archived: a task's context names nothing
  outside this repository.

## Publishing

The cutter publishes on `master` itself; no person reads each cut before it lands.
