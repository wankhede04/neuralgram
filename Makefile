.PHONY: fmt lint typecheck test-unit test-int test security build

fmt:
	uv run ruff format src tests
	uv run ruff check --fix-only src tests

lint:
	uv run ruff format --check src tests
	uv run ruff check src tests

typecheck:
	uv run mypy

test-unit:
	uv run pytest tests/unit --cov --cov-fail-under=85

# Exit code 5 = no tests collected; tolerated until integration suites land (P0-5+).
test-int:
	uv run pytest tests/integration || [ $$? -eq 5 ]

test: test-unit test-int

security:
	git ls-files -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
	uv run pip-audit --skip-editable

build:
	docker build -t neuralgram:dev .
