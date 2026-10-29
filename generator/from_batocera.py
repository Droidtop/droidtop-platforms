#!/usr/bin/env python3
"""Generates the bios/ rows from Batocera's real, maintained BIOS
registry (batocera-systems, GPL -- the same md5/path data Batocera's own
"missing bios" checker runs on). Nothing here is authored by hand: every
file name and md5 comes straight out of the fetched source script, so the
database can be regenerated any time upstream updates theirs. One file per system under bios/ (bios/_order.json names them,
sorted); build.py then composes bios-database.json. A row keeps any key Batocera does not own.

Usage:
  curl -sL https://raw.githubusercontent.com/batocera-linux/batocera.linux/master/package/batocera/core/batocera-scripts/scripts/batocera-systems \
      -o generator/sources/batocera-systems
  python3 generator/from_batocera.py
  python3 generator/build.py
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "sources", "batocera-systems")

# Batocera system key -> ES-DE / droidtop system id, where they differ.
# Only real, known renames; identical ids pass through untouched.
ID_MAP = {
    "3do": "3do",
    "odyssey2": "videopac",
}


def convert(systems):
    """{system id: {"name", "files": [{"file", "md5": [...]}]}} from Batocera's `systems` dict; systems with no BIOS file are left out."""
    out = {}
    for key, spec in systems.items():
        bios_files = spec.get("biosFiles")
        if not bios_files:
            continue
        system_id = ID_MAP.get(key, key)
        merged = {}
        for entry in bios_files:
            path = entry.get("file")
            md5 = entry.get("md5")
            if not path:
                continue
            record = merged.setdefault(path, {"file": path, "md5": []})
            if md5 and md5 != "-" and md5 not in record["md5"]:
                record["md5"].append(md5)
        if merged:
            out[system_id] = {"name": spec.get("name", system_id), "files": list(merged.values())}
    return out


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        tree_ast = ast.parse(f.read())
    systems = None
    for node in ast.walk(tree_ast):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "systems":
                    systems = ast.literal_eval(node.value)
    if systems is None:
        print("systems dict not found in source", file=sys.stderr)
        return 1

    out = convert(systems)
    current = {row["systemId"]: row for row in tree.rows("bios")}
    for system_id, system in sorted(out.items()):
        row = dict(current.get(system_id, {}))
        row.update({"systemId": system_id, "name": system["name"], "files": system["files"]})
        tree.write("bios", row, sort_order=True)
    total = sum(len(v["files"]) for v in out.values())
    print(f"wrote bios/: {len(out)} systems, {total} bios files; run generator/build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
