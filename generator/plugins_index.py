#!/usr/bin/env python3
"""Generate plugins/index.json: what every enginehost plugin repository has published.

Enginehost reads this ONE file from raw.githubusercontent.com before it asks
GitHub's API anything.  The API allows 60 requests an hour to an
unauthenticated address; a refresh across the eleven plugin repositories
costs more than a tenth of that, so a few refreshes from one address (a
fresh emulator instance, a shared connection) spent the allowance and the
catalog came up empty.  Here the same listing is done once, by a workflow
that has a token, and every device reads the result from a host with no API
allowance at all.

The index is a SNAPSHOT and says when it was made: enginehost falls back to
the per-origin API path for any origin this file does not name, and for the
whole file once it is older than a few days.

Run:
  plugins_index.py           write plugins/index.json when it changed
  plugins_index.py --check   fail instead of writing (CI on a normal push)

Reads plugins/origins.json for the repositories to list.  GH_TOKEN, when
set, raises the API allowance; public repositories are readable without it.
"""

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
INDEX_PATH = PLUGINS_DIR / "index.json"
ORIGINS_PATH = PLUGINS_DIR / "origins.json"
SCHEMA_VERSION = 1
RELEASE_ENVELOPE = "enginehost-release.json"

# An asset with no digest of GitHub's own is hashed here, but only when it is
# small enough that downloading it to hash it is not absurd.  The one asset
# that always matters -- the release envelope -- is a few kilobytes, and it is
# the one enginehost verifies before believing anything in it.
HASH_IF_SMALLER_THAN = 2 * 1024 * 1024

# How old the committed index may be before it is rewritten even though
# nothing changed.  Keeps `generatedAt` honest (enginehost stops trusting a
# stale index) without a commit per scheduled run.
REFRESH_AFTER = timedelta(hours=20)

# Server errors are retried this many times in all, with a growing pause.
RETRIES = 4
RETRY_PAUSE_SECONDS = 10


def with_retries(fetch):
    """Runs fetch(), again after a pause when GitHub answers with a server error.

    A single HTTP 500 while listing one repository failed the whole scheduled
    run of 2026-09-25 05:06, so the index stayed six hours behind the builds
    published that morning and Enginehost's catalog did not offer them.
    """
    for attempt in range(RETRIES):
        try:
            return fetch()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == RETRIES - 1:
                raise
        except urllib.error.URLError:
            if attempt == RETRIES - 1:
                raise
        time.sleep(RETRY_PAUSE_SECONDS * (attempt + 1))


def api(url):
    return with_retries(lambda: api_once(url))


def api_once(url):
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "droidtop-platforms-plugins-index")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8")), response.headers.get("Link")


def next_link(link):
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if any(s.strip() == 'rel="next"' for s in segments[1:]):
            return segments[0].strip().strip("<>")
    return None


def releases(repo):
    url = "https://api.github.com/repos/" + repo + "/releases?per_page=100"
    while url:
        page, link = api(url)
        for release in page:
            if not release.get("draft"):
                yield release
        url = next_link(link)


def download(url):
    return with_retries(lambda: download_once(url))


def download_once(url):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "droidtop-platforms-plugins-index")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def digest_of(asset, body=None):
    """GitHub's own digest where it has one; otherwise our own, for small assets."""
    declared = asset.get("digest") or ""
    if declared.startswith("sha256:"):
        return declared.split(":", 1)[1].lower()
    if body is None:
        if asset.get("size", 0) > HASH_IF_SMALLER_THAN:
            # Nothing is lost: the bundle carries its own signature inside and
            # is verified file by file at install time regardless.
            return None
        body = download(asset["browser_download_url"])
    return hashlib.sha256(body).hexdigest()


def stream_of(release, envelope_body):
    """The stream is the release envelope's own channel; the flag is the fallback."""
    if envelope_body is not None:
        try:
            channel = json.loads(envelope_body.decode("utf-8")).get("channel")
        except (ValueError, UnicodeDecodeError):
            channel = None
        if channel in ("stable", "testing", "unstable"):
            return channel
    return "testing" if release.get("prerelease") else "stable"


def index_for(repo, origin):
    entry = {"repo": repo, "origin": origin, "releases": []}
    for release in releases(repo):
        assets = release.get("assets") or []
        envelope = next((a for a in assets if a["name"] == RELEASE_ENVELOPE), None)
        if envelope is None:
            # A release with no envelope is not a plugin release; enginehost
            # skips it too.
            continue
        body = download(envelope["browser_download_url"])
        listed = []
        for asset in assets:
            listed.append(
                {
                    "name": asset["name"],
                    "url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                    "sha256": digest_of(asset, body if asset is envelope else None),
                }
            )
        entry["releases"].append(
            {
                "tag": release["tag_name"],
                "stream": stream_of(release, body),
                "prerelease": bool(release.get("prerelease")),
                "published_at": release.get("published_at"),
                "assets": listed,
            }
        )
    return entry


def generate():
    origins = json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))["origins"]
    entries = []
    for origin in origins:
        repo = origin["repo"]
        url = origin.get("origin") or ("https://github.com/" + repo)
        entries.append(index_for(repo, url))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "origins": entries,
    }


def dump(document):
    """The repository's one JSON style: indent 1, real UTF-8, trailing newline."""
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def body_changed(fresh, existing_text):
    if existing_text is None:
        return True
    try:
        existing = json.loads(existing_text)
    except ValueError:
        return True
    without = dict(existing)
    stamp = without.pop("generatedAt", None)
    compare = dict(fresh)
    compare.pop("generatedAt", None)
    if json.dumps(without, sort_keys=True) != json.dumps(compare, sort_keys=True):
        return True
    # Same content: rewrite only when the timestamp is old enough that
    # enginehost would soon stop trusting it.
    if not stamp:
        return True
    try:
        made = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - made > REFRESH_AFTER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of writing")
    args = parser.parse_args()

    existing = INDEX_PATH.read_text(encoding="utf-8") if INDEX_PATH.is_file() else None
    if args.check:
        # A normal push cannot check the index against GitHub without spending
        # API calls on every commit; what it checks is that the file parses,
        # names the origins it is supposed to, and is not hand-edited nonsense.
        if existing is None:
            sys.exit("plugins/index.json is missing; run generator/plugins_index.py")
        document = json.loads(existing)
        if document.get("schemaVersion") != SCHEMA_VERSION:
            sys.exit("plugins/index.json: unexpected schemaVersion")
        listed = {entry["repo"] for entry in document["origins"]}
        expected = {o["repo"] for o in json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))["origins"]}
        if listed != expected:
            sys.exit(
                "plugins/index.json does not cover plugins/origins.json: "
                + "missing " + str(sorted(expected - listed))
                + ", extra " + str(sorted(listed - expected))
            )
        print("plugins/index.json is consistent with plugins/origins.json")
        return

    try:
        fresh = generate()
    except urllib.error.HTTPError as error:
        sys.exit("GitHub answered HTTP " + str(error.code) + " while listing releases")
    if not body_changed(fresh, existing):
        print("plugins/index.json is already current")
        return
    PLUGINS_DIR.mkdir(exist_ok=True)
    INDEX_PATH.write_text(dump(fresh), encoding="utf-8")
    print("plugins/index.json written: " + str(sum(len(e["releases"]) for e in fresh["origins"])) + " releases")


if __name__ == "__main__":
    main()
