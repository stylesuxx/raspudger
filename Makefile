.PHONY: install test lint format typecheck check build-image

IMAGE ?= raspudger-agent:latest

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

test:
	. .venv/bin/activate && pytest -q

lint:
	. .venv/bin/activate && ruff check .

format:
	. .venv/bin/activate && ruff format .

typecheck:
	. .venv/bin/activate && mypy raspudger rig_mcp

check: lint typecheck test
	. .venv/bin/activate && ruff format --check .

build-image:
	docker build -f docker/Dockerfile -t $(IMAGE) .
