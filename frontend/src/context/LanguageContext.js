import { createContext, useContext, useState, useEffect, useRef } from 'react';
import { setResourceLang } from '@/lib/resourceConfig';

const LanguageContext = createContext();

const SUPPORTED = ['en', 'ru', 'es', 'zh', 'fr', 'de', 'ja', 'ko', 'id'];

// IP-based geolocation runs BEFORE React mounts (see `lib/languageBootstrap.js`),
// so by the time this provider mounts the resolved language is already in
// localStorage — the first paint is in the correct language.
function resolveInitialLang(user) {
  try {
    const stored = localStorage.getItem('ton_city_lang');
    if (stored && SUPPORTED.includes(stored)) return stored;
  } catch {}
  if (user?.language && SUPPORTED.includes(user.language)) return user.language;
  // Default is ENGLISH (not the browser/device locale). Geo-adaptation happens
  // in lib/languageBootstrap.js before mount and is already persisted above.
  return 'en';
}

export const LanguageProvider = ({ children, user }) => {
  const [lang, setLangState] = useState(() => resolveInitialLang(user));
  // Tracks whether we've already adopted the server-side language for this
  // session. After the first adoption, the user's local choice is authoritative
  // and we won't keep overwriting it just because /auth/me returns a stale
  // value on every refresh.
  const hasAdoptedServerLangRef = useRef(false);

  useEffect(() => {
    setResourceLang(lang);
  }, [lang]);

  // ONE-TIME sync from server-side language. Runs only on the first time a
  // logged-in user appears in the tree (i.e. right after login or first
  // /auth/me on page load). After that we trust the user's local choice and
  // push updates *to* the server (see `setLang` below) instead of pulling.
  useEffect(() => {
    if (hasAdoptedServerLangRef.current) return;
    if (!user?.language) return;
    if (!SUPPORTED.includes(user.language)) return;

    let stored = null;
    try { stored = localStorage.getItem('ton_city_lang'); } catch {}

    // If the browser has no stored preference yet, adopt server value.
    // If it already has one, leave it alone — that's an explicit user choice
    // (or geolocated default) and we don't want to clobber it on every refresh.
    if (!stored && user.language !== lang) {
      setLangState(user.language);
      try { localStorage.setItem('ton_city_lang', user.language); } catch {}
    } else if (stored && SUPPORTED.includes(stored) && stored !== user.language) {
      // The client already made a choice (or was auto-picked by IP-geolocation)
      // that differs from the server value. Push it to the server so
      // server-side messages (Telegram notifications, business-stopped alerts,
      // etc.) are delivered in the user's actual UI language.
      try {
        const token = localStorage.getItem('token');
        if (token) {
          const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
          fetch(`${backendUrl}/api/auth/update-language`, {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ language: stored }),
          }).catch(() => {});
        }
      } catch {}
    }
    hasAdoptedServerLangRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.language]);

  const setLang = (newLang) => {
    if (!SUPPORTED.includes(newLang)) return;
    setLangState(newLang);
    try {
      localStorage.setItem('ton_city_lang', newLang);
      localStorage.setItem('ton_city_lang_explicit', '1'); // manual choice — never auto-overridden
    } catch {}
    window.dispatchEvent(new Event('languageChange'));

    // Persist to backend so the choice survives across devices / clean
    // browsers. Best-effort: ignore network errors, localStorage is the
    // source of truth for the current device.
    try {
      const token = localStorage.getItem('token');
      if (token) {
        const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
        fetch(`${backendUrl}/api/auth/update-language`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ language: newLang }),
        }).catch(() => {});
      }
    } catch {}
  };

  return (
    <LanguageContext.Provider value={{ language: lang, lang, setLang }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    let stored = 'en';
    try { stored = localStorage.getItem('ton_city_lang') || 'en'; } catch {}
    return {
      language: stored,
      lang: stored,
      setLang: (l) => { try { localStorage.setItem('ton_city_lang', l); } catch {} },
    };
  }
  return context;
};

export default LanguageContext;
