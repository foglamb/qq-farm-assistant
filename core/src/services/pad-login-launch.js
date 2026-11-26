const fs = require('node:fs');
const path = require('node:path');
const { getProgramRoot } = require('../config/runtime-paths');

function padLaunch(environment = process.env) {
  const component = environment.PAD_LOGIN_COMPONENT_DIR || path.join(getProgramRoot(), 'pad-login');
  const dll = environment.PAD_LOGIN_DLL || '';
  const executable = dll
    ? (environment.DOTNET_EXE || 'dotnet')
    : (environment.PAD_LOGIN_EXECUTABLE || path.join(component, 'PadLogin'));
  const host = dll || executable;
  if (!fs.existsSync(host)) {
    const error = new Error('AndroidPad 登录组件未安装，请先构建 pad-login/PadLogin');
    error.status = 503; error.kind = 'configuration';
    throw error;
  }
  if (!environment.PAD_SIGN_URL) {
    const error = new Error('AndroidPad 签名服务未配置，请设置 PAD_SIGN_URL');
    error.status = 503; error.kind = 'configuration';
    throw error;
  }
  return {
    protocol: 'pad', component, runtime: component, host, executable,
    electron: false,
    argsPrefix: dll ? [dll] : [],
  };
}

module.exports = { padLaunch };
