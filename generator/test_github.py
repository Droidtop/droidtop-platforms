"""The generators' GitHub client: where the token goes, how big a download may be, when a failure is retried.

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import http.server
import os
import sys
import threading
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import github  # noqa: E402
from common import Rejected  # noqa: E402


class Server:
    """A local HTTP server answering from a list of (status, body) in turn."""

    def __init__(self, answers):
        outer = self
        self.answers = list(answers)
        self.requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                status, body = outer.answers.pop(0) if len(outer.answers) > 1 else outer.answers[0]
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/" % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Token(unittest.TestCase):
    client = github.Client("test")

    def header(self, url, api):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "secret"}):
            return self.client._request(url, api).get_header("Authorization")

    def test_the_token_goes_to_the_api(self):
        self.assertEqual("Bearer secret", self.header("https://api.github.com/repos/a/b/releases", True))

    def test_the_token_goes_nowhere_else(self):
        for url in ("https://github.com/a/b/releases/download/v1/x.tar.xz", "https://raw.githubusercontent.com/a/b/main/f", "https://objects.githubusercontent.com/x"):
            self.assertIsNone(self.header(url, False), url)

    def test_a_redirect_off_the_api_drops_it(self):
        handler = github._KeepTokenOnTheApiOnly()
        request = urllib.request.Request("https://api.github.com/repos/a/b/releases/assets/1", headers={"Authorization": "Bearer secret"})
        away = handler.redirect_request(request, None, 302, "Found", {}, "https://objects.githubusercontent.com/signed?x=1")
        self.assertIsNone(away.get_header("Authorization"))
        back = handler.redirect_request(request, None, 302, "Found", {}, "https://api.github.com/other")
        self.assertEqual("Bearer secret", back.get_header("Authorization"))


class Download(unittest.TestCase):
    def test_a_download_within_the_limit_is_returned(self):
        server = Server([(200, b"12345")])
        try:
            self.assertEqual(b"12345", github.Client("t").download(server.url, 5))
        finally:
            server.close()

    def test_a_download_past_the_limit_is_refused(self):
        server = Server([(200, b"123456")])
        try:
            with self.assertRaises(Rejected):
                github.Client("t").download(server.url, 5)
        finally:
            server.close()

    def test_a_server_error_is_retried_and_a_missing_file_is_not(self):
        server = Server([(500, b""), (200, b"ok")])
        try:
            self.assertEqual(b"ok", github.Client("t", retry_pause_seconds=0).download(server.url, 10))
            self.assertEqual(2, len(server.requests))
        finally:
            server.close()
        missing = Server([(404, b"")])
        try:
            with self.assertRaises(Exception):
                github.Client("t", retry_pause_seconds=0).download(missing.url, 10)
            self.assertEqual(1, len(missing.requests))
        finally:
            missing.close()


class Links(unittest.TestCase):
    def test_the_next_page_is_found(self):
        link = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
        self.assertEqual("https://api.github.com/x?page=2", github.next_link(link))
        self.assertIsNone(github.next_link('<https://api.github.com/x?page=1>; rel="prev"'))
        self.assertIsNone(github.next_link(None))


if __name__ == "__main__":
    unittest.main()
