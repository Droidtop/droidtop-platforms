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
import re
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
        "legacy": "hardware-database.json",
        # New since the index: no root-level copy, only legacy/ (the root
        # copies are deprecated and take no new consumer).
        "rootCopy": False,
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


def setup_problems(setup):
    """What droidtop's EmulatorSetup.parse would refuse in a player's optional `setup` object."""
    if setup is None:
        return []
    if not isinstance(setup, dict):
        return ["must be an object"]
    problems = []
    for key in ("biosFolder", "biosFolderKey", "biosManual", "source"):
        if key in setup and not isinstance(setup[key], str):
            problems.append(key + " must be a string")
    if "biosFlat" in setup and not isinstance(setup["biosFlat"], bool):
        problems.append("biosFlat must be true or false")
    if ("biosFolder" in setup or "biosFolderKey" in setup) and not str(setup.get("source", "")).strip():
        problems.append("a BIOS folder needs a source: the emulator's code, its documentation, or a device it was seen on")
    if "biosFolder" in setup and not str(setup["biosFolder"]).startswith("/"):
        problems.append("biosFolder must be an absolute path")
    config = setup.get("config")
    if config is None:
        return problems
    if not isinstance(config, dict) or not str(config.get("file", "")).startswith("/"):
        return problems + ["config needs an absolute file"]
    if config.get("format") not in ("ini", "keyvalue"):
        problems.append("config format must be ini or keyvalue")
    for setting in config.get("settings", []):
        for key in ("id", "label", "key", "manual"):
            if not setting.get(key):
                problems.append("setting missing " + key)
        options = setting.get("options")
        if not options or not all(isinstance(o, dict) and "value" in o and o.get("label") for o in options):
            problems.append("setting " + str(setting.get("id")) + " needs options with a value and a label")
    return problems


# The root tokens a save template may start with: the agent core's saves.rs TOKENS (the one vocabulary every
# side resolves), plus the two an emulator's rule adds.
SAVE_TOKENS = [
    "<base>", "<home>", "<winAppData>", "<winLocalAppData>", "<winLocalAppDataLow>", "<winDocuments>",
    "<winPublic>", "<winProgramData>", "<winDir>", "<xdgData>", "<xdgConfig>",
]
EMULATOR_TOKENS = ["<emuSaves>", "<emuStates>"]
EMULATOR_PLACEHOLDERS = {"rom_stem", "rom_dir", "rom_name"}
ENGINE_BUILTIN_FACTS = {"game_folder"}
ENGINE_FACT_READERS = {"renpy.save_directory", "godot.name", "godot.custom_dir", "love.identity"}
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def climbs(path):
    return path.startswith("/") or ".." in path.replace("\\", "/").split("/")


