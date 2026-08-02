.PHONY: install run format lint test clean docker-build docker-run

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run mypy app

test:
	uv run pytest tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker-build:
	docker build -t ai-db-analyst .

docker-run:
	docker run -p 8000:8000 ai-db-analyst

docker-compose-up:
	docker-compose up --build
