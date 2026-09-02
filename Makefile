.PHONY: init
init:
	uv sync

.PHONY: verify
verify: init
	uv run black --check .
	uv run isort --profile black .
	uv run mypy .
	uv run flake8 --ignore=E501,E704 src tests
	uv run pylint -d 'C0111' src tests
	uv run pytest --cov=solaxng --cov-fail-under=100 --cov-branch --cov-report=term-missing .

.PHONY: test
test:
	uv run pytest --cov=solaxng --cov-fail-under=100 --cov-branch --cov-report=term-missing .

BUMP ?= patch

.PHONY: release
release:
	@case "$(BUMP)" in \
		patch|minor|major) ;; \
		*) echo "Usage: make release BUMP=patch|minor|major" >&2; exit 1 ;; \
	esac
	uv version --bump $(BUMP)
	git add pyproject.toml uv.lock
	git commit -m "chore: bump version to $$(uv version --short)"
	git tag "v$$(uv version --short)"

.PHONY: build
build:
	rm -rf dist
	uv build

.PHONY: publish
publish: build
	uv publish

.PHONY: clean
clean: clean-build clean-pyc clean-test

.PHONY: clean-build
clean-build:
	rm -rf dist

.PHONY: clean-pyc
clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

.PHONY: clean-test
clean-test:
	rm -rf .pytest_cache .mypy_cache .coverage

.PHONY: mrproper
mrproper: clean
	rm -rf .venv
