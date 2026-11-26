// Apply only to a pinned program copy, never to a user's QQ profile.
function patchHost(text) {
  function replace(old, value) {
    if (text.split(old).length !== 2) throw new Error(`Unrecognized NapCat build at: ${old.slice(0, 70)}`);
    text = text.replace(old, value);
  }
  function replaceOne(candidates, value) {
    for (const old of candidates) if (text.split(old).length === 2) return replace(old, value);
    throw new Error(`Unrecognized NapCat build at: ${candidates[0].slice(0, 70)}`);
  }
  if (!text.includes('process.env.NAPCAT_TEST_QQ_DATA')) {
    if (text.includes('function YAe(t) {')) {
      replace('function YAe(t) {', `function YAe(t) {
  if (process.env.NAPCAT_TEST_QQ_DATA) {
    const isolated = xe.resolve(process.env.NAPCAT_TEST_QQ_DATA);
    const global = Sn.platform() === "linux" ? xe.join(isolated, "global") : xe.join(isolated, "nt_qq", "global");
    fe.mkdirSync(global, {recursive: true});
    return [isolated, global];
  }`);
    } else {
      replace('function xke(t) {\n  const e = it.platform();', `function xke(t) {
  const e = it.platform();
  if (process.env.NAPCAT_TEST_QQ_DATA) {
    const isolated = ge.resolve(process.env.NAPCAT_TEST_QQ_DATA);
    const global = e === "linux" || e === "darwin" ? ge.join(isolated, "global") : ge.join(isolated, "nt_qq", "global");
    Ie.mkdirSync(global, {recursive: true});
    return [isolated, global];
  }`);
    }
  }
  replaceOne([
    'await r.init(n.getFullQQVersion(), s.o3HookMode === 1);',
    'await n.init(r.getFullQQVersion(), s.o3HookMode === 1);',
  ], '/* Packet hooks disabled. */');
  replaceOne([
    'S0e(e, t, l5, zAe).then().catch((W) => e.logError(W));',
    'bxe(e, t, nB, bke).then().catch((z) => e.logError(z));',
  ], 'Promise.resolve(); /* WebUI disabled. */');
  if (text.includes('async function e2e(t, e, n, r, i) {')) {
    replace('async function e2e(t, e, n, r, i) {', 'async function e2e(t, e, n, r, i) {\n globalThis.__qqFarmLogin.setLogin(t);');
  } else {
    replace('const u = o.NodeIQQNTWrapperEngine.get(), d = o.NodeIKernelLoginService.get();',
      'const u = o.NodeIQQNTWrapperEngine.get(), d = o.NodeIKernelLoginService.get();\n globalThis.__qqFarmLogin.setLogin(d);');
  }
  replaceOne([
    'c.onQRCodeGetPicture = ({ pngBase64QrcodeData: u, qrcodeUrl: l }) => {',
    'c.onQRCodeGetPicture = ({ pngBase64QrcodeData: u, qrcodeUrl: d }) => {',
  ], `c.onQRCodeGetPicture = (event) => {
    globalThis.__qqFarmLogin.qr(event);
    return; // QR and credentials are delivered over the parent pipe only.
    const {pngBase64QrcodeData: u, qrcodeUrl: l} = event;`);
  for (const [key, call] of [
    ['c.onQRCodeSessionUserScaned = () => {', 'globalThis.__qqFarmLogin.phase("scanned");'],
    ['c.onQRCodeLoginSucceed = async (u) => {', 'globalThis.__qqFarmLogin.phase("initializing");'],
    ['c.onLoginFailed = (...u) => {', 'globalThis.__qqFarmLogin.phase("login_failed");'],
    ['c.onLoginDisConnected = () => {', 'globalThis.__qqFarmLogin.phase("offline");'],
    ['c.onLogoutSucceed = () => {', 'globalThis.__qqFarmLogin.phase("offline");'],
  ]) replace(key, `${key}\n ${call}`);
  replaceOne([
    'c.onQRCodeSessionFailed = (u, l) => {',
    'c.onQRCodeSessionFailed = (u, d) => {',
  ], `${text.includes('c.onQRCodeSessionFailed = (u, l) => {')
    ? 'c.onQRCodeSessionFailed = (u, l) => {\n globalThis.__qqFarmLogin.loginFailed(u, l);'
    : 'c.onQRCodeSessionFailed = (u, d) => {\n globalThis.__qqFarmLogin.loginFailed(u, d);'}`);
  if (text.includes('await n2e(d, U, f);')) {
    replace('await n2e(d, U, f);', 'await n2e(d, U, f);\n await globalThis.__qqFarmLogin.ready(d, S); return;');
  } else {
    // Ake resolves the actual QR/quick-login identity ({ uin, uid, ... }).
    // The wrapper session p is a different object and never proves identity.
    replace('const _ = await Ake(d, e, t, x, g);', 'const _ = await Ake(d, e, t, x, g);');
    replace('await Cke(p, U, f);', 'await Cke(p, U, f);\n await globalThis.__qqFarmLogin.ready(d, _); return;');
  }
  replace('setFileLogEnabled(e) {', 'setFileLogEnabled(e) { e = false;');
  replace('setConsoleLogEnabled(e) {', 'setConsoleLogEnabled(e) { e = false;');
  return text;
}
module.exports = { patchHost };
if (require.main === module) {
  const fs = require('node:fs');
  const [source, destination] = process.argv.slice(2);
  if (!source || !destination) throw new Error('Usage: node patch-napcat.cjs source.mjs destination.mjs');
  fs.writeFileSync(destination, patchHost(fs.readFileSync(source, 'utf8')));
}
