const test = require('node:test');
const assert = require('node:assert/strict');
const { CODE_EXPIRED, CODE_REJECTED, RESCAN_REQUIRED, classifyHandshakeFailure, credentialMetadata } = require('../src/services/code-lifecycle');

test('only an explicit absolute TTL proves time-based Code expiry', () => {
  const now = 1800000000000;
  assert.deepEqual(credentialMetadata(now - 1000, now + 1000, now), { issuedAt: now - 1000, expiresAt: now + 1000, status: null });
  assert.equal(credentialMetadata(now - 1000, now, now).status, CODE_EXPIRED);
  assert.equal(credentialMetadata(now - 1000, now - 1, now).status, CODE_EXPIRED);
  assert.equal(credentialMetadata(now, null, now).status, null);
});

test('HTTP 400 is Code rejection, while transport failures are not mislabeled as expiry', () => {
  assert.equal(classifyHandshakeFailure(400), CODE_REJECTED);
  for (const value of [1006, 401, 403, 500, 0, '400', null, undefined]) {
    if (value === '400') assert.equal(classifyHandshakeFailure(value), CODE_REJECTED);
    else assert.equal(classifyHandshakeFailure(value), null);
  }
  assert.notEqual(CODE_REJECTED, CODE_EXPIRED);
  assert.notEqual(RESCAN_REQUIRED, CODE_EXPIRED);
});
