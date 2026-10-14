#!/usr/bin/env bash
# Hashes this plugin's payload (src/plugin.py) into the shape droidtop's
# PluginBundleInstaller expects. A python plugin's payload is its source, so
# there is nothing to compile. It never touches the signing key; sign.sh is the
# separate signing step CI runs in a job that holds the key.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf build
mkdir -p build
cp src/plugin.py build/plugin.py

python3 - "$(sha256sum build/plugin.py | cut -d' ' -f1)" <<'PY'
import json, sys
manifest = json.load(open("manifest.template.json"))
manifest["payload"] = [{"path": "plugin.py", "sha256": sys.argv[1]}]
json.dump(manifest, open("build/manifest.json", "w"), indent=2, sort_keys=True)
PY

echo "Built build/plugin.py and build/manifest.json (unsigned)"
