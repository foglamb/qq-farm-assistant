const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { createYybRuntime, readYybEnabled } = require('../src/services/yyb-runtime');

function harness(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yyb-runtime-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const env = { FARM_DATA_DIR: dir, YYB_EXECUTABLE: '/fixture/yyb-go', YYB_RESOURCE_ROOT: '/fixture', YYB_PORT: '8450', YYB_API_TOKEN: 'fixture-token' };
  let serving = false;
  const children = [];
  const probe = async (_port, route) => {
    if (route === '/health') return { status: serving ? 200 : 503, data: { data: { ok: serving } } };
    return { status: 200, data: [] };
  };
  const spawn = () => {
    const child = new EventEmitter();
    Object.assign(child, { pid: 4100 + children.length, exitCode: null, signalCode: null });
    child.kill = signal => { child.signalCode = signal; serving = false; queueMicrotask(() => child.emit('exit', null, signal)); };
    serving = true;
    children.push(child);
    return child;
  };
  return { env, children, probe, spawn };
}

test('YYB defaults off and never spawns until explicitly enabled', async t => {
  const h = harness(t);
  const runtime = createYybRuntime({ env: h.env, probe: h.probe, spawn: () => { throw new Error('must not spawn'); } });
  await runtime.restore();
  assert.equal(runtime.getStatus().enabled, false);
  assert.equal(runtime.getStatus().running, false);
  assert.equal(readYybEnabled(h.env), false);
});

test('YYB switch persists and owns only its spawned process', async t => {
  const h = harness(t);
  const runtime = createYybRuntime(h);
  await runtime.setEnabled(true);
  assert.equal(h.children.length, 1);
  assert.equal(runtime.getStatus().running, true);
  assert.equal(readYybEnabled(h.env), true);
  await runtime.setEnabled(false);
  assert.equal(h.children[0].signalCode, 'SIGTERM');
  assert.equal(runtime.getStatus().running, false);
  assert.equal(readYybEnabled(h.env), false);
});

test('shutdown preserves the opt-in choice and a new runtime restores it', async t => {
  const h = harness(t);
  const first = createYybRuntime(h);
  await first.setEnabled(true);
  await first.close();
  assert.equal(first.getStatus().enabled, true);
  assert.equal(first.getStatus().running, false);
  const second = createYybRuntime(h);
  await second.restore();
  assert.equal(second.getStatus().enabled, true);
  assert.equal(second.getStatus().running, true);
  assert.equal(h.children.length, 2);
  await second.close();
});

test('YYB admin routes expose the switch while disabled and reject proxy use', async t => {
  const express = require('express');
  const { registerAdminYybRoutes } = require('../src/controllers/admin-yyb-routes');
  const app = express();
  app.use(express.json());
  let enabled = false;
  const runtime = {
    getStatus: () => ({ enabled, running: enabled, external: false, pid: enabled ? 42 : null, error: null }),
    setEnabled: async value => { enabled = value; return runtime.getStatus(); },
  };
  app.use((req, _res, next) => { req.currentUser = { role: 'admin' }; next(); });
  registerAdminYybRoutes({ app, requireAdminToken: (_req, _res, next) => next(), yybRuntime: runtime,
    getAccountsForUser: () => [], canAccessAccount: () => true });
  const server = app.listen(0, '127.0.0.1');
  t.after(() => server.close());
  await new Promise(resolve => server.once('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let response = await fetch(`${base}/api/yyb/runtime`);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).data.enabled, false);
  response = await fetch(`${base}/api/yyb/accounts`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
  assert.equal(response.status, 503);
  response = await fetch(`${base}/api/yyb/runtime`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: true }) });
  assert.equal(response.status, 200);
  assert.equal(enabled, true);
});
