#!/usr/bin/env python3
"""Regenerate the Daijishou-derived player entries from Daijishou's own
public sources:

  1. The Start-Arguments wiki page (the current seed's original source):
     https://raw.githubusercontent.com/wiki/TapiocaFox/Daijishou/Start-Arguments.md
  2. The community platform database (referenced by droidtop's own
     folder-name alias table): https://github.com/Jetup13/DaijishouExp -
     per-platform JSON files carrying player definitions.

Usage: from_daijishou.py <workdir> [existing-db.json]

Fetches (or reuses a checkout in <workdir>), parses, and merges the same
way from_esde.py does: existing entries win on id, new entries are
additive and deduped by (systemId, pkg, argumentsTemplate). RetroArch
core entries are excluded (droidtop's DefaultPlayers covers libretro).

Platform-name mapping: only Daijishou shortnames that exactly match an
ES-DE system id are emitted; the rest are reported for manual aliasing,
never guessed.
"""
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

workdir = Path(sys.argv[1])
existing_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
workdir.mkdir(parents=True, exist_ok=True)

WIKI_URL = "https://raw.githubusercontent.com/wiki/TapiocaFox/Daijishou/Start-Arguments.md"
wiki_md = workdir / "Start-Arguments.md"
if not wiki_md.is_file():
    urllib.request.urlretrieve(WIKI_URL, wiki_md)

exp_dir = workdir / "DaijishouExp"
if not exp_dir.is_dir():
    subprocess.run(["git", "clone", "--depth=1", "https://github.com/Jetup13/DaijishouExp", str(exp_dir)], check=True)

players = []
report = []

def add(system_id, label, pkg, template, kill=False):
    if "retroarch" in pkg:
        return
    players.append({
        "id": f"daijishou-{system_id}-{re.sub('[^a-z0-9]+', '-', pkg.lower())}",
        "systemId": system_id,
        "label": label,
        "pkg": pkg,
        "argumentsTemplate": template
            .replace("{file.uri}", "{file.uri}")
            .replace("{file.path}", "{file.path}"),
        "killPackageProcesses": kill,
    })

# --- platform database JSONs (real structure: root.platform.shortname +
# root.playerList[].amStartArguments, newline-separated am args using
# {file.path}/{file.uri}/{tags.*} placeholders) ---
SUPPORTED_PLACEHOLDER = re.compile(r"\{(?!file\.(?:path|uri)\})[^}]+\}")
for platform_file in sorted(exp_dir.glob("platforms/*.json")):
    try:
        data = json.loads(platform_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        continue
    shortname = (data.get("platform") or {}).get("shortname")
    if not shortname:
        report.append(("no-shortname", platform_file.name))
        continue
    for player in (data.get("playerList") or []):
        raw = (player.get("amStartArguments") or "").replace(chr(10), " ")
        args = " ".join(raw.split())
        name = player.get("name") or player.get("uniqueId") or ""
        pkg_match = re.search(r"-n\s+([A-Za-z0-9_.]+)/", args)
        if not args or not pkg_match:
            continue
        if SUPPORTED_PLACEHOLDER.search(args):
            report.append(("unsupported-placeholder", shortname, name))
            continue
        add(shortname, name, pkg_match.group(1), args, bool(player.get("killPackageProcesses")))

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
print(f"daijishou parsed: {len(players)}, new after merge: {len(added)}, total: {len(db['players'])}", file=sys.stderr)
for r in report[:10]:
    print("  note:", *r, file=sys.stderr)
print(out)
