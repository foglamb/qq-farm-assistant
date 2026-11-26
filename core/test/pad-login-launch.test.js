const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { padLaunch } = require('../src/services/pad-login-launch');

test('padLaunch uses a real self-contained executable and requires signing', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pad-launch-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const executable = path.join(directory, 'PadLogin'); fs.writeFileSync(executable, 'fixture');
  assert.throws(() => padLaunch({ PAD_LOGIN_EXECUTABLE: executable }), error => error.status === 503 && error.kind === 'configuration');
  const launch = padLaunch({ PAD_LOGIN_EXECUTABLE: executable, PAD_SIGN_URL: 'http://sign.fixture' });
  assert.equal(launch.protocol, 'pad'); assert.equal(launch.executable, executable); assert.deepEqual(launch.argsPrefix, []);
});

test('padLaunch supports framework-dependent development DLLs without hiding the dotnet host', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pad-launch-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const dll = path.join(directory, 'PadLogin.dll'); fs.writeFileSync(dll, 'fixture');
  const launch = padLaunch({ PAD_LOGIN_DLL: dll, DOTNET_EXE: '/tmp/dotnet8/dotnet', PAD_SIGN_URL: 'http://sign.fixture' });
  assert.equal(launch.executable, '/tmp/dotnet8/dotnet'); assert.deepEqual(launch.argsPrefix, [dll]);
});
