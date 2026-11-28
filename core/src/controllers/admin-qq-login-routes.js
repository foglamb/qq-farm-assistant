const { QqScanError } = require('../services/qq-login-service');
const { proxySetting, resolveProxyURL, createSocksBridge } = require('../services/account-proxy');
const { createQqAccountImporter, getQqUpdateTarget } = require('../services/qq-account-import');
const { getUserAccessRejection } = require('../models/access-policy');

function registerAdminQqLoginRoutes({ app, requireAdminToken, qqLogin, provider, addOrUpdateAccount, userStore, resolveProxy = resolveProxyURL, bridgeProxy = createSocksBridge }) {
  const importer = createQqAccountImporter({ qqLogin, provider, addOrUpdateAccount, userStore });
  const owner = req => `${req.currentUser.id}:${req.adminToken}`;
  const run = handler => async (req, res) => {
    res.set('Cache-Control', 'no-store');
    try { await handler(req, res); }
    catch (error) {
      res.status(error instanceof QqScanError ? error.status : 503).json({ ok: false,
        error: error instanceof QqScanError ? error.message : 'QQ 扫码服务暂时不可用，请稍后重试' });
    }
  };
  app.get('/api/qq-login/status', requireAdminToken, run((req, res) => res.json({ ok: true, data: qqLogin.status({ owner: owner(req), admin: req.currentUser.role === 'admin' }) })));
  app.post('/api/qq-login/sessions', requireAdminToken, run(async (req, res) => {
    const target = getQqUpdateTarget(provider, req.currentUser.id, req.body?.targetAccountId, req.currentUser.role);
    const protocol = req.body?.protocol || 'napcat';
    const restoreUin = protocol === 'pad' && req.body?.restore === true && target?.qqLoginProtocol === 'pad' ? String(target.uin || target.qq || '') : '';
    const restoreProfile = restoreUin && target?.qqLoginProfile ? String(target.qqLoginProfile) : '';
    if (req.body?.restore === true && (!restoreUin || !restoreProfile)) throw new QqScanError('当前账号没有可恢复的 AndroidPad 会话', 400, 'configuration');
    // The service compares an absolute directory against its own profile root, so
    // resolve the stored profile id here instead of handing over the bare id.
    let restoreDirectory = '';
    if (restoreProfile) {
      try { restoreDirectory = qqLogin.profilePath(restoreProfile); }
      catch { throw new QqScanError('当前账号的 AndroidPad 登录资料已失效，请使用 QQ 密码登录一次', 409, 'rescan'); }
    }
    let setting;
    try { setting = proxySetting({ ...(target ? { proxyMode: target.proxyMode, proxyProfileId: target.proxyProfileId } : {}), ...req.body }); } catch { throw new QqScanError('请选择有效的代理配置'); }
    const proxyURL = await resolveProxy(setting, {
      userId: target?.userId ?? req.currentUser.id,
    });
    const proxyBridge = proxyURL ? await bridgeProxy(proxyURL) : null;
    try {
      for (const userId of new Set([req.currentUser.id, target?.userId ?? req.currentUser.id])) {
        const rejection = getUserAccessRejection(userStore.getUser(userId));
        if (rejection) throw new QqScanError(rejection.error, 403);
      }
      if (target) getQqUpdateTarget(provider, req.currentUser.id, target.id, req.currentUser.role);
      res.status(201).json({ ok: true, data: qqLogin.create(owner(req), { ...setting, protocol, uin: String(req.body?.uin || ''), password: req.body?.password ? String(req.body.password) : '', restoreUin, profileDirectory: restoreDirectory || undefined, proxyURL, proxyBridge, nativeProxyURL: proxyBridge?.url || '', targetUserId: target?.userId ?? null, targetAccountId: target ? String(target.id) : '' }) });
    } catch (error) { proxyBridge?.close(); throw error; }
  }));
  app.post('/api/qq-login/sessions/:id/import', requireAdminToken, run(async (req, res) => res.json({ ok: true, data: await importer(req) })));
  app.post('/api/qq-login/sessions/:id/captcha', requireAdminToken, run((req, res) => {
    qqLogin.submitCaptcha(owner(req), req.params.id, String(req.body?.ticket || ''), String(req.body?.randstr || ''));
    res.json({ ok: true, data: { accepted: true } });
  }));
  app.post('/api/qq-login/sessions/:id/sms', requireAdminToken, run((req, res) => {
    qqLogin.submitSms(owner(req), req.params.id, String(req.body?.code || ''));
    res.json({ ok: true, data: { accepted: true } });
  }));
  app.get('/api/qq-login/sessions/:id', requireAdminToken, run((req, res) => res.json({ ok: true, data: qqLogin.get(owner(req), req.params.id) })));
  app.delete('/api/qq-login/sessions/:id', requireAdminToken, run((req, res) => { qqLogin.cancel(owner(req), req.params.id); res.json({ ok: true }); }));
  // Signing service settings: admins may point AndroidPad at a self-hosted
  // signer (for example a local 9.3.75 unidbg instance) without a rebuild.
  app.get('/api/qq-login/sign', requireAdminToken, run((req, res) => {
    const store = require('../models/store');
    res.json({ ok: true, data: store.getQqLoginSign(),
      effective: {
        signUrl: process.env.PAD_SIGN_URL || '', xwidUrl: process.env.PAD_LOCAL_XWID_URL || '',
        ptVersion: process.env.PAD_PT_VERSION || '', qua: process.env.PAD_QUA || '',
      } });
  }));
  app.post('/api/qq-login/sign', requireAdminToken, run((req, res) => {
    if (req.currentUser.role !== 'admin') throw new QqScanError('仅管理员可以修改签名服务', 403, 'configuration');
    const store = require('../models/store');
    let saved;
    try { saved = store.setQqLoginSign(req.body || {}); }
    catch (error) { throw new QqScanError(error.message, 400, 'configuration'); }
    res.json({ ok: true, data: saved });
  }));
  // Read-only reachability probe; it never logs in and never echoes secrets.
  app.post('/api/qq-login/sign/test', requireAdminToken, run(async (req, res) => {
    const raw = String(req.body?.signUrl || '').trim();
    if (!/^https?:\/\//i.test(raw)) throw new QqScanError('签名服务地址必须以 http:// 或 https:// 开头', 400, 'configuration');
    let protocol = null;
    try {
      const response = await fetch(raw.replace(/\/+$/, '') + '/', { signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new QqScanError(`签名服务返回 HTTP ${response.status}`, 503, 'configuration');
      const body = await response.json().catch(() => null);
      const info = body?.data?.protocol || null;
      protocol = info
        ? { version: String(info.version || ''), qua: String(info.qua || '') }
        // A signer pool answers with its own shape; report the pool as healthy.
        : body?.data?.backends ? { version: `签名池 ${body.data.backends.length} 个后端`, qua: '' } : null;
    } catch (error) {
      if (error instanceof QqScanError) throw error;
      throw new QqScanError('签名服务无法连接，请检查地址与网络', 503, 'configuration');
    }
    res.json({ ok: true, data: { ok: true, version: protocol?.version || '', qua: protocol?.qua || '' } });
  }));
  // Logged-in QQ numbers, read from saved identity records only.
  app.get('/api/qq-login/identities', requireAdminToken, run((req, res) => {
    const accounts = provider.getAccounts().accounts.filter(account => req.currentUser.role === 'admin' || account.userId === req.currentUser.id);
    const data = accounts.map(account => {
      let uin = '';
      if (account.qqLoginProtocol === 'pad' && account.qqLoginProfile) {
        try {
          const profile = require('node:path').join(require('../config/runtime-paths').getDataDir(), 'qq-login', 'profiles', String(account.qqLoginProfile));
          const identity = JSON.parse(require('node:fs').readFileSync(require('node:path').join(profile, 'identity.json'), 'utf8'));
          if (identity && /^\d{5,20}$/.test(String(identity.uin || ''))) uin = String(identity.uin);
        } catch { /* no saved identity */ }
      }
      return { accountId: String(account.id), name: account.name, protocol: account.qqLoginProtocol || '',
        uin: uin || String(account.uin || account.qq || ''), source: uin ? 'session' : 'account' };
    });
    res.json({ ok: true, data });
  }));
}

module.exports = { registerAdminQqLoginRoutes };
