#!/usr/bin/env python3
"""Sets each platform's RetroArch core in the platforms tree from ES-DE's
real Android es_systems.xml (gitlab.com/es-de/emulationstation-de, MIT,
resources/systems/android/es_systems.xml). Nothing hand-typed.

The core is the one in the system's first RetroArch command, the
`/cores/<core>_libretro_android.so` that ES-DE hands RetroArch as its
LIBRETRO extra. It has to be the ANDROID file: RetroArch's Android cores are
not always named like the Linux ones (Nintendo 64 is
`mupen64plus_next_gles3` on Android, `mupen64plus_next` on Linux; arcade
systems use `mamearcade`), and a core name RetroArch does not have makes
droidtop's generated RetroArch launch name a file that does not exist. A
system whose Android entry has no RetroArch command gets no core.

Only the `retroArchCore` field of platforms/<id>.json is written; ids,
names, extensions and themes are the tree's own. Run generator/build.py
afterwards to regenerate the derived files.

Usage: python3 generator/from_esde_systems.py /path/to/android/es_systems.xml
"""
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

PLATFORMS_DIR = pathlib.Path(__file__).resolve().parent.parent / "platforms"
CORE_RE = re.compile(r"%EMULATOR_RETROARCH%.*?/cores/([A-Za-z0-9_]+)_libretro_android\.so")


def android_cores(path):
    cores = {}
    for system in ET.parse(path).getroot().findall("system"):
        name = system.findtext("name")
        if not name:
            continue
        cores[name] = None
        for command in system.findall("command"):
            match = CORE_RE.search(command.text or "")
            if match:
                cores[name] = match.group(1)
                break
    return cores


def main(path):
    cores = android_cores(path)
    changed = 0
    for file in sorted(PLATFORMS_DIR.glob("*.json")):
        if file.name.startswith("_"):
            continue
        platform = json.loads(file.read_text(encoding="utf-8"))
        if platform["id"] not in cores:
            continue
        core = cores[platform["id"]]
        if platform.get("retroArchCore") == core:
            continue
        platform["retroArchCore"] = core
        file.write_text(json.dumps(platform, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        changed += 1
    print(f"{changed} platform files changed; {sum(1 for c in cores.values() if c)} ES-DE Android systems have a RetroArch core")


if __name__ == "__main__":
    main(sys.argv[1])
