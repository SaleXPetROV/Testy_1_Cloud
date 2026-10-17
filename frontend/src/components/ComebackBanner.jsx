/**
 * ComebackBanner — "welcome back" gift + streak-shield indicator (backend/comeback.py).
 *
 * Shown above the daily-login card on the Tasks page. When the player has been
 * away long enough, GET /api/comeback returns an available bonus; claiming it
 * (POST /api/comeback/claim) credits bonus $CITY, protects the warehouse from
 * the midnight decay for a while, and for long absences grants a streak shield.
 * The shield count is always shown so players understand why a missed day did
 * not reset their streak.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { motion } from 'framer-motion';
import { Gift, Shield } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
const auth = () => ({ headers: { Authorization: `Bearer ${getToken()}` } });

const L = {
  title: { en: 'Welcome back!', ru: 'С возвращением!', es: '¡Bienvenido de nuevo!', zh: '欢迎回来！', fr: 'Content de vous revoir !', de: 'Willkommen zurück!', ja: 'おかえりなさい！', ko: '돌아오신 것을 환영합니다!', id: 'Selamat datang kembali!' },
  away: { en: 'You were away {d} days — here is a gift to get going again.', ru: 'Вас не было {d} дн. — вот подарок, чтобы вернуться в игру.', es: 'Estuviste fuera {d} días: aquí tienes un regalo.', zh: '你离开了 {d} 天——这是回归礼物。', fr: 'Absent {d} jours — voici un cadeau.', de: '{d} Tage weg — hier ein Geschenk.', ja: '{d}日ぶりですね。復帰ギフトをどうぞ。', ko: '{d}일 만이에요 — 복귀 선물이에요.', id: 'Anda pergi {d} hari — ini hadiah untuk memulai lagi.' },
  claim: { en: 'Claim gift', ru: 'Забрать подарок', es: 'Reclamar', zh: '领取', fr: 'Récupérer', de: 'Abholen', ja: '受け取る', ko: '받기', id: 'Klaim' },
  protect: { en: 'warehouse protected {h}h', ru: 'склад защищён {h}ч', es: 'almacén protegido {h}h', zh: '仓库保护 {h}小时', fr: 'entrepôt protégé {h}h', de: 'Lager {h}h geschützt', ja: '倉庫を{h}時間保護', ko: '창고 {h}시간 보호', id: 'gudang terlindungi {h}j' },
  shields: { en: 'Streak shields: {n}', ru: 'Щиты серии: {n}', es: 'Escudos de racha: {n}', zh: '连续护盾：{n}', fr: 'Boucliers de série : {n}', de: 'Serien-Schilde: {n}', ja: '連続シールド：{n}', ko: '연속 보호막: {n}', id: 'Perisai streak: {n}' },
  shieldHint: { en: 'A shield keeps your daily streak alive over one missed day.', ru: 'Щит сохраняет серию входов при пропуске одного дня.', es: 'Un escudo mantiene tu racha si faltas un día.', zh: '护盾可在漏签一天时保住连续记录。', fr: 'Un bouclier sauve votre série si vous manquez un jour.', de: 'Ein Schild rettet deine Serie bei einem verpassten Tag.', ja: 'シールドは1日逃しても連続を維持します。', ko: '보호막은 하루 놓쳐도 연속 기록을 지켜줍니다.', id: 'Perisai menjaga streak saat Anda melewatkan satu hari.' },
};
const tr = (k, lang, vars = {}) => {
  let s = L[k]?.[lang] || L[k]?.en || k;
  Object.entries(vars).forEach(([key, v]) => { s = s.replace(`{${key}}`, v); });
  return s;
};

export default function ComebackBanner({ lang = 'en', onChanged }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/comeback`, auth());
      setData(r.data);
    } catch {
      setData(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const claim = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/comeback/claim`, {}, auth());
      const g = r.data?.granted || {};
      toast.success(`${tr('title', lang)} +${g.city || 0} $CITY`);
      await load();
      onChanged && onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (!data) return null;
  const shieldCount = data.shields || 0;

  return (
    <div className="space-y-2" data-testid="comeback-banner">
      {data.available && (
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-purple-400/50 bg-gradient-to-r from-purple-500/15 to-pink-500/10 p-3 flex items-center gap-3">
          <Gift className="w-6 h-6 text-purple-300 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-white">{tr('title', lang)}</div>
            <div className="text-[11px] text-text-muted">{tr('away', lang, { d: data.away_days })}</div>
            <div className="text-[11px] text-purple-200 mt-0.5">
              +{data.reward.city} $CITY · {tr('protect', lang, { h: data.reward.protect_hours })}
              {data.reward.shields ? ` · +${data.reward.shields} 🛡` : ''}
            </div>
          </div>
          <button type="button" onClick={claim} disabled={busy}
            className="flex-shrink-0 rounded-lg bg-purple-400 text-black font-bold px-3 py-1.5 text-xs disabled:opacity-50"
            data-testid="comeback-claim">{tr('claim', lang)}</button>
        </motion.div>
      )}
      {shieldCount > 0 && (
        <div className="flex items-center gap-1.5 text-[11px] text-cyan-300 px-1" title={tr('shieldHint', lang)} data-testid="streak-shields">
          <Shield className="w-3.5 h-3.5" />
          <span>{tr('shields', lang, { n: shieldCount })}</span>
        </div>
      )}
    </div>
  );
}
