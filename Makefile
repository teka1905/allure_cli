.PHONY: help clean build upload upload-test install dev bump-version lint test

help:
	@echo "Доступные команды:"
	@echo "  make clean        - Удалить артефакты сборки"
	@echo "  make build        - Собрать пакет"
	@echo "  make bump-version - Обновить версию (patch/minor/major)"
	@echo "  make upload-test  - Загрузить на TestPyPI"
	@echo "  make upload       - Загрузить на PyPI"
	@echo "  make install      - Установить в режиме разработки"
	@echo "  make dev          - Установить зависимости для разработки"

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

build: clean
	python -m build
	twine check dist/*

bump-version:
	@echo "Текущая версия:"
	@grep '^version' pyproject.toml
	@echo ""
	@echo "Выберите тип обновления:"
	@echo "  patch - 0.1.0 -> 0.1.1"
	@echo "  minor - 0.1.0 -> 0.2.0"
	@echo "  major - 0.1.0 -> 1.0.0"
	@echo ""
	@read -p "Тип (patch/minor/major): " type; \
	current=$$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	IFS='.' read -r major minor patch <<< "$$current"; \
	case $$type in \
		patch) new="$$major.$$minor.$$((patch + 1))" ;; \
		minor) new="$$major.$$((minor + 1)).0" ;; \
		major) new="$$((major + 1)).0.0" ;; \
		*) echo "Неверный тип: $$type" && exit 1 ;; \
	esac; \
	echo "Новая версия: $$new"; \
	sed -i.bak "s/^version = \".*\"/version = \"$$new\"/" pyproject.toml && rm pyproject.toml.bak; \
	echo "✓ Версия обновлена до $$new в pyproject.toml"

upload-test: build
	twine upload --repository testpypi dist/*

upload: build
	@echo "⚠️  Публикация на PyPI (production)!"
	@read -p "Продолжить? [y/N]: " confirm && [ "$$confirm" = "y" ] || (echo "Отменено" && exit 1)
	twine upload dist/*

install:
	pip install -e .

dev:
	pip install --upgrade pip build twine
