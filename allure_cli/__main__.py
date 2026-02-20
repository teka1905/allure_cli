"""Run as: python -m allure_cli "..." or allure_cli "..." after pip install -e ."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
