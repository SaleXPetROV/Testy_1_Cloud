import { toast } from 'sonner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Cache the translated "feature in development" notice per language so we only
// hit the backend (LibreTranslate / LLM) once per language.
const _cache = {};

const FALLBACK = {
  ru: 'Функция в разработке',
  en: 'Feature in development',
  es: 'Función en desarrollo',
  zh: '功能开发中',
  fr: 'Fonctionnalité en développement',
  de: 'Funktion in Entwicklung',
  ja: '開発中の機能',
  ko: '개발 중인 기능',
  id: 'Fitur dalam pengembangan',
};

export async function fetchDevNotice(lang = 'ru') {
  if (_cache[lang]) return _cache[lang];
  try {
    const r = await fetch(`${API}/i18n/dev-notice?lang=${encodeURIComponent(lang)}`);
    if (r.ok) {
      const d = await r.json();
      const text = (d && d.text) || FALLBACK[lang] || FALLBACK.ru;
      _cache[lang] = text;
      return text;
    }
  } catch (e) { /* ignore */ }
  return FALLBACK[lang] || FALLBACK.ru;
}

// Show a toast telling the user the feature is in development, translated via
// the backend LibreTranslate service (with a static fallback).
export async function showDevNotice(lang = 'ru') {
  const text = await fetchDevNotice(lang);
  try { toast.info(text); } catch (e) { /* noop */ }
  return text;
}
