#!/usr/bin/env python3
"""Generates bios-database.json from Batocera's real, maintained BIOS
registry (batocera-systems, GPL -- the same md5/path data Batocera's own
"missing bios" checker runs on). Nothing here is authored by hand: every
file name and md5 comes straight out of the fetched source script, so the
database can be regenerated any time upstream updates theirs.

Usage:
  curl -sL https://raw.githubusercontent.com/batocera-linux/batocera.linux/master/package/batocera/core/batocera-scripts/scripts/batocera-systems \
      -o generator/sources/batocera-systems
  python3 generator/from_batocera.py
"""
import ast
import json
import os
import sys

SRC = os.path.join(os.path.dirname(__file__), "sources", "batocera-systems")
OUT = os.path.join(os.path.dirname(__file__), "..", "bios-database.json")

# Batocera system key -> ES-DE / droidtop system id, where they differ.
# Only real, known renames; identical ids pass through untouched.
ID_MAP = {
    "3do": "3do",
    "odyssey2": "videopac",
}


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    systems = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "systems":
                    systems = ast.literal_eval(node.value)
    if systems is None:
        print("systems dict not found in source", file=sys.stderr)
        return 1

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
            out[system_id] = {
                "name": spec.get("name", system_id),
                "files": list(merged.values()),
            }

    result = {
        "version": 1,
        "source": "batocera-systems (batocera.linux, GPL) -- regenerate with generator/from_batocera.py",
        "systems": dict(sorted(out.items())),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    total = sum(len(v["files"]) for v in out.values())
    print(f"wrote {OUT}: {len(out)} systems, {total} bios files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
