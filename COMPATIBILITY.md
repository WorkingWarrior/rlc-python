# Python port compatibility status

Status against OCaml revision `634b6c5` (RLC 1.45). The OCaml compiler is the
source of truth.

## Implemented and verified

- The distributed KFN grammar and target filtering, including overloads,
  undefined prototypes, complex and special parameters, repeated, optional,
  uncounted, fake and explicit return parameters.
- The Kepago frontend needed by all shipped runtime headers and the complete
  supplied CLANNAD corpus: declarations and arrays, expressions, blocks,
  labels, flow control, goto families, `select` variants, compile-time
  conditionals/loops, definitions, scoped definitions and inlines, hiding,
  resource files and the commonly used directives.
- OCaml-compatible distinction between `#define`/`#sdefine` (stored AST) and
  `#const`/`#set` (compile-time value), including scoped inline return macros.
- Compile-time intrinsics used by the real headers, including target-version
  predicates, `gameexe` with defaults, constant string comparisons, `array?`,
  `length`, address/variable predicates, `at` and `rlc_parse_string`.
- Prototype-driven lowering for every call shape exercised by the corpus.
  This includes special-parameter arity selection, fake parameters, explicit
  return destinations, string and integer variable checks, repeated and
  uncounted parameters, and calls written without empty parentheses.
- Integer expression normalisation observed in `expr.ml`: constant folding,
  algebraic identities, conditional-unit conversion, boolean-arm conversion,
  self-assignment elimination, compound assignments and the parentheses needed
  for RealLive bytecode's operator precedence.
- Integer and string arrays, inferred and explicit sizes, scalar fill, zeroing,
  indexing and allocation for the forms exercised by the headers and corpus.
- `strLexer`/textout/resource behaviour used by the CLANNAD `.utf` files,
  including physical-line whitespace, interpolation, names, quoting, dynamic
  select strings and materialisation of embedded double quotes.
- RealLive `select` bytecode (conditions, effects, windows and result store),
  labels, `goto`, conditional jumps, `goto_on`/`goto_case`, entrypoints and
  kidoku records.
- Complete deterministic uncompressed KPRL assembly: headers, 100 entrypoints,
  fixups, line references and bytecode. AVG2000 KP2K layout is covered by
  encoding tests.
- RealLive LZ77 compression and masking, including the historical static-method
  `MinLookahead` quirk, long-match candidate tie-breaking, lazy matching and
  end-of-buffer chain termination. The complete compilable CLANNAD corpus is
  identical after compression and masking.
- GAMEEXE parsing, including the supplied CLANNAD `Gameexe.ini`, and
  `#resource`/`#res` loading.
- CLI input encoding, output naming, target/version/compiler/KFN/GAMEEXE
  selection, debug selection, and compressed or uncompressed `.TXT` output.

The obsolete pseudo-stack bytecode generator from the early Python experiment
is not part of this repository.

## CLANNAD corpus differential result

The external validation corpus contains 205 CLANNAD scenarios. Both compilers
were run with target version 1.4.0.5,
compiler version 10002, UTF-8 source input, the distributed `reallive.kfn`, no
debug records, no metadata and uncompressed output.

- OCaml compiles: **201/205**.
- Python compiles: **201/205**.
- Complete files identical byte-for-byte: **201/201** compilable scenarios.
- Complete compressed and masked files identical byte-for-byte: **201/201**
  compilable scenarios.
- OCaml-compilable scenarios rejected by Python: **none**.
- Scenarios compiled by both but producing different bytes: **none**.
- Missing-resource inputs rejected by both: `SEEN6430` (missing
  `SEEN6430.utf`) and `SEEN6801` (missing `SEEN6801.utf`).
- Invalid/incomplete inputs rejected by both: `SEEN9802` (undeclared `VAR07`)
  and `SEEN9820` (string passed where an integer is required at line 850).

The persistent differential tests are in `tests/test_corpus_differential.py`.
Both passes require `RLC_OCAML` and `RLC_CLANNAD_CORPUS`; the full compressed
pass is enabled with `RLC_COMPRESSED_CORPUS=1`. Both latest runs passed all 201
compilable cases and classified the same four rejected inputs.

## Tests

The standalone suite contains **61 tests**, including two small regressions for
compressor behaviours that caused differences on real scenarios. The latest
self-contained run was:

```text
uv run python -m unittest discover -s tests -v

Ran 61 tests in 2.793s
OK (skipped=18)
```

The 18 skips are optional OCaml, CLANNAD-corpus and real-GAMEEXE checks. With
`RLC_OCAML` configured, all 12 self-contained differential tests pass. The
standalone repository was also revalidated over the complete external corpus:
the final uncompressed pass completed in 120.207 seconds and the
compressed/masked pass in 143.187 seconds, both with 201/201 compilable files
identical.

The self-contained suite also passes under the declared minimum Python 3.10.
An isolated installation from the built wheel contains all bundled KFN/KH
assets and successfully compiles a minimal Kepago program without an RLdev
checkout.

It covers lexer/parser behaviour, KFN loading, source-to-AST and
source-to-bytecode integration, runtime headers, real scenarios, complete KPRL
and KP2K layouts, CLI output, compression/masking and both small and full-corpus
OCaml differential comparisons.

## Still partial or not independently covered

Passing the CLANNAD corpus establishes replacement compatibility for this
specific RealLive workload, not every feature in RLC:

- Rare `strLexer.mll` operations not present in this corpus remain incomplete,
  notably full `\a`, `\res` and rewrite/delete resource-string semantics and
  every text-object-specific transformation.
- Some exotic combinations of FuncAsm tags, nested special/complex/repeated
  parameters and string interpolation are not represented by CLANNAD and need
  dedicated differential fixtures.
- Non-inline `return`/user-function semantics are not complete.
- Dramatis personae, character tables and RLdev metadata payload generation are
  not implemented. Corpus comparison deliberately used `--no-metadata`.
- Kinetic-specific opcode substitutions and restrictions are only partial.
  AVG2000 container encoding is tested from the source equations but has not
  received a real-program differential corpus run.
- Game-specific encryption-key variants beyond the verified standard RealLive
  mask, and every historical output mode, still need separate fixtures.
- The Python GAMEEXE reader accepts the real modern CLANNAD file; the historical
  OCaml reader cannot parse every modern full-file form, so shared minimal
  GAMEEXE excerpts are used for byte-for-byte intrinsic tests.
- Exact wording/recovery of every diagnostic and several historical CLI
  switches or automatic discovery behaviours remain incomplete.

These items, rather than CLANNAD scenario compilation, are what still prevent
claiming that the Python implementation is a universal drop-in replacement for
every target and mode supported by OCaml RLC.
