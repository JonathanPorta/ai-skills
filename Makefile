PYTHON ?= python3

.PHONY: help test check integration-open-design

help: ## List available commands
	@printf '%s\n' \
		'make help                     List available commands' \
		'make test                     Run behavioral and security regressions' \
		'make check                    Validate every skill, then run tests' \
		'make integration-open-design  Verify the pinned Open Design contract'

test: ## Run behavioral and security regressions
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

check: ## Validate skills and run the test suite
	$(PYTHON) scripts/check_skills.py
	$(MAKE) test

integration-open-design: ## Verify the exact Open Design source contract in OPEN_DESIGN_REPO
	@test -n "$(OPEN_DESIGN_REPO)" || { printf '%s\n' 'OPEN_DESIGN_REPO is required' >&2; exit 2; }
	OPEN_DESIGN_REPO="$(OPEN_DESIGN_REPO)" $(PYTHON) -m unittest tests.test_open_design_integration
