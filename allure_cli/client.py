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

_AUTH_HINT = "Проверьте ALLURE_TOKEN: создайте новый API-токен в Allure TestOps (профиль → API Tokens) и обновите переменную окружения."


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "allure_cli"


def _cache_key(base_url: str, api_token: str) -> str:
    return hashlib.sha256(f"{base_url.rstrip('/')}:{api_token}".encode()).hexdigest()[:32]


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
    path = _jwt_cache_path(base_url, api_token)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def get_jwt(base_url: str, api_token: str) -> str:
    """Return JWT from cache if present, otherwise exchange API token for JWT via OAuth and cache it."""
    path = _jwt_cache_path(base_url, api_token)
    cached = _read_jwt_cache(path)
    if cached:
        return cached

    url = f"{base_url.rstrip('/')}/api/uaa/oauth/token"
    data = urllib.parse.urlencode({
        "grant_type": "apitoken",
        "scope": "openid",
        "token": api_token,
    }).encode()
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
            raise RuntimeError(f"Ошибка авторизации (401): неверный или истёкший API-токен. {_AUTH_HINT}") from e
        raise RuntimeError(f"Ошибка при получении JWT: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"OAuth response missing access_token: {body}")
    _write_jwt_cache(path, access_token)
    return access_token


def search_test_cases(
    base_url: str,
    jwt: str,
    project_id: int,
    rql: str,
    *,
    page: int = 0,
    size: int = 20,
) -> dict[str, Any]:
    """Search test cases by AQL. Returns API response with 'content' list."""
    params = {"projectId": project_id, "rql": rql, "page": page, "size": size}
    query = urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}/api/testcase/__search?{query}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(f"Ошибка авторизации (401) при поиске тест-кейсов. {_AUTH_HINT}") from e
        raise RuntimeError(f"Ошибка API: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e


def get_test_case_by_id(
    base_url: str,
    jwt: str,
    test_case_id: int,
) -> dict[str, Any] | None:
    """Get test case by ID directly. Returns test case dict or None if not found."""
    url = f"{base_url.rstrip('/')}/api/testcase/{test_case_id}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(f"Ошибка авторизации (401) при получении тест-кейса. {_AUTH_HINT}") from e
        if e.code == 404:
            return None
        raise RuntimeError(f"Ошибка API: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e


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
    On 401 (expired JWT) clears cache, fetches new JWT, retries once.
    """
    jwt = get_jwt(base_url, api_token)
    rql = f'name ~= "{name_query}"'
    try:
        result = search_test_cases(base_url, jwt, project_id, rql, page=0, size=size)
    except RuntimeError as e:
        if "401" not in str(e):
            raise
        clear_jwt_cache(base_url, api_token)
        jwt = get_jwt(base_url, api_token)
        result = search_test_cases(base_url, jwt, project_id, rql, page=0, size=size)
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
    On 401 (expired JWT) clears cache, fetches new JWT, retries once.
    """
    jwt = get_jwt(base_url, api_token)
    try:
        result = get_test_case_by_id(base_url, jwt, test_case_id)
    except RuntimeError as e:
        if "401" not in str(e):
            raise
        clear_jwt_cache(base_url, api_token)
        jwt = get_jwt(base_url, api_token)
        result = get_test_case_by_id(base_url, jwt, test_case_id)
    
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
    text = text.replace('_', ' ')
    
    # Remove dates in various formats
    text = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}', '', text)  # 2024-01-15, 2024/01/15
    text = re.sub(r'\d{2}[-/]\d{2}[-/]\d{4}', '', text)  # 15-01-2024, 15/01/2024
    text = re.sub(r'\d{4}\d{2}\d{2}', '', text)  # 20240115
    
    # Remove timestamps
    text = re.sub(r'\d{2}:\d{2}:\d{2}', '', text)  # 14:30:45
    text = re.sub(r'\d{13,}', '', text)  # Unix timestamps in ms
    
    # Remove version numbers
    text = re.sub(r'v\d+\.\d+(\.\d+)?', '', text)  # v1.2.3, v2.0
    text = re.sub(r'version\s*\d+', '', text)  # version 1, version 2
    
    # Remove common test IDs/numbers in brackets or prefixes
    text = re.sub(r'\[?\b(id|test|case|tc|bug|issue|jira)[-_]?\d+\b\]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'#\d+', '', text)  # #123
    
    # Remove isolated numbers (but keep numbers inside words)
    text = re.sub(r'\b\d+\b', '', text)
    
    # Remove common test prefixes/suffixes (but keep meaningful words)
    stop_words = [
        'test', 'tests', 'testing',
        'check', 'checks', 'checking',
        'verify', 'verifies', 'verification',
        'should', 'must', 'can',
        'when', 'then', 'given',
        'case',
    ]
    
    words = text.split()
    filtered_words = []
    for word in words:
        # Keep word if it's not a stop word or if it's part of a compound
        word_clean = re.sub(r'[^\w]', '', word)
        if word_clean and (word_clean not in stop_words or len(word_clean) > 10):
            filtered_words.append(word_clean)
    
    # Join and clean up extra spaces
    result = ' '.join(filtered_words)
    result = re.sub(r'\s+', ' ', result).strip()
    
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
    jwt = get_jwt(base_url, api_token)
    all_cases = []
    page = 0
    
    while True:
        try:
            result = search_test_cases(
                base_url,
                jwt,
                project_id,
                rql="",  # Empty RQL returns all test cases
                page=page,
                size=page_size,
            )
        except RuntimeError as e:
            if "401" not in str(e):
                raise
            clear_jwt_cache(base_url, api_token)
            jwt = get_jwt(base_url, api_token)
            result = search_test_cases(
                base_url,
                jwt,
                project_id,
                rql="",
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
    jwt: str,
    test_case_id: int,
) -> bool:
    """Delete test case by ID. Returns True on success."""
    url = f"{base_url.rstrip('/')}/api/testcase/{test_case_id}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            # 200 OK, 202 Accepted (async), 204 No Content are all success
            return resp.status in (200, 202, 204)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(f"Ошибка авторизации (401) при удалении тест-кейса. {_AUTH_HINT}") from e
        if e.code == 404:
            return False
        raise RuntimeError(f"Ошибка API: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e


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
    jwt = get_jwt(base_url, api_token)
    deleted = 0
    not_found = 0
    failed = 0

    for test_id in test_case_ids:
        status = "failed"
        try:
            success = delete_test_case(base_url, jwt, test_id)
            status = "deleted" if success else "not_found"
        except RuntimeError as e:
            if "401" not in str(e):
                failed += 1
                if on_progress:
                    on_progress(test_id, "failed")
                continue
            # Refresh JWT and retry once
            clear_jwt_cache(base_url, api_token)
            jwt = get_jwt(base_url, api_token)
            try:
                success = delete_test_case(base_url, jwt, test_id)
                status = "deleted" if success else "not_found"
            except Exception:
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
        updated = case.get("updatedDate")
        if updated:
            try:
                # Allure returns timestamps in milliseconds
                updated_dt = datetime.fromtimestamp(updated / 1000, tz=timezone.utc)
                case["_days_inactive"] = (now - updated_dt).days
            except (ValueError, TypeError):
                case["_days_inactive"] = 0
        else:
            case["_days_inactive"] = 0
    
    # Find inactive tests
    inactive = [c for c in all_cases if c["_days_inactive"] >= days_threshold]
    
    orphaned = []
    
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
                similar.append({
                    "test": other,
                    "similarity": max_sim,
                })
        
        # Only report if we found similar tests
        if similar:
            # Sort by similarity (highest first)
            similar.sort(key=lambda x: x["similarity"], reverse=True)
            
            orphaned.append({
                "old_test": old_test,
                "similar_tests": similar,
                "days_inactive": old_test["_days_inactive"],
            })
    
    return orphaned


def create_test_case(
    base_url: str,
    jwt: str,
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

    url = f"{base_url.rstrip('/')}/api/testcase"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(f"Ошибка авторизации (401) при создании тест-кейса. {_AUTH_HINT}") from e
        raise RuntimeError(f"Ошибка API: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e


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
    jwt = get_jwt(base_url, api_token)
    created = 0
    failed = 0

    for tc in test_cases:
        status = "failed"
        result = None
        tc_name = tc.get("name", "")
        try:
            result = create_test_case(
                base_url,
                jwt,
                project_id,
                tc_name,
                description=tc.get("description", ""),
                full_name=tc.get("full_name", ""),
                tags=tc.get("tags"),
            )
            status = "created" if result else "failed"
        except RuntimeError as e:
            if "401" not in str(e):
                failed += 1
                if on_progress:
                    on_progress(tc_name, "failed", None)
                continue
            # Refresh JWT and retry once
            clear_jwt_cache(base_url, api_token)
            jwt = get_jwt(base_url, api_token)
            try:
                result = create_test_case(
                    base_url,
                    jwt,
                    project_id,
                    tc_name,
                    description=tc.get("description", ""),
                    full_name=tc.get("full_name", ""),
                    tags=tc.get("tags"),
                )
                status = "created" if result else "failed"
            except Exception:
                status = "failed"

        if status == "created":
            created += 1
        else:
            failed += 1

        if on_progress:
            on_progress(tc_name, status, result)

    return {"created": created, "failed": failed}
