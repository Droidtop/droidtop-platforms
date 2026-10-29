"""Reading GitHub for the plugins index: the API, release downloads (bounded) and a repository's tree files."""

import github
import urllib.error

from layout import MAX_DOWNLOAD_BYTES, REPOSITORY_FILE_BRANCHES



# Server errors are retried four times in all, with a growing pause (github.py).
GITHUB = github.Client("droidtop-platforms-plugins-index", retries=4)


def api(url):
    return GITHUB.api(url)


def releases(repo):
    url = "https://api.github.com/repos/" + repo + "/releases?per_page=100"
    while url:
        page, link = api(url)
        for release in page:
            if not release.get("draft"):
                yield release
        url = github.next_link(link)


def download(url):
    return GITHUB.download(url, MAX_DOWNLOAD_BYTES)


def repository_file(repo, name):
    """A file from the repository's tree, from raw.githubusercontent.com (no API allowance)."""
    for branch in REPOSITORY_FILE_BRANCHES:
        try:
            return download("https://raw.githubusercontent.com/" + repo + "/" + branch + "/" + name)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return None
