#!/usr/bin/env bash
# new-plugin.sh <directory> <plugin-id> [<droidtop-ref>]
#
# Starts a droidtop plugin repository from droidtop's own sample
# (Droidtop/droidtop samples/plugin-sample-statustile), so the sample, this
# template and the docs cannot drift: the sample is fetched from droidtop each
# time, nothing of it is copied into this repository (Droidtop/tracker#198).
#
#   template/new-plugin.sh ~/my-plugin com.example.my-plugin
#
# What you get in <directory>:
#   droidtop-plugin/   the sample's build.sh, sign.sh, manifest.template.json and
#                      src/, with the sample's id replaced by <plugin-id>
#   .github/workflows/plugin-bundle.yml   a caller of the shared bundle workflow
#   README.md, DESIGN.md, LICENSE         skeletons to fill in
# Then: write your plugin in droidtop-plugin/src, rename the entry class in
# manifest.template.json, create the repository's PLUGIN_SIGNING_KEY (and
# optionally PLUGIN_SIGNING_CERT) secrets, push, and tag plugin-vX.Y.Z for a
# stable release.
set -euo pipefail
dir=${1:?usage: new-plugin.sh <directory> <plugin-id> [<droidtop-ref>]}
id=${2:?usage: new-plugin.sh <directory> <plugin-id> [<droidtop-ref>]}
ref=${3:-main}
[[ "$id" =~ ^[a-z0-9]+([.-][a-z0-9]+)+$ ]] || { echo "plugin-id must look like com.example.my-plugin" >&2; exit 1; }
[ ! -e "$dir" ] || { echo "$dir already exists" >&2; exit 1; }

here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "${tmp:?}"' EXIT
git clone -q --depth 1 --branch "$ref" --filter=blob:none --sparse https://github.com/Droidtop/droidtop.git "$tmp/droidtop"
git -C "$tmp/droidtop" sparse-checkout set samples/plugin-sample-statustile
sample="$tmp/droidtop/samples/plugin-sample-statustile"

mkdir -p "$dir/droidtop-plugin" "$dir/.github/workflows"
cp -r "$sample/." "$dir/droidtop-plugin/"
rm -f "$dir/droidtop-plugin/README.md"
grep -rl 'droidtop\.sample-statustile' "$dir/droidtop-plugin" | xargs sed -i "s/droidtop\.sample-statustile/$id/g"
cp "$here/plugin-bundle.yml" "$dir/.github/workflows/plugin-bundle.yml"
sed -i "s/__ARTIFACT__/$id/" "$dir/.github/workflows/plugin-bundle.yml"

cat > "$dir/README.md" <<R
# $id

What this plugin does, in one paragraph.

## Building

CI builds and signs it with the shared workflow in Droidtop/droidtop-platforms.
Locally: see droidtop-plugin/build.sh (it needs kotlinc, d8, the NDK and a
compiled :plugin-host).

## Releases

Every signed push to a branch is published as a pre-release (rolling
\`plugin-unstable\` and a permanent \`plugin-build.N\`); a tag \`plugin-vX.Y.Z\`
is the stable release. See CHANGELOG.md.
R
cat > "$dir/DESIGN.md" <<R
# Design

- What the plugin provides (the capabilities in manifest.template.json) and why.
- The permissions it asks for and the reason shown to the person for each.
- What it does when droidtop denies one.
R
cat > "$dir/CHANGELOG.md" <<R
# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
R
echo "Created $dir. Add a LICENSE file, then edit droidtop-plugin/manifest.template.json and src/."
