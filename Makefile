.PHONY: test validate smoke release-check release-attest

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

release-attest: release-check
	@out_dir="$${OUT_DIR:-dist}"; repro_dir=$$(mktemp -d); \
	mkdir -p "$$out_dir"; \
	SOURCE_DATE_EPOCH=0 $(PYTHON) -m pip wheel . --no-deps --no-build-isolation -w "$$out_dir" >/dev/null; \
	SOURCE_DATE_EPOCH=0 $(PYTHON) -m pip wheel . --no-deps --no-build-isolation -w "$$repro_dir" >/dev/null; \
	(cd "$$out_dir" && shasum -a 256 moni-*.whl > SHA256SUMS); \
	test "$$(shasum -a 256 "$$out_dir"/moni-*.whl | cut -d' ' -f1)" = "$$(shasum -a 256 "$$repro_dir"/moni-*.whl | cut -d' ' -f1)"; \
	if test -n "$(GPG_KEY)"; then gpg --local-user "$(GPG_KEY)" --detach-sign --armor "$$out_dir/SHA256SUMS"; else echo "reproducible artifact verified; set GPG_KEY to sign SHA256SUMS"; fi; \
	rm -rf "$$repro_dir"
