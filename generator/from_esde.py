#!/usr/bin/env python3
"""Generate players-database.json entries from ES-DE mobile's own
maintained Android launch database (MIT):

  resources/systems/android/es_systems.xml   - per-system <command> lines
  resources/systems/android/es_find_rules.xml - %EMULATOR_X% -> package/activity

Usage: from_esde.py <es-de-checkout> [existing-db.json]

Only standalone-emulator commands are converted (RetroArch entries are
excluded: droidtop generates those from es_systems' own core mapping
separately). Commands using tokens droidtop's am-start template can't
express are SKIPPED and reported, never guessed at.

Supported placeholders: {file.path}, {file.uri}, {file.dir},
{file.basename}, {system.folder}. Double-quoted spans (the 78 real
MAME4droid commands: a multi-word cli_params string extra) pass through
verbatim -- droidtop's converter tokenizes quote-aware since 2026-08-31,
which is what made un-skipping them correct rather than hopeful.
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

def map_placeholders(value):
    """Rewrite ES-DE %TOKENS% inside a string onto droidtop placeholders;
    None = something unsupported remains."""
    value = value.replace("%ROMRAW%", "{file.path}").replace("%ROM%", "{file.path}")
    value = value.replace("%GAMEDIRRAW%", "{file.dir}").replace("%GAMEDIR%", "{file.dir}")
    # ES-DE writes the system's rom folder as <roms-root>/<system-name>;
    # droidtop's {system.folder} IS that folder, so the pair collapses.
    value = re.sub(r"%ROMPATHRAW?%/[A-Za-z0-9_-]+", "{system.folder}", value)
    value = value.replace("%BASENAME%", "{file.basename}")
    if "%" in value:
        return None
    return value

def map_value(value):
    """Map one ES-DE command value; None = unsupported."""
    if value in ("%ROMSAF%", "%ROMPROVIDER%"):
        return "{file.uri}"
    return map_placeholders(value)

def split_quoted(text):
    """Space-split honoring double quotes, mirroring droidtop's own
    converter: a "..." span stays one token WITH its quotes (the emitted
    template needs them so the converter regroups it), and a \" inside a
    span passes through untouched."""
    tokens, current, in_quotes = [], [], False
    i = 0
    while i < len(text):
        c = text[i]
        if in_quotes and c == "\\" and i + 1 < len(text) and text[i + 1] == '"':
            current.append('\\"')
            i += 2
            continue
        if c == '"':
            in_quotes = not in_quotes
            current.append('"')
        elif c.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(c)
        i += 1
    if in_quotes:
        raise ValueError("unterminated quote: " + text)
    if current:
        tokens.append("".join(current))
    return tokens

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
        try:
            rest_tokens = split_quoted(rest)
        except ValueError:
            skipped.append((system_id, label, "unterminated quote"))
            continue
        for token in rest_tokens:
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
            elif token.startswith("%EXTRABOOLEAN_") or token.startswith("%EXTRABOOL_"):
                # ES-DE writes both spellings; DuckStation and GameHub's
                # own real commands use the short one.
                prefix = "%EXTRABOOLEAN_" if token.startswith("%EXTRABOOLEAN_") else "%EXTRABOOL_"
                key, _, value = token[len(prefix):].partition("%=")
                if "%" in value:
                    unsupported = token
                    break
                parts.append(f"--ez {key} {value}")
            elif token.startswith("%CATEGORY%="):
                # Dolphin/PPSSPP/ScummVM commands carry an intent
                # category; droidtop's converter already speaks -c.
                parts.append("-c " + token.split("=", 1)[1])
            elif token.startswith("%EXTRA_"):
                key, _, value = token[len("%EXTRA_"):].partition("%=")
                # A quoted value (MAME cli_params) keeps its quotes in
                # the emitted template; placeholders map inside it.
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
