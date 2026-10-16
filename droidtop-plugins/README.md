# droidtop-plugins/ - droidtop's official plugin catalog

`index.json` lists every official droidtop plugin that has a signed release, in the plugin
catalog format droidtop reads (schema version 1; Droidtop/droidtop `docs/SPEC.md` 12a, "The
catalog"). droidtop fetches it from `raw.githubusercontent.com`, so a person finds the plugins
under Plugins > Add and installs one with a press, with no file to carry to the device.

It is generated, never edited by hand. `generator/droidtop_plugins_index.py` looks at every
public repository of the Droidtop organisation named `droidtop-plugin-*`, and lists a
`*.droidplugin.tar.xz` release asset only when

- its `manifest.jws` is a detached ES256 JWS over the exact `manifest.json` bytes, the repository's leaf
  certificate in `x5c`, issued by the droidtop root (`droidtop-root.pub`, the key the app pins),
- the leaf is a plugin leaf naming `urn:droidtop:origin:droidtop` and, if it names plugins, the manifest's id, and
- its manifest is under the `droidtop` origin.

Expiry dates are not checked, as the app does not check them.

Plugins have channels and categories. The owner, 2026-10-16 (Droidtop/tracker#179): "Yeah, plugins
are channeled, too. They should also have categories" (Droidtop/droidtop `docs/SPEC.md` 12a
"Channels", `docs/plugin-api.md` 1.2 "Categories"). So each release is listed with its channel as
`stream`:

- `stable`: a release that is not a pre-release;
- `unstable`: a pre-release that is one of `droidtop-plugin-bundle.yml`'s per-push builds (tags
  `plugin-unstable*` and `plugin-build*`);
- `testing`: any other pre-release.

The index keeps the newest 5 stable, 3 testing and 3 unstable releases of each plugin. droidtop
offers a channel's own line and every steadier one, stable by default. Each plugin carries the
`category` of its newest release's manifest when droidtop knows it (`sources`, `emulators`, `system`,
`sync`, `integrations`, `appearance`, `other`, or the earlier `tools`, `themes`, `social` and `games`,
which droidtop reads as their successors). Without one, droidtop shows it under `other`. The app checks
every bundle again on the device (signature, every payload hash), so the index can make the catalog
late, never wrong.

The `Plugins index` workflow runs the generator with the Enginehost one (every six hours, on
`workflow_dispatch`, and on a `plugin-published` repository dispatch, which `plugins/README.md` describes).
A release is therefore in the catalog within hours of publishing. A push that touches these files runs
`--check`, offline.

## Open it in droidtop, or browse it on the web

**[Open this catalog in droidtop](https://droidtop.github.io/add-catalog?address=https%3A%2F%2Fraw.githubusercontent.com%2Fdroidtop%2Fdroidtop-platforms%2Fmain%2Fdroidtop-plugins%2Findex.json)** on the device that has droidtop, or scan the code:

[![QR code of the link above](add-catalog-qr.svg)](https://droidtop.github.io/add-catalog?address=https%3A%2F%2Fraw.githubusercontent.com%2Fdroidtop%2Fdroidtop-platforms%2Fmain%2Fdroidtop-plugins%2Findex.json)

droidtop's own catalog is always in droidtop (Settings > Plugins > Add); the link opens it there.
<https://droidtop.github.io/> shows the same catalog as a web page: every plugin with its description,
versions and channels, permissions in plain language, signature facts and source repository, and an
"Install in droidtop" button on each (`droidtop://install-plugin?catalog=...&id=...`). That page is built
from this `index.json` by [Droidtop/droidtop.github.io](https://github.com/Droidtop/droidtop.github.io).

| File | What it is |
| --- | --- |
| `index.json` | The catalog. Written by the workflow. |
| `add-catalog-qr.svg` | The QR code of the add-catalog link above. |
| `droidtop-root.pub` | The public key of the droidtop root, the key the app pins. A reviewed change only. |
