# RLC Python

RLC Python is a Python port of **RLC**, the Kepago compiler from the historical
[RLdev](https://github.com/theappleman/rldev) toolchain.
It compiles Kepago source into bytecode consumed by VisualArt's RealLive family
of engines. The OCaml RLC 1.45 implementation remains the behavioural source of
truth for this project.

This is a compatibility-focused port, not a new Kepago dialect. The package
includes the original function-definition database and runtime headers needed
for normal compilation, so an RLdev checkout is not required at runtime.

## Compatibility status

The port has been tested against OCaml RLC revision `634b6c5` on the complete
205-file CLANNAD scenario corpus used during development. The reference compiler
accepts 201 files; all 201 are byte-for-byte identical when compiled by RLC
Python, both as uncompressed KPRL and as RealLive-compressed and masked output.
The remaining four inputs are rejected by both compilers: two lack referenced
`.utf` resources and two contain invalid or incomplete source.

That result establishes compatibility for this RealLive workload, not universal
compatibility with every RLC target and historical mode. Rare text-resource
rewrites, unusual nested FuncAsm parameter combinations, non-inline user
functions, RLdev metadata and dramatis-personae payloads, Kinetic-specific
behaviour, AVG2000 real-program output, game-specific encryption keys, and some
historical CLI options still need additional differential coverage. See
[COMPATIBILITY.md](COMPATIBILITY.md) for details.

## Requirements and installation

Python 3.10 or newer is required. The compiler has no third-party runtime
dependencies. Install the current development version directly from GitHub
with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/WorkingWarrior/rlc-python.git
rlc --version
```

To work on the project itself:

```sh
git clone https://github.com/WorkingWarrior/rlc-python.git
cd rlc-python
uv sync --dev
uv run rlc --help
```

## Usage

Compile a Kepago source file to the normal compressed `.TXT` form:

```sh
uv run rlc path/to/SEEN0001.org -e UTF-8 -f 1.4.0.5 -g --no-metadata
```

Use `-u` for uncompressed `.TXT.rl` output, `-o` to choose the output basename,
and `-d` to select the output directory. `--kfn` can override the bundled
`reallive.kfn`; `-i` supplies a GAMEEXE.INI file. Run `uv run rlc --help` for the
complete supported option set.

## Tests

The standard suite is self-contained:

```sh
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

Optional byte-for-byte tests use an externally built OCaml compiler. Point
`RLC_OCAML` at that executable:

```sh
RLC_OCAML=/path/to/rlc uv run python -m unittest tests.test_differential -v
```

The private/external CLANNAD corpus suite additionally requires
`RLC_CLANNAD_CORPUS` to name the directory containing the scenario tree. Set
`RLC_COMPRESSED_CORPUS=1` to enable the slower full compressed pass. A real
GAMEEXE parser check can be enabled with `RLC_GAMEEXE=/path/to/Gameexe.ini`.

```sh
RLC_OCAML=/path/to/rlc \
RLC_CLANNAD_CORPUS=/path/to/seens \
uv run python -m unittest tests.test_corpus_differential -v

RLC_OCAML=/path/to/rlc \
RLC_CLANNAD_CORPUS=/path/to/seens \
RLC_COMPRESSED_CORPUS=1 \
uv run python -m unittest tests.test_corpus_differential -v
```

## Repository layout

- `src/rlc/` — lexer, parser, semantic compiler, bytecode writer, compressor,
  CLI, and packaged runtime assets
- `tests/` — self-contained unit/integration tests and optional differential
  suites
- `COMPATIBILITY.md` — detailed validation record and known limitations
- `RELEASING.md` — maintainer checklist for tagged GitHub releases

## Licensing

The compiler and most bundled RLdev data are GPL-2.0-or-later; see [LICENSE](LICENSE).
`textout.kh` and `rlBabel.kh` are LGPL-2.1-or-later with their original special
linking exception; see [NOTICE](NOTICE), their retained headers, and
[LICENSES/LGPL-2.1-or-later.txt](LICENSES/LGPL-2.1-or-later.txt).
