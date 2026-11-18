#!/usr/bin/env bash
# Builds the wasm of <bn-view> into site/view/pkg (needs the wasm32 target
# and wasm-bindgen-cli at the version web/Cargo.toml pins).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen --target web --no-typescript --out-dir ../site/view/pkg \
  target/wasm32-unknown-unknown/release/base_node_web.wasm
ls -l ../site/view/pkg
