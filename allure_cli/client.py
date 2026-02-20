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
