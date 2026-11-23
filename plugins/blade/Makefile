# make help lists the targets, run in this folder.
#
# Blade's target needs the core of the language and Blender's library: CORE is the checkout of the
# core (python/, rust/), BLENDER_LIB the checkout of Base Node for Blender (python/, rust/); the
# paths of rust/Cargo.toml say the same for Cargo.

CORE ?= ../..
BLENDER_LIB ?= ../blender
PYTEST ?= pytest
export PYTHONPATH := $(abspath $(CORE)/python):$(abspath $(BLENDER_LIB)/python):$(abspath python)

.DEFAULT_GOAL := help
.PHONY: help test test-python test-rust

help: ## List the targets
	@grep -hE '^[a-z-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

test: test-python test-rust ## Every test

test-python: ## The target, its translator and its bridge, with Blender's Python library (pytest)
	$(PYTEST) -q python/tests

test-rust: ## The same with Blender's crate: format, clippy, tests
	cd rust && cargo fmt --check && cargo clippy -q --all-targets -- -D warnings && cargo test -q
