VENV ?= $(CURDIR)/.venv

ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.12
PY := $(VENV)/Scripts/python.exe
BIN := $(VENV)/Scripts
LINT_IMPORTS := $(BIN)/lint-imports.exe
else
PYTHON ?= python3
PY := $(VENV)/bin/python
BIN := $(VENV)/bin
LINT_IMPORTS := $(BIN)/lint-imports
endif

.PHONY: install backend frontend check lint lint-imports types test test-backend test-frontend contracts

install:
	$(PYTHON) -m venv "$(VENV)"
	"$(PY)" -m pip install -e "backend[dev]"
	cd earth-view && npm ci
	cd frontend && npm ci

backend:
	"$(PY)" -m uvicorn earth_platform.main:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

lint:
	"$(PY)" -m ruff check --config backend/pyproject.toml backend scripts
	cd frontend && npm run lint

lint-imports:
	cd backend && "$(LINT_IMPORTS)"

types:
	cd backend && "$(PY)" -m mypy src
	cd frontend && npm run typecheck

test-backend:
	cd backend && "$(PY)" -m pytest

test-frontend:
	cd frontend && npm test

test: test-backend test-frontend

contracts:
	"$(PY)" scripts/export_contracts.py
	cd frontend && npm run gen:contracts

check: lint lint-imports types test
