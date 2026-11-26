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
  core/test/code-lifecycle.test.js \
  core/test/napcat-patch.test.js \
  core/test/yyb-runtime.test.js \
  core/test/docker-healthcheck.test.js \
  core/test/qq-native-login.test.js \
  core/test/qq-login-service.test.js \
  core/test/qq-ondemand.test.js \
  core/test/qq-resident-process.test.js \
  core/test/worker-manager-yyb-start.test.js \
  core/test/runtime-restore-intent.test.js \
  core/test/runtime-engine-restore.test.js \
  core/test/data-provider-account-runtime.test.js
