PYTHON ?= python3

.PHONY: help check

help: ## List available commands
	@printf '%s\n' \
		'make help   List available commands' \
		'make check  Validate every skill and run behavioral tests'

check: ## Validate skills and run the test suite
	$(PYTHON) scripts/check_skills.py
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
