# Local checks, the same as CI. Database tests need HC_TEST_DATABASE_URL (see README).
.PHONY: check lint test web

check: lint test web

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests

test:
	uv run pytest

web:
	cd web && npm ci && npm run typecheck && npm test && npm run build
