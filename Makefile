.PHONY: test validate smoke

PYTHON ?= python3

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error::ResourceWarning \
		$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) moni.py validate examples/moni.json

smoke: test validate
