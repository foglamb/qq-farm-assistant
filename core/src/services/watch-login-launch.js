const fs = require('node:fs');
const path = require('node:path');
const { getProgramRoot } = require('../config/runtime-paths');

/**
 * 手表扫码渠道（PLATFORM_WATCH）。与 NapCat / AndroidPad 并列的第三条通道。
 *
 * 与 Pad 的关键差异：手表扫码走纯 P-256 ECDH + TLV 换票，不需要
 * `libfekit.so` 签名，因此不依赖任何外部签名服务。
 */
function watchLaunch(environment = process.env) {
  const component = environment.WATCH_LOGIN_COMPONENT_DIR || path.join(getProgramRoot(), 'watch-login');
  const host = path.join(component, 'watch_host.py');
  if (!fs.existsSync(host)) {
    const error = new Error('手表扫码组件未安装，请先准备 watch-login/watch_host.py');
    error.status = 503; error.kind = 'configuration';
    throw error;
  }
  const python = environment.WATCH_LOGIN_PYTHON || 'python3';
  return { protocol: 'watch', component, runtime: component, host, executable: python, electron: false, argsPrefix: [] };
}

module.exports = { watchLaunch };
