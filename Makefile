# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

.PHONY: check test coverage lint compile-defaults clean help

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

clean:  ## Remove generated files
	rm -rf .pytest_cache __pycache__ apysource/__pycache__ .mypy_cache

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
