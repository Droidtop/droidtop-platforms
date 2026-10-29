# Generators

Everything here is run by hand or by CI; the output is reviewed and committed, never auto-published. The tree
(`players/`, `bios/`, `platforms/`, `engines/`, ...) is the source of truth; `build.py` composes the rest from it.

## The build

- `build.py` validates the tree and regenerates `index.json`, `legacy/*.json` and the repository-root `*-database.json`.
  `build.py --check` fails when they differ from the tree (CI, and the pre-commit hook `install-hooks.sh` links in).
  It also holds the validation of `setup`, `saves` and `install` rows (docs/FORMAT.md).

## Dataset generators

Each writes **rows into the tree** (one file per id, named in the collection's `_order.json`) through `tree.py`, then you run
`build.py`. None writes a composed monolith.

- `from_batocera.py` rewrites `bios/<system>.json` from Batocera's `batocera-systems` (a verbatim copy is in `sources/`); a row
  keeps any key Batocera does not own. Re-running it on the committed source changes nothing.
- `from_esde.py <es-de-checkout>` adds `players/<id>.json` for ES-DE mobile's standalone-emulator commands (`es_systems.xml`,
  `es_find_rules.xml`). A row already in the tree wins; commands it cannot express are reported, never guessed.
- `from_daijishou.py <workdir>` adds `players/<id>.json` from Daijisho's Start-Arguments wiki and its community platform
  database, the same way. Only shortnames that match an ES-DE system id are emitted.
- `from_esde_systems.py <es_systems.xml>` sets `retroArchCore` on `platforms/<id>.json` from ES-DE's Android file.

## The plugin indexes (run by `.github/workflows/plugins-index.yml`)

- `plugins_index.py` builds `plugins/index.json`, `origins.json` and the key history: what the Enginehost plugin repositories
  published, verified. `droidtop_plugins_index.py` builds `droidtop-plugins/index.json`, droidtop's plugin catalog.
- They share `github.py` (the one GitHub client: the token goes only to the API and not across a redirect, downloads are
  bounded, server errors are retried), `common.py` (`Rejected`, logging, `sha256_hex`) and `jws.py`, which loads Enginehost's
  `scripts/bundle_jws.py` from the checkout `ENGINEHOST_TOOLING` names: the one Python verifier of droidtop's chain signatures.

## Tests

`python3 -m unittest discover -s generator -p 'test_*.py'`. `test_jws.py` needs `ENGINEHOST_TOOLING` and `openssl`, and skips
without them.

Not here yet: iiSU, whose source format and licence are still to be researched.
