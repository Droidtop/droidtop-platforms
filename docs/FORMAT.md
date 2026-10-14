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

Ids are unique within a collection — the file name IS the id. (The split into
one-file-per-row surfaced 20 player ids that had been issued twice by the
generators; the first row of each pair kept its id and the rest gained a `-2`,
`-3` suffix.)
