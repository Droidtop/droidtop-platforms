# droidtop-plugins/ - droidtop's official plugin catalog

`index.json` lists every official droidtop plugin that has a signed release, in the plugin
catalog format droidtop reads (schema version 1; Droidtop/droidtop `docs/SPEC.md` 12a, "The
catalog"). droidtop fetches it from `raw.githubusercontent.com`, so a person finds the plugins
under Plugins > Add and installs one with a press, with no file to carry to the device.

It is generated, never edited by hand. `generator/droidtop_plugins_index.py` looks at every
public repository of the Droidtop organisation named `droidtop-plugin-*`, and lists a
`*.droidplugin.tar.xz` release asset only when

- its `origin.cert` is a certificate from droidtop's plugin master for that plugin id, valid now,
- its `manifest.sig` verifies against the key that certificate certifies, and
- its manifest is under the `droidtop` origin.

A prerelease is the `testing` stream; droidtop offers the `stable` stream only. The app checks every
bundle again on the device (signature, every payload hash), so the index can make the catalog late,
never wrong.

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
| `master-key.json` | The public half of droidtop's plugin master, the key the app pins as `MasterKey`. A reviewed change only. |
