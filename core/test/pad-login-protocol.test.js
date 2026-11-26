const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { QqLoginService } = require('../src/services/qq-login-service');
const { createQqAccountImporter } = require('../src/services/qq-account-import');

function harness(t) {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'farm-pad-protocol-test-'));
  const children = [];
  const launches = [];
  const service = new QqLoginService({ dataDir, environment: {}, resolveProxy: async () => '',
    getLaunch: () => ({ protocol: 'napcat', runtime: dataDir, host: 'host.mjs', executable: 'napcat-node' }),
    getPadLaunch: () => ({ protocol: 'pad', component: dataDir, runtime: dataDir, executable: 'pad-node', argsPrefix: ['PadLogin.dll'], electron: false }),
    spawn(file, args, config) {
      const child = new EventEmitter();
      child.stdout = new PassThrough(); child.stdin = new PassThrough(); child.exitCode = null;
      child.commands = [];
      child.kill = () => { child.exitCode = 0; child.emit('exit', 0); };
      child.stdin.on('data', chunk => {
        const command = JSON.parse(String(chunk));
        child.commands.push(command);
        if (command.command === 'shutdown') child.kill();
        if (command.command === 'request_code') child.requestId = command.requestId;
      });
      child.config = config;
      child.event = (kind, value) => child.stdout.write(`QQFARM_LOGIN:${JSON.stringify({ kind, value: kind === 'code' && child.requestId ? { requestId: child.requestId, ...value } : value })}\n`);
      children.push(child); launches.push({ file, args, config }); return child;
    } });
  t.after(() => { service.close(); for (const child of children) child.kill(); fs.rmSync(dataDir, { recursive: true, force: true }); });
  return { service, children, launches };
}

test('Pad QR requests are rejected with the correct password/NapCat guidance', t => {
  const { service } = harness(t);
  assert.throws(() => service.create('1001:token-a', { protocol: 'pad' }), error => error.status === 400 && error.kind === 'pad_qr_blocked' && /NapCat/.test(error.message));
});

test('Pad password is pipe-only and real captcha/SMS commands stay in their owning session', t => {
  const { service, children } = harness(t);
  const state = service.create('1001:token-a', { protocol: 'pad', uin: '12345678', password: 'private-password' });
  const item = service.owned('1001:token-a', state.sessionId);
  assert.equal(item.password, undefined);
  assert.deepEqual(children[0].commands[0], { command: 'start', mode: 'password', uin: '12345678', password: 'private-password' });
  assert.equal('password' in service.get('1001:token-a', state.sessionId), false);
  children[0].event('state', { phase: 'needs_captcha', message: '需要验证', verifyUrl: 'https://turing.captcha.qcloud.com/?aid=1', phone: '86-138****0000' });
  const pending = service.get('1001:token-a', state.sessionId);
  assert.equal(pending.verifyUrl, 'https://turing.captcha.qcloud.com/?aid=1');
  assert.equal(pending.phone, '86-138****0000');
  assert.equal(item.startTimer._destroyed, true, 'captcha/SMS wait must not hit the initial 45s timeout');
  service.submitCaptcha('1001:token-a', state.sessionId, 'ticket-fixture', 'randstr-fixture');
  service.submitSms('1001:token-a', state.sessionId, '123456');
  assert.deepEqual(children[0].commands.at(-2), { command: 'submit_captcha', ticket: 'ticket-fixture', randstr: 'randstr-fixture' });
  assert.deepEqual(children[0].commands.at(-1), { command: 'submit_sms', code: '123456' });
  assert.throws(() => service.submitCaptcha('1001:another-token', state.sessionId, 'x', 'y'), { status: 404 });
});

test('Pad restore uses the saved profile and never the NapCat launcher', t => {
  const { service, children, launches } = harness(t);
  const directory = service.profilePath(require('node:crypto').randomUUID());
  fs.mkdirSync(directory, { recursive: true });
  const item = service.launch({ protocol: 'pad', profileDirectory: directory, restoreUin: '12345678', userId: 1001 });
  assert.equal(item.protocol, 'pad');
  assert.equal(item.directory, directory);
  assert.equal(launches[0].file, 'pad-node');
  assert.deepEqual(children[0].commands[0], { command: 'start', mode: 'restore', uin: '12345678' });
  assert.equal(item.sessionIdentity, undefined);
});

test('imported account remembers the Pad protocol for subsequent on-demand renewal', async () => {
  let savedAccount;
  const item = {
    id: 'pad-session', userId: 1001, targetUserId: null, code: 'fixture_PAD_CODE_12345678', uin: '12345678',
    directory: '/private/pad-directory', name: 'pad-account', protocol: 'pad', proxyMode: 'direct', proxyProfileId: null,
  };
  const qqLogin = {
    owned: () => item,
    getAccountState: () => ({ code: { valid: true } }),
    saveProfile: async () => 'profile-id',
    retainAccountSession: () => { item.accountKey = 'account-key'; item.imported = true; },
    markImport: () => { item.imported = true; },
  };
  const provider = {
    getAccounts: () => ({ accounts: [] }),
    isAccountRunning: () => false,
    startAccount: async () => {},
    addAccountLog: () => {},
  };
  const addOrUpdateAccount = account => { savedAccount = account; return { accounts: [{ ...account, id: 'account-id' }] }; };
  const importer = createQqAccountImporter({ qqLogin, provider, addOrUpdateAccount, userStore: { DEFAULT_ACCOUNT_LIMIT: 10, getUser: () => ({ id: 1001, role: 'user', accountLimit: 10, card: { isPermanent: true } }) } });
  await importer({ currentUser: { id: 1001, role: 'user' }, params: { id: item.id }, body: {} });
  assert.equal(savedAccount.qqLoginProtocol, 'pad');
  assert.equal(savedAccount.qqLoginProfile, 'profile-id');
  assert.equal(savedAccount.uin, '12345678');
  assert.equal(item.imported, true);
});
