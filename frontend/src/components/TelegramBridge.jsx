/**
 * TelegramBridge — invisible component placed inside BrowserRouter that:
 *   1) initialises Telegram Mini App SDK (safe-area, fullscreen, BackButton…)
 *   2) silently *links* an authenticated user's Telegram identity for
 *      notifications. This component does NOT auto-register users — they
 *      must register via the standard flows (email / Google / wallet) first.
 */
import useTelegramWebApp from '@/hooks/useTelegramWebApp';
import useTelegramAutoLink from '@/hooks/useTelegramAutoLink';

export default function TelegramBridge() {
  const { tg, isTelegram } = useTelegramWebApp();
  useTelegramAutoLink({ isTelegram, tg });
  return null;
}
