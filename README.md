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

CLI поддерживает две команды:

1. **`search`** (по умолчанию) — поиск тест-кейсов по ID или названию
2. **`find-orphaned`** — поиск осиротевших (устаревших) тестов

**Справка:**
```bash
# Общая справка
allure_cli
allure_cli --help

# Справка по команде search
allure_cli search
allure_cli search --help

# Справка по команде find-orphaned
allure_cli find-orphaned --help
```

### Команда `search` (поиск тестов)

```bash
export ALLURE_ENDPOINT=https://allure-testops.example.com
export ALLURE_PROJECT_ID=211
export ALLURE_TOKEN=<ваш_токен>

# Поиск по подстроке названия
allure_cli search "Автоответ в чат"

# Старый синтаксис (без команды) тоже работает
allure_cli "Автоответ в чат"

# Показать справку
allure_cli search
allure_cli search --help
```

**Примеры:**

```bash
# Поиск по подстроке названия — выводит id и name с цветами
allure_cli search "Автоответ в чат"

# Поиск по ID (число)
allure_cli search 12345

# Только ID, по одному на строку (без цветов)
allure_cli search -q "Автоответ в чат"

# Без цветов
allure_cli search --no-color "Автоответ в чат"

# Параметры через аргументы
allure_cli search --url https://allure-testops.example.com --project 211 --token $ALLURE_TOKEN "запрос"
```

**Вывод:**
- В обычном режиме: номер, ID (синий), название (циан), и fullName (серый) если отличается
- Результаты с цветной подсветкой для лучшей читаемости
- В quiet режиме (`-q`): только ID, по одному на строку (без цветов)

**Пример вывода:**
```
Found 3 test cases:

1. ID 12345    User login with valid credentials
   └─ tests.auth.test_login.test_user_login_valid
2. ID 12389    User login with OAuth provider
   └─ tests.auth.oauth.test_login_oauth
3. ID 12401    User login with 2FA enabled
   └─ tests.auth.two_factor.test_login_2fa
```

Где:
- `12345`, `12389`, `12401` — синий, жирный (ID)
- `User login...` — циан (название)
- `tests.auth...` — серый (fullName)

**Примечание:** Значение **ID** — это Allure ID для декоратора `@allure.id("...")` в коде тестов.

### Команда `find-orphaned` (поиск устаревших тестов)

Находит потенциально осиротевшие тест-кейсы — тесты, которые давно не обновлялись и имеют похожие активные тесты (потенциальные дубликаты с новым ID).

**Проблема:** Когда в автотестах меняется название шагов или имя сценария, Allure генерирует новый ID. В БД остаётся старый тест, который больше не выполняется и не поддерживается.

**Решение:** Команда `find-orphaned` ищет такие тесты по двум критериям:
1. Тест не обновлялся N дней (по умолчанию 30)
2. Есть другие тесты с похожими названиями (similarity >= 0.75)

```bash
# Найти осиротевшие тесты (по умолчанию: неактивны 30+ дней + similarity >= 0.75)
allure_cli find-orphaned

# Только неактивные тесты (без проверки схожести)
allure_cli find-orphaned --days 60

# Только тесты с похожими названиями (без проверки неактивности)
allure_cli find-orphaned --similarity 0.8

# Оба критерия одновременно
allure_cli find-orphaned --days 60 --similarity 0.8

# Только ID (для скриптов)
allure_cli find-orphaned -q

# Интерактивное удаление найденных тестов
allure_cli find-orphaned --delete
```

**Параметры:**

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `--days` | Порог неактивности (дни). Если указан один, фильтрует только по дням | 30 (если не указан `--similarity`) |
| `--similarity` | Порог схожести названий (0.0-1.0). Если указан один, фильтрует только по схожести | 0.75 (если не указан `--days`) |
| `--no-normalize` | Отключить умную нормализацию названий (см. ниже) | false (нормализация включена) |
| `--no-color` | Отключить цветной вывод | false (цвета включены) |
| `--delete` | Интерактивное удаление найденных тестов | false |
| `-q, --quiet` | Вывести только ID | false |

**Цветной вывод:**

По умолчанию результаты выводятся с цветами для лучшей читаемости:
- 🔴 **Красный** — осиротевшие тесты (кандидаты на удаление)
- 🟢 **Зелёный** — высокая схожесть (≥0.9) или свежие тесты (<7 дней)
- 🟡 **Жёлтый** — средняя схожесть (0.75-0.9) или средний возраст (7-30 дней)
- 🔵 **Синий** — ID тестов
- 🟣 **Пурпурный** — заголовки секций
- ⚪ **Серый** — второстепенная информация

Цвета автоматически отключаются при:
- Перенаправлении вывода в файл
- Переменной окружения `NO_COLOR`
- Флаге `--no-color`

```bash
# Отключить цвета
allure_cli find-orphaned --no-color

# Или через переменную окружения
NO_COLOR=1 allure_cli find-orphaned
```

**Логика работы флагов:**
- Без флагов: применяются оба критерия (`--days 30 --similarity 0.75`)
- Только `--days N`: ищет тесты неактивные N+ дней (без проверки схожести)
- Только `--similarity X`: ищет тесты с похожими названиями (без проверки неактивности)
- Оба флага: применяются оба критерия одновременно

**Умная нормализация названий:**

По умолчанию включена нормализация названий для более точного поиска дубликатов. Удаляется "шум":
- **Даты**: `2024-01-15`, `15/01/2024`, `20240115`
- **Временные метки**: `14:30:45`, Unix timestamps
- **Версии**: `v1.2.3`, `version 2`
- **ID и номера**: `test-123`, `[ID-456]`, `#789`, изолированные числа
- **Стоп-слова**: `test`, `check`, `verify`, `should`, `when`, `then`, `given`

**Примеры:**
```
Оригинал: "Test [TC-123] User login verification 2024-01-15"
Нормализованное: "user login"

Оригинал: "Check user login #456 v2.0"  
Нормализованное: "user login"

Результат: similarity = 1.0 (идентичны после нормализации)
```

Чтобы отключить нормализацию (сравнивать названия как есть):
```bash
allure_cli find-orphaned --no-normalize
```

**Пример вывода:**

```
Searching for orphaned tests (inactive for 30+ days, similarity >= 0.75)...

Found 2 potentially orphaned test(s):

1. Test ID 12345 (inactive for 45 days)
   Name: User login test
   Similar tests found:
      - ID 12389 (similarity: 0.92, inactive: 2 days)
        User login test updated
      - ID 12401 (similarity: 0.85, inactive: 0 days)
        User login with OAuth test

2. Test ID 11234 (inactive for 67 days)
   Name: Payment flow test
   Similar tests found:
      - ID 12500 (similarity: 0.88, inactive: 1 days)
        Payment flow test refactored
```

**Интерактивное удаление:**

```bash
allure_cli find-orphaned --delete
```

Для каждого найденного теста будет предложено:
- `y` — удалить тест
- `n` — пропустить
- `q` — завершить

## Авторизация

Используется схема из [документации ТестОпс](https://docs.qatools.ru/api): API-токен обменивается на JWT через `POST /api/uaa/oauth/token`, далее запросы к API — с заголовком `Authorization: Bearer <jwt>`.

JWT кэшируется на диск (`~/.cache/allure_cli/` или `$XDG_CACHE_HOME/allure_cli/`), чтобы не запрашивать новый токен при каждом вызове. При ответе 401 от API кэш сбрасывается и токен запрашивается заново автоматически.
