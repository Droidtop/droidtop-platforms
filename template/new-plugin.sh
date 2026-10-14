#!/usr/bin/env bash
# new-plugin.sh <directory> <plugin-id> [native|python]
#
# Starts a droidtop plugin repository from the skeleton in this folder:
#
#   template/new-plugin.sh ~/my-plugin acme.my-plugin          # native (Kotlin) plugin
#   template/new-plugin.sh ~/my-plugin acme.my-plugin python    # python plugin
#
# <plugin-id> is "<origin>.<name>": the origin is you (or your organisation), and
# the same origin must be in the droidtop-plugin-key.json you publish at the
# repository's root (README.md has the key steps). "droidtop" is the official
# origin and cannot be used.
#
# What you get in <directory>:
#   droidtop-plugin/   manifest.template.json, a minimal entry point in src/,
#                      build.sh (never sees the key) and sign.sh (the only
#                      script that does)
#   .github/workflows/plugin-bundle.yml   a caller of the shared bundle workflow
#   README.md, DESIGN.md, CHANGELOG.md    skeletons to fill in
# Add a LICENSE. The skeleton is developer scaffolding: nothing in this folder is
# built, signed or shipped as a plugin itself.
set -euo pipefail
usage="usage: new-plugin.sh <directory> <plugin-id> [native|python]"
dir=${1:?$usage}
id=${2:?$usage}
kind=${3:-native}
[[ "$id" =~ ^[a-z0-9][a-z0-9_-]*\.[a-z0-9][a-z0-9._-]*$ ]] || { echo "plugin-id must look like acme.my-plugin (<origin>.<name>, lower case)" >&2; exit 1; }
origin=${id%%.*}
[ "$origin" != droidtop ] || { echo "the origin \"droidtop\" is the official one; pick your own" >&2; exit 1; }
[ "$kind" = native ] || [ "$kind" = python ] || { echo "kind must be native or python" >&2; exit 1; }
[ ! -e "$dir" ] || { echo "$dir already exists" >&2; exit 1; }

here=$(cd "$(dirname "$0")" && pwd)
skeleton="$here/skeleton/$kind"
label=${id#*.}

mkdir -p "$dir/droidtop-plugin" "$dir/.github/workflows"
cp -r "$skeleton/." "$dir/droidtop-plugin/"
grep -rl -e '__ID__' -e '__ORIGIN__' -e '__LABEL__' "$dir/droidtop-plugin" | xargs sed -i "s/__ID__/$id/g; s/__ORIGIN__/$origin/g; s/__LABEL__/$label/g"
chmod +x "$dir/droidtop-plugin/build.sh" "$dir/droidtop-plugin/sign.sh"
cp "$here/plugin-bundle.yml" "$dir/.github/workflows/plugin-bundle.yml"
sed -i "s/__ARTIFACT__/$id/" "$dir/.github/workflows/plugin-bundle.yml"

cat > "$dir/README.md" <<R
# $id

What this plugin does, in one paragraph.

## Building

CI builds and signs it with the shared workflow in Droidtop/droidtop-platforms
(see .github/workflows/plugin-bundle.yml). Locally, droidtop-plugin/build.sh
lists what it needs.

## Signing and trust

Generate the plugin's key once and keep the private half secret:

    openssl ecparam -name prime256v1 -genkey -noout -out plugin-key.pem
    gh secret set PLUGIN_SIGNING_KEY < plugin-key.pem

Publish the public half at the repository root as droidtop-plugin-key.json:

    {"origin": "$origin", "key": "<base64 of: openssl ec -in plugin-key.pem -pubout -outform DER>"}

A person trusts the origin once under Settings, Accounts and sources, Plugins,
Keys you trust (add this repository's address); droidtop shows the key's
fingerprint and asks before it trusts anything.

## Releases

Every signed push to a branch is published as a pre-release (rolling
\`plugin-unstable\` and a permanent \`plugin-build.N\`); a tag \`plugin-vX.Y.Z\`
is the stable release. See CHANGELOG.md.
R
cat > "$dir/DESIGN.md" <<R
# Design

- What the plugin provides (the "provides" in manifest.template.json) and why.
- The permissions it asks for and the reason shown to the person for each.
- What it does when droidtop denies one.
R
cat > "$dir/CHANGELOG.md" <<R
# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
R
echo "Created $dir ($kind plugin $id). Add a LICENSE, then edit droidtop-plugin/manifest.template.json and src/."
