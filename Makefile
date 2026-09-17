.PHONY: help clean build upload upload-test install dev bump-version lint test

help:
	@echo "Available commands:"
	@echo "  make clean        - Remove build artifacts"
	@echo "  make build        - Build the package"
	@echo "  make bump-version - Bump the version (patch/minor/major)"
	@echo "  make upload-test  - Upload to TestPyPI"
	@echo "  make upload       - Upload to PyPI"
	@echo "  make install      - Install in development mode"
	@echo "  make dev          - Install development dependencies"
	@echo "  make test         - Run the tests"

test:
	python -m unittest discover -s tests -v

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

build: clean
	python -m build
	twine check dist/*

bump-version:
	@echo "Current version:"
	@grep '^version' pyproject.toml
	@echo ""
	@echo "Choose the bump type:"
	@echo "  patch - 0.1.0 -> 0.1.1"
	@echo "  minor - 0.1.0 -> 0.2.0"
	@echo "  major - 0.1.0 -> 1.0.0"
	@echo ""
	@read -p "Type (patch/minor/major): " type; \
	current=$$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	IFS='.' read -r major minor patch <<< "$$current"; \
	case $$type in \
		patch) new="$$major.$$minor.$$((patch + 1))" ;; \
		minor) new="$$major.$$((minor + 1)).0" ;; \
		major) new="$$((major + 1)).0.0" ;; \
		*) echo "Invalid type: $$type" && exit 1 ;; \
	esac; \
	echo "New version: $$new"; \
	sed -i.bak "s/^version = \".*\"/version = \"$$new\"/" pyproject.toml && rm pyproject.toml.bak; \
	echo "✓ Version bumped to $$new in pyproject.toml"

upload-test: build
	twine upload --repository testpypi dist/*

upload: build
	@echo "⚠️  Publishing to PyPI (production)!"
	@read -p "Continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || (echo "Cancelled" && exit 1)
	twine upload dist/*

install:
	pip install -e .

dev:
	pip install --upgrade pip build twine
