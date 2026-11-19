PYTHON ?= python3

.PHONY: help test check setup-bash32 integration-open-design

help: ## List available commands
	@printf '%s\n' \
		'make help                     List available commands' \
		'make test                     Run behavioral and security regressions' \
		'make check                    Validate every skill, then run tests' \
		'make setup-bash32 BASH32_DIR=DIR  Build the pinned Bash 3.2 test interpreter' \
		'make integration-open-design  Verify pinned Open Design plugin loading and staging'

test: ## Run behavioral and security regressions
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

check: ## Validate skills and run the test suite
	$(PYTHON) scripts/check_skills.py
	$(MAKE) test

integration-open-design: ## Verify exact Open Design plugin loading in OPEN_DESIGN_REPO
	@test -n "$(OPEN_DESIGN_REPO)" || { printf '%s\n' 'OPEN_DESIGN_REPO is required' >&2; exit 2; }
	OPEN_DESIGN_REPO="$(OPEN_DESIGN_REPO)" $(PYTHON) -m unittest tests.test_open_design_integration

setup-bash32: ## Build Bash 3.2 for shell compatibility tests (requires gcc, make, bison)
	@test -n "$(BASH32_DIR)" || { printf '%s\n' 'BASH32_DIR is required' >&2; exit 2; }
	bash scripts/setup-bash32.sh "$(BASH32_DIR)"
