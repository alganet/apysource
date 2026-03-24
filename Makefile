# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

.PHONY: check test coverage lint compile-defaults clean dist publish site help

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

lint:  ## Run type checking with mypy
	python -m mypy apysource/

compile-defaults:  ## Regenerate _defaults.py from defaults.toml
	python -m apywire compile --format toml defaults.toml > apysource/_defaults.py

dist:  ## Build source and wheel distributions
	python -m build

publish: dist  ## Build and upload to PyPI
	twine upload dist/*

site:  ## Assemble GitHub Pages site into _site/
	mkdir -p _site
	cp vocab/vocab.ttl vocab/shapes.ttl vocab/index.html _site/
	pylode vocab/vocab.ttl -o _site/vocab.html

clean:  ## Remove generated files
	rm -rf .pytest_cache __pycache__ apysource/__pycache__ .mypy_cache dist build *.egg-info _site

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
