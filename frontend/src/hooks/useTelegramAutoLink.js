/**
 * useTelegramAutoLink — when the user is *already authenticated* and the app
 * is running inside a Telegram Mini App, this hook silently links the
 * Telegram identity (telegram_id / chat_id / username) to the existing
 * account so the user starts receiving bot notifications without any extra UI.
 *
 * IMPORTANT: this hook does NOT create accounts. Registration must go through
 * the regular flows (email / Google / wallet). If there is no JWT in
 * localStorage, the hook is a no-op — the user must register first.
 *
 * Trigger: runs once after a JWT appears in localStorage; re-runs whenever
 * the token changes (so post-registration / post-login is covered).
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export default function useTelegramAutoLink({ isTelegram, tg }) {
  const linkedRef = useRef(false);
  const [tokenTick, setTokenTick] = useState(0);

  // Bump tokenTick every time the JWT changes so the linker effect re-runs.
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === 'token') setTokenTick((n) => n + 1);
    };
    window.addEventListener('storage', onStorage);

    // Patch localStorage so same-tab writes also notify us (storage event
    // only fires across tabs natively).
    const origSet = localStorage.setItem.bind(localStorage);
    const origRemove = localStorage.removeItem.bind(localStorage);
    localStorage.setItem = (k, v) => {
      origSet(k, v);
      if (k === 'token') setTokenTick((n) => n + 1);
    };
    localStorage.removeItem = (k) => {
      origRemove(k);
      if (k === 'token') setTokenTick((n) => n + 1);
    };

    return () => {
      window.removeEventListener('storage', onStorage);
      localStorage.setItem = origSet;
      localStorage.removeItem = origRemove;
    };
  }, []);

  useEffect(() => {
    if (!isTelegram || !tg) return;
    if (linkedRef.current) return;

    const token = localStorage.getItem('token');
    if (!token) return; // user not authenticated yet — wait for registration

    const initData = tg.initData;
    if (!initData) return;

    linkedRef.current = true;

    (async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/auth/telegram-link`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ init_data: initData }),
        });
        if (!res.ok) {
          // 409 = already bound to another account (expected in some flows),
          // 401 = stale token; both are non-fatal.
          if (res.status !== 409 && res.status !== 401) {
            linkedRef.current = false; // allow retry on next token change
          }
          return;
        }
        // success — notify rest of the app so SettingsPage can refresh.
        window.dispatchEvent(new CustomEvent('tg:linked'));
      } catch (e) {
        linkedRef.current = false; // network glitch, allow retry
        // eslint-disable-next-line no-console
        console.warn('[telegram-auto-link] network error', e);
      }
    })();
  }, [isTelegram, tg, tokenTick]);
}
