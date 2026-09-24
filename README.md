# Allure CLI

A CLI for Allure TestOps. Its main job is looking up a test case's Allure ID by name; it can also create, delete and audit test cases, and show why a launch failed — messages, traces and attachments.

[![PyPI version](https://badge.fury.io/py/allure-cli.svg)](https://pypi.org/project/allure-cli/)
[![Python](https://img.shields.io/pypi/pyversions/allure-cli.svg)](https://pypi.org/project/allure-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)

## Installation

```bash
pip install allure-cli
```

After installation the `allure-cli` command is available in your PATH.

## Configuration

Environment variables (or the `--url`, `--token`, `--project` arguments):

| Variable | Description |
|----------|-------------|
| `ALLURE_ENDPOINT` or `ALLURE_TESTOPS_URL` | Allure TestOps base URL (e.g. `https://allure-testops.example.com`) |
| `ALLURE_TOKEN` | API token (created in Allure: profile → API Tokens) |
| `ALLURE_PROJECT_ID` | Project ID (e.g. `211`) |

**To persist them (zsh/bash),** add this to `~/.zshrc` or `~/.bashrc`:

```bash
# Allure TestOps CLI
export ALLURE_ENDPOINT="https://allure-testops.example.com"
export ALLURE_PROJECT_ID="YOUR_PROJECT_ID"
export ALLURE_TOKEN="<YOUR_TOKEN>"
```

## Usage

The CLI has seven commands:

1. **`search`** (the default) — find test cases by ID or name
2. **`find-orphaned`** — find orphaned (stale) tests
3. **`delete`** — delete test cases by ID
4. **`create`** — create test cases, one by one or in bulk from a file
5. **`launches`** — list launches, optionally filtered by name
6. **`failures`** — failed and broken tests of a launch: message, trace, attachments
7. **`attachments`** — list or download the attachments of a test result

**Help:**

```bash
# General help
allure-cli
allure-cli --help

# Per-command help
allure-cli search --help
allure-cli find-orphaned --help
allure-cli delete --help
allure-cli create --help
allure-cli failures --help
```

### `search` — find tests

```bash
export ALLURE_ENDPOINT=https://allure-testops.example.com
export ALLURE_PROJECT_ID=211
export ALLURE_TOKEN=<your_token>

# Search by a substring of the name
allure-cli search "User login"

# The old syntax (no command) still works
allure-cli "User login"

# Search by ID (a number)
allure-cli search 12345

# IDs only, one per line (no colors)
allure-cli search -q "User login"

# Pass the settings as arguments
allure-cli search --url https://allure-testops.example.com --project 211 --token $ALLURE_TOKEN "query"
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--size` | Maximum number of results | 50 |
| `-q, --quiet` | Print IDs only, one per line | false |
| `--no-color` | Disable colored output | false |

**Output:**

- Normal mode: index, ID (blue), name (cyan) and `fullName` (grey) when it differs
- Quiet mode (`-q`): IDs only, one per line, no colors

**Example output:**

```
Found 2 test cases:

1. ID 12345	User login with valid credentials
   └─ tests.auth.test_login.test_user_login_valid
2. ID 12389	User login with OAuth provider
   └─ tests.auth.oauth.test_login_oauth
```

Where:

- `12345`, `12389` — blue, bold (the ID)
- `User login...` — cyan (the name)
- `tests.auth...` — grey (the `fullName`)

**Note:** the **ID** is the Allure ID for the `@allure.id("...")` decorator in your test code.

### `find-orphaned` — find stale tests

Finds test cases that look orphaned: not updated for a long time, and having similar active tests (likely the same scenario under a new ID).

**The problem:** when a step title or scenario name changes in the automated tests, Allure generates a new ID. The old test stays in the database, no longer executed or maintained.

**The solution:** `find-orphaned` looks for such tests by two criteria:

1. The test has not been updated for N days (30 by default)
2. Other tests have similar names (similarity >= 0.75)

```bash
# Find orphaned tests (default: inactive for 30+ days and similarity >= 0.75)
allure-cli find-orphaned

# Inactive tests only (no similarity check)
allure-cli find-orphaned --days 60

# Similar names only (no inactivity check)
allure-cli find-orphaned --similarity 0.8

# Both criteria at once
allure-cli find-orphaned --days 60 --similarity 0.8

# IDs only (for scripts)
allure-cli find-orphaned -q

# Delete the found tests interactively
allure-cli find-orphaned --delete

# Delete every found test without asking about each one
allure-cli find-orphaned --delete --yes
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--days` | Inactivity threshold in days. On its own, filters by age only | 30 (when `--similarity` is not given) |
| `--similarity` | Name similarity threshold, 0.0-1.0. On its own, filters by similarity only | 0.75 (when `--days` is not given) |
| `--no-normalize` | Disable smart name normalization (see below) | false (normalization is on) |
| `--no-color` | Disable colored output | false |
| `--delete` | Delete the found tests interactively | false |
| `-y, --yes` | With `--delete`: delete every found test without asking | false |
| `-q, --quiet` | Print IDs only | false |

**How the flags combine:**

- No flags: both criteria apply (`--days 30 --similarity 0.75`)
- `--days N` only: finds tests inactive for N+ days, without the similarity check
- `--similarity X` only: finds tests with similar names, without the inactivity check
- Both flags: both criteria apply at once

**Smart name normalization:**

Name normalization is on by default, so duplicates are matched more reliably. The "noise" it strips:

- **Dates**: `2024-01-15`, `15/01/2024`, `20240115`
- **Timestamps**: `14:30:45`, Unix timestamps
- **Versions**: `v1.2.3`, `version 2`
- **IDs and numbers**: `test-123`, `[ID-456]`, `#789`, standalone numbers
- **Stop words**: `test`, `check`, `verify`, `should`, `when`, `then`, `given`

**Examples:**

```
Original:   "Test [TC-123] User login verification 2024-01-15"
Normalized: "user login"

Original:   "Check user login #456 v2.0"
Normalized: "user login"

Result: similarity = 1.0 (identical after normalization)
```

To turn normalization off and compare names as they are:

```bash
allure-cli find-orphaned --no-normalize
```

**Colored output:**

Results are colored by default for readability:

- 🟢 **Green** — high similarity (≥0.9) or fresh tests (<7 days)
- 🟡 **Yellow** — medium similarity (0.75-0.9) or medium age (7-30 days)
- 🔴 **Red** — low similarity or old tests (30+ days)
- 🔵 **Blue** — test IDs
- 🟣 **Magenta** — section headings
- ⚪ **Grey** — secondary details

Colors are disabled automatically when:

- The output is redirected to a file
- The `NO_COLOR` environment variable is set
- The `--no-color` flag is given

```bash
# Disable colors
allure-cli find-orphaned --no-color

# Or via the environment variable
NO_COLOR=1 allure-cli find-orphaned
```

**Example output:**

```
Searching for orphaned tests (inactive for 30+ days, similarity >= 0.75)...

Found 2 potentially orphaned test(s):

1. ID 12345	User login test [TC-123] 2024-01-15 (45 days)
   └─ tests.auth.test_login
   Similar tests:
      • ID 12389 (1.00, 2d) Check user login #456 v2.0

2. ID 11234	Payment flow test v1.2 (67 days)
   └─ tests.pay.test_flow
   Similar tests:
      • ID 12500 (1.00, 1d) Payment flow test v2.0
```

**Interactive deletion:**

```bash
allure-cli find-orphaned --delete
```

For every test found you are asked:

- `y` — delete the test
- `n` — skip it
- `a` — delete this one and all the remaining tests, without asking again
- `q` — stop

To skip the prompting entirely, add `--yes`: the list of found tests is printed first, and then all of them are deleted.

```bash
allure-cli find-orphaned --delete --yes
```

### `delete` — delete tests

Deletes test cases by ID. The IDs can be given as arguments, read from a file, or both.

**File format** — either a plain text file with one ID per line, or a CSV file with an `allure_id` column (`,` and `;` separators are both detected):

```
allure_id,name
12345,User login with valid credentials
12999,Payment flow test
```

**Usage:**

```bash
# Delete by IDs given as arguments
allure-cli delete 12345 12999

# Delete the IDs listed in a file
allure-cli delete --file test_cases.csv

# Show what would be deleted and exit
allure-cli delete --file test_cases.csv --dry-run

# Skip the confirmation prompt (dangerous!)
allure-cli delete --file test_cases.csv --yes

# Show the full list instead of truncating it
allure-cli delete --file test_cases.csv --verbose

# Skip fetching test details before deleting (faster)
allure-cli delete --file test_cases.csv --no-fetch
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `-f, --file` | Path to a file with IDs (plain text or CSV with an `allure_id` column) | — |
| `--dry-run` | Only show what would be deleted | false |
| `-y, --yes` | Skip the confirmation prompt | false |
| `-v, --verbose` | Show every test case (lists over 50 are truncated otherwise) | false |
| `--no-fetch` | Don't fetch test details, just show the IDs | false |
| `--no-color` | Disable colored output | false |

**How the deletion is sent:** when the project is known (`--project` or `ALLURE_PROJECT_ID`) and there is more than one ID, the whole batch goes out as a single bulk request. The API confirms the batch as a whole rather than each ID, so the summary says "Submitted". Without a project — and if the bulk request fails — the IDs are deleted one at a time, which costs a request per test case but reports the exact status of each.

**Example output** (bulk, the project is known):

```
About to delete 2 test case(s):

1. ID 12345	User login with valid credentials
   └─ tests.auth.test_login.test_user_login_valid
2. ID 12999    (not found)

Are you sure? [y/N] y
  ✓ Submitted 2 test case(s) in one request

Done. Submitted: 2
```

**Example output** (one by one, no project given):

```
Are you sure? [y/N] y
  ✓ 12345 deleted
  – 12999 not found

Done. Deleted: 1, Not found: 1, Failed: 0
```

### `create` — create tests

Creates a single test case from the command line, or many at once from a CSV or JSON file. The two modes are mutually exclusive: pass either a name or `--file`.

**A single test case:**

```bash
allure-cli create "User login with valid credentials" \
  -d "The user signs in with a correct login and password" \
  --full-name tests.auth.test_login.test_user_login_valid \
  -t smoke -t regression
```

The new ID is printed to stdout, so it can be piped further.

**CSV file** (columns: `name`, optional `description`, `full_name`, `tags`; tags are separated by `;`):

```
name,description,tags
New test case 1,Description for test case 1,tag1;tag2
New test case 2,Description for test case 2,tag3
```

**JSON file:**

```json
[
  {
    "name": "New test case 1",
    "description": "Description for test case 1",
    "tags": ["tag1", "tag2"]
  },
  {
    "name": "New test case 2",
    "description": "Description for test case 2",
    "tags": ["tag3"]
  }
]
```

**Usage:**

```bash
# Create test cases from a CSV file
allure-cli create --file test_cases.csv

# Create test cases from a JSON file
allure-cli create --file test_cases.json

# Show what would be created and exit
allure-cli create --file test_cases.csv --dry-run
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `-f, --file` | Path to a CSV or JSON file for bulk creation | — |
| `-d, --description` | Description (single test case only) | — |
| `--full-name` | Full name / path (single test case only) | — |
| `-t, --tag` | Tag, repeatable (single test case only; in bulk mode tags come from the file) | — |
| `--dry-run` | Only show what would be created | false |
| `--no-color` | Disable colored output | false |

**Example output — a single test case:**

```
Creating test case:
  Name: New test case 1
  Description: Description for test case 1

✓ Created test case:
  ID 12347	New test case 1
```

**Example output — bulk creation:**

```
About to create 1 test case(s):

1. New test case 1
   desc: Description for test case 1
   tags: tag1, tag2
  ✓ 12347 New test case 1

Done. Created: 1, Failed: 0
```

### `launches` — list launches

```bash
# The 10 most recent launches of the project
allure-cli launches

# Launches whose name contains a substring (newest first)
allure-cli launches "pr_15967418"

# IDs only / JSON for scripts
allure-cli launches "nightly" -q
allure-cli launches "nightly" --json
```

| Option | Description | Default |
|--------|-------------|---------|
| `--size` | Maximum number of launches | 10 |
| `-q, --quiet` | Print IDs only, one per line | false |
| `--json` | Print launches as JSON | false |
| `--no-color` | Disable colored output | false |

**Example output:**

```
ID 748636	2026-09-23 18:11	open	user-pr_15967418-37790018 --seed d8002021
```

### `failures` — why a launch is red

Shows every `failed` and `broken` test result of a launch with its error message.
The launch is given by ID or by a substring of its name; the newest matching launch is used.
A number is tried as a launch ID first and then as a name, so a PR or build number found
in launch names works as is.

```bash
# By launch ID
allure-cli failures 748636

# By a part of the launch name (e.g. a PR number)
allure-cli failures 15967418

# Full traces instead of messages
allure-cli failures 748636 --trace

# Also save the attachments (screenshots, logs) to ./allure/<test result id>/
allure-cli failures 748636 --download ./allure

# Everything, traces included, as JSON — handy for scripts and AI agents
allure-cli failures 748636 --json
```

| Option | Description | Default |
|--------|-------------|---------|
| `--trace` | Print the full trace of every failure | false |
| `--download DIR` | Save attachments of every failure to `DIR/<test result id>/` | — |
| `--json` | Print launch, status counts and failures (with traces) as JSON | false |
| `--no-color` | Disable colored output | false |

**Example output:**

```
Launch 748636 · 2026-09-23 18:11 · open
user-pr_15967418-37790018 --seed d8002021
failed 2 · passed 344

1. [failed] Link a knowledge article to a ticket
   └─ scenarios/admin/ticket_page/link_knowledge.py::Scenario
   result 1399454750 · 40.7s
   AssertionError: the knowledge base widget did not show the service
   attachments: 12 → allure/1399454750
```

### `attachments` — files of a test result

```bash
# List the attachments of a test result (the ID comes from `failures`)
allure-cli attachments 1399454750

# Download them
allure-cli attachments 1399454750 --download ./allure/1399454750
```

Attachment files keep their names from Allure; when a name repeats within a test result,
the attachment ID is appended (`shot.png`, `shot_1723967328.png`). Downloading again
overwrites the same files. `--project` is not needed for this command.

## Authorization

The scheme comes from the [TestOps documentation](https://docs.qatools.ru/api): the API token is exchanged for a JWT via `POST /api/uaa/oauth/token`, and API requests then carry an `Authorization: Bearer <jwt>` header.

The JWT is cached on disk (`~/.cache/allure_cli/` or `$XDG_CACHE_HOME/allure_cli/`) so a new one isn't requested on every call. When the API answers 401, the cache is dropped and the token is re-issued automatically.
