const test = require('node:test');
const assert = require('node:assert/strict');
const { patchHost } = require('../qq-login/patch-napcat.cjs');

const common = [
  'c.onQRCodeSessionUserScaned = () => {',
  'c.onQRCodeLoginSucceed = async (u) => {',
  'c.onLoginFailed = (...u) => {',
  'c.onLoginDisConnected = () => {',
  'c.onLogoutSucceed = () => {',
  'setFileLogEnabled(e) {',
  'setConsoleLogEnabled(e) {',
];
const v41 = [
  'function YAe(t) {',
  'await r.init(n.getFullQQVersion(), s.o3HookMode === 1);',
  'S0e(e, t, l5, zAe).then().catch((W) => e.logError(W));',
  'async function e2e(t, e, n, r, i) {',
  'c.onQRCodeGetPicture = ({ pngBase64QrcodeData: u, qrcodeUrl: l }) => {',
  'c.onQRCodeSessionFailed = (u, l) => {',
  'await n2e(d, U, f);',
  ...common,
].join('\n');
const v42 = [
  'function xke(t) {\n  const e = it.platform();',
  'await n.init(r.getFullQQVersion(), s.o3HookMode === 1);',
  'bxe(e, t, nB, bke).then().catch((z) => e.logError(z));',
  'const u = o.NodeIQQNTWrapperEngine.get(), d = o.NodeIKernelLoginService.get();',
  'c.onQRCodeGetPicture = ({ pngBase64QrcodeData: u, qrcodeUrl: d }) => {',
  'c.onQRCodeSessionFailed = (u, d) => {',
  'await Cke(p, U, f);',
  'const _ = await Ake(d, e, t, x, g);',
  'if (i.some((a) => a.uin === n))',
  'r.quickLoginWithUin(n).then(async (a) => {',
  ...common,
].join('\n');

test('NapCat 4.18.41 anchors remain compatible', () => {
  const result = patchHost(v41);
  assert.match(result, /NAPCAT_TEST_QQ_DATA/);
  assert.match(result, /setLogin\(t\)/);
  assert.match(result, /ready\(d, S\)/);
  assert.match(result, /loginFailed\(u, l\)/);
  assert.match(result, /WebUI disabled/);
});

test('NapCat 4.18.42 uses its exact renamed anchors', () => {
  const result = patchHost(v42);
  assert.match(result, /NAPCAT_TEST_QQ_DATA/);
  assert.match(result, /setLogin\(d\)/);
  assert.match(result, /ready\(p, _\)/);
  assert.match(result, /loginFailed\(u, d\)/);
  assert.match(result, /WebUI disabled/);
  assert.match(result, /setRemerberPwd\?\.\(true\)/);
  assert.match(result, /String\(a\.uin\) === String\(n\)/);
  assert.match(result, /event:'napcat_recovery'|__qqFarmLogin\.recovery/);
  assert.doesNotMatch(result, /i\.some\(\(a\) => a\.uin === n\)/);
  assert.doesNotMatch(result, /await n\.init\(/);
});

test('patched runtimes are idempotent and migrate the swapped ready arguments', () => {
  const patched = patchHost(v42);
  assert.equal(patchHost(patched), patched);
  const stale = patched.replace('ready(p, _)', 'ready(d, p)');
  const migrated = patchHost(stale);
  assert.equal(migrated, patched);
  assert.match(migrated, /ready\(p, _\)/);
  assert.doesNotMatch(migrated, /ready\(d, p\)/);
});

test('unknown or incomplete bundles fail closed instead of producing a partial patch', () => {
  assert.throws(() => patchHost(''), /Unrecognized NapCat build/);
  assert.throws(() => patchHost(v42.replace('await Cke(p, U, f);', '')), /Unrecognized NapCat build/);
  assert.throws(() => patchHost(v42.replace('const _ = await Ake(d, e, t, x, g);', '')), /Unrecognized NapCat build/);
});
