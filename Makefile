.PHONY: fmt lint typecheck test-unit test-int test-e2e test coverage-check security build

fmt:
	uv run ruff format src tests
	uv run ruff check --fix-only src tests

lint:
	uv run ruff format --check src tests
	uv run ruff check src tests

typecheck:
	uv run mypy

test-unit:
	uv run pytest tests/unit --cov --cov-report=term

# Exit code 5 = no tests collected; tolerated until integration suites land (P0-5+).
test-int:
	uv run pytest tests/integration --cov --cov-append --cov-report= || [ $$? -eq 5 ]

test-e2e:
	uv run pytest tests/e2e --cov --cov-append --cov-report= || [ $$? -eq 5 ]

# Coverage bar (ADR-0010): >=85% on the combined unit+integration+e2e run.
coverage-check:
	uv run coverage report --fail-under=85

test: test-unit test-int test-e2e coverage-check

security:
	git ls-files -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
	uv run pip-audit --skip-editable

build:
	docker build -t neuralgram:dev .
