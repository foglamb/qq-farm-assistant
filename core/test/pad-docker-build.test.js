const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');

test('the full image compiles PadLogin from source and takes Web from the build stage', () => {
  const dockerfile = fs.readFileSync(path.join(root, 'core/Dockerfile'), 'utf8');
  // The Pad protocol belongs to this project: one build produces the AndroidPad
  // helper from source, so no prebuilt binary has to be committed.
  assert(dockerfile.includes('mcr.microsoft.com/dotnet/sdk'));
  assert(dockerfile.includes('pad-builder'));
  assert(dockerfile.includes('dotnet publish'));
  assert(dockerfile.includes('COPY --from=pad-builder /out/PadLogin /app/pad-login/PadLogin'));
  assert(!dockerfile.includes('COPY pad-login/PadLogin /app/pad-login/PadLogin'));
  const script = path.join(root, 'scripts/build-pad-login.sh');
  assert(fs.existsSync(script));
  assert(fs.statSync(script).mode & 0o111);
  assert(fs.readFileSync(script, 'utf8').includes('--self-contained true'));
});

test('the incremental image reuses web/dist and still compiles PadLogin itself', () => {
  const runtime = fs.readFileSync(path.join(root, 'core/Dockerfile.runtime'), 'utf8');
  assert(runtime.includes('COPY web/dist /app/web/dist'));
  assert(runtime.includes('dotnet publish'));
  assert(runtime.includes('COPY --from=pad /out/PadLogin /app/pad-login/PadLogin'));
  assert(!runtime.includes('COPY pad-login/PadLogin /app/pad-login/PadLogin'));
  const runtimeIgnore = fs.readFileSync(path.join(root, 'core/Dockerfile.runtime.dockerignore'), 'utf8').split(/\r?\n/).map(line => line.trim());
  assert(!runtimeIgnore.includes('dist') && !runtimeIgnore.includes('web/dist'));
});
