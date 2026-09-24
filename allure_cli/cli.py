"""
CLI: get Allure TestOps test case ID(s) by name or ID; inspect launch failures.
Env: ALLURE_ENDPOINT (or ALLURE_TESTOPS_URL), ALLURE_TOKEN, ALLURE_PROJECT_ID.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .client import (
    AuthError,
    bulk_create_test_cases,
    bulk_delete_test_cases,
    bulk_remove_test_cases,
    create_test_case,
    download_attachment,
    find_by_id,
    find_by_name,
    find_launches_by_name,
    find_orphaned_tests,
    get_launch,
    get_launch_results,
    get_launch_statistic,
    get_recent_launches,
    get_test_case_by_id,
    get_test_result,
    get_test_result_attachments,
)


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @staticmethod
    def is_enabled() -> bool:
        """Check if colors should be enabled (TTY and not disabled)."""
        return sys.stderr.isatty() and os.environ.get("NO_COLOR") is None


def _env(key: str, fallback_key: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v is not None:
        return v
    if fallback_key:
        return os.environ.get(fallback_key)
    return None


def _add_connection_args(
    parser: argparse.ArgumentParser, *, project: bool = True
) -> None:
    """--url, --token, [--project] and --no-color, with the usual env defaults."""
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
    if project:
        parser.add_argument(
            "--project",
            type=int,
            default=(
                int(os.environ["ALLURE_PROJECT_ID"])
                if os.environ.get("ALLURE_PROJECT_ID")
                else None
            ),
            help="Project ID (default: ALLURE_PROJECT_ID)",
        )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )


def _colors(no_color: bool):
    """Colors, or a stand-in with every code blanked out."""
    if Colors.is_enabled() and not no_color:
        return Colors
    return type(
        "NoColor", (), {attr: "" for attr in dir(Colors) if not attr.startswith("_")}
    )()


def _check_connection_args(args, *, project: bool = True) -> str | None:
    """Error message for a missing --url/--token/--project, or None."""
    if not args.url:
        return "Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required"
    if not args.token:
        return "Error: --token or ALLURE_TOKEN required"
    if project and args.project is None:
        return "Error: --project or ALLURE_PROJECT_ID required"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get Allure TestOps test case by ID or search by name (substring)."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Search command (default behavior)
    search_parser = subparsers.add_parser(
        "search",
        help="Search test cases by ID or name",
    )
    search_parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Test case ID (number) or search query (substring of test case name)",
    )
    search_parser.add_argument(
        "--url",
        default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
        help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
    )
    search_parser.add_argument(
        "--token",
        default=_env("ALLURE_TOKEN"),
        help="API token (default: ALLURE_TOKEN)",
    )
    search_parser.add_argument(
        "--project",
        type=int,
        default=(
            int(os.environ["ALLURE_PROJECT_ID"])
            if os.environ.get("ALLURE_PROJECT_ID")
            else None
        ),
        help="Project ID (default: ALLURE_PROJECT_ID)",
    )
    search_parser.add_argument(
        "--size",
        type=int,
        default=50,
        help="Max results (default: 50)",
    )
    search_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only IDs, one per line",
    )
    search_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    # Find orphaned tests command
    orphaned_parser = subparsers.add_parser(
        "find-orphaned",
        help="Find potentially orphaned test cases (inactive tests with similar active ones)",
    )
    orphaned_parser.add_argument(
        "--url",
        default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
        help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
    )
    orphaned_parser.add_argument(
        "--token",
        default=_env("ALLURE_TOKEN"),
        help="API token (default: ALLURE_TOKEN)",
    )
    orphaned_parser.add_argument(
        "--project",
        type=int,
        default=(
            int(os.environ["ALLURE_PROJECT_ID"])
            if os.environ.get("ALLURE_PROJECT_ID")
            else None
        ),
        help="Project ID (default: ALLURE_PROJECT_ID)",
    )
    orphaned_parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Inactivity threshold in days (default: 30 if --similarity not set)",
    )
    orphaned_parser.add_argument(
        "--similarity",
        type=float,
        default=None,
        help="Similarity threshold for finding duplicates, 0.0-1.0 (default: 0.75 if --days not set)",
    )
    orphaned_parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Disable smart name normalization (dates, IDs, stop words removal)",
    )
    orphaned_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    orphaned_parser.add_argument(
        "--delete",
        action="store_true",
        help="Interactively delete found orphaned tests",
    )
    orphaned_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="With --delete: delete every found test without asking",
    )
    orphaned_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only IDs of orphaned tests, one per line",
    )

    # Create command
    create_parser = subparsers.add_parser(
        "create",
        help="Create test cases (single or bulk from file)",
    )
    create_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Test case name (for creating a single test case)",
    )
    create_parser.add_argument(
        "-d",
        "--description",
        default="",
        help="Description",
    )
    create_parser.add_argument(
        "--full-name",
        default="",
        help="Full name / path",
    )
    create_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        help="Tag (can be repeated: -t smoke -t regression)",
    )
    create_parser.add_argument(
        "-f",
        "--file",
        default=None,
        help="Path to file for bulk creation (CSV or JSON)",
    )
    create_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating",
    )
    create_parser.add_argument(
        "--url",
        default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
        help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
    )
    create_parser.add_argument(
        "--token",
        default=_env("ALLURE_TOKEN"),
        help="API token (default: ALLURE_TOKEN)",
    )
    create_parser.add_argument(
        "--project",
        type=int,
        default=(
            int(os.environ["ALLURE_PROJECT_ID"])
            if os.environ.get("ALLURE_PROJECT_ID")
            else None
        ),
        help="Project ID (default: ALLURE_PROJECT_ID)",
    )
    create_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    # Delete command
    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete test cases by ID",
    )
    delete_parser.add_argument(
        "ids",
        nargs="*",
        type=int,
        help="Test case IDs to delete",
    )
    delete_parser.add_argument(
        "-f",
        "--file",
        default=None,
        help="Path to file with IDs (plain text: one per line, or CSV with allure_id column)",
    )
    delete_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be deleted, don't actually delete",
    )
    delete_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    delete_parser.add_argument(
        "--url",
        default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
        help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
    )
    delete_parser.add_argument(
        "--token",
        default=_env("ALLURE_TOKEN"),
        help="API token (default: ALLURE_TOKEN)",
    )
    delete_parser.add_argument(
        "--project",
        type=int,
        default=(
            int(os.environ["ALLURE_PROJECT_ID"])
            if os.environ.get("ALLURE_PROJECT_ID")
            else None
        ),
        help="Project ID (default: ALLURE_PROJECT_ID)",
    )
    delete_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    delete_parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching test case details (just show IDs)",
    )
    delete_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show all test cases (don't truncate long lists)",
    )

    # Launches command
    launches_parser = subparsers.add_parser(
        "launches",
        help="List launches, newest first (optionally filtered by name)",
    )
    launches_parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Substring of the launch name (default: all launches)",
    )
    launches_parser.add_argument(
        "--size",
        type=int,
        default=10,
        help="Max results (default: 10)",
    )
    launches_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only IDs, one per line",
    )
    launches_parser.add_argument(
        "--json",
        action="store_true",
        help="Print launches as JSON",
    )
    _add_connection_args(launches_parser)

    # Failures command
    failures_parser = subparsers.add_parser(
        "failures",
        help="Show failed and broken tests of a launch: message, trace, attachments",
    )
    failures_parser.add_argument(
        "launch",
        help="Launch ID, or a substring of the launch name (the newest match is used)",
    )
    failures_parser.add_argument(
        "--trace",
        action="store_true",
        help="Print the full trace of every failure",
    )
    failures_parser.add_argument(
        "--download",
        metavar="DIR",
        default=None,
        help="Save attachments of every failure to DIR/<test result id>/",
    )
    failures_parser.add_argument(
        "--json",
        action="store_true",
        help="Print failures as JSON",
    )
    _add_connection_args(failures_parser)

    # Attachments command
    attachments_parser = subparsers.add_parser(
        "attachments",
        help="List or download attachments of a test result",
    )
    attachments_parser.add_argument(
        "result_id",
        type=int,
        help="Test result ID (shown by the failures command)",
    )
    attachments_parser.add_argument(
        "--download",
        metavar="DIR",
        default=None,
        help="Save the attachments to DIR",
    )
    attachments_parser.add_argument(
        "--json",
        action="store_true",
        help="Print attachments as JSON",
    )
    _add_connection_args(attachments_parser, project=False)

    # Backward compatibility: `allure-cli "query"` means `allure-cli search "query"`.
    # Without this, argparse rejects the query as an unknown command before the
    # old-style fallback below gets a chance to run.
    argv = sys.argv[1:]
    commands = set(subparsers.choices)
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv = ["search"] + argv

    args = parser.parse_args(argv)

    # If no command specified, treat as search (backward compatibility)
    if args.command is None:
        # Check if running without any arguments (not even query)
        if len(sys.argv) == 1:
            # No arguments at all - show help
            parser.print_help()
            return 0

        # Parse as old-style command
        parser_old = argparse.ArgumentParser(
            description="Get Allure TestOps test case by ID or search by name (substring)."
        )
        parser_old.add_argument(
            "query",
            nargs="?",
            default=None,
            help="Test case ID (number) or search query (substring of test case name)",
        )
        parser_old.add_argument(
            "--url",
            default=_env("ALLURE_ENDPOINT") or _env("ALLURE_TESTOPS_URL"),
            help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
        )
        parser_old.add_argument(
            "--token",
            default=_env("ALLURE_TOKEN"),
            help="API token (default: ALLURE_TOKEN)",
        )
        parser_old.add_argument(
            "--project",
            type=int,
            default=(
                int(os.environ["ALLURE_PROJECT_ID"])
                if os.environ.get("ALLURE_PROJECT_ID")
                else None
            ),
            help="Project ID (default: ALLURE_PROJECT_ID)",
        )
        parser_old.add_argument(
            "--size",
            type=int,
            default=50,
            help="Max results (default: 50)",
        )
        parser_old.add_argument(
            "-q",
            "--quiet",
            action="store_true",
            help="Print only IDs, one per line",
        )
        parser_old.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output",
        )
        args = parser_old.parse_args()
        args.command = "search"

    if args.command == "search":
        return _search_command(args)
    elif args.command == "find-orphaned":
        return _find_orphaned_command(args)
    elif args.command == "delete":
        return _delete_command(args)
    elif args.command == "create":
        return _create_command(args)
    elif args.command == "launches":
        return _launches_command(args)
    elif args.command == "failures":
        return _failures_command(args)
    elif args.command == "attachments":
        return _attachments_command(args)
    else:
        parser.print_help()
        return 2


def _search_command(args) -> int:
    """Handle search command."""
    query = args.query

    # If no query provided, show help
    if query is None:
        parser_help = argparse.ArgumentParser(
            prog="allure_cli search",
            description="Search test cases by ID or name",
        )
        parser_help.add_argument(
            "query",
            help="Test case ID (number) or search query (substring of test case name)",
        )
        parser_help.add_argument(
            "--url",
            help="Allure TestOps base URL (default: ALLURE_ENDPOINT or ALLURE_TESTOPS_URL)",
        )
        parser_help.add_argument("--token", help="API token (default: ALLURE_TOKEN)")
        parser_help.add_argument(
            "--project", type=int, help="Project ID (default: ALLURE_PROJECT_ID)"
        )
        parser_help.add_argument("--size", type=int, help="Max results (default: 50)")
        parser_help.add_argument(
            "-q", "--quiet", action="store_true", help="Print only IDs, one per line"
        )
        parser_help.add_argument(
            "--no-color", action="store_true", help="Disable colored output"
        )
        parser_help.print_help()
        return 0

    if not query:
        print("Error: Provide query as argument", file=sys.stderr)
        return 2

    if not args.url:
        print(
            "Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required",
            file=sys.stderr,
        )
        return 2
    if not args.token:
        print("Error: --token or ALLURE_TOKEN required", file=sys.stderr)
        return 2
    if args.project is None:
        print("Error: --project or ALLURE_PROJECT_ID required", file=sys.stderr)
        return 2

    # Determine if query is an ID (pure number) or a name search
    is_id_search = query.isdigit()

    try:
        if is_id_search:
            cases = find_by_id(
                args.url,
                args.token,
                args.project,
                int(query),
            )
        else:
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
            c = (
                Colors
                if (Colors.is_enabled() and not args.no_color)
                else type(
                    "NoColor",
                    (),
                    {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
                )()
            )
            search_type = "ID" if is_id_search else "name"
            print(
                f"{c.YELLOW}No test cases found for {search_type}: {c.BOLD}{query!r}{c.RESET}",
                file=sys.stderr,
            )
        return 0

    if args.quiet:
        for c in cases:
            print(c["id"])
        return 0

    c = (
        Colors
        if (Colors.is_enabled() and not args.no_color)
        else type(
            "NoColor",
            (),
            {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
        )()
    )

    # Print header with count
    count = len(cases)
    if count == 1:
        print(f"{c.GREEN}Found 1 test case:{c.RESET}\n", file=sys.stderr)
    else:
        print(f"{c.GREEN}Found {count} test cases:{c.RESET}\n", file=sys.stderr)

    for i, test_case in enumerate(cases, 1):
        name = test_case.get("name", "")
        full = test_case.get("fullName", "")
        test_id = test_case["id"]

        # Main line: ID and name
        print(
            f"{c.DIM}{i}.{c.RESET} ID {c.BLUE}{c.BOLD}{test_id}{c.RESET}\t{c.CYAN}{name}{c.RESET}"
        )

        # Full name if different
        if full and full != name:
            print(f"   {c.DIM}└─ {full}{c.RESET}")

    return 0


def _find_orphaned_command(args) -> int:
    """Handle find-orphaned command."""
    if args.yes and not args.delete:
        print("Error: --yes only makes sense together with --delete", file=sys.stderr)
        return 2
    if not args.url:
        print(
            "Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required",
            file=sys.stderr,
        )
        return 2
    if not args.token:
        print("Error: --token or ALLURE_TOKEN required", file=sys.stderr)
        return 2
    if args.project is None:
        print("Error: --project or ALLURE_PROJECT_ID required", file=sys.stderr)
        return 2

    # Determine which filters to apply based on explicit flags
    days = args.days
    similarity = args.similarity

    # If neither flag is set, use both defaults
    if days is None and similarity is None:
        days = 30
        similarity = 0.75
    # If only --days is set, use it without similarity filter
    elif days is not None and similarity is None:
        similarity = 0.0  # No similarity filtering
    # If only --similarity is set, use it without days filter
    elif days is None and similarity is not None:
        days = 0  # No days filtering
    # Both flags set explicitly - use both

    # Build search message
    filters = []
    if days > 0:
        filters.append(f"inactive for {days}+ days")
    if similarity > 0:
        filters.append(f"similarity >= {similarity}")

    if filters:
        filter_text = ", ".join(filters)
        print(f"Searching for orphaned tests ({filter_text})...", file=sys.stderr)
    else:
        print("Searching for orphaned tests...", file=sys.stderr)

    try:
        orphaned = find_orphaned_tests(
            args.url,
            args.token,
            args.project,
            days_threshold=days,
            similarity_threshold=similarity,
            normalize_names=not args.no_normalize,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not orphaned:
        if not args.quiet:
            c = (
                Colors
                if (Colors.is_enabled() and not args.no_color)
                else type(
                    "NoColor",
                    (),
                    {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
                )()
            )
            print(f"{c.GREEN}✓ No orphaned tests found.{c.RESET}", file=sys.stderr)
        return 0

    if args.quiet:
        for item in orphaned:
            print(item["old_test"]["id"])
        return 0

    c = (
        Colors
        if (Colors.is_enabled() and not args.no_color)
        else type(
            "NoColor",
            (),
            {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
        )()
    )

    label = (
        "inactive"
        if not any(item["similar_tests"] for item in orphaned)
        else "potentially orphaned"
    )
    print(
        f"\n{c.BOLD}{c.YELLOW}Found {len(orphaned)} {label} test(s):{c.RESET}\n",
        file=sys.stderr,
    )

    for i, item in enumerate(orphaned, 1):
        old = item["old_test"]
        days = item["days_inactive"]

        print(
            f"{c.DIM}{i}.{c.RESET} ID {c.BLUE}{c.BOLD}{old['id']}{c.RESET}"
            f"\t{c.CYAN}{old.get('name', 'N/A')}{c.RESET}"
            f" {c.DIM}({c.YELLOW}{days}{c.RESET}{c.DIM} days){c.RESET}"
        )
        if old.get("fullName") and old["fullName"] != old.get("name"):
            print(f"   {c.DIM}└─ {old['fullName']}{c.RESET}")

        if item["similar_tests"]:
            print(f"   {c.MAGENTA}Similar tests:{c.RESET}")
            for sim_item in item["similar_tests"][:3]:
                sim_test = sim_item["test"]
                sim_score = sim_item["similarity"]
                sim_days = sim_test.get("_days_inactive", 0)

                if sim_score >= 0.9:
                    sim_color = c.GREEN
                elif sim_score >= 0.75:
                    sim_color = c.YELLOW
                else:
                    sim_color = c.RED

                if sim_days < 7:
                    days_color = c.GREEN
                elif sim_days < 30:
                    days_color = c.YELLOW
                else:
                    days_color = c.RED

                print(
                    f"      {c.DIM}•{c.RESET} ID {c.BLUE}{sim_test['id']}{c.RESET} "
                    f"{c.DIM}({sim_color}{sim_score:.2f}{c.RESET}{c.DIM}, "
                    f"{days_color}{sim_days}{c.RESET}{c.DIM}d){c.RESET} "
                    f"{c.DIM}{sim_test.get('name', 'N/A')}{c.RESET}"
                )

            if len(item["similar_tests"]) > 3:
                extra = len(item["similar_tests"]) - 3
                print(f"      {c.DIM}... and {extra} more{c.RESET}")
        print()

    # Interactive deletion
    if args.delete:
        return _interactive_delete(
            args.url,
            args.token,
            orphaned,
            no_color=args.no_color,
            assume_yes=args.yes,
            project_id=args.project,
        )

    return 0


def _delete_ids(
    base_url: str, api_token: str, ids: list, c, project_id: int | None = None
) -> dict:
    """
    Delete test cases and report what happened.

    With a known project the whole batch goes out as one bulk request; otherwise
    (and if bulk fails) the ids are deleted one by one, which also tells us which
    of them were missing.

    The returned "mode" says which path ran: the bulk API confirms the batch as a
    whole (204) and not each id, so its counts are "submitted", not "verified".
    """
    if project_id is not None and len(ids) > 1:
        try:
            count = bulk_remove_test_cases(base_url, api_token, project_id, ids)
            print(
                f"  {c.GREEN}✓ Submitted {count} test case(s) in one request{c.RESET}",
                file=sys.stderr,
            )
            return {"deleted": count, "not_found": 0, "failed": 0, "mode": "bulk"}
        except RuntimeError as e:
            print(
                f"  {c.YELLOW}Bulk delete failed ({e}); deleting one by one{c.RESET}",
                file=sys.stderr,
            )

    def on_progress(test_id: int, status: str) -> None:
        if status == "deleted":
            print(f"  {c.GREEN}✓ {test_id} deleted{c.RESET}", file=sys.stderr)
        elif status == "not_found":
            print(f"  {c.YELLOW}– {test_id} not found{c.RESET}", file=sys.stderr)
        else:
            print(f"  {c.RED}✗ {test_id} failed{c.RESET}", file=sys.stderr)

    result = bulk_delete_test_cases(base_url, api_token, ids, on_progress=on_progress)
    return {**result, "mode": "single"}


def _interactive_delete(
    base_url: str,
    api_token: str,
    orphaned: list,
    no_color: bool = False,
    assume_yes: bool = False,
    project_id: int | None = None,
) -> int:
    """
    Delete orphaned tests: one by one with a prompt, or all at once when
    assume_yes is set (--yes) or the user answers 'a' to a prompt.
    """
    c = (
        Colors
        if (Colors.is_enabled() and not no_color)
        else type(
            "NoColor",
            (),
            {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
        )()
    )

    ids = [item["old_test"]["id"] for item in orphaned]
    deleted_count = 0
    skipped_count = 0
    not_found_count = 0
    failed_count = 0

    used_bulk = False

    def delete_batch(batch: list) -> None:
        nonlocal deleted_count, not_found_count, failed_count, used_bulk
        result = _delete_ids(base_url, api_token, batch, c, project_id=project_id)
        deleted_count += result["deleted"]
        not_found_count += result["not_found"]
        failed_count += result["failed"]
        used_bulk = used_bulk or result.get("mode") == "bulk"

    def print_summary(prefix: str) -> None:
        # A bulk request is confirmed as a whole, so we can only claim submission.
        verb = "Submitted" if used_bulk else "Deleted"
        tail = ""
        if not_found_count:
            tail += f", {c.YELLOW}Not found: {not_found_count}{c.RESET}"
        if failed_count:
            tail += f", {c.RED}Failed: {failed_count}{c.RESET}"
        print(
            f"\n{c.BOLD}{c.CYAN}{prefix}{c.RESET} "
            f"{c.GREEN}{verb}: {deleted_count}{c.RESET}, "
            f"{c.YELLOW}Skipped: {skipped_count}{c.RESET}{tail}",
            file=sys.stderr,
        )

    # --yes: no prompting at all, the list above is the only confirmation
    if assume_yes:
        print(
            f"\n{c.BOLD}{c.CYAN}Deleting all {len(ids)} test(s) without confirmation...{c.RESET}",
            file=sys.stderr,
        )
        delete_batch(ids)
        print_summary("Done.")
        return 0

    print(f"\n{c.BOLD}{c.CYAN}--- Interactive Deletion ---{c.RESET}", file=sys.stderr)
    print(
        f"For each test, choose: {c.GREEN}[y]{c.RESET}es to delete, {c.YELLOW}[n]{c.RESET}o to skip, "
        f"{c.MAGENTA}[a]{c.RESET}ll remaining, {c.RED}[q]{c.RESET}uit\n",
        file=sys.stderr,
    )

    for i, item in enumerate(orphaned, 1):
        old = item["old_test"]
        test_id = old["id"]

        print(
            f"\n{c.BOLD}[{i}/{len(orphaned)}]{c.RESET} Test ID {c.RED}{c.BOLD}{test_id}{c.RESET}: {old.get('name', 'N/A')}",
            file=sys.stderr,
        )
        print(
            f"{c.DIM}Inactive for {item['days_inactive']} days{c.RESET}",
            file=sys.stderr,
        )

        while True:
            try:
                choice = (
                    input(
                        f"Delete this test? {c.GREEN}[y]{c.RESET}/{c.YELLOW}[n]{c.RESET}/"
                        f"{c.MAGENTA}[a]{c.RESET}/{c.RED}[q]{c.RESET}: "
                    )
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                print(f"\n{c.YELLOW}Aborted.{c.RESET}", file=sys.stderr)
                return 0

            if choice == "q":
                print_summary("Stopped.")
                return 0
            elif choice == "y":
                delete_batch([test_id])
                break
            elif choice == "a":
                remaining = ids[i - 1:]
                print(
                    f"{c.DIM}Deleting the remaining {len(remaining)} test(s)...{c.RESET}",
                    file=sys.stderr,
                )
                delete_batch(remaining)
                print_summary("Done.")
                return 0
            elif choice == "n":
                print(f"{c.DIM}Skipped test {test_id}{c.RESET}", file=sys.stderr)
                skipped_count += 1
                break
            else:
                print(f"{c.RED}Invalid choice. Use y/n/a/q{c.RESET}", file=sys.stderr)

    print_summary("Done.")
    return 0


def _delete_command(args) -> int:
    """Handle delete command."""
    import csv

    if not args.url:
        print(
            "Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required",
            file=sys.stderr,
        )
        return 2
    if not args.token:
        print("Error: --token or ALLURE_TOKEN required", file=sys.stderr)
        return 2

    c = (
        Colors
        if (Colors.is_enabled() and not args.no_color)
        else type(
            "NoColor",
            (),
            {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
        )()
    )

    # Collect IDs from positional args
    all_ids: list[int] = list(args.ids or [])

    # Collect IDs from file
    if args.file:
        file_path = args.file
        try:
            with open(file_path, encoding="utf-8") as fh:
                if file_path.endswith(".csv"):
                    # Detect delimiter by reading first line
                    first_line = fh.readline()
                    fh.seek(0)
                    delimiter = ";" if ";" in first_line else ","
                    reader = csv.DictReader(fh, delimiter=delimiter)
                    for row in reader:
                        raw = row.get("allure_id", "").strip()
                        if raw.isdigit():
                            all_ids.append(int(raw))
                else:
                    for line in fh:
                        stripped = line.strip()
                        if stripped.isdigit():
                            all_ids.append(int(stripped))
        except OSError as e:
            print(f"Error: cannot read file {file_path}: {e}", file=sys.stderr)
            return 2

    # Deduplicate while preserving order
    seen: set[int] = set()
    unique_ids: list[int] = []
    for tid in all_ids:
        if tid not in seen:
            seen.add(tid)
            unique_ids.append(tid)

    if not unique_ids:
        print(
            "Error: no test case IDs provided (use positional args and/or --file)",
            file=sys.stderr,
        )
        return 2

    # Summary
    print(
        f"{c.BOLD}About to delete {len(unique_ids)} test case(s):{c.RESET}\n",
        file=sys.stderr,
    )

    # Fetch test case details (unless --no-fetch)
    fetched: list[dict | None] = []
    if not args.no_fetch:
        for tid in unique_ids:
            try:
                tc = get_test_case_by_id(args.url, args.token, tid)
            except AuthError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            except Exception:
                tc = None
            fetched.append(tc)
    else:
        fetched = [None] * len(unique_ids)

    # Display test case list
    _print_delete_list(c, unique_ids, fetched, args.no_fetch, args.verbose)

    # Dry run
    if args.dry_run:
        print(f"\n{c.CYAN}Dry run — nothing was deleted.{c.RESET}", file=sys.stderr)
        return 0

    # Confirmation
    if not args.yes:
        try:
            answer = input(f"\nAre you sure? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{c.YELLOW}Aborted.{c.RESET}", file=sys.stderr)
            return 0
        if answer != "y":
            print(f"{c.YELLOW}Aborted.{c.RESET}", file=sys.stderr)
            return 0

    # Execute
    try:
        result = _delete_ids(
            args.url, args.token, unique_ids, c, project_id=args.project
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Final summary. The bulk API confirms the batch, not each id, so it can only
    # report what was submitted.
    if result.get("mode") == "bulk":
        print(
            f"\n{c.BOLD}Done.{c.RESET} "
            f"{c.GREEN}Submitted: {result['deleted']}{c.RESET}",
            file=sys.stderr,
        )
    else:
        print(
            f"\n{c.BOLD}Done.{c.RESET} "
            f"{c.GREEN}Deleted: {result['deleted']}{c.RESET}, "
            f"{c.YELLOW}Not found: {result['not_found']}{c.RESET}, "
            f"{c.RED}Failed: {result['failed']}{c.RESET}",
            file=sys.stderr,
        )
    return 0


def _print_delete_list(
    c, unique_ids: list[int], fetched: list, no_fetch: bool, verbose: bool
) -> None:
    """Print the list of test cases about to be deleted."""
    total = len(unique_ids)
    show_head = 20
    show_tail = 5
    truncate = not verbose and total > 50

    for idx, (tid, tc) in enumerate(zip(unique_ids, fetched)):
        i = idx + 1

        # Truncation: show first 20, then "... and N more", then last 5
        if truncate and show_head < idx < total - show_tail:
            if idx == show_head:
                skipped = total - show_head - show_tail
                print(
                    f"\n   {c.DIM}... and {skipped} more ...{c.RESET}\n",
                    file=sys.stderr,
                )
            continue

        if no_fetch:
            # --no-fetch mode: just show IDs
            print(
                f"{c.DIM}{i}.{c.RESET} ID {c.BLUE}{c.BOLD}{tid}{c.RESET}",
                file=sys.stderr,
            )
        elif tc is None:
            # Fetched but not found
            print(
                f"{c.DIM}{i}.{c.RESET} ID {c.BLUE}{c.BOLD}{tid}{c.RESET}    {c.YELLOW}(not found){c.RESET}",
                file=sys.stderr,
            )
        else:
            # Full details
            name = tc.get("name", "")
            full = tc.get("fullName", "")
            print(
                f"{c.DIM}{i}.{c.RESET} ID {c.BLUE}{c.BOLD}{tid}{c.RESET}\t{c.CYAN}{name}{c.RESET}",
                file=sys.stderr,
            )
            if full and full != name:
                print(f"   {c.DIM}└─ {full}{c.RESET}", file=sys.stderr)


def _parse_create_file(file_path: str) -> list[dict]:
    """Parse a CSV or JSON file for bulk test case creation."""
    import csv as csv_mod
    import json as json_mod

    try:
        with open(file_path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as e:
        raise RuntimeError(f"cannot read file {file_path}: {e}") from e

    # JSON
    if file_path.endswith(".json"):
        try:
            data = json_mod.loads(raw)
        except json_mod.JSONDecodeError as e:
            raise RuntimeError(f"invalid JSON in {file_path}: {e}") from e
        if not isinstance(data, list):
            raise RuntimeError(f"JSON file must contain an array of objects")
        result = []
        for item in data:
            if not isinstance(item, dict) or "name" not in item:
                continue
            entry: dict = {"name": item["name"]}
            if item.get("description"):
                entry["description"] = item["description"]
            if item.get("full_name"):
                entry["full_name"] = item["full_name"]
            if item.get("tags"):
                tags = item["tags"]
                if isinstance(tags, list):
                    entry["tags"] = tags
                elif isinstance(tags, str) and tags:
                    entry["tags"] = [t.strip() for t in tags.split(";") if t.strip()]
            result.append(entry)
        return result

    # CSV (default)
    # Auto-detect delimiter
    delimiter = ";" if ";" in raw.split("\n", 1)[0] else ","
    reader = csv_mod.DictReader(raw.splitlines(), delimiter=delimiter)
    result = []
    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        entry = {"name": name}
        desc = (row.get("description") or "").strip()
        if desc:
            entry["description"] = desc
        fn = (row.get("full_name") or "").strip()
        if fn:
            entry["full_name"] = fn
        tags_raw = (row.get("tags") or "").strip()
        if tags_raw:
            entry["tags"] = [t.strip() for t in tags_raw.split(";") if t.strip()]
        result.append(entry)
    return result


def _create_command(args) -> int:
    """Handle create command."""
    if not args.url:
        print(
            "Error: --url or ALLURE_ENDPOINT/ALLURE_TESTOPS_URL required",
            file=sys.stderr,
        )
        return 2
    if not args.token:
        print("Error: --token or ALLURE_TOKEN required", file=sys.stderr)
        return 2
    if args.project is None:
        print("Error: --project or ALLURE_PROJECT_ID required", file=sys.stderr)
        return 2

    c = (
        Colors
        if (Colors.is_enabled() and not args.no_color)
        else type(
            "NoColor",
            (),
            {attr: "" for attr in dir(Colors) if not attr.startswith("_")},
        )()
    )

    has_name = args.name is not None
    has_file = args.file is not None

    if has_name and has_file:
        print("Error: provide either a name or --file, not both", file=sys.stderr)
        return 2
    if not has_name and not has_file:
        print(
            "Error: provide a test case name or --file for bulk creation",
            file=sys.stderr,
        )
        return 2

    # --- Single creation ---
    if has_name:
        tags = args.tag or []
        print(f"{c.BOLD}Creating test case:{c.RESET}", file=sys.stderr)
        print(f"  {c.CYAN}Name:{c.RESET} {args.name}", file=sys.stderr)
        if args.description:
            print(
                f"  {c.CYAN}Description:{c.RESET} {args.description}", file=sys.stderr
            )
        if args.full_name:
            print(f"  {c.CYAN}Full name:{c.RESET} {args.full_name}", file=sys.stderr)
        if tags:
            print(f"  {c.CYAN}Tags:{c.RESET} {', '.join(tags)}", file=sys.stderr)

        if args.dry_run:
            print(f"\n{c.CYAN}Dry run — nothing was created.{c.RESET}", file=sys.stderr)
            return 0

        try:
            result = create_test_case(
                args.url,
                args.token,
                args.project,
                args.name,
                description=args.description,
                full_name=args.full_name,
                tags=tags if tags else None,
            )
        except Exception as e:
            print(f"{c.RED}Error: {e}{c.RESET}", file=sys.stderr)
            return 1

        if result:
            tc_id = result.get("id", "?")
            tc_name = result.get("name", "")
            tc_full = result.get("fullName", "")
            print(f"\n{c.GREEN}✓ Created test case:{c.RESET}", file=sys.stderr)
            print(
                f"  ID {c.BLUE}{c.BOLD}{tc_id}{c.RESET}\t{c.CYAN}{tc_name}{c.RESET}",
                file=sys.stderr,
            )
            if tc_full and tc_full != tc_name:
                print(f"  {c.DIM}└─ {tc_full}{c.RESET}", file=sys.stderr)
            # Print ID to stdout for piping
            print(tc_id)
        else:
            print(f"{c.RED}✗ Failed to create test case{c.RESET}", file=sys.stderr)
            return 1

        return 0

    # --- Bulk creation from file ---
    try:
        test_cases = _parse_create_file(args.file)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not test_cases:
        print("Error: no valid test cases found in file", file=sys.stderr)
        return 2

    print(
        f"{c.BOLD}About to create {len(test_cases)} test case(s):{c.RESET}\n",
        file=sys.stderr,
    )

    for i, tc in enumerate(test_cases, 1):
        print(f"{c.DIM}{i}.{c.RESET} {c.CYAN}{tc['name']}{c.RESET}", file=sys.stderr)
        if tc.get("description"):
            print(f"   {c.DIM}desc: {tc['description'][:80]}{c.RESET}", file=sys.stderr)
        if tc.get("full_name"):
            print(f"   {c.DIM}full: {tc['full_name']}{c.RESET}", file=sys.stderr)
        if tc.get("tags"):
            print(f"   {c.DIM}tags: {', '.join(tc['tags'])}{c.RESET}", file=sys.stderr)

    if args.dry_run:
        print(f"\n{c.CYAN}Dry run — nothing was created.{c.RESET}", file=sys.stderr)
        return 0

    # Progress callback
    def _on_progress(name: str, status: str, result: dict | None) -> None:
        if status == "created":
            tc_id = result.get("id", "?") if result else "?"
            print(f"  {c.GREEN}✓ {tc_id} {name}{c.RESET}", file=sys.stderr)
        else:
            print(f"  {c.RED}✗ FAILED {name}{c.RESET}", file=sys.stderr)

    try:
        summary = bulk_create_test_cases(
            args.url,
            args.token,
            args.project,
            test_cases,
            on_progress=_on_progress,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        f"\n{c.BOLD}Done.{c.RESET} "
        f"{c.GREEN}Created: {summary['created']}{c.RESET}, "
        f"{c.RED}Failed: {summary['failed']}{c.RESET}",
        file=sys.stderr,
    )
    return 0


def _format_ts(ms: int | None) -> str:
    """Allure timestamp (ms since epoch) as local 'YYYY-MM-DD HH:MM'."""
    if not ms:
        return "?"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _launch_summary(launch: dict) -> dict:
    return {
        "id": launch.get("id"),
        "name": launch.get("name"),
        "createdDate": launch.get("createdDate"),
        "closed": launch.get("closed"),
    }


def _launches_command(args) -> int:
    """Handle launches command."""
    error = _check_connection_args(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    try:
        if args.query:
            launches = find_launches_by_name(
                args.url, args.token, args.project, args.query, size=args.size
            )
        else:
            launches = get_recent_launches(
                args.url, args.token, args.project, size=args.size
            )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                [_launch_summary(la) for la in launches], ensure_ascii=False, indent=2
            )
        )
        return 0
    if args.quiet:
        for launch in launches:
            print(launch["id"])
        return 0

    c = _colors(args.no_color)
    if not launches:
        what = f" matching {args.query!r}" if args.query else ""
        print(f"{c.YELLOW}No launches found{what}{c.RESET}", file=sys.stderr)
        return 0

    for launch in launches:
        state = "closed" if launch.get("closed") else "open"
        print(
            f"ID {c.BLUE}{c.BOLD}{launch['id']}{c.RESET}\t"
            f"{c.DIM}{_format_ts(launch.get('createdDate'))}\t{state}{c.RESET}\t"
            f"{c.CYAN}{launch.get('name', '')}{c.RESET}"
        )
    return 0


def _resolve_launch(args, c) -> dict | None:
    """
    Find the launch the user means: an ID, or else the newest launch whose name
    contains the argument. A number is tried as an ID first and then as a name —
    launch names often carry numbers (PR, build) that are not launch IDs.
    """
    if args.launch.isdigit():
        launch = get_launch(args.url, args.token, int(args.launch))
        if launch:
            return launch
    matches = find_launches_by_name(
        args.url, args.token, args.project, args.launch, size=2
    )
    if not matches:
        return None
    if len(matches) > 1:
        print(
            f"{c.DIM}Several launches match {args.launch!r}, using the newest one{c.RESET}",
            file=sys.stderr,
        )
    return matches[0]


def _safe_filename(name: str) -> str:
    """Attachment name as a file name: no path separators or control characters."""
    cleaned = "".join("_" if ch in '/\\:*?"<>|' or ord(ch) < 32 else ch for ch in name)
    cleaned = cleaned.strip(" .")
    return cleaned or "attachment"


def _save_attachments(
    base_url: str, api_token: str, attachments: list[dict], target: Path
) -> list[str]:
    """
    Download attachments into target, one file per attachment, and return the paths.

    Names repeat within a result (the same log attached twice), so a repeated name
    gets the attachment id appended. A second run writes the same paths again.
    """
    target.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    paths = []
    for attachment in attachments:
        filename = _safe_filename(attachment.get("name") or str(attachment["id"]))
        if filename in used:
            stem, dot, ext = filename.rpartition(".")
            filename = (
                f"{stem}_{attachment['id']}.{ext}"
                if dot
                else f"{filename}_{attachment['id']}"
            )
        used.add(filename)
        path = target / filename
        path.write_bytes(download_attachment(base_url, api_token, attachment["id"]))
        paths.append(str(path))
    return paths


def _failures_command(args) -> int:
    """Handle failures command."""
    error = _check_connection_args(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    c = _colors(args.no_color)
    try:
        launch = _resolve_launch(args, c)
        if launch is None:
            print(
                f"{c.YELLOW}No launch found for {args.launch!r}{c.RESET}",
                file=sys.stderr,
            )
            return 1
        statistic = get_launch_statistic(args.url, args.token, launch["id"])
        short_results = get_launch_results(
            args.url, args.token, args.project, launch["id"]
        )
        failures = []
        for short in short_results:
            result = get_test_result(args.url, args.token, short["id"]) or short
            if args.download:
                attachments = get_test_result_attachments(
                    args.url, args.token, short["id"]
                )
                result["_attachments"] = _save_attachments(
                    args.url,
                    args.token,
                    attachments,
                    Path(args.download) / str(short["id"]),
                )
            failures.append(result)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "launch": _launch_summary(launch),
            "statistic": statistic,
            "failures": [
                {
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "name": r.get("name"),
                    "fullName": r.get("fullName"),
                    "testCaseId": r.get("testCaseId"),
                    "duration": r.get("duration"),
                    "message": r.get("message"),
                    "trace": r.get("trace"),
                    **(
                        {"attachments": r["_attachments"]}
                        if "_attachments" in r
                        else {}
                    ),
                }
                for r in failures
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    state = "closed" if launch.get("closed") else "open"
    created = _format_ts(launch.get("createdDate"))
    print(
        f"{c.BOLD}Launch {launch['id']}{c.RESET} {c.DIM}· {created} · {state}{c.RESET}\n"
        f"{c.CYAN}{launch.get('name', '')}{c.RESET}",
        file=sys.stderr,
    )
    if statistic:
        counts = " · ".join(
            f"{status} {count}" for status, count in sorted(statistic.items())
        )
        print(f"{c.DIM}{counts}{c.RESET}\n", file=sys.stderr)

    if not failures:
        print(f"{c.GREEN}✓ No failed or broken tests.{c.RESET}", file=sys.stderr)
        return 0

    for i, result in enumerate(failures, 1):
        status = result.get("status", "?")
        color = c.RED if status == "failed" else c.YELLOW
        print(
            f"{c.DIM}{i}.{c.RESET} {color}[{status}]{c.RESET} {c.BOLD}{result.get('name', '')}{c.RESET}"
        )
        if result.get("fullName"):
            print(f"   {c.DIM}└─ {result['fullName']}{c.RESET}")
        duration = result.get("duration")
        took = f" · {duration / 1000:.1f}s" if duration else ""
        print(
            f"   {c.DIM}result {c.RESET}{c.BLUE}{result['id']}{c.RESET}{c.DIM}{took}{c.RESET}"
        )
        text = result.get("trace") if args.trace else result.get("message")
        for line in (text or "").rstrip().splitlines():
            print(f"   {line}")
        if "_attachments" in result:
            print(
                f"   {c.DIM}attachments: {len(result['_attachments'])} → "
                f"{Path(args.download) / str(result['id'])}{c.RESET}"
            )
        print()
    return 0


def _attachments_command(args) -> int:
    """Handle attachments command."""
    error = _check_connection_args(args, project=False)
    if error:
        print(error, file=sys.stderr)
        return 2

    try:
        attachments = get_test_result_attachments(args.url, args.token, args.result_id)
        paths = (
            _save_attachments(args.url, args.token, attachments, Path(args.download))
            if args.download
            else None
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        items = [
            {k: a.get(k) for k in ("id", "name", "contentType", "contentLength")}
            for a in attachments
        ]
        if paths is not None:
            for item, path in zip(items, paths):
                item["path"] = path
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    c = _colors(args.no_color)
    if not attachments:
        print(
            f"{c.YELLOW}No attachments for result {args.result_id}{c.RESET}",
            file=sys.stderr,
        )
        return 0

    for i, attachment in enumerate(attachments):
        where = f"\t{c.DIM}→ {paths[i]}{c.RESET}" if paths is not None else ""
        kind = attachment.get("contentType", "?")
        size = attachment.get("contentLength", "?")
        print(
            f"ID {c.BLUE}{attachment['id']}{c.RESET}\t"
            f"{c.DIM}{kind}\t{size} B{c.RESET}\t"
            f"{c.CYAN}{attachment.get('name', '')}{c.RESET}{where}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
