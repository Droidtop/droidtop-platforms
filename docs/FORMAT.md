# Format of a composed database

The shape of the composed documents the apps parse. For what this repository is, see the [README](../README.md).

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
      "storagePathTemplate": "optional: the same launch with {file.path}, used only when the emulator holds all-files access",
      "killPackageProcesses": false,
      "setup": "optional: what the emulator needs beyond the launch, below"
    }
  ]
}
```

`setup` is what droidtop's emulator setup helper reads for this emulator (droidtop
docs/SPEC.md "Emulator setup helper"). droidtop takes the first row of a package
that carries one, so put the same object on every row of that package. `{pkg}` in
a path is the row's `pkg`. Every value must be cited from the emulator's source
or seen on a device; a guessed folder or key would make droidtop write files the
emulator never reads.

```json
"setup": {
  "biosFolder": "absolute folder the emulator reads firmware from, or omit and use biosFolderKey",
  "biosFolderKey": "a key of the config file below whose value is that folder",
  "biosManual": "where the emulator's own menus show that folder, e.g. Settings > Directory > System/BIOS",
  "biosFlat": "optional, true when the emulator reads BIOS files from the top of its folder under any name (the PCSX2 family); droidtop then copies a file under its base name, not the bios-database subfolder",
  "source": "where the folder was read from: the emulator's code (file and line), its documentation, or the device it was seen on. Required with biosFolder or biosFolderKey",
  "config": {
    "file": "absolute path of the emulator's config file",
    "format": "ini | keyvalue",
    "writesOnExit": false,
    "settings": [
      {
        "id": "unique within the row",
        "label": "what the person reads",
        "about": "one sentence",
        "section": "INI section, omitted for keyvalue",
        "key": "the key in the file",
        "options": [ { "value": "as written in the file", "label": "as shown" } ],
        "manual": "where the same option is in the emulator's own menus"
      }
    ]
  }
}
```

A row with only `biosManual` and `source` is the honest fallback for an emulator whose BIOS is picked in its own
screens or kept where no other app can write: droidtop then says where the emulator takes it, with the emulator
one press away, and copies nothing.

droidtop keeps its own BIOS files in a games folder's `bios` folder and copies them into the emulator's folder
named here, before a launch and from the BIOS row (droidtop docs/SPEC.md 7e4 "One source of BIOS files").

Ids are unique within a collection — the file name IS the id. (The split into
one-file-per-row surfaced 20 player ids that had been issued twice by the
generators; the first row of each pair kept its id and the rest gained a `-2`,
`-3` suffix.)

## Save rules: the optional `saves` object

`saves` says where a game's saves are, so droidtop can find them and show them. It is on an engine row
(`engines/<id>.json`) or, like `setup`, on a player row, and droidtop takes the first row of a package that
carries one. It is versioned: `"v": 1`, and an app skips a `saves` whose `v` it does not know. An unknown field
inside a known `v` is refused by the generator. It never changes where a game saves. It only says where. Every
rule needs a `source`: the engine's or emulator's own code, or a shipped game, that it was read from
(`generator/build.py` fails a `saves` without one, and one that uses a token or placeholder droidtop does not
have).

Templates use Ludusavi's vocabulary, as the agent core does: a root token, then a path that may hold `*` and `?`.
The tokens are `<base>` (the game folder), `<home>`, `<winAppData>`, `<winLocalAppData>`,
`<winLocalAppDataLow>`, `<winDocuments>`, `<winPublic>`, `<winProgramData>`, `<winDir>`, `<xdgData>` and
`<xdgConfig>`.

An engine row:

```json
"saves": {
  "v": 1,
  "beside": ["game/saves"],
  "data": {"windows": "<winAppData>/RenPy", "linux": "<home>/.renpy", "mac": "<home>/Library/RenPy"},
  "user": ["{save_directory}"],
  "hostUser": ["{save_directory|game_folder}"],
  "facts": {"save_directory": "renpy.save_directory"},
  "source": "renpy.py path_to_saves; renpy/savelocation.py init"
}
```

- `beside`: paths in the game folder, for an engine that saves beside the game. A trailing `/` means the whole
  folder.
- `data`: the engine's per-user system location on each OS. Under Enginehost this is the engine family's save root
  (`<volume>/Enginehost/saves` unless the person moved it), the folder `ENGINEHOST_SAVE_PATH` and its kin point at.
  Omit it for an engine with no such location.
- `user`: the game's own paths below `data` (a template may use `{fact}`; an entry whose fact is unknown is
  skipped, never guessed). `hostUser` replaces `user` under Enginehost, where it differs (a game folder name in
  place of a name the engine would have read; a folder Enginehost names for the game).
- `facts`: named readers droidtop has, which read one value from the game's own files:
  `renpy.save_directory` (`config.save_directory` in `options.rpy`), `godot.name` and `godot.custom_dir`
  (`project.godot`), `love.identity` (`t.identity` in `conf.lua`, in the folder or in a `.love` file). Built in:
  `{game_folder}` is the game folder's name made safe as one folder name, the name Enginehost gives a game it names a
  folder for. `{a|b}` is the first of the two that is known.

A player row:

```json
"saves": {
  "v": 1,
  "folders": ["/storage/emulated/0/RetroArch/saves", "/storage/emulated/0/Android/data/{pkg}/files/saves"],
  "folderKey": "savefile_directory",
  "config": {"file": "/storage/emulated/0/Android/data/{pkg}/files/retroarch.cfg", "format": "keyvalue"},
  "patterns": ["<emuSaves>/{rom_stem}.srm", "{rom_dir}/{rom_stem}.srm"],
  "states": ["<emuStates>/{rom_stem}.state*"],
  "statesFolders": ["/storage/emulated/0/RetroArch/states"],
  "statesFolderKey": "savestate_directory",
  "source": "RetroArch platform_unix.c, configuration.c, runloop.c"
}
```

- `<emuSaves>` is every folder in `folders`, and the value of `folderKey` in `config` when the file sets one
  (`default` or empty means the cited default). `<emuStates>` is the same for `statesFolders`. `{pkg}` is the row's
  package. A pattern may also start with `{rom_dir}/`, the folder the game file is in.
- `patterns`: the game's saves. Placeholders: `{rom_stem}` (file name without extension), `{rom_name}` (with it),
  `{rom_dir}`.
- `states`: save states. They are tied to one emulator version, so droidtop looks for them but does not count them
  as the game's saves unless the person turns that on.
- `cards`: memory cards shared by every game on the emulator. They are a set of their own, never part of a
  game's `patterns`.
- `systems`: `{"<systemId>": {"patterns": [...], "states": [...], "cards": [...]}}`, replacing the emulator-wide
  lists for that system, for an emulator that saves by a different rule per system.
