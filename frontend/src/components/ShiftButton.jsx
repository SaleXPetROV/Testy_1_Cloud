import { useEffect, useState, useRef } from 'react';
import { Zap, Clock } from 'lucide-react';
import { toast } from 'sonner';
import { useLanguage } from '@/context/LanguageContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const L = {
  start: { ru: 'Начать смену (8 ч)', en: 'Start shift (8 h)', es: 'Iniciar turno (8 h)', zh: '开始轮班 (8小时)', fr: "Démarrer le quart (8 h)", de: 'Schicht starten (8 Std.)', ja: 'シフト開始 (8時間)', ko: '교대 시작 (8시간)', id: 'Mulai shift (8 jam)' },
  running: { ru: 'Смена идёт', en: 'Shift running', es: 'Turno en curso', zh: '轮班进行中', fr: 'Quart en cours', de: 'Schicht läuft', ja: 'シフト稼働中', ko: '교대 진행 중', id: 'Shift berjalan' },
  restart: { ru: 'Запустить смену (8 ч)', en: 'Restart shift (8 h)', es: 'Reanudar turno (8 h)', zh: '重启轮班 (8小时)', fr: 'Relancer le quart (8 h)', de: 'Schicht neu starten (8 Std.)', ja: 'シフト再開 (8時間)', ko: '교대 재시작 (8시간)', id: 'Mulai ulang shift (8 jam)' },
  auto: { ru: 'Работает без смены', en: 'Works without a shift', es: 'Funciona sin turno', zh: '无需轮班即可运行', fr: 'Fonctionne sans quart', de: 'Läuft ohne Schicht', ja: 'シフト不要で稼働', ko: '교대 없이 가동', id: 'Berjalan tanpa shift' },
  started: { ru: 'Смена запущена!', en: 'Shift started!', es: '¡Turno iniciado!', zh: '轮班已开始!', fr: 'Quart démarré !', de: 'Schicht gestartet!', ja: 'シフト開始!', ko: '교대 시작!', id: 'Shift dimulai!' },
  durability_zero: { ru: 'Смена не запущена: прочность бизнеса 0%. Отремонтируйте бизнес.', en: 'Shift not started: durability is 0%. Repair the business.', es: 'Turno no iniciado: durabilidad 0%. Repara el negocio.', zh: '未开始:耐久度为0%。请修理企业。', fr: 'Quart non démarré : durabilité 0%. Réparez le business.', de: 'Schicht nicht gestartet: Haltbarkeit 0%. Reparieren Sie das Geschäft.', ja: 'シフト未開始:耐久度0%。修理してください。', ko: '교대 미시작: 내구도 0%. 사업을 수리하세요.', id: 'Shift tidak dimulai: durabilitas 0%. Perbaiki bisnis.' },
  no_resources: { ru: 'Смена не запущена: недостаточно ресурсов для работы бизнеса.', en: 'Shift not started: not enough resources to run the business.', es: 'Turno no iniciado: recursos insuficientes.', zh: '未开始:资源不足,无法运营。', fr: 'Quart non démarré : ressources insuffisantes.', de: 'Schicht nicht gestartet: nicht genug Ressourcen.', ja: 'シフト未開始:資源が不足しています。', ko: '교대 미시작: 자원이 부족합니다.', id: 'Shift tidak dimulai: sumber daya tidak cukup.' },
};

const pad = (n) => String(n).padStart(2, '0');

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${pad(h)}:${pad(m)}:${pad(ss)}`;
}

// Per-business 8-hour shift control. Shows the live countdown while the shift
// runs and a "Start shift" button when idle. Calls onChanged() after a
// successful start so the parent can refresh the business list.
// `inline` renders the control without full-width margins so it can sit in a
// row of action buttons (e.g. РЕМОНТ | НАЧАТЬ СМЕНУ | АПГРЕЙД).
export default function ShiftButton({ business, onChanged, inline = false }) {
  const { language: lang } = useLanguage();
  const tr = (k) => (L[k][lang] || L[k].ru);
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const endRef = useRef(0);

  // Sync local end time from the business prop.
  useEffect(() => {
    const end = business?.shift_ends_at ? new Date(business.shift_ends_at).getTime() : 0;
    endRef.current = end;
    setRemaining(end ? Math.max(0, Math.floor((end - Date.now()) / 1000)) : 0);
  }, [business?.shift_ends_at]);

  useEffect(() => {
    const id = setInterval(() => {
      if (!endRef.current) { setRemaining(0); return; }
      setRemaining(Math.max(0, Math.floor((endRef.current - Date.now()) / 1000)));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const active = remaining > 0;
  // The server decides (core/business_rules.py → `auto_operates` in
  // /my/businesses). The local check is only a fallback for older payloads.
  const autoOperates = typeof business?.auto_operates === 'boolean'
    ? business.auto_operates
    : !!(business?.tutorial || business?.is_trial);
  if (autoOperates) {                     // tutorial / trial business: say so instead of showing nothing
    return (
      <div className={`${inline ? 'flex-1 min-w-0' : 'w-full'} min-h-[3.25rem] rounded-xl bg-emerald-500/10 border border-emerald-400/30 flex items-center justify-center gap-2 text-emerald-300 text-xs font-bold uppercase tracking-wide px-2 text-center`}
        data-testid={`shift-auto-${business?.id}`}>
        <Zap className="w-4 h-4 shrink-0" />{tr('auto')}
      </div>
    );
  }

  const startShift = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API}/business/${business.id}/start-shift`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const code = data.detail;
        const msg = (L[code] && (L[code][lang] || L[code].ru)) || (typeof code === 'string' ? code : 'Error');
        throw new Error(msg);
      }
      const end = data.shift_ends_at ? new Date(data.shift_ends_at).getTime() : Date.now() + 8 * 3600 * 1000;
      endRef.current = end;
      setRemaining(Math.max(0, Math.floor((end - Date.now()) / 1000)));
      toast.success(tr('started'));
      if (onChanged) onChanged();
    } catch (e) {
      toast.error(e.message || 'Error');
    } finally {
      setLoading(false);
    }
  };

  if (active) {
    return (
      <div
        data-testid={`shift-active-${business.id}`}
        className={inline
          ? "flex-1 min-w-0 h-full min-h-[3.25rem] flex flex-col items-center justify-center gap-0.5 px-2 rounded-xl bg-green-500/15 border border-green-500/40 text-green-300 font-bold"
          : "w-full mt-3 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-green-500/15 border border-green-500/40 text-green-300 font-bold"}
      >
        <span className="uppercase text-[10px] tracking-wide flex items-center gap-1">
          <Clock className="w-3.5 h-3.5 shrink-0 animate-pulse" />
          {tr('running')}
        </span>
        <span className="font-mono text-sm" data-testid={`shift-timer-${business.id}`}>{fmt(remaining)}</span>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={startShift}
      disabled={loading}
      data-testid={`start-shift-btn-${business.id}`}
      className={inline
        ? "flex-1 min-w-0 h-full min-h-[3.25rem] flex items-center justify-center gap-1 px-2 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 text-white font-bold uppercase text-[10px] sm:text-xs leading-tight text-center tracking-wide shadow-lg shadow-orange-500/30 transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
        : "w-full mt-3 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-gradient-to-r from-cyber-cyan to-neon-purple text-black font-bold uppercase text-xs tracking-wide shadow-lg shadow-cyber-cyan/30 transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"}
    >
      <Zap className="w-4 h-4 shrink-0" />
      {business?.shift_started_at ? tr('restart') : tr('start')}
    </button>
  );
}
