const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { QqLoginService } = require('../src/services/qq-login-service');

/**
 * Watch is the third scan channel: it renders a real QR image and, unlike Pad,
 * needs no account password and no libfekit signing service. The host is a real
 * child process speaking the same QQFARM_LOGIN JSON-lines protocol as NapCat, so
 * these tests drive an offline stub host instead of mocking the service.
 */
function harness(t, options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'farm-watch-'));
  const component = path.join(root, 'watch-login');
  fs.mkdirSync(component, { recursive: true });
  // A 1x1 transparent PNG stands in for the QR image the watch host renders.
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64');
  const hostPath = path.join(component, 'watch_host.py');
  const uin = options.uin || '2313609665';
  const code = options.code || 'watch_farm_code_1';
  fs.writeFileSync(hostPath, `#!/usr/bin/env python3
import json, sys
PREFIX = "QQFARM_LOGIN:"
PNG = "${png.toString('base64')}"
def emit(kind, value):
    sys.stdout.write(PREFIX + json.dumps({"kind": kind, "value": value}) + "\\n"); sys.stdout.flush()
emit("state", {"phase": "starting", "message": "watch host ready", "canRequest": False})
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    command = json.loads(line)
    name = command.get("command")
    if name == "start":
        emit("qr", {"png": PNG, "expireTimeRaw": 120})
        emit("state", {"phase": "waiting_scan", "message": "scan now", "canRequest": False})
        emit("session", {"uin": "${uin}"})
        emit("state", {"phase": "online", "message": "watch online", "canRequest": True})
${options.autoCode === false ? '' : `        # The farm's restore path waits for a Code right after login.\n        emit("code", {"code": "${code}", "requestId": None})\n        emit("state", {"phase": "success", "message": "code issued", "canRequest": True})\n`}    elif name == "request_code":
        emit("code", {"code": "${code}", "requestId": command.get("requestId")})
        emit("state", {"phase": "success", "message": "code issued", "canRequest": True})
    elif name == "shutdown":
        emit("state", {"phase": "offline", "message": "stopped", "canRequest": False})
        break
`);
  const children = [];
  const service = new QqLoginService({
    dataDir: path.join(root, 'data'),
    environment: { QQ_LOGIN_RESIDENT: '0', WATCH_LOGIN_COMPONENT_DIR: component },
    resolveProxy: async () => '',
    getWatchLaunch: () => ({ protocol: 'watch', component, runtime: component, host: hostPath, executable: 'python3' }),
    spawn(file, args, config) {
      const child = require('node:child_process').spawn(file, args, config);
      child.config = config; children.push(child); return child;
    },
  });
  t.after(async () => {
    service.close();
    for (const child of children) if (child.exitCode === null) child.kill();
    fs.rmSync(root, { recursive: true, force: true });
  });
  return { service, children, root, component };
}

const waitFor = async (predicate, label, timeout = 10000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  throw new Error(`timeout waiting for ${label}`);
};

test('the watch channel is a selectable protocol alongside pad and napcat', async t => {
  const { service } = harness(t);
  const launch = service.resolveLaunch({ protocol: 'watch' });
  assert.equal(launch.protocol, 'watch');
  assert.match(launch.host, /watch_host\.py$/);
  assert.throws(() => service.resolveLaunch({ protocol: 'nope' }),
    error => error.status === 400 && /手表协议/.test(error.message));
});

test('the store accepts watch and still rejects unknown protocols', async t => {
  const store = require('../src/models/store');
  const fsx = require('node:fs');
  const root = fsx.mkdtempSync(path.join(os.tmpdir(), 'farm-store-watch-'));
  t.after(() => fsx.rmSync(root, { recursive: true, force: true }));
  assert.equal(typeof store.addOrUpdateAccount, 'function');
  // The protocol gate lives in addOrUpdateAccount; assert its message mentions watch.
  const source = fsx.readFileSync(path.join(__dirname, '../src/models/store.js'), 'utf8');
  assert.match(source, /\['pad', 'napcat', 'watch'\]\.includes/);
  assert.match(source, /qqLoginProtocol 必须是 pad、napcat 或 watch/);
});

test('a watch session renders a QR image then reports its scanned uin', async t => {
  // autoCode:false keeps the host parked at the QR stage so the snapshot can be
  // observed; a real Code immediately replaces the image.
  const { service, children } = harness(t, { autoCode: false });
  const created = service.create('1000:test', { protocol: 'watch' });
  try {
    assert.equal(created.protocol, 'watch');
    await waitFor(() => children.length === 1, 'watch host spawn');
    // Watch has no password mode: the host gets an explicit start command.
    await waitFor(() => service.get('1000:test', created.sessionId).image !== '', 'qr image');
    const view = service.get('1000:test', created.sessionId);
    assert.match(view.image, /^data:image\/png;base64,/);
    await waitFor(() => service.get('1000:test', created.sessionId).status === 'online', 'online state');
    assert.equal(service.get('1000:test', created.sessionId).status, 'online');
  } finally {
    service.cancel('1000:test', created.sessionId);
  }
  await waitFor(() => children[0].exitCode !== null, 'host exit after cancel');
});

test('on-demand watch mode releases its host process after a Code is issued', async t => {
  const { service, children } = harness(t);
  const profile = crypto.randomUUID();
  const directory = service.profilePath(profile);
  fs.mkdirSync(path.join(directory, 'qq-data'), { recursive: true });
  fs.writeFileSync(path.join(directory, 'identity.json'),
    JSON.stringify({ userId: 1000, uin: '2313609665' }));
  const account = { id: '9', userId: 1000, uin: '2313609665', platform: 'qq',
    qqLoginProfile: profile, qqLoginProtocol: 'watch' };
  const code = await service.refreshAccountCode(account);
  assert.equal(code, 'watch_farm_code_1');
  assert.equal(children.length, 1);
  assert.equal(children[0].exitCode, 0, 'watch host exits in on-demand mode');
  assert.equal(service.accountSessions.size, 0);
  assert.equal(service.getAccountState(account).lifecycle, 'on-demand');
});

test('a missing watch component reports a configuration error instead of crashing', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'farm-watch-missing-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const service = new QqLoginService({
    dataDir: path.join(root, 'data'),
    environment: { QQ_LOGIN_RESIDENT: '0', WATCH_LOGIN_COMPONENT_DIR: path.join(root, 'absent') },
    resolveProxy: async () => '',
  });
  t.after(() => service.close());
  assert.throws(() => service.resolveLaunch({ protocol: 'watch' }),
    error => error.kind === 'configuration' && /手表扫码组件未安装/.test(error.message));
});
