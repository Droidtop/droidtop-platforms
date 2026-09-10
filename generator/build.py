#!/usr/bin/env python3
"""Validate the droidtop-platforms tree and generate index.json + the legacy files.

The repository is the TREE: one file per engine, platform, player, BIOS set
and device, under the collection directories.  Everything else here is
GENERATED from it and must never be hand-edited:

  index.json          what a client fetches first: every file with its sha256,
                      so a refresh downloads only what actually changed.
  legacy/*.json       the monolithic documents the apps parsed before the
                      split, composed from the tree.
  *.json (repo root)  the same monolithic documents at the raw URLs already
                      shipped in released app builds.  DEPRECATED: they exist
                      so an installed build keeps updating until it reads the
                      index, and they go away once no supported build fetches
                      them.  See README.md.

Order matters and is not guessed: each collection directory carries an
`_order.json` naming its ids in order, because for `engines` the order IS
detection precedence (first matching row wins), and making that explicit and
reviewable in one file beats inferring it from a directory listing.

Usage:
  build.py           regenerate the derived files
  build.py --check   fail if the derived files are not what the tree says
                     (what CI and the pre-commit hook run)
"""

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEGACY_DIR = ROOT / "legacy"
INDEX_PATH = ROOT / "index.json"
SCHEMA_VERSION = 1

# name -> how the collection composes back into a monolithic document.
#   key      the document's array/object field
#   form     "array" (order is _order.json) or "object" (keyed by id)
#   idField  the id field inside an object-form file, dropped when composing
#   legacy   the monolithic file name, or None for a collection nothing
#            consumes as a monolith yet
COLLECTIONS = {
    "engines": {
        "key": "engines",
        "form": "array",
        "idField": "id",
        "legacy": "engines-database.json",
    },
    "platforms": {
        "key": "platforms",
        "form": "array",
        "idField": "id",
        "legacy": "platforms-database.json",
    },
    "players": {
        "key": "players",
        "form": "array",
        "idField": "id",
        "legacy": "players-database.json",
    },
    "bios": {
        "key": "systems",
        "form": "object",
        "idField": "systemId",
        "legacy": "bios-database.json",
    },
    "hardware": {
        "key": "devices",
        "form": "object",
        "idField": "id",
        "legacy": None,
    },
    "controllers": {
        "key": "controllers",
        "form": "object",
        "idField": "id",
        "legacy": None,
    },
}


def dump(document):
    """The repository's one JSON style: indent 1, real UTF-8, trailing newline."""
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_collection(name):
    """(meta, [(id, path, text, document)]) in _order.json order."""
    directory = ROOT / name
    if not directory.is_dir():
        raise SystemExit("missing collection directory: " + name)
    meta_path = directory / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    order_path = directory / "_order.json"
    if not order_path.is_file():
        raise SystemExit("missing " + str(order_path.relative_to(ROOT)))
    order = json.loads(order_path.read_text(encoding="utf-8"))["order"]

    on_disk = sorted(p.name[:-5] for p in directory.glob("*.json") if not p.name.startswith("_"))
    if sorted(order) != on_disk:
        missing = sorted(set(on_disk) - set(order))
        extra = sorted(set(order) - set(on_disk))
        raise SystemExit(
            name + "/_order.json does not match the directory: "
            + ("unlisted files " + str(missing) + " " if missing else "")
            + ("listed but absent " + str(extra) if extra else "")
        )
    if len(set(order)) != len(order):
        raise SystemExit(name + "/_order.json repeats an id")

    items = []
    id_field = COLLECTIONS[name]["idField"]
    for item_id in order:
        path = directory / (item_id + ".json")
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        declared = document.get(id_field)
        if declared != item_id:
            raise SystemExit(
                str(path.relative_to(ROOT)) + ": " + id_field + " is "
                + repr(declared) + ", which is not the file name"
            )
        items.append((item_id, name + "/" + item_id + ".json", text, document))
    return meta, items


