"""
Allure TestOps API client.
Auth: exchange API token for JWT (Bearer) per https://docs.qatools.ru/api
"""

import urllib.parse
import urllib.request
import urllib.error
import json
from typing import Any

_AUTH_HINT = "Проверьте ALLURE_TOKEN: создайте новый API-токен в Allure TestOps (профиль → API Tokens) и обновите переменную окружения."


def get_jwt(base_url: str, api_token: str) -> str:
    """Exchange API token for JWT via OAuth."""
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
        if e.code == 401:
            raise RuntimeError(f"Ошибка авторизации (401): неверный или истёкший API-токен. {_AUTH_HINT}") from e
        raise RuntimeError(f"Ошибка при получении JWT: HTTP {e.code}: {e.read().decode() if e.fp else ''}") from e
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"OAuth response missing access_token: {body}")
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
    """
    jwt = get_jwt(base_url, api_token)
    rql = f'name ~= "{name_query}"'
    result = search_test_cases(base_url, jwt, project_id, rql, page=0, size=size)
    return result.get("content") or []
