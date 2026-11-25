PYTHON ?= python3
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy

.PHONY: check lint types test format privacy dist
check: lint types privacy test

lint:
	$(RUFF) check .
	$(RUFF) format --check .

types:
	$(MYPY)

test:
	$(PYTHON) -m unittest discover -s tests -v

format:
	$(RUFF) check --fix .
	$(RUFF) format .

privacy:
	$(PYTHON) scripts/source_package.py --check

dist: privacy
	$(PYTHON) scripts/source_package.py
