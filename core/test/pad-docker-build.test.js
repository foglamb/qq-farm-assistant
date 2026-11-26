const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');

test('Docker consumes a prebuilt self-contained PadLogin without an MCR build stage', () => {
  const dockerfile = fs.readFileSync(path.join(root, 'core/Dockerfile'), 'utf8');
  assert(dockerfile.includes('COPY pad-login/PadLogin /app/pad-login/PadLogin'));
  assert(!dockerfile.includes('mcr.microsoft.com/dotnet/sdk'));
  assert(!dockerfile.includes('--from=pad-builder'));
  const script = path.join(root, 'scripts/build-pad-login.sh');
  assert(fs.existsSync(script));
  assert(fs.statSync(script).mode & 0o111);
  assert(fs.readFileSync(script, 'utf8').includes('--self-contained true'));
  const runtime = fs.readFileSync(path.join(root, 'core/Dockerfile.runtime'), 'utf8');
  assert(runtime.includes('COPY web/dist /app/web/dist'));
  assert(runtime.includes('COPY pad-login/PadLogin /app/pad-login/PadLogin'));
  const runtimeIgnore = fs.readFileSync(path.join(root, 'core/Dockerfile.runtime.dockerignore'), 'utf8').split(/\r?\n/).map(line => line.trim());
  assert(!runtimeIgnore.includes('dist') && !runtimeIgnore.includes('web/dist'));
});
