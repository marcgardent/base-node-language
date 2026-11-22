# make help lists the targets. BLENDER names the blender to run (default: blender on the PATH).

BLENDER ?= blender
# The Blenders of the promised versions (`promised` in targets/blender.json), a space apart, for
# make test-promised: BLENDERS="/path/to/blender-5.2/blender /path/to/blender-5.3/blender"
BLENDERS ?= $(BLENDER)
PYTEST ?= pytest
VERSION ?= $(shell python3 -c "import json; print(json.load(open('stdlib/manifest.json'))['stdlib_version'])")
BLENDER_RUN = $(BLENDER) --background --factory-startup --python-exit-code 1 --python

.DEFAULT_GOAL := help
.PHONY: help test python-min test-python test-rust test-web test-blender test-promised test-libraries extension backend docs srt-check bump release ci

help: ## List the targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

test: python-min test-python test-rust test-web test-blender ## Every test but the third-party libraries

# The oldest Python pyproject.toml accepts: a newer one reads syntax it refuses (a backslash in an
# f-string expression before 3.12), and the CI runs an older one
PYTHON_MIN ?= 3.10

python-min: ## Every tracked .py parses with the oldest Python pyproject.toml accepts (uv fetches it)
	uv run -q --no-project --python $(PYTHON_MIN) python -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $$(git ls-files '*.py')

test-python: ## Python parser, formatter, targets (pytest)
	PYTHONPATH=python $(PYTEST) -q python/tests

test-rust: ## Rust core (rust/) and Blender library (rust-blender/): format, clippy, tests
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q
	cd rust-blender && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q

test-web: ## bn-view web component: clippy, tests
	cd web && cargo clippy -q --all-targets -- -D warnings && cargo test -q

test-blender: ## Blender add-on tests, and the backend the reference reads checked against Blender
	$(BLENDER_RUN) base-node-for-blender/tests/test_extension.py
	$(BLENDER_RUN) base-node-for-blender/tests/export_backend.py -- --check

test-promised: ## make test-blender and make test-libraries with each Blender of BLENDERS (the promised versions)
	@for b in $(BLENDERS); do \
	  echo "== $$b"; $(MAKE) --no-print-directory test-blender test-libraries BLENDER=$$b || exit 1; \
	done

test-libraries: ## Third-party node group libraries, round-tripped (non-regression)
	$(BLENDER_RUN) base-node-for-blender/tests/test_libraries.py

srt-check: ## Build examples/tutorials/srt_subtitles/srt_subtitles.bn in Blender and check it reads .srt files
	$(BLENDER_RUN) examples/srt_subtitles_check.py

extension: ## Build the add-on .zip into dist/
	BLENDER=$(BLENDER) base-node-for-blender/build.sh dist

backend: ## Write targets/backends/blender-<x.y>.json and blender-<x.y>/<module>.json from the Blender it runs (BLENDER=…), then its catalog targets/blender/<x.y>.json
	$(BLENDER_RUN) base-node-for-blender/tests/export_backend.py
	PYTHONPATH=python python3 -m base_node_blender.targets

docs: ## Write the reference pages into site/reference/
	PYTHONPATH=python python3 -m base_node_cli.cli docs

bump: ## Write VERSION (x.y.z or x.y.z-rc.n) everywhere the version is written; ARCHIVE=1 builds site/extensions/ again
	python3 tools/bump.py $(if $(filter command environment,$(firstword $(origin VERSION))),$(VERSION),$(error Say the version: make bump VERSION=x.y.z)) $(if $(ARCHIVE),--archive)

release: ## Tag main's head vVERSION and push the tag: the CI runs on it
	git fetch -q origin main
	git tag -a v$(VERSION) origin/main -m "base-node-language $(VERSION)"
	git push origin v$(VERSION)

ci: ## Run the CI by hand on the pushed head of the current branch (BRANCH=…)
	gh workflow run ci.yml --ref $(or $(BRANCH),$(shell git branch --show-current))
