# template/ - starting a droidtop plugin repository

`new-plugin.sh <directory> <plugin-id> [native|python]` makes a buildable plugin
repository from the skeleton in `skeleton/`:

| Kind | What the skeleton has | Entry point |
|---|---|---|
| `native` (default, `native_bundle`) | `src/plugin/Plugin.kt`, compiled with kotlinc against droidtop's `:plugin-host` and dexed with d8 | `plugin.Plugin` |
| `python` | `src/plugin.py`, hashed as it is (the payload is the source) | `handle()` in `plugin.py` |

`flutter_embed` is not in the skeleton: its build needs a pinned Flutter SDK that
the shared workflow does not install, so see docs/plugin-api.md and pass the
workflow's `prepare-script` input to install one.

The skeleton is developer scaffolding. It is never built, signed or shipped as a
plugin from this repository, and no plugin id in it is real. The plugin API
itself is documented in Droidtop/droidtop `docs/plugin-api.md`; what a new
plugin provides and asks for is declared in its `manifest.template.json`.

Each skeleton holds `build.sh` (compiles or hashes the payload, never sees a
key), `sign.sh` (the only script that does) and `manifest.template.json`.
`plugin-bundle.yml` is the short caller of the shared bundle workflow
(`../.github/workflows/droidtop-plugin-bundle.yml`, pinned by commit). Its
inputs and the signing split (a build job that never sees the key, a sign job
that does) are described at the top of that file. The signing secrets are the
new repository's own `PLUGIN_SIGNING_KEY` (and `PLUGIN_SIGNING_CERT`, only for
official plugins); nothing here creates or reads them. The generated README
says how to make a key and publish its public half.
