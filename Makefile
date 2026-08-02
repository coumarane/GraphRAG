.PHONY: sync lint format format-check typecheck test unit integration evaluation acceptance compose-config up down

sync:
	uv sync --all-extras

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

unit:
	uv run pytest tests/unit

integration:
	uv run pytest tests/integration

evaluation:
	uv run pytest tests/evaluation -m evaluation

test:
	uv run pytest

compose-config:
	docker compose config

up:
	docker compose up -d --wait

down:
	docker compose down

acceptance: format-check lint typecheck unit evaluation compose-config
