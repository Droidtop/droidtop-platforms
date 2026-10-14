#!/usr/bin/env bash
# Signs and packages the payload build.sh made (build/manifest.json and
# build/classes.jar) into __ID__.droidplugin.tar.xz. The only script that
# touches the plugin's private key: CI runs it in the sign job with the
# repository's PLUGIN_SIGNING_KEY secret (the PATH of a PEM it wrote for the
# job). The key is never committed. If PLUGIN_SIGNING_CERT names a file (a
# certificate from droidtop's plugin master, only official plugins have one) it
# is packaged as origin.cert.
set -euo pipefail
cd "$(dirname "$0")"

: "${PLUGIN_SIGNING_KEY:?set to the plugin's P-256 private key PEM}"
: "${BUNDLE_DIR:=build}"

test -f "$BUNDLE_DIR/manifest.json" || { echo "missing $BUNDLE_DIR/manifest.json: run build.sh first" >&2; exit 1; }
test -f "$BUNDLE_DIR/classes.jar" || { echo "missing $BUNDLE_DIR/classes.jar: run build.sh first" >&2; exit 1; }

openssl dgst -sha256 -sign "$PLUGIN_SIGNING_KEY" "$BUNDLE_DIR/manifest.json" | base64 -w0 > "$BUNDLE_DIR/manifest.sig"

rm -f "$BUNDLE_DIR/origin.cert"
CERT_FILE=
if [ -n "${PLUGIN_SIGNING_CERT:-}" ]; then
  test -f "$PLUGIN_SIGNING_CERT" || { echo "PLUGIN_SIGNING_CERT is not a file" >&2; exit 1; }
  cp "$PLUGIN_SIGNING_CERT" "$BUNDLE_DIR/origin.cert"
  CERT_FILE=origin.cert
fi

tar -C "$BUNDLE_DIR" --sort=name -cf - manifest.json manifest.sig $CERT_FILE classes.jar | xz -9e > __ID__.droidplugin.tar.xz

echo "Signed __ID__.droidplugin.tar.xz"
sha256sum __ID__.droidplugin.tar.xz