def saves_problems(kind, saves):
    """What droidtop's save-rule parser would refuse, or what would make it write or search a place nobody cited."""
    if not isinstance(saves, dict):
        return ["saves must be an object"]
    problems = []
    if saves.get("v") != 1:
        problems.append("saves.v must be 1")
    if not isinstance(saves.get("source"), str) or not saves["source"].strip():
        problems.append("saves needs a source: the engine's or emulator's own code, or a shipped game, that the rule was read from")
    known = (
        {"v", "beside", "data", "user", "hostUser", "facts", "source"}
        if kind == "engine"
        else {"v", "folders", "folderKey", "statesFolders", "statesFolderKey", "config", "patterns", "states", "cards", "systems", "source"}
    )
    problems.extend("saves has the unknown field " + key for key in saves if key not in known)
    if kind == "engine":
        facts = saves.get("facts", {})
        if not isinstance(facts, dict) or any(v not in ENGINE_FACT_READERS for v in facts.values()):
            problems.append("saves.facts must name only readers droidtop has " + str(sorted(ENGINE_FACT_READERS)))
            facts = {}
        for path in saves.get("beside", []):
            if climbs(path):
                problems.append("saves.beside " + path + " must stay inside the game folder")
        for key, template in saves.get("data", {}).items():
            if key not in ("windows", "linux", "mac"):
                problems.append("saves.data has the unknown system " + key)
            if not any(template == t or template.startswith(t + "/") for t in SAVE_TOKENS):
                problems.append("saves.data " + template + " must start with a known token")
        for field in ("user", "hostUser"):
            for template in saves.get(field, []):
                if climbs(template):
                    problems.append("saves." + field + " " + template + " must stay inside the save root")
                for placeholder in PLACEHOLDER.findall(template):
                    for name in placeholder.split("|"):
                        if name not in facts and name not in ENGINE_BUILTIN_FACTS:
                            problems.append("saves." + field + " " + template + " uses {" + name + "}, which is not a fact")
        if saves.get("user") and not saves.get("data"):
            problems.append("saves.user needs saves.data")
    else:
        for field in ("folders", "statesFolders"):
            for folder in saves.get(field, []):
                if not folder.startswith("/"):
                    problems.append("saves." + field + " " + folder + " must be an absolute path")
        config = saves.get("config")
        if config is not None and (not str(config.get("file", "")).startswith("/") or config.get("format") not in ("ini", "keyvalue")):
            problems.append("saves.config needs an absolute file and a format of ini or keyvalue")
        for field in ("patterns", "states", "cards"):
            for template in saves.get(field, []):
                token = next((t for t in EMULATOR_TOKENS + ["{rom_dir}"] if template.startswith(t + "/")), None)
                if token is None:
                    problems.append("saves." + field + " " + template + " must start with <emuSaves>/, <emuStates>/ or {rom_dir}/")
                if ".." in template.split("/"):
                    problems.append("saves." + field + " " + template + " must stay inside its folder")
                for name in PLACEHOLDER.findall(template):
                    if name not in EMULATOR_PLACEHOLDERS:
                        problems.append("saves." + field + " " + template + " uses {" + name + "}, which droidtop cannot fill")
        for system, rule in saves.get("systems", {}).items():
            if not isinstance(rule, dict) or not isinstance(rule.get("patterns", []), list):
                problems.append("saves.systems." + system + " must be an object with patterns")
        if ("patterns" in saves or "cards" in saves) and not (saves.get("folders") or saves.get("folderKey")):
            problems.append("saves.patterns and cards need folders or a folderKey")
    return problems


ABIS = {"arm64-v8a", "armeabi-v7a", "x86_64", "x86"}
INSTALL_KINDS = {
    "play": ({"id"}, {"id"}),
    "fdroid": ({"id"}, {"id"}),
    "izzyondroid": ({"id"}, {"id"}),
    "github": ({"repo"}, {"repo", "asset", "abis"}),
    "gitlab": ({"repo"}, {"repo", "asset", "abis"}),
    "page": ({"url"}, {"url"}),
}
INSTALL_COMMON = {"kind", "official", "channel"}
PACKAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
REPO_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")


