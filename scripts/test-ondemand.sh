#!/bin/sh
# Focused contract tests for the custom on-demand QQ lifecycle.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ -n "${QQ_FARM_TEST_NODE_PATH:-}" ]; then
  NODE_PATH=$QQ_FARM_TEST_NODE_PATH
  export NODE_PATH
fi
node --require ./core/test/setup.cjs --test \
  core/test/qq-ondemand.test.js \
  core/test/qq-resident-process.test.js \
  core/test/runtime-restore-intent.test.js \
  core/test/runtime-engine-restore.test.js \
  core/test/data-provider-account-runtime.test.js
