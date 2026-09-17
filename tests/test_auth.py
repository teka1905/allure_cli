"""
Auth tests: an expired JWT is refreshed transparently for every command.

Run: make test  (or python -m unittest discover -s tests)
"""

import ast
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp()

from allure_cli import cli, client  # noqa: E402

BASE = "https://allure.example"
TOKEN = "api-token-123"
PROJECT = 7
ARGS = ["--url", BASE, "--token", TOKEN, "--project", str(PROJECT)]


class _Resp:
    """Minimal stand-in for an urlopen response."""

    def __init__(self, body=None, status=200):
        self.body = json.dumps(body).encode() if body is not None else b""
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Server:
    """
    Fake server: accepts 'Bearer fresh' only.
    Any other JWT gets a 401, like an expired one.
    """

    def __init__(self, oauth_fails=False):
        self.calls = []
        self.oauth_fails = oauth_fails

    def __call__(self, req, *args, **kwargs):
        url = req.full_url
        auth = req.headers.get("Authorization")
        self.calls.append((req.method, url.split("?")[0], auth))

        if "/oauth/token" in url:
            if self.oauth_fails:
                raise self._401(url)
            return _Resp({"access_token": "fresh"})
        if auth != "Bearer fresh":
            raise self._401(url)
        if req.method == "DELETE":
            return _Resp(status=204)
        if req.method == "POST":
            return _Resp({"id": 555, "name": "my case"})
        if "/__search" in url:
            return _Resp({"content": [{"id": 555, "name": "my case"}], "totalPages": 1})
        return _Resp({"id": 555, "name": "my case"})

    @staticmethod
    def _401(url):
        return urllib.error.HTTPError(
            url, 401, "Unauthorized", {}, io.BytesIO(b"expired")
        )

    @property
    def refreshed(self):
        return any("/oauth/token" in call[1] for call in self.calls)

    @property
    def oauth_attempts(self):
        return sum("/oauth/token" in call[1] for call in self.calls)


#: Stand-in for the CLI's color holder, with every code blanked out.
_NO_COLOR = type("NoColor", (), {a: "" for a in dir(cli.Colors) if not a.startswith("_")})()


class _QuietCliTest(unittest.TestCase):
    """Base: hides command output so the test run stays readable."""

    def setUp(self):
        self._streams = (sys.stdout, sys.stderr)
        sys.stdout = sys.stderr = io.StringIO()

    def tearDown(self):
        sys.stdout, sys.stderr = self._streams


class ExpiredJwtRefreshTest(_QuietCliTest):
    """Every command must survive an expired JWT sitting in the cache."""

    def setUp(self):
        super().setUp()
        self.server = _Server()
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self.server
        # Cache holds an expired JWT — as after a long gap between runs.
        client.clear_jwt_cache(BASE, TOKEN)
        client._write_jwt_cache(client._jwt_cache_path(BASE, TOKEN), "stale")
        client._memory_cache[client._cache_key(BASE, TOKEN)] = "stale"

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        super().tearDown()

    def _run(self, argv):
        sys.argv = ["allure-cli"] + argv
        return cli.main()

    def test_search_by_name(self):
        self.assertEqual(self._run(["search", "my case"] + ARGS), 0)
        self.assertTrue(self.server.refreshed)

    def test_search_by_id(self):
        self.assertEqual(self._run(["search", "555"] + ARGS), 0)
        self.assertTrue(self.server.refreshed)

    def test_create_single(self):
        self.assertEqual(self._run(["create", "my case"] + ARGS), 0)
        self.assertTrue(self.server.refreshed)

    def test_create_bulk_from_file(self):
        path = Path(tempfile.mkdtemp()) / "cases.csv"
        path.write_text("name\nbulk case\n", encoding="utf-8")
        self.assertEqual(self._run(["create", "-f", str(path)] + ARGS), 0)
        self.assertTrue(self.server.refreshed)

    def test_delete(self):
        self.assertEqual(self._run(["delete", "555", "-y"] + ARGS), 0)
        self.assertTrue(self.server.refreshed)

    def test_find_orphaned_interactive_delete(self):
        cli.input = lambda *a, **kw: "y"
        try:
            orphaned = [
                {
                    "old_test": {"id": 42, "name": "old case"},
                    "similar_tests": [],
                    "days_inactive": 99,
                }
            ]
            rc = cli._interactive_delete(BASE, TOKEN, orphaned, no_color=True)
        finally:
            del cli.input
        self.assertEqual(rc, 0)
        self.assertTrue(self.server.refreshed)
        self.assertIn(
            ("DELETE", f"{BASE}/api/testcase/42", "Bearer fresh"), self.server.calls
        )


