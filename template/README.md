# template/ — starting a droidtop plugin repository

`new-plugin.sh <directory> <plugin-id>` makes a plugin repository from droidtop's
own sample, `samples/plugin-sample-statustile` in Droidtop/droidtop. The sample is
fetched from droidtop each time and nothing of it is copied into this
repository, so the sample, the template and `docs/plugin-api.md` cannot drift
apart: change the sample and the next new plugin has the change.

What this folder holds is only what the sample does not: `plugin-bundle.yml`, the
short caller of the shared bundle workflow (`../.github/workflows/droidtop-plugin-bundle.yml`,
pinned by commit), and the script. The workflow's inputs and the signing split
(a build job that never sees the key, a sign job that does) are described at the
top of that file. The signing secrets are the repository's own
`PLUGIN_SIGNING_KEY` and `PLUGIN_SIGNING_CERT`; nothing here creates or reads them.
