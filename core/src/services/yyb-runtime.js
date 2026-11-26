const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');

function statePath(env = process.env) {
  return env.YYB_STATE_FILE || path.join(env.FARM_DATA_DIR || path.join(process.cwd(), 'core', 'data'), 'yyb-runtime.json');
}

function readEnabled(env = process.env) {
  try {
    const saved = JSON.parse(fs.readFileSync(statePath(env), 'utf8'));
    if (typeof saved.enabled === 'boolean') return saved.enabled;
  } catch {}
  return env.YYB_ENABLED === '1';
}

function probeHttp(port, route, token) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: route, timeout: 2000,
      headers: token ? { authorization: `Bearer ${token}` } : {} }, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(body) }); }
        catch { reject(new Error('YYB returned invalid JSON')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('YYB probe timeout')));
    req.on('error', reject);
    req.end();
  });
}

function createYybRuntime(options = {}) {
  const env = options.env || process.env;
  const file = statePath(env);
  const spawnFn = options.spawn || spawn;
  const probe = options.probe || probeHttp;
  let enabled = readEnabled(env);
  let child = null;
  let external = false;
  let error = null;
  let transition = Promise.resolve();

  function save() {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ enabled }), { mode: 0o600 });
    fs.renameSync(tmp, file);
  }
  function alive() { return !!child && child.exitCode === null && !child.signalCode && !child.spawnError; }
  function status() {
    return { enabled, running: external || alive(), external, pid: alive() ? child.pid : null, error };
  }
  async function healthy() {
    try {
      const reply = await probe(env.YYB_PORT || 8450, '/health', null);
      return reply.status === 200 && reply.data.data?.ok === true;
    } catch { return false; }
  }
  async function terminate() {
    const current = child;
    child = null;
    external = false;
    if (!current || current.exitCode !== null || current.signalCode || current.spawnError) return;
    try { current.kill('SIGTERM'); } catch {}
    const deadline = Date.now() + 5000;
    while (current.exitCode === null && !current.signalCode && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    if (current.exitCode === null && !current.signalCode) {
      try { current.kill('SIGKILL'); } catch {}
    }
  }
  async function start() {
    if (alive() || external) return status();
    error = null;
    if (await healthy()) {
      const auth = await probe(env.YYB_PORT || 8450, '/accounts', env.YYB_API_TOKEN || env.YYB_API_KEY);
      if (auth.status !== 200) throw Object.assign(new Error('YYB 端口被其他服务占用或 Token 不一致'), { status: 503 });
      external = true;
      return status();
    }
    const current = spawnFn(env.YYB_EXECUTABLE, ['-host', '127.0.0.1', '-port', String(env.YYB_PORT || 8450), '-resource-root', env.YYB_RESOURCE_ROOT], {
      cwd: path.dirname(env.YYB_RESOURCE_ROOT), env, windowsHide: true, stdio: 'inherit',
    });
    child = current;
    current.once('error', cause => { current.spawnError = true; if (child === current) error = cause.message; });
    current.once('exit', (code, signal) => {
      if (child === current) child = null;
      if (enabled && code !== 0) error = `YYB 服务退出（${signal || code}）`;
    });
    const deadline = Date.now() + 30000;
    while (!(await healthy())) {
      if (current.spawnError || current.exitCode !== null || current.signalCode) throw Object.assign(new Error(error || 'YYB 启动失败'), { status: 503 });
      if (Date.now() >= deadline) {
        await terminate();
        error = 'YYB 启动超时';
        throw Object.assign(new Error(error), { status: 503 });
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return status();
  }
  function setEnabled(value) {
    if (typeof value !== 'boolean') return Promise.reject(Object.assign(new Error('enabled 必须为布尔值'), { status: 400 }));
    const task = transition.then(async () => {
      enabled = value;
      save();
      if (enabled) return start();
      await terminate();
      error = null;
      return status();
    });
    transition = task.catch(() => {});
    return task;
  }
  return {
    getStatus: status,
    setEnabled,
    restore: () => enabled ? setEnabled(true) : Promise.resolve(status()),
    close: () => terminate(),
  };
}

module.exports = { createYybRuntime, readYybEnabled: readEnabled, yybStatePath: statePath };
