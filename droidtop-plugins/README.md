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

| File | What it is |
| --- | --- |
| `index.json` | The catalog. Written by the workflow. |
| `master-key.json` | The public half of droidtop's plugin master, the key the app pins as `MasterKey`. A reviewed change only. |
