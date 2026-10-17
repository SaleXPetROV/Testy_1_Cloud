/**
 * TelegramChoiceModal — shown when a Telegram identity opening the app is NOT
 * yet linked to any account (backend returns {status:"choice_required"}).
 *
 * The user chooses:
 *   • "Создать новый аккаунт"  → create a fresh passwordless Telegram account.
 *   • "Привязать к существующему" → go to the login screen; after they log in,
 *     the Telegram identity is auto-linked (useTelegramAutoLink).
 */
import { useState } from 'react';
import { UserPlus, LinkIcon, Send } from 'lucide-react';

export default function TelegramChoiceModal({ open, telegram, onCreateNew, onLinkExisting, lang = 'ru' }) {
  const [busy, setBusy] = useState('');
  if (!open) return null;

  const name = telegram?.first_name || (telegram?.username ? `@${telegram.username}` : '');
  const t = lang === 'ru'
    ? {
        title: 'Вход через Telegram',
        hello: name ? `Привет, ${name}!` : 'Привет!',
        body: 'Этот Telegram ещё не привязан к аккаунту GRAM City. Что сделать?',
        create: 'Создать новый аккаунт',
        createHint: 'Быстрый старт — новый профиль на этот Telegram',
        link: 'Привязать к существующему',
        linkHint: 'Войдите в свой аккаунт — Telegram привяжется автоматически',
        creating: 'Создаём…',
      }
    : {
        title: 'Sign in with Telegram',
        hello: name ? `Hi, ${name}!` : 'Hi!',
        body: 'This Telegram is not linked to a GRAM City account yet. What would you like to do?',
        create: 'Create a new account',
        createHint: 'Quick start — a fresh profile for this Telegram',
        link: 'Link to an existing account',
        linkHint: 'Log in to your account — Telegram will link automatically',
        creating: 'Creating…',
      };

  const doCreate = async () => {
    if (busy) return;
    setBusy('create');
    try { await onCreateNew?.(); } finally { setBusy(''); }
  };
  const doLink = async () => {
    if (busy) return;
    setBusy('link');
    try { await onLinkExisting?.(); } finally { setBusy(''); }
  };

  return (
    <div
      className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md"
      data-testid="tg-choice-modal"
    >
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b0f17] p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center justify-center mb-4">
          <div className="w-16 h-16 rounded-full bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
            <Send className="w-8 h-8 text-cyber-cyan" />
          </div>
        </div>
        <h2 className="text-xl font-bold text-white text-center mb-1" data-testid="tg-choice-title">{t.title}</h2>
        <p className="text-sm text-cyber-cyan text-center mb-2">{t.hello}</p>
        <p className="text-sm text-white/70 text-center leading-relaxed mb-6">{t.body}</p>

        <button
          type="button"
          onClick={doCreate}
          disabled={!!busy}
          data-testid="tg-choice-create-btn"
          className="w-full flex items-center gap-3 rounded-xl bg-cyber-cyan text-black font-semibold py-3 px-4 mb-3 transition-[filter,transform] hover:brightness-110 active:scale-[0.99] disabled:opacity-60"
        >
          <UserPlus className="w-5 h-5 shrink-0" />
          <span className="text-left">
            <span className="block leading-tight">{busy === 'create' ? t.creating : t.create}</span>
            <span className="block text-xs font-normal opacity-80">{t.createHint}</span>
          </span>
        </button>

        <button
          type="button"
          onClick={doLink}
          disabled={!!busy}
          data-testid="tg-choice-link-btn"
          className="w-full flex items-center gap-3 rounded-xl bg-white/5 border border-white/15 text-white font-semibold py-3 px-4 transition-colors hover:bg-white/10 active:scale-[0.99] disabled:opacity-60"
        >
          <LinkIcon className="w-5 h-5 shrink-0 text-cyber-cyan" />
          <span className="text-left">
            <span className="block leading-tight">{t.link}</span>
            <span className="block text-xs font-normal text-white/60">{t.linkHint}</span>
          </span>
        </button>
      </div>
    </div>
  );
}
