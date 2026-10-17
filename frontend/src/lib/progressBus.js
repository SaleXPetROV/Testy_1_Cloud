/**
 * Instant XP / progress refresh without polling.
 * After any successful action of the player (POST / PUT / PATCH / DELETE to /api), widgets that show
 * XP (City Pass header bar, City Pass page, leagues) are told to re-read once — debounced 600 ms,
 * so a burst of actions makes ONE request. Nothing runs while the player does nothing.
 */
const EVT = 'gc:progress';
let timer = null;
const SKIP = /\/api\/(pass\/me|auth\/|ws\/|analytics|track|fingerprint|notifications\/read)/;

export function emitProgress() {
  clearTimeout(timer);
  timer = setTimeout(() => window.dispatchEvent(new Event(EVT)), 600);
}

export function onProgress(cb) {
  window.addEventListener(EVT, cb);
  return () => window.removeEventListener(EVT, cb);
}

let installed = false;
export function installProgressBus(axiosInstance) {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  const isAction = (method, url) => /^(POST|PUT|PATCH|DELETE)$/i.test(method || 'GET') && /\/api\//.test(url || '') && !SKIP.test(url || '');
  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const res = await origFetch(input, init);
    try {
      const url = typeof input === 'string' ? input : input?.url;
      const method = init?.method || (typeof input !== 'string' && input?.method) || 'GET';
      if (res.ok && isAction(method, url)) emitProgress();
    } catch (e) { /* never break a request */ }
    return res;
  };
  if (axiosInstance?.interceptors) {
    axiosInstance.interceptors.response.use((r) => {
      try { if (isAction(r.config?.method, r.config?.url)) emitProgress(); } catch (e) { /* ignore */ }
      return r;
    });
  }
}
