/**
 * Centralised helpers for normalising backend API error payloads
 * into safe, human-readable strings.
 *
 * Why this exists:
 *   FastAPI + Pydantic v2 returns 422 validation errors as
 *   `detail: Array<{ type, loc, msg, input, ctx, url }>`. Passing that
 *   array straight into a React child (e.g. `toast.error(data.detail)`)
 *   crashes the app with:
 *     "Objects are not valid as a React child"
 *
 * Always run server error payloads through `formatErrorDetail` before
 * passing them to UI components / toasts.
 */

// Локализованные сообщения для структурированных кодов ошибок бэкенда.
const INSUFFICIENT_FUNDS_I18N = {
  en: 'Insufficient funds: need {need} $CITY, available {have} $CITY (bonus + main balance)',
  ru: 'Недостаточно средств: нужно {need} $CITY, доступно {have} $CITY (бонусный + основной баланс)',
  es: 'Fondos insuficientes: se necesitan {need} $CITY, disponibles {have} $CITY (bono + saldo principal)',
  zh: '余额不足：需要 {need} $CITY，可用 {have} $CITY（奖励 + 主余额）',
  fr: 'Fonds insuffisants : {need} $CITY requis, {have} $CITY disponibles (bonus + solde principal)',
  de: 'Unzureichendes Guthaben: {need} $CITY benötigt, {have} $CITY verfügbar (Bonus + Hauptguthaben)',
  ja: '残高不足：必要 {need} $CITY、利用可能 {have} $CITY（ボーナス + メイン残高）',
  ko: '잔액 부족: 필요 {need} $CITY, 사용 가능 {have} $CITY (보너스 + 기본 잔액)',
  id: 'Saldo tidak cukup: butuh {need} $CITY, tersedia {have} $CITY (bonus + saldo utama)',
};

function currentLang() {
  try { return localStorage.getItem('ton_city_lang') || 'en'; } catch { return 'en'; }
}

export function formatErrorDetail(detail) {
  if (detail === null || detail === undefined) return '';
  if (typeof detail === 'string') return detail;

  if (typeof detail === 'object' && !Array.isArray(detail) && detail.code === 'insufficient_funds') {
    const tpl = INSUFFICIENT_FUNDS_I18N[currentLang()] || INSUFFICIENT_FUNDS_I18N.en;
    return tpl.replace('{need}', detail.need_city).replace('{have}', detail.have_city);
  }

  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        if (entry && typeof entry === 'object') {
          const field = Array.isArray(entry.loc)
            ? entry.loc.filter((p) => p !== 'body').join('.')
            : '';
          const msg = entry.msg || entry.message || entry.type || JSON.stringify(entry);
          return field ? `${field}: ${msg}` : String(msg);
        }
        return String(entry);
      })
      .join('; ');
  }

  if (typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail);
  }

  return String(detail);
}

/**
 * Extract a friendly error message from a variety of common shapes:
 *   - axios error: `err.response.data.detail`
 *   - fetch result: `{ detail, message }`
 *   - thrown `Error`: `err.message`
 *   - plain string
 */
export function getApiErrorMessage(err, fallback = '') {
  if (!err) return fallback;
  if (typeof err === 'string') return err;
  if (err?.response?.data?.detail !== undefined) {
    return formatErrorDetail(err.response.data.detail) || fallback;
  }
  if (err?.response?.data?.message) return String(err.response.data.message);
  if (err?.detail !== undefined) return formatErrorDetail(err.detail) || fallback;
  if (err?.message) return String(err.message);
  return fallback;
}
