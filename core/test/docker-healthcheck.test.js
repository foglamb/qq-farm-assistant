const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const path = require('node:path');
const run = promisify(execFile);

test('health ignores YYB when disabled and checks both services after explicit enable', async (t) => {
  let mainStatus = 200;
  let yybStatus = 200;
  let yybOK = true;
  const main = http.createServer((_req, res) => { res.writeHead(mainStatus); res.end('panel'); });
  const yyb = http.createServer((_req, res) => { res.writeHead(yybStatus); res.end(JSON.stringify({ data: { ok: yybOK } })); });
  for (const server of [main, yyb]) {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    t.after(() => server.close());
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yyb-health-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const stateFile = path.join(dir, 'yyb-runtime.json');
  const verify = () => run(process.execPath, [path.join(__dirname, '../docker/healthcheck.js')], {
    env: { ...process.env, ADMIN_PORT: String(main.address().port), YYB_PORT: String(yyb.address().port),
      YYB_STATE_FILE: stateFile, YYB_ENABLED: '0' },
    timeout: 8000,
  });
  await verify();
  yybStatus = 503;
  await verify();
  fs.writeFileSync(stateFile, JSON.stringify({ enabled: true }));
  await assert.rejects(verify(), err => err.code === 1);
  yybStatus = 200;
  yybOK = false;
  await assert.rejects(verify(), err => err.code === 1);
  yybOK = true;
  await verify();
  mainStatus = 503;
  await assert.rejects(verify(), err => err.code === 1);
});
