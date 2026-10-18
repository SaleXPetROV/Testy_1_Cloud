/**
 * ONE personal WebSocket (/api/ws/<user>) for the whole app.
 * Before: the businesses page and the notification bell each opened their own socket and re-opened it on every
 * re-render (the `user` object changes with the balance) — the console filled with «WebSocket is closed before
 * the connection is established», and the server kept only one of the two sockets anyway.
 * subscribe(userKey, handler) -> unsubscribe. Reconnects with back-off; closes a few seconds after the last
 * subscriber leaves (so a quick unmount / mount does not re-connect).
 */
const subs = new Set();
let ws = null;
let key = null;
let retry = 0;
let retryTimer = null;
let closeTimer = null;
let pingTimer = null;

function url(k) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = (process.env.REACT_APP_BACKEND_URL || '').replace(/^https?:\/\//, '') || window.location.host;
  return `${scheme}://${host}/api/ws/${encodeURIComponent(k)}`;
}

function open() {
  if (!key || ws) return;
  try { ws = new WebSocket(url(key)); } catch (_) { ws = null; schedule(); return; }
  const me = ws;
  me.onopen = () => {
    retry = 0;
    clearInterval(pingTimer);
    pingTimer = setInterval(() => { try { if (me.readyState === 1) me.send(JSON.stringify({ type: 'ping' })); } catch (_) { /* ignore */ } }, 45000);
  };
  me.onmessage = (ev) => {
    let data; try { data = JSON.parse(ev.data); } catch (_) { return; }
    subs.forEach((fn) => { try { fn(data); } catch (_) { /* a broken handler must not stop the others */ } });
  };
  me.onerror = () => {};
  me.onclose = () => {
    if (ws === me) ws = null;
    clearInterval(pingTimer);
    if (subs.size && key) schedule();
  };
}

function schedule() {
  clearTimeout(retryTimer);
  const delay = Math.min(30000, 1000 * 2 ** Math.min(retry, 5));
  retry += 1;
  retryTimer = setTimeout(open, delay);
}

export function subscribeUserSocket(userKey, handler) {
  if (!userKey) return () => {};
  clearTimeout(closeTimer);
  if (key && key !== userKey && ws) { try { ws.close(); } catch (_) { /* ignore */ } ws = null; }
  key = userKey;
  subs.add(handler);
  open();
  return () => {
    subs.delete(handler);
    if (!subs.size) {
      closeTimer = setTimeout(() => {
        if (subs.size) return;
        clearTimeout(retryTimer); clearInterval(pingTimer);
        const s = ws; ws = null;
        // never close a socket that is still connecting (that is exactly the console error) — wait for it
        if (s && s.readyState === 0) s.onopen = () => { try { s.close(); } catch (_) { /* ignore */ } };
        else if (s) { try { s.close(); } catch (_) { /* ignore */ } }
      }, 3000);
    }
  };
}
