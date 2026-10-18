/**
 * SmartNotificationSettings — settings block for smart notifications
 * (backend/smart_notify.py, GET/PUT /api/notifications/smart).
 *
 *  • toggles: warehouse / durability / market price
 *  • quiet hours (Telegram held back, delivered when they end)
 *  • Telegram messages per day: 1 or 2 (in-game notifications are not limited)
 *  • the browser time zone is saved automatically so quiet hours are local
 *
 * Labels come from translationsExtra (en/ru written by hand; other languages
 * via `npm run i18n:autofill` → LibreTranslate).
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { BellRing } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { useTranslation } from '@/lib/translations';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
const auth = () => ({ headers: { Authorization: `Bearer ${getToken()}` } });

const browserTz = () => {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; }
};
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const hh = (h) => `${String(h).padStart(2, '0')}:00`;

function Row({ label, checked, onChange, testId }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1.5 cursor-pointer">
      <span className="text-sm text-white">{label}</span>
      <Switch checked={!!checked} onCheckedChange={onChange} data-testid={testId} />
    </label>
  );
}

export default function SmartNotificationSettings({ lang = 'en', disabled = false }) {
  const { t } = useTranslation(lang);
  const [p, setP] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/notifications/smart`, auth());
      setP(r.data);
      // Keep the player's time zone up to date so quiet hours follow their clock.
      const tz = browserTz();
      if (tz && tz !== r.data?.timezone) {
        const u = await axios.put(`${API}/notifications/smart`, { timezone: tz }, auth());
        setP((prev) => ({ ...(prev || {}), ...u.data }));
      }
    } catch {
      setP(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (patch) => {
    setP((prev) => ({ ...prev, ...patch }));            // optimistic
    try {
      const r = await axios.put(`${API}/notifications/smart`, patch, auth());
      setP((prev) => ({ ...prev, ...r.data }));
      toast.success(t('smartNotifSaved'));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
      load();
    }
  };

  if (!p) return null;

  return (
    <div className={`glass-panel rounded-2xl p-4 sm:p-8 border border-white/10 ${disabled ? 'opacity-50 pointer-events-none' : ''}`}
      data-testid="settings-smart-notifications">
      <div className="flex items-center gap-2 mb-1">
        <BellRing className="w-5 h-5 text-yellow-400" />
        <h3 className="text-base sm:text-lg font-bold text-white uppercase tracking-wide">{t('smartNotifTitle')}</h3>
      </div>
      <p className="text-xs text-text-muted mb-3">{t('smartNotifDesc')}</p>

      <div className="divide-y divide-white/5">
        <Row label={t('smartNotifWarehouse')} checked={p.warehouse} onChange={(v) => save({ warehouse: v })} testId="smart-toggle-warehouse" />
        <Row label={t('smartNotifDurability')} checked={p.durability} onChange={(v) => save({ durability: v })} testId="smart-toggle-durability" />
        <Row label={t('smartNotifPrice')} checked={p.price} onChange={(v) => save({ price: v })} testId="smart-toggle-price" />
        <Row label={t('smartNotifShift')} checked={p.shift} onChange={(v) => save({ shift: v })} testId="smart-toggle-shift" />
      </div>

      <div className="mt-4 space-y-2">
        <Row label={t('smartNotifQuiet')} checked={p.quiet_enabled} onChange={(v) => save({ quiet_enabled: v })} testId="smart-toggle-quiet" />
        {p.quiet_enabled && (
          <div className="flex items-center gap-2 text-sm text-white pl-1">
            <span className="text-text-muted">{t('smartNotifQuietFrom')}</span>
            <select value={p.quiet_start} onChange={(e) => save({ quiet_start: Number(e.target.value) })}
              className="bg-white/5 border border-white/10 rounded-md px-2 py-1" data-testid="smart-quiet-start">
              {HOURS.map((h) => <option key={h} value={h}>{hh(h)}</option>)}
            </select>
            <span className="text-text-muted">{t('smartNotifQuietTo')}</span>
            <select value={p.quiet_end} onChange={(e) => save({ quiet_end: Number(e.target.value) })}
              className="bg-white/5 border border-white/10 rounded-md px-2 py-1" data-testid="smart-quiet-end">
              {HOURS.map((h) => <option key={h} value={h}>{hh(h)}</option>)}
            </select>
          </div>
        )}
        {p.timezone && (
          <div className="text-[11px] text-text-muted pl-1">{t('smartNotifTimezone')}: {p.timezone}</div>
        )}
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-white">{t('smartNotifLimit')}</span>
          <div className="flex gap-1" data-testid="smart-daily-limit">
            {[1, 2].map((n) => (
              <button key={n} type="button" onClick={() => save({ daily_limit: n })}
                className={`w-9 h-8 rounded-md text-sm font-bold border ${p.daily_limit === n ? 'bg-yellow-400 text-black border-yellow-400' : 'bg-white/5 text-white border-white/10'}`}>
                {n}
              </button>
            ))}
          </div>
        </div>
        <p className="text-[11px] text-text-muted mt-1">{t('smartNotifLimitHint')}</p>
        {!p.telegram_linked && <p className="text-[11px] text-cyan-300 mt-1">{t('smartNotifNoTelegram')}</p>}
      </div>
    </div>
  );
}
