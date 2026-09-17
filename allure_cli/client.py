"""
Allure TestOps API client.
Auth: exchange API token for JWT (Bearer) per https://docs.qatools.ru/api
JWT cached on disk; refreshed automatically on 401.
"""

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_AUTH_HINT = "Check ALLURE_TOKEN: create a new API token in Allure TestOps (profile → API Tokens) and update the environment variable."


class AuthError(RuntimeError):
    """HTTP 401: JWT expired or API token invalid."""


class ApiError(RuntimeError):
    """Non-401 HTTP error from the API; carries the status code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return Path(base) / "allure_cli"


def _cache_key(base_url: str, api_token: str) -> str:
    return hashlib.sha256(f"{base_url.rstrip('/')}:{api_token}".encode()).hexdigest()[
        :32
    ]


def _jwt_cache_path(base_url: str, api_token: str) -> Path:
    return _cache_dir() / f"jwt_{_cache_key(base_url, api_token)}.json"


def _read_jwt_cache(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text())
        token = data.get("access_token")
        return token if token else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _write_jwt_cache(path: Path, access_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"access_token": access_token}), encoding="utf-8")


def clear_jwt_cache(base_url: str, api_token: str) -> None:
    """Remove cached JWT for this url+token (e.g. after 401)."""
    _memory_cache.pop(_cache_key(base_url, api_token), None)
    path = _jwt_cache_path(base_url, api_token)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# In-process JWT cache, keyed like the on-disk one.
_memory_cache: dict[str, str] = {}


def get_jwt(base_url: str, api_token: str) -> str:
    """
    Return JWT from cache (memory, then disk), otherwise exchange the API token
    for a JWT via OAuth and cache it.

    Callers should not pass the JWT to API functions themselves — `request()`
    obtains and refreshes it. This is exposed for introspection/debugging.
    """
    key = _cache_key(base_url, api_token)
    cached = _memory_cache.get(key) or _read_jwt_cache(
        _jwt_cache_path(base_url, api_token)
    )
    if cached:
        _memory_cache[key] = cached
        return cached
    return _exchange_api_token(base_url, api_token)


def _exchange_api_token(base_url: str, api_token: str) -> str:
    """Exchange the API token for a fresh JWT and cache it (memory + disk)."""
    path = _jwt_cache_path(base_url, api_token)
    url = f"{base_url.rstrip('/')}/api/uaa/oauth/token"
    data = urllib.parse.urlencode(
        {
            "grant_type": "apitoken",
            "scope": "openid",
            "token": api_token,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        clear_jwt_cache(base_url, api_token)
        if e.code == 401:
            raise AuthError(
                f"Authorization error (401): invalid or expired API token. {_AUTH_HINT}"
            ) from e
        raise RuntimeError(
            f"Failed to obtain JWT: HTTP {e.code}: {e.read().decode() if e.fp else ''}"
        ) from e
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"OAuth response missing access_token: {body}")
    _write_jwt_cache(path, access_token)
    _memory_cache[_cache_key(base_url, api_token)] = access_token
    return access_token


def request(
    base_url: str,
    api_token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    context: str = "",
) -> tuple[int, Any]:
    """
    The single entry point for every authenticated API call.

    Authorization is handled here and nowhere else: the JWT is taken from the
    cache, and on 401 (expired JWT) it is discarded, re-issued from the API
    token and the request is retried once. API functions therefore never see
    or pass a JWT — new endpoints get token refresh for free by going through
    this function.

    Returns (status_code, parsed_json_or_None).
    Raises AuthError if auth cannot be recovered, ApiError for other HTTP errors.
    """
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    where = f" {context}" if context else ""

    def send(jwt: str) -> tuple[int, Any]:
        headers = {
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthError(
                    f"Authorization error (401){where}. {_AUTH_HINT}"
                ) from e
            raise ApiError(
                f"API error: HTTP {e.code}: {e.read().decode() if e.fp else ''}",
                e.code,
            ) from e

    try:
        return send(get_jwt(base_url, api_token))
    except AuthError:
        clear_jwt_cache(base_url, api_token)
        return send(_exchange_api_token(base_url, api_token))


def search_test_cases(
    base_url: str,
    api_token: str,
    project_id: int,
    rql: str,
    *,
    page: int = 0,
    size: int = 20,
) -> dict[str, Any]:
    """Search test cases by AQL. Returns API response with 'content' list."""
    _, data = request(
        base_url,
        api_token,
        "GET",
        "/api/testcase/__search",
        params={"projectId": project_id, "rql": rql, "page": page, "size": size},
        context="while searching test cases",
    )
    return data or {}


def get_test_case_by_id(
    base_url: str,
    api_token: str,
    test_case_id: int,
) -> dict[str, Any] | None:
    """Get test case by ID directly. Returns test case dict or None if not found."""
    try:
        _, data = request(
            base_url,
            api_token,
            "GET",
            f"/api/testcase/{test_case_id}",
            context="while fetching the test case",
        )
    except ApiError as e:
        if e.code == 404:
            return None
        raise
    return data


def find_by_name(
    base_url: str,
    api_token: str,
    project_id: int,
    name_query: str,
    *,
    size: int = 50,
) -> list[dict[str, Any]]:
    """
    Get test cases whose name contains name_query (AQL: name ~= "...").
    Returns list of test case dicts (id, name, fullName, ...).
    """
    rql = f'name ~= "{name_query}"'
    result = search_test_cases(base_url, api_token, project_id, rql, page=0, size=size)
    return result.get("content") or []


def find_by_id(
    base_url: str,
    api_token: str,
    project_id: int,
    test_case_id: int,
) -> list[dict[str, Any]]:
    """
    Get test case by exact ID using direct API call.
    Returns list with single test case dict (id, name, fullName, ...) or empty list.
    """
    result = get_test_case_by_id(base_url, api_token, test_case_id)

    if result is None:
        return []
    return [result]


def normalize_test_name(name: str) -> str:
    """
    Normalize test name for better similarity comparison.
    Removes noise: dates, version numbers, IDs, common test prefixes.
    """
    import re

    if not name:
        return ""

    text = name.lower()

    # Replace underscores with spaces for snake_case names
    text = text.replace("_", " ")

    # Remove dates in various formats
    text = re.sub(r"\d{4}[-/]\d{2}[-/]\d{2}", "", text)  # 2024-01-15, 2024/01/15
    text = re.sub(r"\d{2}[-/]\d{2}[-/]\d{4}", "", text)  # 15-01-2024, 15/01/2024
    text = re.sub(r"\d{4}\d{2}\d{2}", "", text)  # 20240115

    # Remove timestamps
    text = re.sub(r"\d{2}:\d{2}:\d{2}", "", text)  # 14:30:45
    text = re.sub(r"\d{13,}", "", text)  # Unix timestamps in ms

    # Remove version numbers
    text = re.sub(r"v\d+\.\d+(\.\d+)?", "", text)  # v1.2.3, v2.0
    text = re.sub(r"version\s*\d+", "", text)  # version 1, version 2

    # Remove common test IDs/numbers in brackets or prefixes
    text = re.sub(
        r"\[?\b(id|test|case|tc|bug|issue|jira)[-_]?\d+\b\]?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"#\d+", "", text)  # #123

    # Remove isolated numbers (but keep numbers inside words)
    text = re.sub(r"\b\d+\b", "", text)

    # Remove common test prefixes/suffixes (but keep meaningful words)
    stop_words = [
        "test",
        "tests",
        "testing",
        "check",
        "checks",
        "checking",
        "verify",
        "verifies",
        "verification",
        "should",
        "must",
        "can",
        "when",
        "then",
        "given",
        "case",
    ]

    words = text.split()
    filtered_words = []
    for word in words:
        # Keep word if it's not a stop word or if it's part of a compound
        word_clean = re.sub(r"[^\w]", "", word)
        if word_clean and (word_clean not in stop_words or len(word_clean) > 10):
            filtered_words.append(word_clean)

    # Join and clean up extra spaces
    result = " ".join(filtered_words)
    result = re.sub(r"\s+", " ", result).strip()

    return result


def similarity_ratio(s1: str, s2: str, *, normalize: bool = True) -> float:
    """
    Calculate similarity ratio between two strings using Levenshtein distance.
    Returns value between 0.0 (completely different) and 1.0 (identical).

    Args:
        s1: First string
        s2: Second string
        normalize: If True, normalize strings before comparison (remove dates, numbers, stop words)
    """
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    # Normalize if requested
    if normalize:
        s1 = normalize_test_name(s1)
        s2 = normalize_test_name(s2)

        # After normalization, check again
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

    s1_lower = s1.lower()
    s2_lower = s2.lower()

    # Calculate Levenshtein distance
    len1, len2 = len(s1_lower), len(s2_lower)
    if len1 > len2:
        s1_lower, s2_lower = s2_lower, s1_lower
        len1, len2 = len2, len1

    current_row = range(len1 + 1)
    for i in range(1, len2 + 1):
        previous_row = current_row
        current_row = [i] + [0] * len1
        for j in range(1, len1 + 1):
            add = previous_row[j] + 1
            delete = current_row[j - 1] + 1
            change = previous_row[j - 1]
            if s1_lower[j - 1] != s2_lower[i - 1]:
                change += 1
            current_row[j] = min(add, delete, change)

    distance = current_row[len1]
    max_len = max(len(s1), len(s2))
    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


def get_all_test_cases(
    base_url: str,
    api_token: str,
    project_id: int,
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """
    Get all test cases from project using pagination.
    Returns list of test case dicts with id, name, fullName, updatedDate, etc.
    """
    all_cases = []
    page = 0

    while True:
        result = search_test_cases(
            base_url,
            api_token,
            project_id,
            rql="",  # Empty RQL returns all test cases
            page=page,
            size=page_size,
        )

        content = result.get("content") or []
        if not content:
            break

        all_cases.extend(content)

        # Check if we've reached the last page
        total_pages = result.get("totalPages", 0)
        if page >= total_pages - 1:
            break

        page += 1

    return all_cases


def delete_test_case(
    base_url: str,
    api_token: str,
    test_case_id: int,
) -> bool:
    """Delete test case by ID. Returns True on success."""
    try:
        status, _ = request(
            base_url,
            api_token,
            "DELETE",
            f"/api/testcase/{test_case_id}",
            context="while deleting the test case",
        )
    except ApiError as e:
        if e.code == 404:
            return False
        raise
    # 200 OK, 202 Accepted (async), 204 No Content are all success
    return status in (200, 202, 204)


def bulk_remove_test_cases(
    base_url: str,
    api_token: str,
    project_id: int,
    test_case_ids: list[int],
) -> int:
    """
    Delete many test cases in a single request (POST /api/testcase/bulk/remove).

    Returns the number of ids submitted; the API answers 204 without per-id
    detail, so use bulk_delete_test_cases() when you need to know which ids
    were missing.
    """
    if not test_case_ids:
        return 0
    request(
        base_url,
        api_token,
        "POST",
        "/api/testcase/bulk/remove",
        body={
            "selection": {
                "projectId": project_id,
                # Must stay False: inverted=True means "everything EXCEPT these
                # ids", i.e. it would wipe the rest of the project.
                "inverted": False,
                "leafsInclude": list(test_case_ids),
            }
        },
        context="while deleting test cases",
    )
    return len(test_case_ids)


def bulk_delete_test_cases(
    base_url: str,
    api_token: str,
    test_case_ids: list[int],
    *,
    on_progress: "callable | None" = None,
) -> dict[str, int]:
    """
    Delete multiple test cases by IDs.
    On 401 (expired JWT) clears cache, fetches new JWT, retries once per item.

    Args:
        base_url: Allure TestOps URL
        api_token: API token
        test_case_ids: List of test case IDs to delete
        on_progress: Optional callback(test_id, status) called after each deletion.
                     status is one of: "deleted", "not_found", "failed"

    Returns dict with counts: {"deleted": N, "not_found": M, "failed": K}
    """
    deleted = 0
    not_found = 0
    failed = 0

    for test_id in test_case_ids:
        try:
            success = delete_test_case(base_url, api_token, test_id)
            status = "deleted" if success else "not_found"
        except RuntimeError:
            status = "failed"

        if status == "deleted":
            deleted += 1
        elif status == "not_found":
            not_found += 1
        else:
            failed += 1

        if on_progress:
            on_progress(test_id, status)

    return {"deleted": deleted, "not_found": not_found, "failed": failed}


def find_orphaned_tests(
    base_url: str,
    api_token: str,
    project_id: int,
    *,
    days_threshold: int = 30,
    similarity_threshold: float = 0.75,
    normalize_names: bool = True,
) -> list[dict[str, Any]]:
    """
    Find potentially orphaned test cases:
    1. Tests not updated for days_threshold days
    2. Tests with similar names (similarity >= similarity_threshold) but different IDs

    Args:
        base_url: Allure TestOps URL
        api_token: API token
        project_id: Project ID
        days_threshold: Inactivity threshold in days (0 = no filtering)
        similarity_threshold: Similarity threshold 0.0-1.0 (0 = no filtering)
        normalize_names: Use smart name normalization (remove dates, IDs, stop words)

    Returns list of dicts with:
    - old_test: test case dict (orphaned candidate)
    - similar_tests: list of test case dicts (potential replacements)
    - similarity: similarity score
    - days_inactive: days since last update
    """
    from datetime import datetime, timezone

    all_cases = get_all_test_cases(base_url, api_token, project_id)

    # Parse dates and calculate inactive days
    now = datetime.now(timezone.utc)
    for case in all_cases:
        # Prefer lastModifiedDate, fall back to createdDate
        ts = case.get("lastModifiedDate") or case.get("createdDate")
        if ts:
            try:
                # Allure returns timestamps in milliseconds
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                case["_days_inactive"] = (now - dt).days
            except (ValueError, TypeError):
                case["_days_inactive"] = 0
        else:
            case["_days_inactive"] = 0

    # Find inactive tests (days_threshold=0 means no filtering)
    if days_threshold > 0:
        inactive = [c for c in all_cases if c["_days_inactive"] >= days_threshold]
    else:
        inactive = all_cases

    orphaned = []

    # If no similarity filtering requested, just return inactive tests
    if similarity_threshold <= 0:
        for old_test in inactive:
            orphaned.append(
                {
                    "old_test": old_test,
                    "similar_tests": [],
                    "days_inactive": old_test["_days_inactive"],
                }
            )
        return orphaned

    # O(n²) similarity comparison — only when similarity is requested
    for old_test in inactive:
        old_name = old_test.get("name", "")
        old_full = old_test.get("fullName", "")
        old_text = f"{old_name} {old_full}"

        similar = []

        # Compare with all other tests
        for other in all_cases:
            if other["id"] == old_test["id"]:
                continue

            other_name = other.get("name", "")
            other_full = other.get("fullName", "")
            other_text = f"{other_name} {other_full}"

            # Calculate similarity on name
            name_sim = similarity_ratio(old_name, other_name, normalize=normalize_names)
            # Calculate similarity on full name
            full_sim = similarity_ratio(old_text, other_text, normalize=normalize_names)
            # Use max similarity
            max_sim = max(name_sim, full_sim)

            if max_sim >= similarity_threshold:
                similar.append(
                    {
                        "test": other,
                        "similarity": max_sim,
                    }
                )

        # Only report if we found similar tests
        if similar:
            # Sort by similarity (highest first)
            similar.sort(key=lambda x: x["similarity"], reverse=True)

            orphaned.append(
                {
                    "old_test": old_test,
                    "similar_tests": similar,
                    "days_inactive": old_test["_days_inactive"],
                }
            )

    return orphaned


def create_test_case(
    base_url: str,
    api_token: str,
    project_id: int,
    name: str,
    *,
    description: str = "",
    full_name: str = "",
    precondition: str = "",
    expected_result: str = "",
    tags: list[str] | None = None,
    links: list[dict] | None = None,
) -> dict | None:
    """Create a new test case. Returns the created test case dict on success, None on failure."""
    body: dict[str, Any] = {
        "name": name,
        "projectId": project_id,
    }
    if description:
        body["description"] = description
    if full_name:
        body["fullName"] = full_name
    if precondition:
        body["precondition"] = precondition
    if expected_result:
        body["expectedResult"] = expected_result
    if tags:
        body["tags"] = [{"name": t} for t in tags]
    if links:
        body["links"] = links

    _, data = request(
        base_url,
        api_token,
        "POST",
        "/api/testcase",
        body=body,
        context="while creating the test case",
    )
    return data


def bulk_create_test_cases(
    base_url: str,
    api_token: str,
    project_id: int,
    test_cases: list[dict],
    *,
    on_progress: "callable | None" = None,
) -> dict[str, int]:
    """
    Create multiple test cases.
    On 401 (expired JWT) clears cache, fetches new JWT, retries once per item.

    Args:
        base_url: Allure TestOps URL
        api_token: API token
        project_id: Project ID
        test_cases: List of dicts with keys: name, optionally description, full_name, tags
        on_progress: Optional callback(name, status, result) called after each creation.
                     status is one of: "created", "failed"
                     result is the created test case dict or None

    Returns dict with counts: {"created": N, "failed": M}
    """
    created = 0
    failed = 0

    for tc in test_cases:
        result = None
        tc_name = tc.get("name", "")
        try:
            result = create_test_case(
                base_url,
                api_token,
                project_id,
                tc_name,
                description=tc.get("description", ""),
                full_name=tc.get("full_name", ""),
                tags=tc.get("tags"),
            )
            status = "created" if result else "failed"
        except RuntimeError:
            status = "failed"

        if status == "created":
            created += 1
        else:
            failed += 1

        if on_progress:
            on_progress(tc_name, status, result)

    return {"created": created, "failed": failed}
