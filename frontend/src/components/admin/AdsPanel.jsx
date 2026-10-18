/** Admin → «Данные» → «Monetag»: the Monetag SDK tag + rewarded ads before the daily login bonus. Russian only. */
import { useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const inp = 'rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm w-full';

export default function AdsPanel() {
  const h = { headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } };
  const [c, setC] = useState(null);
  useEffect(() => { axios.get(`${API}/admin/ads`, h).then((r) => setC(r.data)).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!c) return null;
  const set = (k, v) => setC((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try { const r = await axios.put(`${API}/admin/ads`, c, h); setC(r.data); toast.success('Сохранено'); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
  };
  const postback = `${window.location.origin.replace(/:\d+$/, '')}/api/ads/monetag/postback?ymid={ymid}&event={event_type}&secret=${c.postback_secret}`;
  return (
    <div className="rounded-xl border border-yellow-400/30 bg-yellow-500/5 p-4 space-y-3 mb-4" data-testid="admin-ads">
      <div className="font-bold text-white">📺 Monetag: реклама перед ежедневным бонусом</div>
      <label className="block space-y-1 text-xs text-text-muted">
        <span>Тег SDK из кабинета Monetag (шаг 1 «Чтобы установить SDK скопируйте этот тег») — вставьте целиком</span>
        <textarea rows={3} className={`${inp} font-mono`} value={c.sdk_tag || ''} onChange={(e) => set('sdk_tag', e.target.value)}
          placeholder={"<script src='//libtl.com/sdk.js' data-zone='10012345' data-sdk='show_10012345'></script>"} data-testid="ads-sdk-tag" />
      </label>
      {c.sdk_src ? (
        <div className="text-[11px] text-emerald-300 break-all" data-testid="ads-sdk-parsed">Из тега: SDK {c.sdk_src} · зона {c.monetag_zone_id} · функция {c.sdk_fn}</div>
      ) : (
        <div className="text-[11px] text-text-muted">Тег ещё не сохранён — используется SDK https://libtl.com/sdk.js и зона ниже.</div>
      )}
      {c.sdk_src && !/^https:\/\/([a-z0-9-]+\.)*libtl\.com\//i.test(c.sdk_src) && (
        <div className="text-[11px] text-amber-300">Домен SDK не libtl.com: добавьте его в CSP_EXTRA_SCRIPT_SRC (frontend/.env) и пересоберите фронтенд, иначе браузер заблокирует скрипт.</div>
      )}
      <div className="text-[11px] text-text-muted">В кабинете Monetag активируйте формат «Вознаграждённый интерстициальный» (Rewarded Interstitial) — его показывает кнопка «Смотреть рекламу» в «Ежедневном входе».</div>
      <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!c.enabled} onChange={(e) => set('enabled', e.target.checked)} data-testid="ads-enabled" /> Включено</label>
      <div className="grid md:grid-cols-3 gap-3 text-xs text-text-muted">
        <label className="space-y-1"><span>ID зоны (заполняется из тега)</span><input className={inp} value={c.monetag_zone_id} onChange={(e) => set('monetag_zone_id', e.target.value)} data-testid="ads-zone" /></label>
        <label className="space-y-1"><span>Сколько реклам до бонуса</span><input type="number" min={0} max={5} className={inp} value={c.daily_ads_required} onChange={(e) => set('daily_ads_required', e.target.value)} /></label>
        <label className="space-y-1"><span>Мин. пауза между рекламами, сек</span><input type="number" min={0} className={inp} value={c.min_gap_sec} onChange={(e) => set('min_gap_sec', e.target.value)} /></label>
      </div>
      <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!c.verify_postback} onChange={(e) => set('verify_postback', e.target.checked)} /> Засчитывать только просмотры, подтверждённые Monetag (postback)</label>
      <div className="text-[11px] text-text-muted break-all">Postback URL для кабинета Monetag: <span className="text-white">{postback}</span></div>
      <div className="text-[11px] text-text-muted">Сегодня просмотров: {c.views_today} · игроков: {c.players_today}. Пока реклама выключена или нет зоны — бонус выдаётся без рекламы.</div>
      <Button size="sm" onClick={save}>Сохранить</Button>
    </div>
  );
}
