const test = require('node:test');
const assert = require('node:assert/strict');
const express = require('express');
const { once } = require('node:events');
const { registerAdminQqLoginRoutes } = require('../src/controllers/admin-qq-login-routes');

test('Pad captcha and SMS routes forward only to the authenticated session', async t => {
  const calls = [];
  const app = express(); app.use(express.json());
  registerAdminQqLoginRoutes({ app,
    userStore: { getUser: id => ({ id, role: 'user', card: { isPermanent: true } }) },
    requireAdminToken(req, res, next) {
      if (!req.headers['x-admin-token']) return res.status(401).json({ ok: false });
      req.adminToken = req.headers['x-admin-token']; req.currentUser = { id: 1001, role: 'user' }; next();
    },
    qqLogin: {
      submitCaptcha(...args) { calls.push(['captcha', ...args]); },
      submitSms(...args) { calls.push(['sms', ...args]); },
    },
  });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.close(); server.closeAllConnections(); });
  const base = `http://127.0.0.1:${server.address().port}/api/qq-login/sessions/pad-session`;
  const headers = { 'x-admin-token': 'panel-token', 'content-type': 'application/json' };
  const captcha = await fetch(`${base}/captcha`, { method: 'POST', headers, body: JSON.stringify({ ticket: 'ticket-fixture', randstr: 'randstr-fixture' }) });
  assert.equal(captcha.status, 200);
  const sms = await fetch(`${base}/sms`, { method: 'POST', headers, body: JSON.stringify({ code: '123456' }) });
  assert.equal(sms.status, 200);
  assert.deepEqual(calls, [
    ['captcha', '1001:panel-token', 'pad-session', 'ticket-fixture', 'randstr-fixture'],
    ['sms', '1001:panel-token', 'pad-session', '123456'],
  ]);
});

test('Pad restore route maps an existing account to its saved Uin without a password', async t => {
  let created;
  const app = express(); app.use(express.json());
  registerAdminQqLoginRoutes({ app,
    userStore: { getUser: id => ({ id, role: 'user', card: { isPermanent: true } }) },
    requireAdminToken(req, res, next) { req.adminToken = req.headers['x-admin-token']; req.currentUser = { id: 1001, role: 'user' }; next(); },
    provider: { getAccounts: () => ({ accounts: [{ id: 7, userId: 1001, platform: 'qq', uin: '12345678', qqLoginProtocol: 'pad', qqLoginProfile: 'saved-profile', proxyMode: 'direct', proxyProfileId: null }] }) },
    qqLogin: { create(owner, options) { created = { owner, options }; return { sessionId: 'restore-session' }; } },
    resolveProxy: async () => '',
  });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.close(); server.closeAllConnections(); });
  const response = await fetch(`http://127.0.0.1:${server.address().port}/api/qq-login/sessions`, { method: 'POST', headers: { 'x-admin-token': 'panel-token', 'content-type': 'application/json' }, body: JSON.stringify({ protocol: 'pad', targetAccountId: '7', restore: true }) });
  assert.equal(response.status, 201, JSON.stringify(await response.clone().json()));
  assert.equal(created.options.restoreUin, '12345678');
  assert.equal(created.options.profileDirectory, 'saved-profile');
  assert.equal(created.options.password, '');
});
