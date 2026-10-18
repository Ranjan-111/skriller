# Reference formatting record

On 2026-10-17 the source verification found pre-existing whitespace differences
in `twitter_cli/cli.py` and `twitter_cli/output.py`: one trailing space and two
blank lines had been removed. Both local files were compared with the exact
pinned GitHub commit and their Python syntax trees (including type comments)
matched. The existing files were preserved.

`PROVENANCE.json` retains the original upstream `sha256` for every acquired
file. These two records additionally include the verified `workspace_sha256`
and an explicit formatting note. Offline tests check that exact local state.
This record is not an upstream source file.

The product never imports these reference CLI/output modules. Its copied
`models.py`, `parser.py` and license in `src/skriller/_vendor/twitter` remain
byte-identical to their pinned upstream originals, with separate strict tests.
