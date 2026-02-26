# Allure CLI

CLI для работы с Allure TestOps. Основная задача — получение Allure ID тест-кейса по названию.

[![PyPI version](https://badge.fury.io/py/allure-cli.svg)](https://pypi.org/project/allure-cli/)
[![Python](https://img.shields.io/pypi/pyversions/allure-cli.svg)](https://pypi.org/project/allure-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Требования

- Python 3.10+
- Внешние зависимости не нужны (только stdlib)

## Установка

```bash
pip install allure-cli
```

После установки команда `allure_cli` будет доступна в PATH.

## Настройка

Переменные окружения (или аргументы `--url`, `--token`, `--project`):

| Переменная | Описание |
|------------|----------|
| `ALLURE_ENDPOINT` или `ALLURE_TESTOPS_URL` | Базовый URL Allure TestOps (например, `https://allure-testops.example.com`) |
| `ALLURE_TOKEN` | API-токен (создаётся в Allure: профиль → API Tokens) |
| `ALLURE_PROJECT_ID` | ID проекта (например, `211`) |

**Постоянно (zsh/bash):** добавьте в `~/.zshrc` или `~/.bashrc`:

```bash
# Allure TestOps CLI
export ALLURE_ENDPOINT="https://allure-testops.example.com"
export ALLURE_PROJECT_ID="YOUR_PROJECT_ID"
export ALLURE_TOKEN="<YOUR_TOKEN>"
```

## Использование

```bash
export ALLURE_ENDPOINT=https://allure-testops.example.com
export ALLURE_PROJECT_ID=211
export ALLURE_TOKEN=<ваш_токен>

allure_cli "Автоответ в чат"
```

## Примеры

```bash
# Поиск по подстроке названия — выводит id и name
allure_cli "Автоответ в чат"

# Только ID, по одному на строку
allure_cli -q "Автоответ в чат"

# Параметры через аргументы
allure_cli --url https://allure-testops.example.com --project 211 --token $ALLURE_TOKEN "запрос"
```

Вывод (обычный режим): `id` и название тест-кейса; при наличии — `fullName` со следующей строки. Значение **id** — это Allure ID для декоратора `AllureID("...")` в коде тестов.

## Авторизация

Используется схема из [документации ТестОпс](https://docs.qatools.ru/api): API-токен обменивается на JWT через `POST /api/uaa/oauth/token`, далее запросы к API — с заголовком `Authorization: Bearer <jwt>`.

JWT кэшируется на диск (`~/.cache/allure_cli/` или `$XDG_CACHE_HOME/allure_cli/`), чтобы не запрашивать новый токен при каждом вызове. При ответе 401 от API кэш сбрасывается и токен запрашивается заново автоматически.
