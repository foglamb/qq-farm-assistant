const CODE_EXPIRED = 'code_expired';
const CODE_REJECTED = 'code_rejected';
const RESCAN_REQUIRED = 'rescan_required';

function classifyHandshakeFailure(status) {
  return Number(status) === 400 ? CODE_REJECTED : null;
}

function credentialMetadata(issuedAt, expiresAt, now = Date.now()) {
  const issued = Number.isSafeInteger(issuedAt) && issuedAt > 0 ? issuedAt : null;
  const expires = Number.isSafeInteger(expiresAt) && expiresAt > 0 ? expiresAt : null;
  return {
    issuedAt: issued,
    expiresAt: expires,
    status: expires && now >= expires ? CODE_EXPIRED : null,
  };
}

module.exports = { CODE_EXPIRED, CODE_REJECTED, RESCAN_REQUIRED, classifyHandshakeFailure, credentialMetadata };
