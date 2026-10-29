"""Writing generated rows into the tree (players/, bios/): the repository's sources of truth.

The dataset generators (from_batocera.py, from_esde.py, from_daijishou.py) used to write the composed monolith files, which
build.py regenerates from the tree and refuses to see edited. They now write one file per row, as from_esde_systems.py does for
platforms/, and keep `_order.json` naming the ids; `build.py` then composes the monoliths. Rows already in the tree are never
overwritten by a generator that only adds (players); bios rows are rewritten from the upstream registry, keeping any key the
registry does not own.
"""

import json
import pathlib

import build

ROOT = build.ROOT


def _directory(collection):
    return ROOT / collection


def order(collection):
    return json.loads((_directory(collection) / "_order.json").read_text(encoding="utf-8"))["order"]


def rows(collection):
    """Every row of [collection], in its _order.json order."""
    return [json.loads((_directory(collection) / (item + ".json")).read_text(encoding="utf-8")) for item in order(collection)]


def write(collection, row, sort_order=False):
    """Writes [row] as <collection>/<id>.json and names its id in _order.json (appended, or sorted in when [sort_order])."""
    id_field = build.COLLECTIONS[collection]["idField"]
    item = row[id_field]
    directory = _directory(collection)
    (directory / (item + ".json")).write_text(build.dump(row), encoding="utf-8")
    ids = order(collection)
    if item not in ids:
        ids.append(item)
        if sort_order:
            ids.sort()
        (directory / "_order.json").write_text(build.dump({"order": ids}), encoding="utf-8")
