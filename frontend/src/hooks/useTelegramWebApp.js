/**
 * useTelegramWebApp — single source of truth for Telegram Mini App integration.
 *
 * Responsibilities:
 *  • One-time SDK init: ready → expand → requestFullscreen → setHeaderColor
 *    → setBackgroundColor → disableVerticalSwipes
 *  • Sets <html class="is-telegram"> so CSS can target Mini App-only tweaks.
 *  • Bridges Telegram safe-area insets into CSS variables (--tg-safe-top/bottom)
 *    so the existing layout can pad away from Telegram's overlay chrome.
 *  • Exposes a small surface: { tg, isTelegram, webAppUser, haptic }.
 *  • Auto-syncs Telegram BackButton with React Router navigation.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const HEADER_COLOR = '#05060A';
const BG_COLOR = '#05060A';

const safeCall = (fn) => {
  try { fn?.(); } catch (e) { /* silent — older Telegram clients lack newer APIs */ }
};

// Each newer Telegram WebApp method LOGS a console.error/warn when called
// on an older client (e.g. version 6.0). The SDK does this BEFORE returning,
// so wrapping in try/catch does NOT suppress the log spam visible in the
// browser DevTools. `versionAtLeast` lets us gate the call entirely so the
// SDK never gets a chance to print the warning.
const versionAtLeast = (tg, minVer) => {
  try {
    if (tg?.isVersionAtLeast) return !!tg.isVersionAtLeast(minVer);
    // Fallback for very old WebApp builds that lack the helper.
    const cur = String(tg?.version || '0').split('.').map((n) => parseInt(n, 10) || 0);
    const min = minVer.split('.').map((n) => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(cur.length, min.length); i++) {
      if ((cur[i] || 0) > (min[i] || 0)) return true;
      if ((cur[i] || 0) < (min[i] || 0)) return false;
    }
    return true;
  } catch { return false; }
};

const readSafeAreaVars = (tg) => {
  // Telegram exposes safe-area data via either CSS vars (newer clients)
  // or JS API (older). Read from JS first, fall back to CSS.
  const top =
    Number(tg?.contentSafeAreaInset?.top ?? 0) ||
    Number(tg?.safeAreaInset?.top ?? 0) || 0;
  const bottom =
    Number(tg?.contentSafeAreaInset?.bottom ?? 0) ||
    Number(tg?.safeAreaInset?.bottom ?? 0) || 0;
  const left =
    Number(tg?.contentSafeAreaInset?.left ?? 0) ||
    Number(tg?.safeAreaInset?.left ?? 0) || 0;
  const right =
    Number(tg?.contentSafeAreaInset?.right ?? 0) ||
    Number(tg?.safeAreaInset?.right ?? 0) || 0;
  return { top, bottom, left, right };
};

const applySafeAreaVars = (tg, isTelegram) => {
  const root = document.documentElement;
  // OUTSIDE a real Telegram Mini App we want absolutely no extra spacing
  // (the in-app browser already gives us a clean viewport).
  if (!isTelegram) {
    root.style.setProperty('--tg-safe-top', '0px');
    root.style.setProperty('--tg-safe-bottom', '0px');
    root.style.setProperty('--tg-safe-left', '0px');
    root.style.setProperty('--tg-safe-right', '0px');
    return;
  }
  const { top, bottom, left, right } = readSafeAreaVars(tg);
  // Add a top offset ONLY when Telegram OVERLAYS its "Закрыть / ˅ / ⋮" chrome
  // directly over the app content — i.e. in FULLSCREEN mode (the floating
  // "Закрыть" pill, no title bar). In the default windowed mode Telegram
  // draws its own title bar ("GRAM CITY") OUTSIDE the webview, so the content
  // already starts below it and any extra padding just creates an ugly double
  // gap. So: fullscreen → clear the chrome (>=56px); windowed → no padding
  // (use whatever inset the client reports, normally 0).
  const isFullscreen = !!(tg && tg.isFullscreen);
  const MIN_TG_TOP = 56;
  const topInset = isFullscreen ? Math.max(top, MIN_TG_TOP) : top;
  root.style.setProperty('--tg-safe-top', `${topInset}px`);
  root.style.setProperty('--tg-safe-bottom', `${bottom}px`);
  root.style.setProperty('--tg-safe-left', `${left}px`);
  root.style.setProperty('--tg-safe-right', `${right}px`);
};

