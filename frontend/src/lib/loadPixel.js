/**
 * Deferred Meta (Facebook) Pixel loader.
 *
 * The pixel used to live inline in index.html and fired `fbq('track','PageView')`
 * synchronously on every page open — a third-party request BEFORE any user
 * interaction. That contributes to Safari's "activity with no interaction"
 * heuristic. We now load `fbevents.js` and send the first PageView only AFTER
 * the first real user gesture. The pixel id is unchanged, so tracking still
 * works — it just starts a moment later.
 */

import { onFirstGesture } from './firstGesture';

const PIXEL_ID = '2001550760477854';
let initialised = false;

function initPixel() {
  if (initialised) return;
  initialised = true;
  try {
    /* eslint-disable */
    !function (f, b, e, v, n, t, s) {
      if (f.fbq) return; n = f.fbq = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0';
      n.queue = []; t = b.createElement(e); t.async = !0;
      t.src = v; s = b.getElementsByTagName(e)[0];
      s.parentNode.insertBefore(t, s);
    }(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');
    /* eslint-enable */
    window.fbq('init', PIXEL_ID);
    window.fbq('track', 'PageView');
  } catch (_) { /* noop */ }
}

/** Register the pixel to load on the first user gesture. */
export function setupDeferredPixel() {
  onFirstGesture(initPixel);
}
