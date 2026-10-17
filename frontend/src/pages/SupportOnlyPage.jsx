import { useEffect, useState } from 'react';
import { useLanguage } from '@/context/LanguageContext';
import SupportModal from '@/components/SupportModal';

/**
 * SupportOnlyPage
 * ---------------------------------------------------------------------------
 * Dedicated route that renders ONLY the support chat UI. Opened from the
 * Telegram bot ("Поддержка" in Help) as a Mini App / browser window so users
 * can chat with support and nothing else.
 *
 * Behaviour:
 *  • On mobile / inside Telegram Web App — the chat fills the whole viewport.
 *  • On desktop browsers — the chat is rendered inside a 420 px mobile-shaped
 *    frame in the middle of a dark backdrop, matching how it feels inside
 *    Telegram. This keeps the UX consistent (agents / users don't see a huge
 *    left sidebar variant that doesn't match the Mini App preview).
 *
 * Auth token and language are passed in the URL by the bot:
 *   /support-only?auth=<jwt>&lang=ru
 * App.js writes them to localStorage before this page mounts.
 */
export default function SupportOnlyPage() {
  const { language: lang } = useLanguage();
  const [open, setOpen] = useState(true);

  // Detect desktop viewport (≥ 768 px) so we can mount inside a phone-shaped
  // frame. The check runs client-side only.
  const [isDesktop, setIsDesktop] = useState(
    typeof window !== 'undefined' && window.innerWidth >= 768
      && !window.Telegram?.WebApp?.initData
  );
  useEffect(() => {
    const onResize = () => {
      const inTg = !!window.Telegram?.WebApp?.initData;
      setIsDesktop(window.innerWidth >= 768 && !inTg);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const handleOpenChange = (v) => {
    if (!v && window.Telegram?.WebApp?.close) {
      try { window.Telegram.WebApp.close(); return; } catch (_) { /* ignore */ }
    }
    setOpen(true);
  };

  // Solid dark canvas for both variants.
  useEffect(() => {
    const prev = document.body.style.background;
    document.body.style.background = '#05070c';
    return () => { document.body.style.background = prev; };
  }, []);

  // Desktop: render inside a 420 px phone-shaped container centred on the
  // page. We attach the SupportModal to this container via CSS overrides
  // (a wrapper with `.support-only-frame` scopes fixed positioning to the
  // frame instead of the whole viewport).
  if (isDesktop) {
    return (
      <div
        className="min-h-screen w-full flex items-center justify-center p-6"
        style={{ background: '#05070c' }}
        data-testid="support-only-page-desktop"
      >
        <div
          className="relative w-[420px] h-[85vh] max-h-[820px] rounded-3xl overflow-hidden border border-cyan-500/20 shadow-[0_20px_80px_rgba(0,0,0,0.7)] bg-void"
        >
          <SupportModal
            open={open}
            onOpenChange={handleOpenChange}
            language={lang || 'ru'}
            forceFullscreen
            disablePortal
          />
        </div>
      </div>
    );
  }

  // Mobile / Telegram Mini App: full-viewport chat.
  return (
    <div
      className="min-h-screen w-full bg-void"
      data-testid="support-only-page"
      style={{ background: '#05070c' }}
    >
      <SupportModal open={open} onOpenChange={handleOpenChange} language={lang || 'ru'} forceFullscreen />
    </div>
  );
}
