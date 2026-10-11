.PHONY: test validate smoke release-check

PYTHON ?= python3

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error::ResourceWarning \
		$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) moni.py validate examples/moni.json

smoke: test validate

release-check: smoke
	@artifact_dir=$$(mktemp -d); \
	$(PYTHON) -m pip wheel . --no-deps --no-build-isolation -w "$$artifact_dir" >/dev/null; \
	$(PYTHON) -c 'import glob, zipfile, sys; wheel = glob.glob(sys.argv[1] + "/*.whl")[0]; names = set(zipfile.ZipFile(wheel).namelist()); required = {"moni.py", "history.py", "notifier.py", "agent.py", "api.py", "components.py"}; missing = sorted(required - {name.rsplit("/", 1)[-1] for name in names}); sys.exit("missing release modules: " + ", ".join(missing)) if missing else print("release artifact verified: " + wheel)' "$$artifact_dir"; \
	rm -rf "$$artifact_dir"
