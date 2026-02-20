#!/usr/bin/env bash
# Run from anywhere (without pip install). Script finds project root by its own path.
cd "$(dirname "$0")" && PYTHONPATH="$(pwd)" exec python -m allure_cli "$@"
