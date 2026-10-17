/**
 * Meta (Facebook) Conversions API browser signals.
 *
 * Reads the `_fbp` (browser id) and `_fbc` (click id) cookies that the Meta
 * Pixel sets, so they can be forwarded to the backend and included in the
 * server-side "Lead" event. If the Pixel isn't loaded / cookies are blocked
 * (Brave, in-app crypto wallet browsers, etc.) these come back empty and the
 * backend falls back to CRM-style matching.
 */

/** Read a single cookie value by name. Returns '' when absent. */
function readCookie(name) {
  if (typeof document === 'undefined' || !document.cookie) return '';
  const match = document.cookie.match(
    new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)')
  );
  return match ? decodeURIComponent(match[1]) : '';
}

/**
 * Returns { fbp, fbc } read from the `_fbp` / `_fbc` cookies.
 * Empty strings are omitted so we don't send noise to the backend.
 */
export function getFbCookies() {
  const out = {};
  const fbp = readCookie('_fbp');
  const fbc = readCookie('_fbc');
  if (fbp) out.fbp = fbp;
  if (fbc) out.fbc = fbc;
  return out;
}
