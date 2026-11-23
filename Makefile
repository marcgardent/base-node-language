# make help lists the targets: those of the core of the language.

PYTEST ?= pytest
# The version of the core: that of its crate
VERSION ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' rust/Cargo.toml)

.DEFAULT_GOAL := help
.PHONY: help test python-min test-python test-rust wasm identifiers bump bump-check release ci

help: ## List the targets
	@grep -hE '^[a-z-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

test: python-min test-python test-rust wasm bump-check ## Every test of the core

# The oldest Python pyproject.toml accepts: a newer one reads syntax it refuses (a backslash in an
# f-string expression before 3.12), and the CI runs an older one
PYTHON_MIN ?= 3.10

python-min: ## Every tracked .py parses with the oldest Python pyproject.toml accepts (uv fetches it)
	uv run -q --no-project --python $(PYTHON_MIN) python -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $$(git ls-files '*.py')

test-python: ## The Python parser and formatter, the command line (pytest)
	PYTHONPATH=python $(PYTEST) -q python/tests

test-rust: ## The crate (rust/): format, clippy, tests
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q

wasm: ## The crate builds for wasm32-unknown-unknown
	cd rust && cargo check -q --target wasm32-unknown-unknown

identifiers: ## Write the characters of an identifier (python/base_node/identifiers.py, rust/src/identifiers.rs) from the Unicode of this Python
	python3 tools/identifiers.py

bump: ## Write VERSION (x.y.z or x.y.z-rc.n) everywhere the version is written
	python3 tools/bump.py $(if $(filter command environment,$(firstword $(origin VERSION))),$(VERSION),$(error Say the version: make bump VERSION=x.y.z))

bump-check: ## Every place holds the version of rust/Cargo.toml
	python3 tools/bump.py --check

release: ## Tag main's head vVERSION and push the tag: the CI runs on it
	git fetch -q origin main
	git tag -a v$(VERSION) origin/main -m "base-node-language $(VERSION)"
	git push origin v$(VERSION)

ci: ## Run the CI by hand on the pushed head of the current branch (BRANCH=…)
	gh workflow run ci.yml --ref $(or $(BRANCH),$(shell git branch --show-current))