export default function useTelegramWebApp() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialisedRef = useRef(false);

  const tg = typeof window !== 'undefined' ? window.Telegram?.WebApp : null;
  // initData is non-empty only inside a real Telegram client.
  const isTelegram = Boolean(tg && tg.initData && tg.initData.length > 0);

  const webAppUser = useMemo(() => {
    try { return tg?.initDataUnsafe?.user || null; } catch { return null; }
  }, [tg]);

  // ── One-time bootstrap ──
  useEffect(() => {
    if (!tg || initialisedRef.current) return;
    initialisedRef.current = true;

    safeCall(() => tg.ready());
    safeCall(() => tg.expand());
    // NOTE: `tg.requestFullscreen()` was intentionally REMOVED here.
    // Fullscreen mode makes Telegram render its "Закрыть / ˅ / ⋮" chrome
    // OVER the mini-app viewport, and on stock Android that chrome sits
    // right on top of our fixed header row (see screenshots reported by
    // user). Removing this call restores Telegram's default layout: its
    // chrome takes its own strip at the very top and our layout starts
    // below it, so the app header, MobileNav burger and top-right buttons
    // are never covered. `expand()` alone is enough to grow the viewport
    // to full available height while keeping the chrome above.
    // Each of these methods was added in a specific WebApp version and
    // logs a noisy `[Telegram.WebApp] Method X is not supported in version Y`
    // on older clients (incl. Telegram Desktop 6.0). Gate them so the SDK
    // never prints those errors. See https://core.telegram.org/bots/webapps
    if (versionAtLeast(tg, '7.7'))  safeCall(() => tg.disableVerticalSwipes?.());
    if (versionAtLeast(tg, '6.1'))  safeCall(() => tg.setHeaderColor(HEADER_COLOR));
    if (versionAtLeast(tg, '6.1'))  safeCall(() => tg.setBackgroundColor(BG_COLOR));
    if (versionAtLeast(tg, '7.10')) safeCall(() => tg.setBottomBarColor?.(BG_COLOR));

    if (isTelegram) {
      document.documentElement.classList.add('is-telegram');
    }

    applySafeAreaVars(tg, isTelegram);

    // Re-sync safe-area on viewport / theme / fullscreen events
    const refresh = () => applySafeAreaVars(tg, isTelegram);
    safeCall(() => tg.onEvent?.('viewportChanged', refresh));
    safeCall(() => tg.onEvent?.('safeAreaChanged', refresh));
    safeCall(() => tg.onEvent?.('contentSafeAreaChanged', refresh));
    safeCall(() => tg.onEvent?.('fullscreenChanged', refresh));
    safeCall(() => tg.onEvent?.('themeChanged', refresh));

    return () => {
      safeCall(() => tg.offEvent?.('viewportChanged', refresh));
      safeCall(() => tg.offEvent?.('safeAreaChanged', refresh));
      safeCall(() => tg.offEvent?.('contentSafeAreaChanged', refresh));
      safeCall(() => tg.offEvent?.('fullscreenChanged', refresh));
      safeCall(() => tg.offEvent?.('themeChanged', refresh));
    };
  }, [tg, isTelegram]);

  // ── BackButton synced with React Router ──
  useEffect(() => {
    if (!isTelegram || !tg?.BackButton) return;
    // Домашние экраны мини-аппа: корень и карта GRAM Island. Когда игрок
    // открывает проект через Telegram, он попадает сразу на карту (/ton-island)
    // — это стартовый экран, и «Назад» здесь вести некуда. На таких экранах мы
    // ПРЯЧЕМ свою кнопку BackButton, чтобы Telegram показывал нативную кнопку
    // «Закрыть», а её нажатие закрывало мини-приложение.
    const HOME_ROUTES = ['/', '', '/ton-island', '/island'];
    const onRoot = HOME_ROUTES.includes(location.pathname);

    const handler = () => {
      // Either pop history if possible, otherwise go home.
      if (window.history.length > 1) navigate(-1);
      else navigate('/');
    };

    // На домашнем экране (карта) дополнительно навешиваем закрытие мини-аппа
    // на аппаратную кнопку «назад» устройства, если пользователь всё же её нажмёт.
    const closeHandler = () => { safeCall(() => tg.close?.()); };

    if (onRoot) {
      safeCall(() => tg.BackButton.offClick(handler));
      safeCall(() => tg.BackButton.hide());
      // Разрешаем подтверждение закрытия и вешаем закрытие на back-событие.
      safeCall(() => tg.BackButton.onClick(closeHandler));
    } else {
      safeCall(() => tg.BackButton.offClick(closeHandler));
      safeCall(() => tg.BackButton.onClick(handler));
      safeCall(() => tg.BackButton.show());
    }

    return () => {
      safeCall(() => tg.BackButton.offClick(handler));
      safeCall(() => tg.BackButton.offClick(closeHandler));
    };
  }, [isTelegram, tg, location.pathname, navigate]);

  // ── Public helpers ──
  const haptic = useMemo(() => ({
    impact: (style = 'light') => safeCall(() => tg?.HapticFeedback?.impactOccurred?.(style)),
    notification: (type = 'success') => safeCall(() => tg?.HapticFeedback?.notificationOccurred?.(type)),
    selection: () => safeCall(() => tg?.HapticFeedback?.selectionChanged?.()),
  }), [tg]);

  return { tg, isTelegram, webAppUser, haptic };
}
