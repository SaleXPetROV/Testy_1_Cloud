/** Monetag rewarded ads for the Telegram Mini App.
 *  The SDK tag is set by the admin (admin → «Данные» → «Monetag»); /api/ads/config returns what was parsed from it:
 *  sdk_src (e.g. https://libtl.com/sdk.js), zone_id (data-zone) and sdk_fn (data-sdk, e.g. show_10012345).
 *  showRewardedAd(cfg, ymid) resolves after the ad was watched, rejects if it failed / was closed. */
const loaded = {};

function loadSdk({ zone_id: zone, sdk_src: src, sdk_fn: fnName }) {
  const fn = fnName || `show_${zone}`;
  const key = `${src}|${fn}`;
  if (loaded[key]) return loaded[key];
  loaded[key] = new Promise((resolve, reject) => {
    if (typeof window[fn] === 'function') { resolve(window[fn]); return; }
    const s = document.createElement('script');
    s.src = src || 'https://libtl.com/sdk.js';
    s.async = true;
    s.dataset.zone = String(zone);
    s.dataset.sdk = fn;
    s.onload = () => {
      let tries = 0;
      const wait = () => {                      // the SDK defines show_<zone> right after loading
        if (typeof window[fn] === 'function') resolve(window[fn]);
        else if (tries++ > 50) reject(new Error('sdk'));
        else setTimeout(wait, 100);
      };
      wait();
    };
    s.onerror = () => { delete loaded[key]; reject(new Error('sdk')); };
    document.head.appendChild(s);
  });
  return loaded[key];
}

export async function showRewardedAd(cfg, ymid) {
  const show = await loadSdk(cfg);
  // ymid comes back in Monetag's postback, so the server can confirm the view
  return show({ ymid: ymid || undefined });
}
