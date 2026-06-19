.PHONY: test test-py test-web install build lint check

install:
	uv sync
	cd web && npm install

test-py:
	uv run pytest

test-web:
	cd web && npm test

test: test-py test-web

build:
	cd web && npm run build

lint:
	uv run ruff check kb tests
	uv run ruff format --check kb tests
	uv run mypy kb

## Schnellprüfung: Deps ok + Lint + beide Suites grün + PWA baut.
check: install lint test build
