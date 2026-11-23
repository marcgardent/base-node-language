# make help lists the targets, run in this folder. BLENDER names the blender to run (default: blender
# on the PATH).
#
# The core of the language is this library's one dependency: the checkout CORE (python/ for the
# package base_node, rust/ for the crate base-node, the path rust/Cargo.toml and web/Cargo.toml give).

CORE ?= ../..
BLENDER ?= blender
# The Blenders of the promised versions (`promised` in targets/blender.json), a space apart, for
# make test-promised: BLENDERS="/path/to/blender-5.2/blender /path/to/blender-5.3/blender"
BLENDERS ?= $(BLENDER)
PYTEST ?= pytest
DIST ?= dist
export PYTHONPATH := $(abspath $(CORE)/python):$(abspath python)
BLENDER_RUN = $(BLENDER) --background --factory-startup --python-exit-code 1 --python
# The modules of the core the add-on embeds as lang/: those of its package base_node
CORE_PACKAGE = $(abspath $(CORE)/python/base_node)
LANG = __init__.py ast.py colors.py errors.py format.py header.py identifiers.py lexer.py names.py parser.py printer.py py.typed

.DEFAULT_GOAL := help
.PHONY: help test python-min test-python test-rust test-web test-blender test-promised test-libraries addon-lang extension backend names docs srt-check bump bump-check

help: ## List the targets
	@grep -hE '^[a-z-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

test: python-min test-python test-rust test-web test-blender ## Every test but the third-party libraries

# The oldest Python pyproject.toml accepts
PYTHON_MIN ?= 3.10

python-min: ## Every tracked .py of this folder parses with the oldest Python pyproject.toml accepts (uv fetches it)
	uv run -q --no-project --python $(PYTHON_MIN) python -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $$(git ls-files '*.py')

test-python: ## Python library: Blender's nodes, the checker, the targets, the commands (pytest)
	$(PYTEST) -q python/tests

test-rust: ## Rust library (rust/): format, clippy, tests
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q

test-web: ## bn-view web component: clippy, tests
	cd web && cargo clippy -q --all-targets -- -D warnings && cargo test -q

addon-lang: ## Link the modules of the core into addon/lang/, which the add-on embeds
	mkdir -p addon/lang
	for m in $(LANG); do ln -sfn "$(CORE_PACKAGE)/$$m" "addon/lang/$$m"; done

test-blender: addon-lang ## Blender add-on tests, and the backend the reference reads checked against Blender
	$(BLENDER_RUN) addon/tests/test_extension.py
	$(BLENDER_RUN) addon/tests/export_backend.py -- --check

test-promised: ## make test-blender and make test-libraries with each Blender of BLENDERS (the promised versions)
	@for b in $(BLENDERS); do \
	  echo "== $$b"; $(MAKE) --no-print-directory test-blender test-libraries BLENDER=$$b || exit 1; \
	done

test-libraries: addon-lang ## Third-party node group libraries, round-tripped (non-regression)
	$(BLENDER_RUN) addon/tests/test_libraries.py

srt-check: addon-lang ## Build examples/tutorials/srt_subtitles/srt_subtitles.bn in Blender and check it reads .srt files
	$(BLENDER_RUN) examples/srt_subtitles_check.py

extension: addon-lang ## Build the add-on .zip into DIST (default dist/)
	BLENDER=$(BLENDER) addon/build.sh $(DIST)

backend: addon-lang ## Write targets/backends/blender-<x.y>.json and blender-<x.y>/<module>.json from the Blender it runs (BLENDER=…), then its catalog targets/blender/<x.y>.json
	$(BLENDER_RUN) addon/tests/export_backend.py
	python3 -m base_node_blender.targets

names: ## Format FILES ("a.bn b.bn"), the inputs of Blender's nodes by name, without Blender
	python3 -m base_node_blender.cli fmt --names $(or $(FILES),$(error Say the files: make names FILES="a.bn b.bn"))

docs: ## Write the reference pages into site/reference/
	python3 -m base_node_blender.cli docs --core $(CORE)

bump: ## Write VERSION (x.y.z or x.y.z-rc.n) everywhere this folder writes its version, and CORE_VERSION (default: VERSION) where it says the core it needs; ARCHIVE=1 builds site/extensions/ again
	python3 tools/bump.py $(or $(VERSION),$(error Say the version: make bump VERSION=x.y.z)) --core $(or $(CORE_VERSION),$(VERSION)) $(if $(ARCHIVE),--archive)

bump-check: ## Every place holds the version of stdlib/manifest.json, and the core it needs is CORE's
	python3 tools/bump.py --check --core-dir $(CORE)