class BulkOrphanDeletionTest(_QuietCliTest):
    """find-orphaned can delete everything at once: --yes upfront, or 'a' mid-prompt."""

    def setUp(self):
        super().setUp()
        self.server = _Server()
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self.server
        client.clear_jwt_cache(BASE, TOKEN)
        self.orphaned = [
            {"old_test": {"id": tid, "name": f"case {tid}"}, "similar_tests": [], "days_inactive": 99}
            for tid in (1, 2, 3)
        ]

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        super().tearDown()

    def _deleted_ids(self):
        return [int(call[1].rsplit("/", 1)[-1]) for call in self.server.calls if call[0] == "DELETE"]

    def test_assume_yes_deletes_all_without_prompting(self):
        def no_prompt(*a, **kw):
            raise AssertionError("--yes must not ask anything")

        cli.input = no_prompt
        try:
            rc = cli._interactive_delete(
                BASE, TOKEN, self.orphaned, no_color=True, assume_yes=True
            )
        finally:
            del cli.input
        self.assertEqual(rc, 0)
        self.assertEqual(self._deleted_ids(), [1, 2, 3])

    def test_answer_all_deletes_current_and_remaining(self):
        answers = iter(["n", "a"])          # skip the first, then take the rest
        cli.input = lambda *a, **kw: next(answers)
        try:
            rc = cli._interactive_delete(BASE, TOKEN, self.orphaned, no_color=True)
        finally:
            del cli.input
        self.assertEqual(rc, 0)
        self.assertEqual(self._deleted_ids(), [2, 3])

    def test_yes_without_delete_is_rejected(self):
        sys.argv = ["allure-cli", "find-orphaned", "--yes"] + ARGS
        self.assertEqual(cli.main(), 2)
        self.assertEqual(self._deleted_ids(), [])


class BulkRemoveEndpointTest(_QuietCliTest):
    """Deleting many test cases goes out as one request when the project is known."""

    def setUp(self):
        super().setUp()
        self.bulk_calls = []
        self.deleted_one_by_one = []
        self.bulk_status = 204
        client.clear_jwt_cache(BASE, TOKEN)
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self._server

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        super().tearDown()

    def _server(self, req, *args, **kwargs):
        url = req.full_url
        if "/oauth/token" in url:
            return _Resp({"access_token": "fresh"})
        if url.endswith("/api/testcase/bulk/remove"):
            self.bulk_calls.append(json.loads(req.data.decode()))
            if self.bulk_status != 204:
                raise urllib.error.HTTPError(
                    url, self.bulk_status, "Server Error", {}, io.BytesIO(b"nope")
                )
            return _Resp(status=204)
        if req.method == "DELETE":
            self.deleted_one_by_one.append(int(url.rsplit("/", 1)[-1]))
            return _Resp(status=204)
        return _Resp({"content": [], "totalPages": 1})

    def test_one_request_for_the_whole_batch(self):
        result = cli._delete_ids(BASE, TOKEN, [1, 2, 3], _NO_COLOR, project_id=211)
        self.assertEqual(len(self.bulk_calls), 1)
        self.assertEqual(self.deleted_one_by_one, [])
        self.assertEqual(result["deleted"], 3)

    def test_selection_payload_never_inverts(self):
        cli._delete_ids(BASE, TOKEN, [1, 2, 3], _NO_COLOR, project_id=211)
        selection = self.bulk_calls[0]["selection"]
        self.assertEqual(selection["leafsInclude"], [1, 2, 3])
        self.assertEqual(selection["projectId"], 211)
        # inverted=True would mean "delete everything except these ids"
        self.assertIs(selection["inverted"], False)

    def test_falls_back_to_one_by_one_when_bulk_fails(self):
        self.bulk_status = 500
        result = cli._delete_ids(BASE, TOKEN, [1, 2, 3], _NO_COLOR, project_id=211)
        self.assertEqual(len(self.bulk_calls), 1)
        self.assertEqual(self.deleted_one_by_one, [1, 2, 3])
        self.assertEqual(result["deleted"], 3)

    def test_without_project_deletes_one_by_one(self):
        result = cli._delete_ids(BASE, TOKEN, [1, 2], _NO_COLOR, project_id=None)
        self.assertEqual(self.bulk_calls, [])
        self.assertEqual(self.deleted_one_by_one, [1, 2])
        self.assertEqual(result["deleted"], 2)


