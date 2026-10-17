/**
 * SessionExpiredModal — shown when the current device's session was overridden
 * by a login on another device (backend returns 401 `session_invalidated`).
 *
 * CRITICAL: inside a Telegram Mini App we must NOT auto re-authenticate on a
 * 401, otherwise two devices ping-pong each other's sessions forever. Instead
 * we surface this modal and re-authenticate ONLY when the user taps the button.
 */
import { useState } from 'react';
import { ShieldAlert, LogIn } from 'lucide-react';

export default function SessionExpiredModal({ open, onReauth, lang = 'ru' }) {
  const [busy, setBusy] = useState(false);
  if (!open) return null;

  const t = lang === 'ru'
    ? {
        title: 'Сессия завершена',
        body: 'Вы вошли с другого устройства. Здесь сессия была закрыта в целях безопасности (один аккаунт — одно активное устройство).',
        hint: 'Нажмите кнопку ниже, чтобы вернуть доступ на этом устройстве.',
        btn: 'Войти здесь',
        loading: 'Входим…',
      }
    : {
        title: 'Session ended',
        body: 'You signed in on another device. This session was closed for security (one account = one active device).',
        hint: 'Tap the button below to restore access on this device.',
        btn: 'Log in here',
        loading: 'Signing in…',
      };

  const handleClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onReauth?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md"
      data-testid="session-expired-modal"
    >
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b0f17] p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center justify-center mb-5">
          <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-400/30 flex items-center justify-center">
            <ShieldAlert className="w-8 h-8 text-red-400" />
          </div>
        </div>
        <h2 className="text-xl font-bold text-white text-center mb-3" data-testid="session-expired-title">
          {t.title}
        </h2>
        <p className="text-sm text-white/70 text-center leading-relaxed mb-2">{t.body}</p>
        <p className="text-sm text-white/50 text-center leading-relaxed mb-6">{t.hint}</p>
        <button
          type="button"
          onClick={handleClick}
          disabled={busy}
          data-testid="session-expired-reauth-btn"
          className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-cyber-cyan text-black font-semibold py-3 px-4 transition-[filter,transform] hover:brightness-110 active:scale-[0.98] disabled:opacity-60"
        >
          <LogIn className="w-5 h-5" />
          {busy ? t.loading : t.btn}
        </button>
      </div>
    </div>
  );
}
