.PHONY: sync lint format format-check typecheck test unit integration evaluation acceptance compose-config up down

BACKEND := --directory backend

sync:
	uv $(BACKEND) sync --all-extras

lint:
	uv $(BACKEND) run ruff check .

format:
	uv $(BACKEND) run ruff format .

format-check:
	uv $(BACKEND) run ruff format --check .

typecheck:
	uv $(BACKEND) run mypy src

unit:
	uv $(BACKEND) run pytest tests/unit

integration:
	uv $(BACKEND) run pytest tests/integration

evaluation:
	uv $(BACKEND) run pytest tests/evaluation -m evaluation

test:
	uv $(BACKEND) run pytest

compose-config:
	docker compose config

up:
	docker compose up -d --wait

down:
	docker compose down

acceptance: format-check lint typecheck unit evaluation compose-config
