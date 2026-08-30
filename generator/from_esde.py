#!/usr/bin/env python3
"""Generate players-database.json entries from ES-DE mobile's own
maintained Android launch database (MIT):

  resources/systems/android/es_systems.xml   - per-system <command> lines
  resources/systems/android/es_find_rules.xml - %EMULATOR_X% -> package/activity

Usage: from_esde.py <es-de-checkout> [existing-db.json]

Only standalone-emulator commands are converted (RetroArch entries are
excluded: droidtop generates those from es_systems' own core mapping
separately). Commands using tokens droidtop's am-start template can't
express ({file.uri}/{file.path} are the only placeholders) are SKIPPED
and reported, never guessed at.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

es_root = Path(sys.argv[1])
existing_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

# emulator name -> (package, activity)
find_rules = {}
for emulator in ET.parse(es_root / "resources/systems/android/es_find_rules.xml").getroot():
    name = emulator.get("name")
    for rule in emulator:
        if rule.get("type") == "androidpackage":
            entry = rule.find("entry")
            if entry is not None and "/" in (entry.text or ""):
                pkg, activity = entry.text.split("/", 1)
                find_rules[name] = (pkg, pkg + activity if activity.startswith(".") else activity)
            break

players = []
skipped = []

def map_value(value):
    """Map an ES-DE command value onto droidtop template placeholders; None = unsupported."""
    if value in ("%ROM%", "%ROMRAW%"):
        return "{file.path}"
    if value in ("%ROMSAF%", "%ROMPROVIDER%"):
        return "{file.uri}"
    if "%" in value:
        return None
    return value

for system in ET.parse(es_root / "resources/systems/android/es_systems.xml").getroot():
    system_id = system.findtext("name")
    for command in system.findall("command"):
        text = (command.text or "").strip()
        label = command.get("label") or system_id
        match = re.match(r"%EMULATOR_([A-Z0-9_-]+)%\s*(.*)", text)
        if not match:
            continue
        emulator_name, rest = match.group(1), match.group(2)
        if emulator_name == "RETROARCH":
            continue  # covered by droidtop's own libretro-core mapping
        resolved = find_rules.get(emulator_name)
        if not resolved:
            skipped.append((system_id, label, "no find rule"))
            continue
        pkg, activity = resolved

        parts = [f"-n {pkg}/{activity}"]
        unsupported = None
        # tokenize on spaces EXCEPT inside quotes; quoted args are
        # unsupported by droidtop's converter -> skip the whole command
        if '"' in rest:
            skipped.append((system_id, label, "quoted argument"))
            continue
        for token in rest.split():
            if token == "%ACTIVITY_CLEAR_TASK%":
                parts.append("--activity-clear-task")
            elif token == "%ACTIVITY_CLEAR_TOP%":
                parts.append("--activity-no-history") if False else parts.append("--activity-clear-top")
            elif token.startswith("%ACTION%="):
                parts.append("-a " + token.split("=", 1)[1])
            elif token.startswith("%MIMETYPE%="):
                parts.append("-t " + token.split("=", 1)[1])
            elif token.startswith("%DATA%="):
                value = map_value(token.split("=", 1)[1])
                if value is None:
                    unsupported = token
                    break
                parts.append("-d " + value)
            elif token.startswith("%EXTRAINTEGER_"):
                key, _, value = token[len("%EXTRAINTEGER_"):].partition("%=")
                if "%" in value:
                    unsupported = token
                    break
                parts.append(f"--ei {key} {value}")
            elif token.startswith("%EXTRABOOLEAN_"):
                key, _, value = token[len("%EXTRABOOLEAN_"):].partition("%=")
                if "%" in value:
                    unsupported = token
                    break
                parts.append(f"--ez {key} {value}")
            elif token.startswith("%EXTRA_"):
                key, _, value = token[len("%EXTRA_"):].partition("%=")
                mapped = map_value(value)
                if mapped is None:
                    unsupported = token
                    break
                parts.append(f"-e {key} {mapped}")
            elif token.startswith("%"):
                unsupported = token
                break
            else:
                unsupported = token
                break
        if unsupported:
            skipped.append((system_id, label, unsupported))
            continue

        players.append({
            "id": f"esde-{system_id}-{emulator_name.lower()}",
            "systemId": system_id,
            "label": label,
            "pkg": pkg,
            "argumentsTemplate": " ".join(parts),
            "killPackageProcesses": False,
        })

# merge with the existing database: existing (Daijishou-derived) entries
# win on exact id; ES-DE entries are additive, deduped against existing
# by (systemId, pkg, argumentsTemplate)
existing = []
if existing_path and existing_path.is_file():
    existing = json.load(open(existing_path))["players"]
seen_ids = {p["id"] for p in existing}
seen_shape = {(p["systemId"], p["pkg"], p["argumentsTemplate"]) for p in existing}
added = [
    p for p in players
    if p["id"] not in seen_ids and (p["systemId"], p["pkg"], p["argumentsTemplate"]) not in seen_shape
]

db = {"version": 2, "players": existing + added}
out = Path(__file__).resolve().parent.parent / "players-database.json"
json.dump(db, open(out, "w"), indent=1)
print(f"esde commands converted: {len(players)}, new after merge: {len(added)}, total: {len(db['players'])}", file=sys.stderr)
print(f"skipped (unsupported/no rule): {len(skipped)}", file=sys.stderr)
for s in skipped[:15]:
    print("  skip:", *s, file=sys.stderr)
print(out)
