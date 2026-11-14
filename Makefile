PY ?= .venv/bin/python

lint:
	$(PY) -m black --check scripts tests
	$(PY) -m isort --check-only scripts tests
	$(PY) -m flake8 scripts tests

test:
	$(PY) -m pytest -q tests

ci: lint test

ci-docker:
	docker run --rm -v "$(PWD):/workspace" -w /workspace python:3.13-slim sh -c "apt-get update -qq && apt-get install -y -qq --no-install-recommends make >/dev/null && pip install -q -e '.[dev]' && make PY=python ci"

.PHONY: lint test ci ci-docker
