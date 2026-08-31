#! /usr/bin/env sh

set -e

echo "Syncing dependencies..."
uv sync

echo "Running black..."
uv run black --check .

echo "Running isort"
uv run isort --profile black .

echo "Running mypy..."
uv run mypy .

echo "Running flake8..."
uv run flake8 --ignore=E501,E704 src tests

echo "Running pylint..."
uv run pylint -d 'C0111' src tests

echo "Running pytest..."
uv run pytest --cov=solax --cov-fail-under=100 --cov-branch --cov-report=term-missing .
