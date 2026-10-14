"""The plugin's one module. droidtop imports it inside its embedded interpreter
and calls these top-level functions; only the standard library is available.

  handle(call_json: str) -> str    one contract 2 envelope in, one reply out
  invoke(payload_json: str) -> str the contract 1 entry point droidtop still requires
  on_load(data_dir: str) -> None   optional
  on_unload() -> None              optional

A reply is {"ok": true, "data": {...}} or
{"ok": false, "error": {"code": "UNSUPPORTED", "message": "..."}}.
To call droidtop (a toast, a stored value, the network state) use
droidtop.host.call(api, op, args); docs/plugin-api.md lists the apis and the
permission each one needs in the manifest.
"""
import json


def handle(call_json):
    call = json.loads(call_json)
    if call.get("point") == "ui.status_tile" and call.get("op") == "state":
        return json.dumps({"ok": True, "data": {"label": "Hello", "value": "It works"}})
    return json.dumps({
        "ok": False,
        "error": {"code": "UNSUPPORTED", "message": "Unsupported: %s %s" % (call.get("point"), call.get("op"))},
    })


def invoke(payload_json):
    return json.dumps({"ok": False, "values": {}, "error": "this plugin answers contract 2 calls only"})
