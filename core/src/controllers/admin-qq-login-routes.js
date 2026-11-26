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
      res.status(201).json({ ok: true, data: qqLogin.create(owner(req), { ...setting, protocol, uin: String(req.body?.uin || ''), password: req.body?.password ? String(req.body.password) : '', restoreUin, profileDirectory: restoreProfile || undefined, proxyURL, proxyBridge, nativeProxyURL: proxyBridge?.url || '', targetUserId: target?.userId ?? null, targetAccountId: target ? String(target.id) : '' }) });
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
}

module.exports = { registerAdminQqLoginRoutes };
