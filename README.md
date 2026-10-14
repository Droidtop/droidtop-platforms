<h1 align="center">droidtop-platforms</h1>

<p align="center">
  <b>The data behind droidtop and Enginehost.</b><br>
  Which platforms exist, which emulator launches what, which engine a folder is, what firmware a system needs, and what a handheld's hardware really reports.
</p>

<p align="center">
  <a href="https://github.com/Droidtop/droidtop-platforms/actions/workflows/generated-files.yml"><img alt="Generated files check" src="https://img.shields.io/github/actions/workflow/status/Droidtop/droidtop-platforms/generated-files.yml?branch=main&label=generated%20files&style=flat-square"></a>
  <img alt="Data, not code" src="https://img.shields.io/badge/data-JSON-555555?style=flat-square">
  <a href="LICENSE"><img alt="License: GPL-3.0" src="https://img.shields.io/github/license/Droidtop/droidtop-platforms?style=flat-square"></a>
</p>

<p align="center">
  <a href="#what-is-in-it">What is in it</a> ·
  <a href="#how-the-apps-use-it">How the apps use it</a> ·
  <a href="#where-the-data-comes-from">Sources</a> ·
  <a href="#changing-it">Changing it</a> ·
  <a href="#the-plugin-catalogs">Plugin catalogs</a> ·
  <a href="#licence">Licence</a>
</p>

This repository is the separately updatable database that [droidtop](https://github.com/Droidtop/droidtop) and [Enginehost](https://github.com/Droidtop/enginehost) read. It is mostly JSON, one small file per entry.

## What is in it

| Folder | One file is | Used for |
|---|---|---|
| `platforms/` | A platform | Name, file extensions, RetroArch core and theme |
| `players/` | A standalone-emulator launch preset | How to start a game in an installed emulator |
| `engines/` | A game-engine detection row | Telling Ren'Py, RPG Maker, KiriKiri and others apart from a folder |
| `bios/` | One system's firmware needs | Which files, with MD5 sums |
| `hardware/` | One device's measured facts | Panels and pad identity, read off the device |
| `controllers/` | A pad profile | Pads beyond SDL's gamecontrollerdb |

Hardware entries record what was read off the device itself, never a spec sheet.

## How the apps use it

Both apps take a bundled copy from a pinned checkout of this repository at build time, with the commit recorded in the app. At runtime they refresh from `index.json`, which lists every file with its SHA-256, so between builds an app downloads only the files that changed.

## Where the data comes from

Console data is generated from other frontends' own maintained databases:

- ES-DE mobile's `es_systems.xml` and `es_find_rules.xml` (MIT): platforms and most players.
- Batocera's `batocera-systems` (GPL): the BIOS registry, the same data Batocera's missing-firmware checker uses.
- Daijisho's public Start-Arguments wiki: the original player seed.

Engine rows, Windows and Linux entries and hardware facts are droidtop's own. No upstream frontend maintains them.

## Changing it

The tree is the source. Everything else is generated, never hand-edited:

- `index.json` is what apps fetch first.
- `legacy/*.json` are the monolithic documents, composed back out of the tree in the schema the apps parse.
- The same four files at the repository root are deprecated. Released app builds still fetch those URLs, so they stay until no supported build does. Do not add a new consumer.

Run `generator/build.py` after any change to the tree, and `generator/build.py --check` to verify. CI runs `--check`, and so does the pre-commit hook that `generator/install-hooks.sh` links in.

Each collection folder also holds `_meta.json` (document-level fields) and `_order.json` (the ids, in order). For `engines` the order is detection precedence: the first matching row wins, so it is a real editorial decision and lives in one reviewable file.

The shape of the composed documents, and the `setup` block that droidtop's emulator setup helper reads, are in [docs/FORMAT.md](docs/FORMAT.md). A value in `setup` must be cited from the emulator's source or seen on a device. A guessed folder or key would make droidtop write files the emulator never reads.

## The plugin catalogs

This repository also publishes two generated indexes for the apps:

- [`droidtop-plugins/`](droidtop-plugins/README.md): droidtop's official plugin catalog, with an add-catalog link and QR code.
- [`plugins/`](plugins/README.md): what the Enginehost plugin repositories have published, so Enginehost does not spend GitHub's API allowance.

[`template/`](template/README.md) starts a new droidtop plugin repository.

## Licence

GPL-3.0, see [LICENSE](LICENSE). The BIOS registry (`bios/`, `bios-database.json`) is generated from Batocera's GPL-licensed `batocera-systems`, a verbatim copy of which is kept in `generator/sources/`, so the repository as a whole carries the GPL. The more permissive inputs (ES-DE's MIT rules, the Daijisho wiki, and droidtop's own engine and hardware rows) are compatible and add no condition beyond keeping their notices.
