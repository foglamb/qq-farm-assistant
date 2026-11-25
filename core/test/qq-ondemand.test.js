const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { QqLoginService } = require('../src/services/qq-login-service');

function harness(t, resident) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'farm-ondemand-'));
  const runtime = path.join(root, 'runtime');
  fs.mkdirSync(path.join(runtime, 'napcat'), { recursive: true });
  // Run the real host/service. Only QQ's proprietary native implementation is
  // replaced by this deterministic, offline fixture.
  fs.writeFileSync(path.join(runtime, 'napcat', 'napcat.mjs'), `
    import fs from 'node:fs';
    import path from 'node:path';
    const data = process.env.FARM_QQ_SESSION_DIR;
    fs.mkdirSync(path.join(data, 'qq-data'), {recursive:true});
    const counter = path.join(data, 'qq-data', 'requests');
    const uin = process.env.FARM_QQ_RESTORE_UIN || '12345678';
    await globalThis.__qqFarmLogin.ready({getNodeMiscService:()=>({loginWithAppId:async()=>{
      const count = fs.existsSync(counter) ? Number(fs.readFileSync(counter, 'utf8')) + 1 : 1;
      fs.writeFileSync(counter, String(count));
      return {errCode:0,result:'fixture_ONDEMAND_CODE_'+count,expiresAt:1800000000};
    }})},{uin});
  `);
  const children = [];
  const service = new QqLoginService({
    dataDir: path.join(root, 'data'),
    environment: { QQ_LOGIN_RESIDENT: resident ? '1' : '0' },
    resolveProxy: async () => '',
    getLaunch: () => ({ runtime, host: path.resolve(__dirname, '../qq-login/host.mjs'), executable: process.execPath }),
    spawn(file, args, config) { const child = require('node:child_process').spawn(file, args, config); child.config = config; children.push(child); return child; },
  });
  t.after(async () => {
    service.close();
    for (const child of children) if (child.exitCode === null) child.kill();
    fs.rmSync(root, { recursive: true, force: true });
  });
  const profile = crypto.randomUUID();
  const directory = service.profilePath(profile);
  fs.mkdirSync(path.join(directory, 'qq-data'), { recursive: true });
  fs.writeFileSync(path.join(directory, 'identity.json'), JSON.stringify({ userId: 1000, uin: '12345678' }));
  const account = { id: '1', userId: 1000, uin: '12345678', platform: 'qq', qqLoginProfile: profile };
  return { service, children, account, directory };
}

test('on-demand mode disables prewarm, releases QQ after each Code and restores the same profile', async t => {
  const { service, children, account, directory } = harness(t, false);
  service.start();
  assert.equal(children.length, 0, 'no QQ process is prewarmed');

  assert.equal(await service.refreshAccountCode(account), 'fixture_ONDEMAND_CODE_1');
  assert.equal(children.length, 1);
  assert.equal(children[0].exitCode, 0);
  assert.equal(service.accountSessions.size, 0);
  assert.equal(service.trackedItems.size, 0);
  assert.equal(service.status({ owner: '1000:test', admin: true }).residentAccounts, 0);
  assert.equal(service.getAccountState(account).lifecycle, 'on-demand');
  assert.equal(service.getAccountState(account).code.expiresAt, 1800000000000);
  assert.equal(service.getAccountState(account).code.status, null);
  const metadataText = fs.readFileSync(path.join(directory, 'code-meta.json'), 'utf8');
  assert.equal(metadataText.includes('fixture_ONDEMAND_CODE'), false);
  assert.equal(fs.existsSync(path.join(directory, 'identity.json')), true);
  assert.equal(fs.existsSync(path.join(directory, 'qq-data')), true);

  assert.equal(await service.refreshAccountCode(account), 'fixture_ONDEMAND_CODE_2');
  assert.equal(children.length, 2, 'the next renewal starts a fresh helper');
  assert.equal(children[1].exitCode, 0);
  assert.equal(service.accountSessions.size, 0);
  assert.equal(fs.readFileSync(path.join(directory, 'qq-data', 'requests'), 'utf8'), '2');
  assert.equal(children[1].config.env.FARM_QQ_SESSION_DIR, directory);
});

test('default resident mode retains upstream process reuse behavior', async t => {
  const { service, children, account } = harness(t, true);
  service.start();
  assert.equal(children.length, 1, 'upstream prewarm remains enabled');
  assert.equal(await service.refreshAccountCode(account), 'fixture_ONDEMAND_CODE_1');
  assert.equal(children.length, 2, 'the prewarmed process is replaced during restore');
  assert.equal(children[1].exitCode, null);
  assert.equal(service.accountSessions.size, 1);
  assert.equal(service.getAccountState(account).state, 'online');

  assert.equal(await service.refreshAccountCode(account), 'fixture_ONDEMAND_CODE_2');
  assert.equal(children.length, 2, 'resident mode reuses the same QQ process');
  assert.equal(children[1].exitCode, null);
  await service.stopAccount(account);
  assert.equal(children[1].exitCode, 0);
});