def install_problems(install, pkg):
    """What would make droidtop offer an install nobody cited, or one it cannot act on."""
    if not isinstance(install, dict):
        return ["install must be an object"]
    problems = []
    if install.get("v") != 1:
        problems.append("install.v must be 1")
    if not isinstance(install.get("source"), str) or not install["source"].strip():
        problems.append("install needs a source: the project's own page or README, or the store listing, each source was read from")
    problems.extend("install has the unknown field " + k for k in install if k not in {"v", "sources", "needs", "source"})
    sources = install.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("install.sources must be a non-empty list; leave `install` out when no source is confirmed")
        sources = []
    needs = install.get("needs", [])
    if not isinstance(needs, list) or not all(isinstance(n, str) and n.strip() for n in needs):
        problems.append("install.needs must be a list of names")
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or source.get("kind") not in INSTALL_KINDS:
            problems.append("install.sources entry needs a kind of " + str(sorted(INSTALL_KINDS)))
            continue
        kind = source["kind"]
        required, allowed = INSTALL_KINDS[kind]
        label = "install " + kind + " source"
        for key in required:
            if not isinstance(source.get(key), str) or not source[key].strip():
                problems.append(label + " needs " + key)
        problems.extend(label + " has the unknown field " + k for k in source if k not in allowed | INSTALL_COMMON)
        if "official" in source and not isinstance(source["official"], bool):
            problems.append(label + " official must be true or false")
        if "channel" in source and source["channel"] not in ("stable", "nightly"):
            problems.append(label + " channel must be stable or nightly")
        if kind in ("play", "fdroid", "izzyondroid") and isinstance(source.get("id"), str):
            if not PACKAGE_ID.match(source["id"]):
                problems.append(label + " id " + source["id"] + " is not a package name")
            elif source["id"] != pkg:
                problems.append(label + " id " + source["id"] + " is not this row's package " + pkg)
        if kind in ("github", "gitlab") and isinstance(source.get("repo"), str):
            if not REPO_PATH.match(source["repo"]) or (kind == "github" and source["repo"].count("/") != 1):
                problems.append(label + " repo " + source["repo"] + " must be owner/name (a GitLab group path may be deeper)")
            asset = source.get("asset")
            if isinstance(asset, str):
                try:
                    re.compile(asset)
                except re.error as error:
                    problems.append(label + " asset is not a regular expression: " + str(error))
        if kind in ("github", "gitlab"):
            # `asset` is there only where a release's file names were read; without it droidtop opens the releases page.
            abis = source.get("abis")
            if abis is not None and ("asset" not in source or not isinstance(abis, list) or not abis or not set(abis) <= ABIS):
                problems.append(label + " abis (only with an asset, some of " + str(sorted(ABIS)) + ") is wrong")
        if kind == "page" and isinstance(source.get("url"), str) and not source["url"].startswith("https://"):
            problems.append(label + " url must be https")
        key = (kind, source.get("id") or source.get("repo") or source.get("url"), source.get("channel"))
        if key in seen:
            problems.append(label + " is listed twice")
        seen.add(key)
    return problems


ENGINEHOST_PKG = "dev.enginehost"


def runners_problems(runners, registered_cores):
    """An engine row's `runners`: the apps that run its games and what they need, each cited."""
    if not isinstance(runners, dict):
        return ["runners must be an object"]
    problems = []
    if runners.get("v") != 1:
        problems.append("runners.v must be 1")
    if not isinstance(runners.get("source"), str) or not runners["source"].strip():
        problems.append("runners needs a source: the page or code each runner and core was read from")
    problems.extend("runners has the unknown field " + k for k in runners if k not in {"v", "enginehost", "source"})
    host = runners.get("enginehost")
    if host is None:
        return problems
    if not isinstance(host, dict):
        return problems + ["runners.enginehost must be an object"]
    problems.extend("runners.enginehost has the unknown field " + k for k in host if k not in {"core", "install"})
    core = host.get("core")
    if not isinstance(core, dict) or set(core) != {"repo"} or not isinstance(core["repo"], str):
        problems.append("runners.enginehost.core must be {\"repo\": \"Droidtop/enginehost-...\"}")
    elif core["repo"] not in registered_cores:
        problems.append("runners.enginehost.core " + core["repo"] + " is not in plugins/origins.json")
    if "install" in host:
        problems.extend("runners.enginehost." + p for p in install_problems(host["install"], ENGINEHOST_PKG))
    else:
        problems.append("runners.enginehost needs the install object of Enginehost itself")
    return problems


def registered_cores():
    """The core repositories plugins/origins.json registers: the only ones a runner may name."""
    path = ROOT / "plugins" / "origins.json"
    return {o["repo"] for o in json.loads(path.read_text(encoding="utf-8")).get("origins", [])} if path.is_file() else set()


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
        if "saves" in engine:
            problems.extend(path + ": " + p for p in saves_problems("engine", engine["saves"]))
        if "runners" in engine:
            problems.extend(path + ": " + p for p in runners_problems(engine["runners"], registered_cores()))
    if not any(engine.get("detect") for _, _, _, engine in collections["engines"][1]):
        problems.append("engines: no row carries a detection rule at all")
    for _, path, _, player in collections["players"][1]:
        for field in ("systemId", "label", "pkg"):
            if not player.get(field):
                problems.append(path + ": missing " + field)
        problems.extend(path + ": setup " + p for p in setup_problems(player.get("setup")))
        if "saves" in player:
            problems.extend(path + ": " + p for p in saves_problems("player", player["saves"]))
        if "install" in player:
            problems.extend(path + ": " + p for p in install_problems(player["install"], player.get("pkg")))
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
            if spec.get("rootCopy", True):
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
