#!/usr/bin/env python3
"""Generates platforms-database.json from ES-DE's real es_systems.xml
(gitlab.com/es-de/emulationstation-de, MIT) -- the same source droidtop's
formerly compiled-in system list was generated from. Nothing hand-typed:
ids, display names, extensions, theme folders and RetroArch core names
(first %CORE_RETROARCH%/<core>_libretro.so command) all come straight out
of ES-DE's own data.

Usage: python3 generator/from_esde_systems.py /path/to/es_systems.xml
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

OUT = os.path.join(os.path.dirname(__file__), "..", "platforms-database.json")
CORE_RE = re.compile(r"%CORE_RETROARCH%/([A-Za-z0-9_]+)_libretro\.so")


def main(path):
    tree = ET.parse(path)
    platforms = []
    for system in tree.getroot().findall("system"):
        name = system.findtext("name")
        fullname = system.findtext("fullname") or name
        if not name:
            continue
        extensions = sorted({
            ext.lstrip(".").lower()
            for ext in (system.findtext("extension") or "").split()
            if ext.startswith(".")
        })
        core = None
        for command in system.findall("command"):
            match = CORE_RE.search(command.text or "")
            if match:
                core = match.group(1)
                break
        platforms.append({
            "id": name,
            "name": fullname,
            "extensions": extensions,
            "retroArchCore": core,
            "theme": system.findtext("theme") or name,
        })
    result = {
        "version": 1,
        "source": "ES-DE es_systems.xml (linux), MIT -- regenerate with generator/from_esde_systems.py",
        "platforms": platforms,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    print(f"wrote {OUT}: {len(platforms)} platforms, {sum(1 for p in platforms if p['retroArchCore'])} with RetroArch cores")


if __name__ == "__main__":
    main(sys.argv[1])
