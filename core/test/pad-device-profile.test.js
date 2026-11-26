const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');

test('Pad shares only device identity and handles native SMS events', () => {
  const session = fs.readFileSync(path.join(root, 'pad-login/PadSession.cs'), 'utf8');
  const profile = fs.readFileSync(path.join(root, 'pad-login/PadDeviceProfile.cs'), 'utf8');
  assert(session.includes('if (saved is null) ApplySharedDeviceProfile(_context.Keystore)'));
  assert(session.includes('if (success) SaveSharedDeviceProfile(_context.Keystore)'));
  assert(session.includes('RegisterEvent<BotSMSEvent>'));
  assert(session.includes('_phase = "needs_sms"'));
  for (const field of ['Guid', 'AndroidId', 'Qimei', 'DeviceName']) assert(profile.includes(field));
  const declaration = profile.split(/\r?\n/).find(line => line.includes('record PadDeviceProfile')) || '';
  for (const secret of ['WLoginSigs', 'Password', 'A2', 'Uid', 'Uin']) assert(!declaration.includes(secret), secret);
});
