# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

.PHONY: check test coverage lint format compile-defaults clean dist publish site help

# =============================================================================
# VERIFICATION
# =============================================================================

check: lint coverage  ## Run all verification — exit 1 on any failure
	@echo ""

# =============================================================================
# DEVELOPMENT
# =============================================================================

test:  ## Run unit tests
	python -m pytest tests/ -v

coverage:  ## Run tests with coverage report (library code only)
	python -m slipcover --source apysource -m pytest tests/ -q

lint:  ## Run ruff (lint) and mypy (type checking)
	python -m ruff check apysource/ tests/
	python -m mypy apysource/

format:  ## Auto-format and fix lint issues with ruff
	python -m ruff format apysource/ tests/
	python -m ruff check --fix apysource/ tests/

compile-defaults:  ## Regenerate _defaults.py from defaults.toml
	python -m apywire compile --format toml defaults.toml > apysource/_defaults.py

dist:  ## Build source and wheel distributions
	python -m build

publish: dist  ## Build and upload to PyPI
	twine upload dist/*

# The `sv:` namespace IS https://alganet.github.io/apysource/vocab.ttl# — the
# filenames below are that URL. Every Turtle file ever written has it in a
# @prefix, so the _site/ names are fixed even though their sources moved into
# the package (where a wheel can carry the shapes). Change a source path here;
# never a destination one.
site:  ## Assemble GitHub Pages site into _site/
	mkdir -p _site
	cp apysource/vocab/vocab.ttl apysource/vocab/shapes.ttl site/index.html _site/
	pylode apysource/vocab/vocab.ttl -o _site/vocab.html

clean:  ## Remove generated files
	rm -rf .pytest_cache __pycache__ apysource/__pycache__ .mypy_cache dist build *.egg-info _site

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
