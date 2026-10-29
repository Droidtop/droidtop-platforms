"""The one GitHub client of the index generators (plugins_index.py, droidtop_plugins_index.py).

Three rules, each learned from a way this went wrong:

- The token goes only to the API (`https://api.github.com/`). It used to be added to every URL but raw.githubusercontent.com,
  `browser_download_url`s included, and urllib copies a request's headers to the redirect it follows, so the token reached
  the signed storage host a download redirects to. The redirect handler below also drops it from any redirect that leaves the
  API.
- A download has a size limit and fails past it, instead of reading whatever the host sends.
- A server error is retried after a growing pause: one HTTP 500 while listing one repository failed the whole scheduled run of
  2026-09-25 05:06, and the index stayed six hours behind the builds published that morning.
"""

import json
import os
import time
import urllib.error
import urllib.request

from common import Rejected

API = "https://api.github.com/"


class _KeepTokenOnTheApiOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and not newurl.startswith(API):
            redirected.remove_header("Authorization")
        return redirected


_OPENER = urllib.request.build_opener(_KeepTokenOnTheApiOnly)


def next_link(link):
    """The `rel="next"` address of a `Link` header, or None."""
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if any(s.strip() == 'rel="next"' for s in segments[1:]):
            return segments[0].strip().strip("<>")
    return None


class Client:
    def __init__(self, user_agent, retries=3, retry_pause_seconds=10):
        self.user_agent = user_agent
        self.retries = retries
        self.retry_pause_seconds = retry_pause_seconds

    def _request(self, url, api):
        request = urllib.request.Request(url)
        request.add_header("User-Agent", self.user_agent)
        if api:
            request.add_header("Accept", "application/vnd.github+json")
            request.add_header("X-GitHub-Api-Version", "2022-11-28")
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token and url.startswith(API):
            request.add_header("Authorization", "Bearer " + token)
        return request

    def _retrying(self, fetch):
        for attempt in range(self.retries):
            try:
                return fetch()
            except urllib.error.HTTPError as error:
                if error.code < 500 or attempt == self.retries - 1:
                    raise
            except urllib.error.URLError:
                if attempt == self.retries - 1:
                    raise
            time.sleep(self.retry_pause_seconds * (attempt + 1))

    def api(self, url):
        """(the JSON answer, its `Link` header) of a GET to the API."""
        def once():
            with _OPENER.open(self._request(url, True), timeout=60) as response:
                return json.loads(response.read().decode("utf-8")), response.headers.get("Link")
        return self._retrying(once)

    def paged(self, url):
        """Every item of a list the API answers in pages."""
        while url:
            page, link = self.api(url)
            yield from page
            url = next_link(link)

    def download(self, url, limit, timeout=120):
        """The body at [url], at most [limit] bytes; Rejected when there is more."""
        def once():
            with _OPENER.open(self._request(url, False), timeout=timeout) as response:
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise Rejected(url + " is larger than " + str(limit) + " bytes")
                return data
        return self._retrying(once)
