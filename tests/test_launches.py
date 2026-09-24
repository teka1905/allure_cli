"""
Launch data tests: launches, failures and attachments commands.

Run: make test  (or python -m unittest discover -s tests)
"""

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("XDG_CACHE_HOME", tempfile.mkdtemp())

from allure_cli import cli, client  # noqa: E402

BASE = "https://allure.example"
TOKEN = "api-token-123"
PROJECT = 7
ARGS = ["--url", BASE, "--token", TOKEN, "--project", str(PROJECT), "--no-color"]

LAUNCH_ID = 10
PR_NUMBER = "15967418"  # a number inside the launch name, not a launch id
RESULT_ID = 100
#: Not JSON and not UTF-8: must reach the file untouched.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\xff binary"


class _Resp:
    """Minimal stand-in for an urlopen response."""

    def __init__(self, body=None, status=200, raw=None):
        if raw is not None:
            self.body = raw
        else:
            self.body = json.dumps(body).encode() if body is not None else b""
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _AllureServer:
    """
    Fake Allure with one launch that has one failed result and two attachments
    sharing a name. Accepts 'Bearer fresh' only, like the auth tests.
    """

    def __init__(self):
        self.calls = []
        self.launches = [
            {
                "id": LAUNCH_ID,
                "name": f"user-pr_{PR_NUMBER}-1 --seed x",
                "createdDate": 0,
                "closed": True,
            }
        ]

    def __call__(self, req, *args, **kwargs):
        parsed = urllib.parse.urlparse(req.full_url)
        path, query = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((path, query))

        if path.endswith("/oauth/token"):
            return _Resp({"access_token": "fresh"})
        if req.headers.get("Authorization") != "Bearer fresh":
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"")
            )

        if path == "/api/launch/__search" or path == "/api/launch":
            return _Resp({"content": self.launches, "totalPages": 1})
        if path == f"/api/launch/{LAUNCH_ID}" and self.launches:
            return _Resp(self.launches[0])
        if path.startswith("/api/launch/") and path.endswith("/statistic"):
            return _Resp(
                [{"status": "failed", "count": 1}, {"status": "passed", "count": 5}]
            )
        if path.startswith("/api/launch/"):
            # Allure answers 403, not 404, for a launch id that does not exist
            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", {}, io.BytesIO(b"")
            )
        if path == "/api/testresult/__search":
            return _Resp(
                {
                    "content": [{"id": RESULT_ID, "name": "login", "status": "failed"}],
                    "totalPages": 1,
                }
            )
        if path == f"/api/testresult/{RESULT_ID}":
            return _Resp(
                {
                    "id": RESULT_ID,
                    "name": "login",
                    "fullName": "tests/login.py::Scenario",
                    "status": "failed",
                    "message": "AssertionError: boom",
                    "trace": "Traceback ...\nAssertionError: boom",
                }
            )
        if path == "/api/testresult/attachment":
            return _Resp(
                {
                    "content": [
                        {
                            "id": 1,
                            "name": "shot.png",
                            "contentType": "image/png",
                            "contentLength": len(PNG_BYTES),
                        },
                        {
                            "id": 2,
                            "name": "shot.png",
                            "contentType": "image/png",
                            "contentLength": len(PNG_BYTES),
                        },
                    ],
                    "totalPages": 1,
                }
            )
        if path.startswith("/api/testresult/attachment/") and path.endswith("/content"):
            return _Resp(raw=PNG_BYTES)
        raise AssertionError(f"unexpected request {path}")

    def paths(self):
        return [path for path, _ in self.calls]