def compose(name, meta, items):
    """The monolithic document this collection used to be."""
    spec = COLLECTIONS[name]
    document = {"version": meta.get("version", 1)}
    for key, value in meta.items():
        if key != "version":
            document[key] = value
    if spec["form"] == "object":
        body = {}
        for item_id, _, _, item in items:
            copy = {k: v for k, v in item.items() if k != spec["idField"]}
            body[item_id] = copy
        document[spec["key"]] = body
    else:
        document[spec["key"]] = [item for _, _, _, item in items]
    return document


def validate(collections):
    """The rules a single file cannot check for itself.

    Deliberately NOT here: "every player's systemId is a platform" and "every
    BIOS set names a platform". The collections come from three independent
    upstream vocabularies -- ES-DE's system ids (platforms), Batocera's
    (BIOS), and Daijisho's plus droidtop's own engine ids (players) -- and
    dozens of real, working rows legitimately name an id no other collection
    has (`3ds`, `wiiware`, `kirikiri`, `bbc`). A check that fails on those
    would only teach people to stop running it.
    """
    problems = []
    for _, path, _, engine in collections["engines"][1]:
        if not isinstance(engine.get("detect", []), list):
            problems.append(path + ": detect must be a list of rules")
        if not isinstance(engine.get("strategies", []), list):
            problems.append(path + ": strategies must be a list")
    if not any(engine.get("detect") for _, _, _, engine in collections["engines"][1]):
        problems.append("engines: no row carries a detection rule at all")
    for _, path, _, player in collections["players"][1]:
        for field in ("systemId", "label", "pkg"):
            if not player.get(field):
                problems.append(path + ": missing " + field)
    for _, path, _, platform in collections["platforms"][1]:
        if not platform.get("name"):
            problems.append(path + ": missing name")
    for _, path, _, system in collections["bios"][1]:
        if not isinstance(system.get("files"), list):
            problems.append(path + ": files must be a list")
    if problems:
        raise SystemExit("\n".join(problems))


def generate():
    collections = {name: read_collection(name) for name in COLLECTIONS}
    validate(collections)

    files = []
    outputs = {}
    index_collections = {}
    for name, spec in COLLECTIONS.items():
        meta, items = collections[name]
        entry = {
            "key": spec["key"],
            "form": spec["form"],
            "version": meta.get("version", 1),
            "meta": {k: v for k, v in meta.items() if k != "version"},
        }
        if spec["form"] == "object":
            entry["idField"] = spec["idField"]
        if spec["legacy"]:
            entry["legacy"] = spec["legacy"]
        index_collections[name] = entry
        for _, path, text, _ in items:
            files.append({"path": path, "collection": name, "sha256": sha256(text)})
        if spec["legacy"]:
            composed = dump(compose(name, meta, items))
            outputs["legacy/" + spec["legacy"]] = composed
            outputs[spec["legacy"]] = composed

    outputs["index.json"] = dump(
        {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "collections": index_collections,
            "files": files,
        }
    )
    return outputs


def normalized(text):
    """index.json's timestamp is the only part that legitimately changes every run."""
    document = json.loads(text)
    if isinstance(document, dict):
        document.pop("generatedAt", None)
    return json.dumps(document, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of writing")
    args = parser.parse_args()

    outputs = generate()
    LEGACY_DIR.mkdir(exist_ok=True)

    stale = []
    for relative, text in outputs.items():
        path = ROOT / relative
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        same = current == text or (
            current is not None
            and relative == "index.json"
            and normalized(current) == normalized(text)
        )
        if same:
            continue
        if args.check:
            stale.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if args.check and stale:
        print("Generated files are stale; run generator/build.py:", file=sys.stderr)
        for relative in stale:
            print("  " + relative, file=sys.stderr)
        return 1
    if not args.check:
        print("Wrote " + str(len(outputs)) + " generated files from the tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
