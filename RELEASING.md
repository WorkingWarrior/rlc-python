# Releasing

RLC Python releases are published as GitHub Releases with source and wheel
artifacts attached.

1. Update `__version__` in `src/rlc/__init__.py`.
2. Update the test record in `COMPATIBILITY.md` if the suite changed.
3. Run the same checks as CI:

   ```sh
   uv sync --dev --locked
   uv run ruff check .
   uv run ruff format --check .
   uv run python -m unittest discover -s tests -v
   uv build
   ```

4. Commit the release changes and tag that commit with the matching version,
   for example `v0.1.0`.
5. Push the commit and tag. The Release workflow verifies that the tag matches
   the package version and creates a draft GitHub Release with both distribution
   artifacts attached.
6. Review the generated notes and attached files, then publish the draft.

PyPI publishing is not configured. Add it separately only after the project
name and trusted-publisher settings have been established on PyPI.
