/**
 * Administrator key support for the dashboard.
 *
 * Write/admin API routes answer 401 ("Administrator huquqi talab qilinadi") when the dashboard is opened from
 * anywhere but the server's own localhost. This wrapper asks for ADMIN_API_KEY once per browser session,
 * keeps it in sessionStorage (never localStorage) and sends it as X-Admin-Key on same-origin /api/ calls.
 */
(function () {
  var STORAGE_KEY = 'legalRagAdminKey';
  var nativeFetch = window.fetch.bind(window);

  function readKey() {
    try { return sessionStorage.getItem(STORAGE_KEY) || ''; } catch (e) { return ''; }
  }
  function writeKey(value) {
    try { sessionStorage.setItem(STORAGE_KEY, value); } catch (e) { /* private mode: ask again next time */ }
  }
  function isSameOriginApi(url) {
    try {
      var u = new URL(url, window.location.origin);
      return u.origin === window.location.origin && u.pathname.indexOf('/api/') === 0;
    } catch (e) {
      return false;
    }
  }
  function withKey(init, key) {
    var headers = new Headers((init && init.headers) || {});
    if (key) headers.set('X-Admin-Key', key);
    return Object.assign({}, init || {}, { headers: headers });
  }
  async function needsAdminKey(res) {
    if (res.status !== 401 && res.status !== 403) return false;
    try {
      var body = await res.clone().json();
      return typeof body.detail === 'string' && body.detail.indexOf('Administrator') !== -1;
    } catch (e) {
      return false;
    }
  }

  window.fetch = async function (input, init) {
    if (typeof input !== 'string' && !(input instanceof URL)) return nativeFetch(input, init);
    var url = String(input);
    if (!isSameOriginApi(url)) return nativeFetch(input, init);

    var res = await nativeFetch(input, withKey(init, readKey()));
    if (await needsAdminKey(res)) {
      var entered = window.prompt('Administrator kaliti (ADMIN_API_KEY) kiritilsin:');
      if (entered && entered.trim()) {
        writeKey(entered.trim());
        res = await nativeFetch(input, withKey(init, entered.trim()));
      }
    }
    return res;
  };
})();
