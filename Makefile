# make help lists the targets. BLENDER names the blender to run (default: blender on the PATH).

BLENDER ?= blender
PYTEST ?= pytest
BLENDER_RUN = $(BLENDER) --background --factory-startup --python-exit-code 1 --python

.DEFAULT_GOAL := help
.PHONY: help test python-min test-python test-rust test-web test-blender test-libraries extension backend docs

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

test-rust: ## Rust parser: format, clippy, tests
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q

test-web: ## bn-view web component: clippy, tests
	cd web && cargo clippy -q --all-targets -- -D warnings && cargo test -q

test-blender: ## Blender add-on tests, and the backend the reference reads checked against Blender
	$(BLENDER_RUN) base-node-for-blender/tests/test_extension.py
	$(BLENDER_RUN) base-node-for-blender/tests/export_backend.py -- --check

test-libraries: ## Third-party node group libraries, round-tripped (non-regression)
	$(BLENDER_RUN) base-node-for-blender/tests/test_libraries.py

extension: ## Build the add-on .zip into dist/
	BLENDER=$(BLENDER) base-node-for-blender/build.sh dist

backend: ## Write targets/backends/blender-<version>.json and blender-<version>/<module>.json again from Blender
	$(BLENDER_RUN) base-node-for-blender/tests/export_backend.py

docs: ## Write the reference pages into site/reference/
	PYTHONPATH=python python3 -m base_node.cli docs
