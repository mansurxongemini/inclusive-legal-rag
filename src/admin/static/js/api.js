/**
 * Centralized API Client — Inclusive Legal RAG
 * Wraps all `/api/v1/inclusive/*` endpoints with unified error handling and timeouts.
 */

async function request(url, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    const contentType = res.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');
    const data = isJson ? await res.json() : await res.text();

    if (!res.ok) {
      const errorMsg = (data && data.detail) || (data && data.message) || `Server xatosi: HTTP ${res.status}`;
      const err = new Error(errorMsg);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error(`So'rov vaqti tugadi (${Math.round(timeoutMs / 1000)}s). Server bilan aloqa kechikmoqda.`);
    }
    throw err;
  }
}

export const api = {
  // 1. Tizim statistikasi
  fetchStats: () => request('/api/v1/inclusive/stats'),
  getStats: () => request('/api/v1/inclusive/stats'),
  getAdminStats: () => request('/api/v1/admin/stats'),

  // 2. Qonunchilik hujjatlari ro'yxati
  fetchDocuments: ({ doc_type, authority, q } = {}) => {
    const params = new URLSearchParams();
    if (doc_type && doc_type !== 'all') params.append('doc_type', doc_type);
    if (authority && authority !== 'all') params.append('authority', authority);
    if (q) params.append('q', q);
    const queryString = params.toString();
    return request(`/api/v1/inclusive/documents${queryString ? '?' + queryString : ''}`);
  },

  // 3. Tanlangan hujjat normalari
  fetchDocumentNorms: (lawNumber) => 
    request(`/api/v1/inclusive/documents/${encodeURIComponent(lawNumber)}/norms`),

  // 4. Normani tahrirlash va qayta vektorlash
  updateNorm: (canonicalId, payload) => 
    request(`/api/v1/inclusive/norms/${encodeURIComponent(canonicalId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload)
    }),

  // 5. Sinov so'rovi (Playground query)
  sendQuery: (payload) => 
    request('/api/v1/inclusive/query', {
      method: 'POST',
      body: JSON.stringify(payload)
    }, 45000),

  // 6. API kalitlar ro'yxati
  fetchApiKeys: () => 
    request('/api/v1/inclusive/admin/api-keys'),

  // 7. Yangi API kalit yaratish
  createApiKey: (payload) => 
    request('/api/v1/inclusive/admin/api-keys', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  // 8. API kalitni bekor qilish
  revokeApiKey: (keyId) => 
    request(`/api/v1/inclusive/admin/api-keys/${encodeURIComponent(keyId)}`, {
      method: 'DELETE'
    }),

  // 9. Yangi norma qo'shish (Manual upload)
  uploadArticle: (payload) => 
    request('/api/v1/inclusive/admin/upload-article', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  // 10. Papkadan yangilash (data/qonunlar import)
  importFolder: (directoryPath = 'data/qonunlar') => 
    request('/api/v1/inclusive/admin/import-folder', {
      method: 'POST'
    }, 90000),

  // 11. Lex.uz URL import
  importUrl: (payload) => 
    request('/api/v1/inclusive/admin/import-url', {
      method: 'POST',
      body: JSON.stringify(payload)
    }, 60000),

  // 12. Vektorlash inspektori (Lex.uz parsing & visualization)
  inspectDocument: (payload, timeoutMs = 30000) => 
    request('/api/v1/inclusive/admin/inspect-document', {
      method: 'POST',
      body: JSON.stringify(payload)
    }, timeoutMs),

  // 13. Vektor hisoblash (BGE-M3 test)
  testVector: (payload) => 
    request('/api/v1/inclusive/admin/test-vector', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  // 14. TypeSafe Jev 1.13 semantik tahlili
  testJev: (payload) => 
    request('/api/v1/inclusive/admin/test-jev', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
};
