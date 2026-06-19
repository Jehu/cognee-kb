.PHONY: test test-py test-web install build check

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

## Schnellprüfung: Deps ok + beide Suites grün + PWA baut.
check: install test build
