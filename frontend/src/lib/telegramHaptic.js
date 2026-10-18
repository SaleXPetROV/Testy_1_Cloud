/**
 * Telegram WebApp haptic feedback helpers (safe outside Telegram).
 * Use these directly in onClick handlers without importing any hook.
 */
const tg = () => {
  const w = typeof window !== 'undefined' ? window.Telegram?.WebApp : null;
  // HapticFeedback exists from WebApp 6.1; on 6.0 (and outside Telegram) the SDK only logs an error
  try { return w && w.initData && w.isVersionAtLeast && w.isVersionAtLeast('6.1') ? w : null; } catch (_) { return null; }
};
const safe = (fn) => { try { fn(); } catch (_) { /* no-op */ } };

export const hapticImpact = (style = 'light') =>
  safe(() => tg()?.HapticFeedback?.impactOccurred?.(style));

export const hapticNotification = (type = 'success') =>
  safe(() => tg()?.HapticFeedback?.notificationOccurred?.(type));

export const hapticSelection = () =>
  safe(() => tg()?.HapticFeedback?.selectionChanged?.());
