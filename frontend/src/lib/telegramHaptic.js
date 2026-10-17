/**
 * Telegram WebApp haptic feedback helpers (safe outside Telegram).
 * Use these directly in onClick handlers without importing any hook.
 */
const tg = () => (typeof window !== 'undefined' ? window.Telegram?.WebApp : null);
const safe = (fn) => { try { fn(); } catch (_) { /* no-op */ } };

export const hapticImpact = (style = 'light') =>
  safe(() => tg()?.HapticFeedback?.impactOccurred?.(style));

export const hapticNotification = (type = 'success') =>
  safe(() => tg()?.HapticFeedback?.notificationOccurred?.(type));

export const hapticSelection = () =>
  safe(() => tg()?.HapticFeedback?.selectionChanged?.());
