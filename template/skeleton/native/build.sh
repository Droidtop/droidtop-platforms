#!/usr/bin/env bash
# Compiles, dexes and hashes this plugin's payload from src/ in the exact shape
# droidtop's PluginBundleInstaller expects (docs/plugin-api.md). It never touches
# the signing key, so CI runs it in a job that does not hold the key; sign.sh is
# the separate signing step.
#
# Prerequisites (the shared bundle workflow provides all of them):
#   - kotlinc on PATH, d8 on PATH (Android SDK build-tools)
#   - PLUGIN_HOST_CLASSPATH: a jar of droidtop's compiled :plugin-host classes
#   - ANDROID_JAR: android.jar of the compileSdk
set -euo pipefail
cd "$(dirname "$0")"

: "${PLUGIN_HOST_CLASSPATH:?set to a jar/dir containing dev.droidtop.pluginhost.* compiled classes}"
: "${ANDROID_JAR:?set ANDROID_JAR to android.jar for the target compileSdk}"

rm -rf build
mkdir -p build/classes

kotlinc -cp "$PLUGIN_HOST_CLASSPATH:$ANDROID_JAR" -d build/classes $(find src -name '*.kt')
d8 --output build --lib "$ANDROID_JAR" $(find build/classes -name '*.class')

# classes.jar is a zip with classes.dex at its root: what the plugin process loads.
(cd build && zip -q classes.jar classes.dex)

python3 - "$(sha256sum build/classes.jar | cut -d' ' -f1)" <<'PY'
import json, sys
manifest = json.load(open("manifest.template.json"))
manifest["payload"] = [{"path": "classes.jar", "sha256": sys.argv[1]}]
json.dump(manifest, open("build/manifest.json", "w"), indent=2, sort_keys=True)
PY

echo "Built build/classes.jar and build/manifest.json (unsigned)"
