# droidtop-platforms

The separately-updatable platform database behind
[droidtop](https://github.com/droidtop/droidtop) and
[enginehost](https://github.com/droidtop/enginehost): what platforms exist,
which emulator launches what, which game engine a folder is, what firmware a
system needs, and what a given handheld's hardware actually reports.

Both apps take their BUNDLED copy from a pinned checkout of this repository at
build time (a submodule at `vendor/droidtop-platforms`, copied into generated
assets, with the commit recorded in the app) and REFRESH it at runtime from
`index.json`. So a build ships one identifiable state of this repository, and
between builds the apps pull only the files that changed.

## The tree is the source; everything else is generated

```
engines/<id>.json        one registry row: detection rules, launch-strategy
                         priority, and the enginehost family/context mapping
platforms/<id>.json      one platform: name, extensions, RetroArch core, theme
players/<id>.json        one standalone-emulator launch preset
bios/<systemId>.json     one system's firmware requirements (file + md5)
hardware/<device>.json   one device's real, measured facts: panels, pad identity
controllers/<v>-<p>.json pad profiles beyond SDL's gamecontrollerdb (see its README)
```

Each collection directory also holds two files that are not data:

- `_meta.json` — the document-level fields of the composed database
  (`version`, and the `comment`/`source` line that says where the data came
  from).
- `_order.json` — the ids, in order. This exists because for `engines` the
  order IS detection precedence: rules OR, conditions AND, and the FIRST
  matching row wins. It cannot be inferred from a directory listing, and it is
  a real editorial decision — `renpy` is the first row and `renpy-fallback`
  the second to last, deliberately — so it lives in one reviewable file rather
  than being encoded in file names.

One file per registry ROW, not per engine family, for the same reason: two
rows of one family sit at opposite ends of the detection order on purpose, so
a per-family file would need an ordering mechanism the format does not have.

### Generated, never hand-edited

`generator/build.py` validates the tree and writes:

- **`index.json`** — schema version, generation time, one entry per collection
  (its composed document's shape) and one entry per file with its `sha256`.
  This is what a client fetches first; it then downloads only the files whose
  hash it does not already have.
- **`legacy/*.json`** — the monolithic documents (`engines-database.json`,
  `platforms-database.json`, `players-database.json`, `bios-database.json`)
  composed back out of the tree, byte for byte the schema the apps parse.
- **the same four files at the repository root** — DEPRECATED. They exist
  only because released app builds already fetch those exact raw URLs and must
  keep updating until they read the index. When no supported build fetches
  them any more they are deleted and `legacy/` is the only copy. Do not add a
  new consumer of the root files.

Run `generator/build.py` after any change to the tree, and
`generator/build.py --check` to verify (CI runs `--check`; so does the
pre-commit hook in `generator/hooks/pre-commit`, which
`generator/install-hooks.sh` links into `.git/hooks`).

## Where the data comes from

Console entries are GENERATED from other frontends' own maintained databases,
not hand-written (see `generator/`):

- ES-DE mobile's `es_systems.xml` + `es_find_rules.xml` (MIT) — platforms and
  most players.
- Batocera's `batocera-systems` (GPL) — the BIOS registry, the same md5/path
  data Batocera's own missing-firmware checker runs on.
- Daijishō's public Start-Arguments wiki — the original player seed.

Engine rows, Windows/Linux entries and hardware facts are droidtop's own to
author; no upstream frontend maintains those. Hardware entries record what was
read off the device itself, never a spec sheet.

The three sources keep their own system vocabularies, so a player or BIOS set
naming an id no platform has (`3ds`, `wiiware`, `bbc`) is normal and not an
error — the generator deliberately does not "validate" that away.

## Format of a composed database

```json
{
  "version": 2,
  "players": [
    {
      "id": "unique-id",
      "systemId": "es-de system id (e.g. psx, n64)",
      "label": "Display name",
      "pkg": "android.package.name",
      "argumentsTemplate": "am-start arguments with {file.uri}/{file.path} placeholders",
      "killPackageProcesses": false
    }
  ]
}
```

Ids are unique within a collection — the file name IS the id. (The split into
one-file-per-row surfaced 20 player ids that had been issued twice by the
generators; the first row of each pair kept its id and the rest gained a `-2`,
`-3` suffix.)
