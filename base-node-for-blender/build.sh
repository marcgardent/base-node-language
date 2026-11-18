#!/bin/sh
# Build the extension .zip: base-node-for-blender/build.sh [output dir, default dist]
#
# In the repository, stdlib/, lang/_targets/ and the modules of lang/ that are python/base_node's
# are symbolic links to their one source. Blender's `extension build` skips links, so the folder is
# copied first with its links resolved into files, and that copy is built. BLENDER names the
# blender to run.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "${1:-dist}"
out=$(cd "${1:-dist}" && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp -RL "$here" "$stage/base_node"
"${BLENDER:-blender}" --command extension build --source-dir "$stage/base_node" --output-dir "$out"
