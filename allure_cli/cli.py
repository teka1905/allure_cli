"""
CLI: get Allure TestOps test case ID(s) by name.
Env: ALLURE_ENDPOINT (or ALLURE_TESTOPS_URL), ALLURE_TOKEN, ALLURE_PROJECT_ID.
"""

import argparse
import os
import sys

from .client import find_by_name


def _env(key: str, fallback_key: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is not None:
        return v
    if fallback_key:
        return os.environ.get(fallback_key)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get Allure TestOps test case ID(s) by name (search substring)."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Search query (substring of test case name). If omitted, read from stdin.",
    )
    parser.add_argument(
        "--url",
        default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
        help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
    )
    parser.add_argument(
        "--token",
        default=_env("ALLURE_TOKEN"),
        help="API token (default: ALLURE_TOKEN)",
    )
    parser.add_argument(
        "--project",
        type=int,
        default=(int(os.environ["ALLURE_PROJECT_ID"]) if os.environ.get("ALLURE_PROJECT_ID") else None),
        help="Project ID (default: ALLURE_PROJECT_ID)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=50,
        help="Max results (default: 50)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Print only IDs, one per line",
    )
    args = parser.parse_args()

    query = args.query
    if query is None:
        query = sys.stdin.read().strip()
    if not query:
        parser.error("Provide query as argument or via stdin")
        return 2

    if not args.url:
        print("Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required", file=sys.stderr)
        return 2
    if not args.token:
        print("Error: --token or ALLURE_TOKEN required", file=sys.stderr)
        return 2
    if args.project is None:
        print("Error: --project or ALLURE_PROJECT_ID required", file=sys.stderr)
        return 2

    try:
        cases = find_by_name(
            args.url,
            args.token,
            args.project,
            query,
            size=args.size,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not cases:
        if not args.quiet:
            print(f"No test cases found for: {query!r}", file=sys.stderr)
        return 0

    if args.quiet:
        for c in cases:
            print(c["id"])
        return 0

    for c in cases:
        name = c.get("name", "")
        full = c.get("fullName", "")
        print(f"{c['id']}\t{name}")
        if full and full != name:
            print(f"    {full}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