class LaunchDataTest(unittest.TestCase):
    def setUp(self):
        self._streams = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        self.server = _AllureServer()
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self.server
        client.clear_jwt_cache(BASE, TOKEN)

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        sys.stdout, sys.stderr = self._streams

    def _run(self, argv):
        sys.argv = ["allure-cli"] + argv
        return cli.main()

    def test_number_that_is_not_a_launch_id_is_searched_by_name(self):
        self.assertEqual(self._run(["failures", PR_NUMBER] + ARGS), 0)
        searches = [q for p, q in self.server.calls if p == "/api/launch/__search"]
        self.assertEqual(len(searches), 1)
        self.assertEqual(searches[0]["rql"], f'name ~= "{PR_NUMBER}"')
        self.assertIn("AssertionError: boom", sys.stdout.getvalue())

    def test_launch_id_is_used_directly(self):
        self.assertEqual(self._run(["failures", str(LAUNCH_ID)] + ARGS), 0)
        self.assertNotIn("/api/launch/__search", self.server.paths())

    def test_failures_ask_for_failed_and_broken_of_that_launch(self):
        self._run(["failures", str(LAUNCH_ID)] + ARGS)
        (query,) = [q for p, q in self.server.calls if p == "/api/testresult/__search"]
        self.assertEqual(
            query["rql"],
            f'launch = {LAUNCH_ID} and (status = "failed" or status = "broken")',
        )
        self.assertEqual(query["projectId"], str(PROJECT))

    def test_download_keeps_bytes_and_separates_repeated_names(self):
        target = Path(tempfile.mkdtemp())
        self.assertEqual(
            self._run(["failures", str(LAUNCH_ID), "--download", str(target)] + ARGS), 0
        )
        saved = sorted(p.name for p in (target / str(RESULT_ID)).iterdir())
        self.assertEqual(saved, ["shot.png", "shot_2.png"])
        self.assertEqual((target / str(RESULT_ID) / "shot.png").read_bytes(), PNG_BYTES)

    def test_download_twice_overwrites_instead_of_piling_up(self):
        target = Path(tempfile.mkdtemp())
        for _ in range(2):
            self._run(
                [
                    "attachments",
                    str(RESULT_ID),
                    "--download",
                    str(target),
                    "--no-color",
                    "--url",
                    BASE,
                    "--token",
                    TOKEN,
                ]
            )
        self.assertEqual(
            sorted(p.name for p in target.iterdir()), ["shot.png", "shot_2.png"]
        )

    def test_failures_json_carries_message_and_trace(self):
        self.assertEqual(self._run(["failures", str(LAUNCH_ID), "--json"] + ARGS), 0)
        payload = json.loads(sys.stdout.getvalue())
        self.assertEqual(payload["launch"]["id"], LAUNCH_ID)
        self.assertEqual(payload["statistic"], {"failed": 1, "passed": 5})
        (failure,) = payload["failures"]
        self.assertEqual(failure["message"], "AssertionError: boom")
        self.assertIn("Traceback", failure["trace"])

    def test_unknown_launch_is_an_error(self):
        self.server.launches = []
        self.assertEqual(self._run(["failures", "nope"] + ARGS), 1)
        self.assertNotIn("/api/testresult/__search", self.server.paths())

    def test_launches_quiet_prints_ids(self):
        self.assertEqual(self._run(["launches", "pr_", "-q"] + ARGS), 0)
        self.assertEqual(sys.stdout.getvalue().split(), [str(LAUNCH_ID)])

    def test_expired_jwt_is_refreshed_for_every_data_command(self):
        commands = [
            ["launches"] + ARGS,
            ["failures", str(LAUNCH_ID), "--download", tempfile.mkdtemp()] + ARGS,
            ["attachments", str(RESULT_ID), "--url", BASE, "--token", TOKEN],
        ]
        for argv in commands:
            with self.subTest(command=argv[0]):
                client.clear_jwt_cache(BASE, TOKEN)
                client._write_jwt_cache(client._jwt_cache_path(BASE, TOKEN), "stale")
                client._memory_cache[client._cache_key(BASE, TOKEN)] = "stale"
                self.server.calls.clear()
                self.assertEqual(self._run(argv), 0)
                self.assertIn("/api/uaa/oauth/token", self.server.paths())


class AqlQuotingTest(unittest.TestCase):
    def test_quotes_and_backslashes_are_escaped(self):
        self.assertEqual(
            client._aql_string('say "hi" \\ bye'), '"say \\"hi\\" \\\\ bye"'
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
