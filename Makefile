# make help lists the targets. The core of the language is here; a host is under plugins/, with its own
# Makefile: its targets are run from here too when the checkout has it (plugins/blender).

BLENDER ?= blender
PYTEST ?= pytest
# The version of the core: that of its crate
VERSION ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' rust/Cargo.toml)
# The Blender host, when the checkout has it
BLENDER_PLUGIN := $(wildcard plugins/blender/Makefile)
IN_BLENDER = $(if $(BLENDER_PLUGIN),$(MAKE) --no-print-directory -C plugins/blender,$(error make $@ needs plugins/blender, which this checkout has not))

.DEFAULT_GOAL := help
.PHONY: help test python-min test-python test-rust test-web test-blender test-promised test-libraries extension backend names identifiers docs srt-check bump release ci

help: ## List the targets
	@grep -hE '^[a-z-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

test: python-min test-python test-rust ## Every test of the core, and of plugins/blender but the third-party libraries
ifneq ($(BLENDER_PLUGIN),)
	$(IN_BLENDER) test-web test-blender BLENDER=$(BLENDER)
endif

# The oldest Python pyproject.toml accepts: a newer one reads syntax it refuses (a backslash in an
# f-string expression before 3.12), and the CI runs an older one
PYTHON_MIN ?= 3.10

python-min: ## Every tracked .py parses with the oldest Python pyproject.toml accepts (uv fetches it)
	uv run -q --no-project --python $(PYTHON_MIN) python -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $$(git ls-files '*.py')

test-python: ## The core's Python parser and formatter (pytest), then plugins/blender's
	PYTHONPATH=python $(PYTEST) -q python/tests
ifneq ($(BLENDER_PLUGIN),)
	$(IN_BLENDER) test-python PYTEST="$(PYTEST)"
endif

test-rust: ## The core's crate (rust/): format, clippy, tests, then plugins/blender's
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q
ifneq ($(BLENDER_PLUGIN),)
	$(IN_BLENDER) test-rust
endif

identifiers: ## Write the characters of an identifier (python/base_node/identifiers.py, rust/src/identifiers.rs) from the Unicode of this Python
	python3 tools/identifiers.py

# The targets of plugins/blender, run in its folder (make -C plugins/blender help)
test-web: ## plugins/blender: bn-view web component: clippy, tests
	$(IN_BLENDER) $@
test-blender: ## plugins/blender: the add-on's tests, and the backend the reference reads checked against Blender
	$(IN_BLENDER) $@ BLENDER=$(BLENDER)
test-promised: ## plugins/blender: make test-blender and make test-libraries with each Blender of BLENDERS
	$(IN_BLENDER) $@ BLENDER=$(BLENDER) $(if $(BLENDERS),BLENDERS="$(BLENDERS)")
test-libraries: ## plugins/blender: third-party node group libraries, round-tripped (non-regression)
	$(IN_BLENDER) $@ BLENDER=$(BLENDER)
srt-check: ## plugins/blender: build the srt_subtitles tutorial in Blender and check it reads .srt files
	$(IN_BLENDER) $@ BLENDER=$(BLENDER)
extension: ## plugins/blender: build the add-on .zip into dist/
	$(IN_BLENDER) $@ BLENDER=$(BLENDER) DIST=$(abspath dist)
backend: ## plugins/blender: write the backend and the catalog of the Blender it runs (BLENDER=…)
	$(IN_BLENDER) $@ BLENDER=$(BLENDER)
names: ## plugins/blender: format FILES ("a.bn b.bn"), the inputs of Blender's nodes by name, without Blender
	$(IN_BLENDER) $@ FILES="$(abspath $(or $(FILES),$(error Say the files: make names FILES="a.bn b.bn")))"
docs: ## plugins/blender: write the reference pages into plugins/blender/site/reference/
	$(IN_BLENDER) $@

bump: ## Write VERSION (x.y.z or x.y.z-rc.n) everywhere the version is written, in the core and each plugin; ARCHIVE=1 builds the add-on's archive again
	python3 tools/bump.py $(if $(filter command environment,$(firstword $(origin VERSION))),$(VERSION),$(error Say the version: make bump VERSION=x.y.z)) $(if $(ARCHIVE),--archive)

release: ## Tag main's head vVERSION and push the tag: the CI runs on it
	git fetch -q origin main
	git tag -a v$(VERSION) origin/main -m "base-node-language $(VERSION)"
	git push origin v$(VERSION)

ci: ## Run the CI by hand on the pushed head of the current branch (BRANCH=…)
	gh workflow run ci.yml --ref $(or $(BRANCH),$(shell git branch --show-current))
