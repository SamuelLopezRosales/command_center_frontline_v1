.PHONY: setup lint format test ci hooks test-env test-env-down

PY := uv run --python 3.12

setup:
	uv sync --python 3.12

hooks:
	$(PY) pre-commit install

lint:
	$(PY) ruff check .
	$(PY) ruff format --check .

format:
	$(PY) ruff format .
	$(PY) ruff check --fix .

test:
	$(PY) pytest

# Pipeline mínimo de integración (T-016): lint, pruebas, cdk synth y docker build, sin AWS
ci:
	powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci.ps1

test-env:
	docker compose up -d --wait

test-env-down:
	docker compose down
