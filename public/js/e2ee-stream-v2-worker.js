'use strict';

function b64ToBytes(value) {
  const binary = atob(String(value || '').replace(/\s+/g, ''));
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

self.onmessage = async (event) => {
  const payload = event?.data || {};
  if (payload.type !== 'decrypt-chunk') return;
  const id = payload.id;
  try {
    const rawKey = payload.keyBytes;
    const ciphertext = payload.ciphertext;
    if (!(rawKey instanceof ArrayBuffer) || !(ciphertext instanceof ArrayBuffer)) {
      throw new Error('缺少有效的 E2EE Streaming v2 chunk 資料');
    }
    const key = await crypto.subtle.importKey('raw', rawKey, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64ToBytes(payload.nonce) },
      key,
      ciphertext,
    );
    self.postMessage({ type: 'decrypt-chunk-ok', id, plaintext }, [plaintext]);
  } catch (err) {
    self.postMessage({ type: 'decrypt-chunk-error', id, message: err?.message || 'E2EE chunk 解密失敗' });
  }
};
