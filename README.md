# droidtop-platforms

The separately-updatable player/platform database for
[droidtop](https://github.com/droidtop/droidtop) — standalone-emulator
launch definitions (`players-database.json`), consumed by droidtop's
`KnownPlayers`/`PlayersDatabaseUpdater` (bundled seed + user-driven refresh
from this repository's raw URL).

## Format

```json
{
  "version": 1,
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

## Sources

Console entries are GENERATED from other frontends' own maintained
databases, not hand-written (see `generator/`):

- ES-DE mobile's `es_systems.xml` + `es_find_rules.xml` (MIT) — primary.
- Daijishō's public Start-Arguments wiki — the current seed's origin.
- iiSU's database — planned, format/license research pending.

Windows, Linux, and engine-game entries are droidtop's own to author.
