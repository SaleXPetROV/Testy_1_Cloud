import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { getFbCookies } from '@/lib/fbTracking';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Carries the machine-readable error `code` returned by the backend so the UI
// can render a friendly, localized message instead of Google's raw reason.
class GoogleAuthError extends Error {
  constructor(code, rawDetail) {
    super(code || 'google_generic');
    this.code = code || null;
    this.rawDetail = rawDetail;
  }
}

// Localized, human-friendly messages by error code and UI language.
// Falls back to English, then to a generic message.
const GOOGLE_ERROR_MESSAGES = {
  ru: {
    google_config_error: 'Вход через Google временно недоступен из-за ошибки настройки. Попробуйте войти по email или напишите в поддержку.',
    google_session_expired: 'Сессия входа через Google истекла. Пожалуйста, попробуйте ещё раз.',
    google_state_invalid: 'Сессия входа устарела. Пожалуйста, начните вход заново.',
    google_no_id_token: 'Google не вернул данные аккаунта. Попробуйте ещё раз.',
    google_no_email: 'Google не предоставил email. Разрешите доступ к email и повторите.',
    google_not_configured: 'Вход через Google временно недоступен. Попробуйте позже или войдите по email.',
    google_generic: 'Не удалось войти через Google. Пожалуйста, попробуйте ещё раз.',
  },
  en: {
    google_config_error: 'Google sign-in is temporarily unavailable due to a configuration issue. Please use email or contact support.',
    google_session_expired: 'Your Google sign-in session expired. Please try again.',
    google_state_invalid: 'Your sign-in session is stale. Please start again.',
    google_no_id_token: 'Google did not return account details. Please try again.',
    google_no_email: 'Google did not provide an email. Please allow email access and retry.',
    google_not_configured: 'Google sign-in is temporarily unavailable. Please try later or use email.',
    google_generic: 'Google sign-in failed. Please try again.',
  },
};

function friendlyGoogleError(err, lang) {
  const dict = GOOGLE_ERROR_MESSAGES[lang] || GOOGLE_ERROR_MESSAGES.en;
  const code = err && err.code;
  if (code && dict[code]) return dict[code];
  // Legacy string details from older backends: sniff for known Google reasons.
  const raw = String((err && (err.rawDetail || err.message)) || '').toLowerCase();
  if (raw.includes('invalid_client') || raw.includes('unauthorized_client') || raw.includes('redirect_uri')) {
    return dict.google_config_error;
  }
  if (raw.includes('invalid_grant') || raw.includes('expired') || raw.includes('state')) {
    return dict.google_session_expired;
  }
  return dict.google_generic;
}

export default function GoogleCallback({ setUser, onAuthSuccess }) {
  const { lang } = useLanguage();
  const { t } = useTranslation(lang);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState(null);
  // StrictMode в dev вызывает useEffect дважды — предотвращаем повторную отправку
  const executed = useRef(false);

  useEffect(() => {
    if (executed.current) return;
    executed.current = true;

    const code = searchParams.get('code');
    const errorParam = searchParams.get('error');
    const stateParam = searchParams.get('state');

    if (errorParam) {
      setError(t('googleAuthCancelled'));
      toast.error(t('googleAuthCancelled'));
      setTimeout(() => navigate('/auth?mode=login'), 2000);
      return;
    }

    if (code) {
      handleGoogleCallback(code, stateParam);
    } else {
      setError(t('googleAuthNoCode'));
      setTimeout(() => navigate('/auth?mode=login'), 2000);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGoogleCallback = async (code, stateParam) => {
    try {
      const redirectUri = window.location.origin + '/auth/google/callback';

      // F26: defense-in-depth — verify the state we stored before redirect
      // matches what Google returned, then hand it to the backend for the
      // authoritative one-time check.
      const savedState = sessionStorage.getItem('google_oauth_state');
      if (savedState && stateParam && savedState !== stateParam) {
        throw new Error(t('googleAuthFailed'));
      }
      sessionStorage.removeItem('google_oauth_state');

      const res = await fetch(`${API}/auth/google/callback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code,
          redirect_uri: redirectUri,
          state: stateParam || undefined,
          ...getFbCookies(),
          referral_code: localStorage.getItem('ref_code') || undefined
        })
      });

      const data = await res.json();

      if (!res.ok) {
        // Backend returns a structured detail {code, reason} for Google errors
        // so we can show a friendly, localized message (never a raw
        // "invalid_client"). Fall back to string detail / generic text.
        const code = (data && data.detail && typeof data.detail === 'object')
          ? data.detail.code
          : null;
        throw new GoogleAuthError(code, data?.detail);
      }

      // Success - save token and user
      localStorage.setItem('token', data.token);
      localStorage.setItem('ton_city_token', data.token);

      // === ТРИГГЕР ФЕЙСБУКА (регистрация через Google) ===
      if (data.is_new_user) {
        localStorage.setItem('just_registered', '1');
        if (window.fbq) {
          window.fbq('track', 'CompleteRegistration');
          console.log('Фейсбук поймал регистрацию!');
        }
      } else {
        // Existing user logging in → show referral invite popup
        localStorage.setItem('pending_referral_invite', '1');
      }

      if (setUser && data.user) {
        setUser(data.user);
      }

      window.dispatchEvent(new Event('ton-city-auth'));

      // Navigate to GRAM Island map after successful auth
      navigate('/ton-island', { replace: true });

      if (onAuthSuccess) {
        // Fire-and-forget so we don't keep the "please wait" screen
        onAuthSuccess().catch(() => {});
      }

      toast.success(t('googleLoginSuccess'));
    } catch (e) {
      console.error('Google callback error:', e);
      const friendly = friendlyGoogleError(e, lang);
      setError(friendly);
      toast.error(friendly);
      setTimeout(() => navigate('/auth?mode=login'), 3000);
    }
  };

  return (
    <div className="min-h-screen bg-void flex items-center justify-center" data-testid="google-callback-page">
      <div className="text-center p-8">
        {error ? (
          <div className="text-red-400">
            <p className="text-xl mb-2">{t('errorTitle')}</p>
            <p className="text-sm text-text-muted">{error}</p>
            <p className="text-xs text-text-muted mt-4">{t('redirecting')}</p>
          </div>
        ) : (
          <div className="text-cyber-cyan">
            <Loader2 className="w-10 h-10 animate-spin mx-auto" />
          </div>
        )}
      </div>
    </div>
  );
}