class LegacySyntaxTest(_QuietCliTest):
    """`allure-cli "query"` without a command still searches, as the README promises."""

    def setUp(self):
        super().setUp()
        self.server = _Server()
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self.server
        client.clear_jwt_cache(BASE, TOKEN)

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        super().tearDown()

    def test_query_without_command_searches(self):
        sys.argv = ["allure-cli", "my case"] + ARGS
        self.assertEqual(cli.main(), 0)
        self.assertTrue(any("/__search" in call[1] for call in self.server.calls))

    def test_id_without_command_searches_by_id(self):
        sys.argv = ["allure-cli", "555"] + ARGS
        self.assertEqual(cli.main(), 0)
        self.assertTrue(any(call[1].endswith("/api/testcase/555") for call in self.server.calls))

    def test_bare_invocation_prints_help(self):
        sys.argv = ["allure-cli"]
        self.assertEqual(cli.main(), 0)
        self.assertIn("usage:", sys.stdout.getvalue())


class InvalidTokenTest(_QuietCliTest):
    """When the API token itself is invalid, the refresh must not loop."""

    def setUp(self):
        super().setUp()
        self.server = _Server(oauth_fails=True)
        self._real_urlopen = client.urllib.request.urlopen
        client.urllib.request.urlopen = self.server
        client.clear_jwt_cache(BASE, TOKEN)
        client._write_jwt_cache(client._jwt_cache_path(BASE, TOKEN), "stale")

    def tearDown(self):
        client.urllib.request.urlopen = self._real_urlopen
        client.clear_jwt_cache(BASE, TOKEN)
        super().tearDown()

    def test_create_reports_error_without_retry_loop(self):
        sys.argv = ["allure-cli", "create", "my case"] + ARGS
        self.assertEqual(cli.main(), 1)
        self.assertLessEqual(self.server.oauth_attempts, 2)


class NoBypassTest(unittest.TestCase):
    """
    Guard against a repeat of the bug: token refresh lives in request() only,
    so commands must not reach the network or take a JWT themselves.
    """

    #: The only functions allowed to call urlopen directly.
    TRANSPORT = {"request", "_exchange_api_token"}

    def test_api_functions_do_not_take_a_jwt(self):
        for name, func in vars(client).items():
            if name.startswith("_") or not inspect.isfunction(func):
                continue
            params = inspect.signature(func).parameters
            self.assertNotIn(
                "jwt",
                params,
                f"{name}() takes a jwt — request() must hand out the token, "
                f"otherwise the command will forget to refresh an expired one",
            )

    def test_only_transport_calls_urlopen(self):
        source = Path(client.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        # Nested functions count as part of the enclosing one: the transport may
        # split itself into helpers, while an API function must not reach the network.
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name in self.TRANSPORT:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "urlopen"
                ):
                    offenders.append(node.name)
        self.assertEqual(
            offenders,
            [],
            f"{offenders} reach the network around request(), which is where refresh lives",
        )

    def test_cli_never_handles_tokens(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "jwt",
            source.lower(),
            "the CLI must not deal with JWTs — it passes the API token only",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
